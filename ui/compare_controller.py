"""Split Comparison: the 2-up side-by-side view and its action buttons.

Split Comparison shows two photos of the active photo session next to each
other so the photographer can inspect them together and triage them in one
gesture. The left canvas is the regular preview canvas; the right canvas is
the comparison canvas. Both are owned by the `App` widget tree, so the
methods here only draw into them.

Every method here is a mixin method: it operates on `self`, which is the
`App` that owns the widget tree.
"""

from __future__ import annotations

from tkinter import messagebox
from typing import TYPE_CHECKING

from photo_session import PhotoSessionError
from session_startup import preview_paths_for
from split_compare import CompareCandidate
from ui.gui_targets import gui_module

if TYPE_CHECKING:
    from PIL import Image


class CompareControllerMixin:
    """Split Comparison and the action buttons it shares with the preview."""

    def toggle_compare_mode(self):
        self.compare_mode = not self.compare_mode
        if self.compare_mode:
            if hasattr(self, "compare_mode_button") and self.compare_mode_button:
                self.compare_mode_button.configure(text="1-Up (C)", fg_color="#3b82f6")
            if hasattr(self, "preview_host") and hasattr(self, "compare_canvas"):
                self.preview_host.grid_columnconfigure(0, weight=1)
                self.preview_host.grid_columnconfigure(1, weight=1)
                self.preview_canvas.grid_configure(padx=(0, 4))
                self.compare_canvas.grid(row=0, column=1, sticky="nsew", padx=(4, 0))
        else:
            if hasattr(self, "compare_mode_button") and self.compare_mode_button:
                self.compare_mode_button.configure(text="2-Up (C)", fg_color=["#3a7ebf", "#1f538d"])
            if hasattr(self, "preview_host") and hasattr(self, "compare_canvas"):
                self.compare_canvas.grid_remove()
                self.preview_host.grid_columnconfigure(1, weight=0)
                self.preview_canvas.grid_configure(padx=0)
            self.compare_pair = None
            self.compare_photo = None
            self.compare_source_image = None
            self.compare_source_path = None
        self.refresh_preview()
        self.refresh_ui()

    def pick_compare_candidate(self, choice: int):
        if not getattr(self, "compare_mode", False) or not getattr(self, "compare_pair", None):
            return
        pair = self.compare_pair
        try:
            self.compare_pair_selector.pick(pair, choice, self.session)
        except PhotoSessionError as error:
            messagebox.showerror("Keep or Nah", str(error))
            return
        except OSError as error:
            messagebox.showerror("Keep or Nah", f"Could not process the file.\n\n{error}")
            return

        self.preview_pipeline.reset(preview_paths_for(self.session))
        self.prune_preview_texture_cache(set(preview_paths_for(self.session)))
        self.reset_zoom_state()
        self.preview_source_path = None
        self.preview_source_image = None
        self.compare_source_path = None
        self.compare_source_image = None
        self.reset_preview_request_state()
        self.persist_session()
        self.refresh_ui()
        self.refresh_preview()

    def display_compare_image(
        self,
        image: Image.Image,
        rel_x: float = 0.5,
        rel_y: float = 0.5,
        cache_key: tuple[object, ...] | None = None,
        candidate: CompareCandidate | None = None,
    ):
        if not hasattr(self, "compare_canvas"):
            return
        canvas_width = max(self.compare_canvas.winfo_width(), 1)
        canvas_height = max(self.compare_canvas.winfo_height(), 1)
        display_width = image.width
        display_height = image.height
        self.compare_photo = self.get_preview_texture(cache_key, image)

        region_width = max(canvas_width, display_width)
        region_height = max(canvas_height, display_height)
        origin_x = max((region_width - display_width) / 2, 0)
        origin_y = max((region_height - display_height) / 2, 0)

        self.compare_canvas.delete("all")
        self.compare_canvas.configure(scrollregion=(0, 0, region_width, region_height))
        self.compare_canvas.create_image(origin_x, origin_y, anchor="nw", image=self.compare_photo)
        if candidate is not None:
            sharpness_str = (
                f" ({candidate.sharpness:.0f})" if candidate.sharpness is not None else ""
            )
            best_str = " ★" if candidate.is_best_shot else ""
            badge_text = f"[ 2 ] Keep Right{best_str}{sharpness_str}"
            self.compare_canvas.create_text(
                24,
                24,
                text=badge_text,
                fill="#3b82f6",
                font=("SF Pro Text", 14, "bold"),
                anchor="nw",
                tags=("compare-badge",),
            )
        self.restore_compare_view_center(rel_x, rel_y)

    def clear_compare_preview(self, message: str = ""):
        if not hasattr(self, "compare_canvas"):
            return
        self.compare_canvas.delete("all")
        self.compare_photo = None
        if message:
            width = max(self.compare_canvas.winfo_width(), 320)
            height = max(self.compare_canvas.winfo_height(), 240)
            self.compare_canvas.create_text(
                self.compare_canvas.canvasx(width / 2),
                self.compare_canvas.canvasy(height / 2),
                text=message,
                fill=self._apply_appearance_mode(("gray45", "gray65")),
                font=("SF Pro Display", 22, "bold"),
            )

    def restore_compare_view_center(self, rel_x: float, rel_y: float):
        if not hasattr(self, "compare_canvas") or not hasattr(self.compare_canvas, "bbox"):
            return
        bbox = self.compare_canvas.bbox("all")
        if not bbox:
            return

        left, top, right, bottom = bbox
        total_width = max(right - left, 1)
        total_height = max(bottom - top, 1)
        viewport_width = max(self.compare_canvas.winfo_width(), 1)
        viewport_height = max(self.compare_canvas.winfo_height(), 1)

        if total_width <= viewport_width:
            if hasattr(self.compare_canvas, "xview_moveto"):
                self.compare_canvas.xview_moveto(0)
        else:
            center_x = left + rel_x * total_width
            left_target = center_x - (viewport_width / 2)
            fraction = (left_target - left) / max(total_width - viewport_width, 1)
            if hasattr(self.compare_canvas, "xview_moveto"):
                self.compare_canvas.xview_moveto(min(max(fraction, 0.0), 1.0))

        if total_height <= viewport_height:
            if hasattr(self.compare_canvas, "yview_moveto"):
                self.compare_canvas.yview_moveto(0)
        else:
            center_y = top + rel_y * total_height
            top_target = center_y - (viewport_height / 2)
            fraction = (top_target - top) / max(total_height - viewport_height, 1)
            if hasattr(self.compare_canvas, "yview_moveto"):
                self.compare_canvas.yview_moveto(min(max(fraction, 0.0), 1.0))

    def refresh_compare_preview(self, preserve_view: bool = False):
        if not hasattr(self, "compare_canvas") or not getattr(self, "compare_mode", False):
            return
        pair = self.compare_pair_selector.resolve_pair(
            self.session,
            getattr(self, "burst_info_map", None),
            getattr(self, "best_shots", None),
            candidate_offset=getattr(self, "compare_candidate_offset", 1),
        )
        self.compare_pair = pair
        if pair is None:
            self.clear_compare_preview("Need ≥2 photos to compare")
            return

        c2 = pair[1]
        canvas_width = max(self.compare_canvas.winfo_width(), 1)
        canvas_height = max(self.compare_canvas.winfo_height(), 1)
        if canvas_width < 8 or canvas_height < 8:
            return

        rel_x, rel_y = self.get_view_center() if preserve_view else (0.5, 0.5)
        mode = "fit" if self.zoom_factor == 1.0 and not preserve_view else "zoom"

        lookup = self.preview_pipeline.get_best_preview(c2.preview_path)
        if lookup.image is None or (
            mode != "fit" and not self.preview_pipeline.has_source(c2.preview_path)
        ):
            c2_idx = next((i for i, g in enumerate(self.session.queue) if g.stem == c2.stem), 0)
            self.preview_pipeline.start_preview_request(
                c2.preview_path,
                c2_idx,
                progressive_enabled=self.settings.progressive_preview,
            )

        if mode == "fit":
            if lookup.image is not None and lookup.stage is not None:
                texture_key = (
                    c2.preview_path,
                    lookup.stage,
                    lookup.image.width,
                    lookup.image.height,
                )
                self.display_compare_image(
                    lookup.image, rel_x=rel_x, rel_y=rel_y, cache_key=texture_key, candidate=c2
                )
            else:
                self.clear_compare_preview("Loading...")
        elif self.preview_pipeline.has_source(c2.preview_path):
            source_img = self.preview_pipeline.get_cached_source_copy(c2.preview_path)
            if source_img is not None:
                image_width = source_img.width
                image_height = source_img.height
                fit_scale = min(canvas_width / image_width, canvas_height / image_height)
                display_scale = max(fit_scale * self.zoom_factor, 0.01)
                display_width = max(round(image_width * display_scale), 1)
                display_height = max(round(image_height * display_scale), 1)
                resized = source_img.resize(
                    (display_width, display_height), gui_module().Image.Resampling.LANCZOS
                )
                texture_key = (
                    c2.preview_path,
                    "zoom",
                    display_width,
                    display_height,
                    round(self.zoom_factor, 3),
                )
                self.display_compare_image(
                    resized, rel_x=rel_x, rel_y=rel_y, cache_key=texture_key, candidate=c2
                )
        elif (
            lookup.image is not None
            and lookup.stage is not None
            and self.settings.progressive_preview
        ):
            texture_key = (c2.preview_path, lookup.stage, lookup.image.width, lookup.image.height)
            self.display_compare_image(
                lookup.image, rel_x=rel_x, rel_y=rel_y, cache_key=texture_key, candidate=c2
            )
        else:
            self.clear_compare_preview("Loading...")

    def toggle_action_buttons(self):
        self.show_action_buttons = not self.show_action_buttons
        self.update_action_button_visibility()
        self.schedule_preview_refresh()

    def update_action_button_visibility(self):
        button_text = "Hide Buttons" if self.show_action_buttons else "Show Buttons"
        self.toggle_actions_button.configure(text=button_text)
        if self.show_action_buttons:
            self.footer_frame.grid()
        else:
            self.footer_frame.grid_remove()
