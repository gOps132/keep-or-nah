"""Preview rendering, texture caching, and the loading overlay.

The preview canvas is the largest surface in the desktop GUI. It draws the
representative of the active photo group, caches the Tk textures it draws so
a zoom change does not re-decode the same image, and shows a spinner while a
preview is still being decoded.

Every method here is a mixin method: it operates on `self`, which is the
`App` that owns the widget tree. A Tk widget has exactly one parent, so
nothing here ever creates a widget against a root of its own.
"""

from __future__ import annotations

import tkinter as tk
from collections import OrderedDict
from pathlib import Path
from typing import TYPE_CHECKING

from ui.gui_targets import gui_module
from view_filter import empty_preview_message, unavailable_preview_message

if TYPE_CHECKING:
    from PIL import Image, ImageTk


class PreviewControllerMixin:
    """Preview rendering, texture caching, and the loading overlay."""

    def handle_preview_configure(self, _event=None):
        if self.destroyed:
            return
        self.scale_preview_display_to_current_canvas()
        self.schedule_preview_refresh()

    def scale_preview_display_to_current_canvas(self):
        rendered = self.rendered_preview_size
        if not rendered:
            return
        canvas = self.preview_canvas
        new_size = (max(canvas.winfo_width(), 1), max(canvas.winfo_height(), 1))
        if new_size == rendered:
            return
        scale_x = new_size[0] / rendered[0]
        scale_y = new_size[1] / rendered[1]
        canvas.scale("all", 0, 0, scale_x, scale_y)
        old_region = self.rendered_preview_scrollregion
        new_region = None
        if old_region:
            x1, y1, x2, y2 = old_region
            new_region = (x1 * scale_x, y1 * scale_y, x2 * scale_x, y2 * scale_y)
            canvas.configure(scrollregion=new_region)
        self.rendered_preview_scrollregion = new_region
        self.rendered_preview_size = new_size

    def schedule_preview_refresh(self, _event=None):
        if self.preview_refresh_job is not None:
            self.after_cancel(self.preview_refresh_job)
        self.preview_refresh_job = self.after(80, self.refresh_preview_or_placeholder)

    def schedule_preview_poll(self):
        if self.preview_poll_job is not None or self.destroyed:
            return
        self.preview_poll_job = self.after(45, self.poll_preview_pipeline)

    def poll_preview_pipeline(self):
        self.preview_poll_job = None
        completed = self.preview_pipeline.drain_completed()
        current = self.session.active_photo
        if self.destroyed or current is None or self.preview_request_key is None:
            return

        relevant = any(
            event.path == current and event.request_id == self.preview_request_id
            for event in completed
        )
        if relevant or (completed and not self.preview_request_needs_more_work(current)):
            self.refresh_preview()
            return

        if self.preview_request_needs_more_work(current):
            self.schedule_preview_poll()

    def preview_request_needs_more_work(self, current: Path) -> bool:
        lookup = self.preview_pipeline.get_best_preview(current)
        if lookup.unavailable:
            return False
        fit_mode = self.zoom_factor == 1.0
        if fit_mode:
            return not lookup.failed and lookup.stage != "full"
        return not self.preview_pipeline.has_source(current)

    def clear_preview(self, message="No Photo"):
        self.preview_source_image = None
        self.preview_source_path = None
        self.preview_photo = None
        self.preview_canvas.delete("all")
        width = max(self.preview_canvas.winfo_width(), 320)
        height = max(self.preview_canvas.winfo_height(), 240)
        self.preview_canvas.configure(scrollregion=(0, 0, width, height))
        self.rendered_preview_size = (width, height)
        self.rendered_preview_scrollregion = (0, 0, width, height)
        if message:
            self.preview_canvas.create_text(
                width / 2,
                height / 2,
                text=message,
                fill=self._apply_appearance_mode(("gray45", "gray65")),
                font=("SF Pro Display", 22, "bold"),
            )
        if self.loading_overlay_visible:
            self.render_loading_overlay()

    def refresh_preview_or_placeholder(self):
        current = self.session.active_photo
        if current is None:
            self.reset_preview_request_state()
            self.clear_preview(empty_preview_message(self.session))
            self.preview_refresh_job = None
            return
        self.refresh_preview()

    def get_preview_texture(
        self, cache_key: tuple[object, ...] | None, image: Image.Image
    ) -> ImageTk.PhotoImage:
        # `ImageTk` is resolved through the composition root so a patch on
        # `gui_app.ImageTk` still reaches this code.
        image_tk = gui_module().ImageTk
        if cache_key is None:
            return image_tk.PhotoImage(image)

        cached = self.preview_texture_cache.get(cache_key)
        if cached is not None:
            self.preview_texture_cache.move_to_end(cache_key)
            return cached

        texture = image_tk.PhotoImage(image)
        self.preview_texture_cache[cache_key] = texture
        while len(self.preview_texture_cache) > self.preview_texture_cache_limit:
            self.preview_texture_cache.popitem(last=False)
        return texture

    def prune_preview_texture_cache(self, allowed_paths: set[Path] | None = None):
        if not allowed_paths:
            self.preview_texture_cache = OrderedDict()
            return

        for key in list(self.preview_texture_cache.keys()):
            path = key[0]
            if isinstance(path, Path) and path in allowed_paths:
                continue
            self.preview_texture_cache.pop(key, None)

    def schedule_loading_overlay_delay(self, request_key: tuple[Path, int, int, str, bool]):
        if not self.settings.loading_indicator or self.destroyed:
            return
        if self.loading_overlay_delay_job is not None:
            self.after_cancel(self.loading_overlay_delay_job)
        self.loading_overlay_delay_job = self.after(
            140, lambda: self.maybe_show_loading_overlay(request_key)
        )

    def maybe_show_loading_overlay(self, request_key: tuple[Path, int, int, str, bool]):
        self.loading_overlay_delay_job = None
        if self.destroyed or self.preview_request_key != request_key:
            return
        current = self.session.active_photo
        if current is None:
            return
        if not self.preview_request_needs_more_work(current):
            return
        self.loading_overlay_visible = True
        self.loading_overlay_angle = 0
        self.render_loading_overlay()
        self.schedule_loading_animation()

    def schedule_loading_animation(self):
        if (
            self.loading_animation_job is not None
            or not self.loading_overlay_visible
            or self.destroyed
        ):
            return
        self.loading_animation_job = self.after(90, self.advance_loading_animation)

    def advance_loading_animation(self):
        self.loading_animation_job = None
        if not self.loading_overlay_visible or self.destroyed:
            return
        self.loading_overlay_angle = (self.loading_overlay_angle + 24) % 360
        self.render_loading_overlay()
        self.schedule_loading_animation()

    def hide_loading_overlay(self):
        if self.loading_overlay_delay_job is not None:
            self.after_cancel(self.loading_overlay_delay_job)
            self.loading_overlay_delay_job = None
        if self.loading_animation_job is not None:
            self.after_cancel(self.loading_animation_job)
            self.loading_animation_job = None
        self.loading_overlay_visible = False
        self.preview_canvas.delete("preview-loading")

    def render_loading_overlay(self):
        self.preview_canvas.delete("preview-loading")
        if not self.loading_overlay_visible:
            return

        width = max(self.preview_canvas.winfo_width(), 320)
        height = max(self.preview_canvas.winfo_height(), 240)
        center_x = self.preview_canvas.canvasx(width / 2)
        center_y = self.preview_canvas.canvasy(height / 2)
        spinner_size = 38
        spinner_color = self._apply_appearance_mode(("#2563eb", "#93c5fd"))
        text_color = self._apply_appearance_mode(("gray35", "gray78"))

        self.preview_canvas.create_arc(
            center_x - spinner_size / 2,
            center_y - spinner_size / 2 - 14,
            center_x + spinner_size / 2,
            center_y + spinner_size / 2 - 14,
            start=self.loading_overlay_angle,
            extent=290,
            style=tk.ARC,
            outline=spinner_color,
            width=4,
            tags="preview-loading",
        )
        self.preview_canvas.create_text(
            center_x,
            center_y + 22,
            text="Loading preview",
            fill=text_color,
            font=("SF Pro Display", 14, "bold"),
            tags="preview-loading",
        )

    def display_preview_image(
        self,
        image: Image.Image,
        rel_x: float = 0.5,
        rel_y: float = 0.5,
        cache_key: tuple[object, ...] | None = None,
    ):
        canvas_width = max(self.preview_canvas.winfo_width(), 1)
        canvas_height = max(self.preview_canvas.winfo_height(), 1)
        display_width = image.width
        display_height = image.height
        self.preview_photo = self.get_preview_texture(cache_key, image)

        region_width = max(canvas_width, display_width)
        region_height = max(canvas_height, display_height)
        origin_x = max((region_width - display_width) / 2, 0)
        origin_y = max((region_height - display_height) / 2, 0)

        self.preview_canvas.delete("all")
        self.preview_canvas.configure(scrollregion=(0, 0, region_width, region_height))
        self.preview_canvas.create_image(origin_x, origin_y, anchor="nw", image=self.preview_photo)
        session = getattr(self, "session", None)
        current = getattr(session, "active_photo", None) if session is not None else None
        best_shots = getattr(self, "best_shots", ())
        if getattr(self, "compare_mode", False) and getattr(self, "compare_pair", None):
            c1 = self.compare_pair[0]
            sharpness_str = f" ({c1.sharpness:.0f})" if c1.sharpness is not None else ""
            best_str = " ★" if c1.is_best_shot else ""
            badge_text = f"[ 1 ] Keep Left{best_str}{sharpness_str}"
            self.preview_canvas.create_text(
                24,
                24,
                text=badge_text,
                fill="#22c55e",
                font=("SF Pro Text", 14, "bold"),
                anchor="nw",
                tags=("compare-badge",),
            )
        elif current and current in best_shots:
            self.preview_canvas.create_text(
                region_width - 24,
                24,
                text="★ Best Shot (Burst)",
                fill="#eab308",
                font=("SF Pro Text", 13, "bold"),
                anchor="ne",
                tags=("best-shot-badge",),
            )
        self.rendered_preview_size = (canvas_width, canvas_height)
        self.rendered_preview_scrollregion = (0, 0, region_width, region_height)
        self.restore_view_center(rel_x, rel_y)
        if self.loading_overlay_visible:
            self.render_loading_overlay()

    def refresh_preview(self, reload_image=False, preserve_view=False):
        self.preview_refresh_job = None
        current = self.session.active_photo
        if current is None:
            return

        canvas_width = self.preview_canvas.winfo_width()
        canvas_height = self.preview_canvas.winfo_height()
        if canvas_width < 8 or canvas_height < 8:
            self.schedule_preview_refresh()
            return

        if getattr(self, "compare_mode", False):
            self.compare_pair = self.compare_pair_selector.resolve_pair(
                self.session,
                getattr(self, "burst_info_map", None),
                getattr(self, "best_shots", None),
                candidate_offset=getattr(self, "compare_candidate_offset", 1),
            )
            self.refresh_compare_preview(preserve_view=preserve_view)

        self.preview_pipeline.set_viewport(canvas_width, canvas_height)
        rel_x, rel_y = self.get_view_center() if preserve_view else (0.5, 0.5)
        mode = "fit" if self.zoom_factor == 1.0 and not preserve_view else "zoom"
        request_key = (
            current,
            canvas_width,
            canvas_height,
            mode,
            self.settings.progressive_preview,
        )
        if request_key != self.preview_request_key:
            self.preview_request_key = request_key
            self.preview_request_id = self.preview_pipeline.start_preview_request(
                current,
                self.session.active_index,
                progressive_enabled=self.settings.progressive_preview,
            )

        lookup = self.preview_pipeline.get_best_preview(current)
        if lookup.unavailable:
            self.hide_loading_overlay()
            self.clear_preview(unavailable_preview_message(current))
            return

        if mode == "fit":
            if lookup.failed:
                self.hide_loading_overlay()
                self.clear_preview("Preview Error")
                return

            if lookup.image is not None and lookup.stage is not None:
                self.preview_source_path = None
                self.preview_source_image = None
                texture_key = (current, lookup.stage, lookup.image.width, lookup.image.height)
                self.display_preview_image(
                    lookup.image, rel_x=rel_x, rel_y=rel_y, cache_key=texture_key
                )
                if lookup.stage == "full":
                    self.hide_loading_overlay()
                    return
                self.schedule_preview_poll()
                self.schedule_loading_overlay_delay(request_key)
                return

            self.clear_preview("")
            self.schedule_preview_poll()
            self.schedule_loading_overlay_delay(request_key)
            return

        if reload_image or self.preview_source_path != current or self.preview_source_image is None:
            if self.preview_pipeline.has_source(current):
                self.preview_source_image = self.preview_pipeline.get_cached_source_copy(current)
                self.preview_source_path = (
                    current if self.preview_source_image is not None else None
                )
            else:
                if (
                    lookup.image is not None
                    and lookup.stage is not None
                    and self.settings.progressive_preview
                ):
                    texture_key = (current, lookup.stage, lookup.image.width, lookup.image.height)
                    self.display_preview_image(
                        lookup.image, rel_x=rel_x, rel_y=rel_y, cache_key=texture_key
                    )
                else:
                    self.clear_preview("")
                self.schedule_preview_poll()
                self.schedule_loading_overlay_delay(request_key)
                return

        if self.preview_source_image is None:
            self.clear_preview("Preview Error")
            return

        image_width = self.preview_source_image.width
        image_height = self.preview_source_image.height
        fit_scale = min(canvas_width / image_width, canvas_height / image_height)
        display_scale = max(fit_scale * self.zoom_factor, 0.01)
        display_width = max(round(image_width * display_scale), 1)
        display_height = max(round(image_height * display_scale), 1)

        resized = self.preview_source_image.resize(
            (display_width, display_height), gui_module().Image.Resampling.LANCZOS
        )
        texture_key = (current, "zoom", display_width, display_height, round(self.zoom_factor, 3))
        self.display_preview_image(resized, rel_x=rel_x, rel_y=rel_y, cache_key=texture_key)
        self.hide_loading_overlay()
