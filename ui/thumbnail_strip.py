"""Thumbnail Strip: the horizontal strip of asynchronously decoded thumbnails.

The Thumbnail Strip shows one thumbnail per photo group in the active photo
session. Decoding happens on a worker thread through the native core, and
the decoded bytes are turned into Tk images on the Tk main thread when the
results land.

Every method here is a mixin method: it operates on `self`, which is the
`App` that owns the widget tree. A Tk widget has exactly one parent, so
nothing here ever creates a widget against a root of its own.
"""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from pathlib import Path
from typing import TYPE_CHECKING

from session_startup import preview_paths_for
from ui.gui_targets import gui_module

if TYPE_CHECKING:
    from PIL import ImageTk

STRIP_THUMBNAIL_SIZE = 72

_MISSING = object()


class ThumbnailStripMixin:
    """The Thumbnail Strip and the worker that decodes its thumbnails."""

    def schedule_thumbnail_strip_rebuild(self, _event=None):
        if self.destroyed:
            return
        if self.thumbnail_rebuild_job is not None:
            self.after_cancel(self.thumbnail_rebuild_job)
        self.thumbnail_rebuild_job = self.after(60, self._flush_thumbnail_strip_rebuild)

    def _flush_thumbnail_strip_rebuild(self):
        self.thumbnail_rebuild_job = None
        self.refresh_thumbnail_strip(force_rebuild=True)

    def get_thumbnail_photo(self, path: Path) -> ImageTk.PhotoImage | None:
        raw = self.thumbnail_raws.get(path, _MISSING)
        if raw is _MISSING:
            # Nothing decoded yet: the native worker will fill it in and the
            # strip redraws once the result lands on the main thread.
            return None

        cached = self.thumbnail_cache.get(path)
        if cached is not None:
            self.thumbnail_cache.move_to_end(path)
            return cached

        if raw is None:
            return None

        try:
            photo = self.make_strip_photo_from_raw(path, raw)
        except (OSError, ValueError):
            photo = None
        self.thumbnail_cache[path] = photo
        if len(self.thumbnail_cache) > self.thumbnail_cache_limit:
            self.thumbnail_cache.popitem(last=False)
        return photo

    @staticmethod
    def make_strip_photo_from_raw(path: Path, raw: object) -> ImageTk.PhotoImage:
        # `Image` and `ImageTk` are resolved through the composition root so a
        # patch on `gui_app.Image` still reaches this code.
        gui = gui_module()
        image = gui.Image.frombytes("RGBA", (raw.width, raw.height), raw.data)
        return gui.ImageTk.PhotoImage(image)

    @staticmethod
    def decode_strip_thumbnail(path: object) -> object:
        """Run on the worker thread only; never on the Tk main thread."""
        thumbnail_rgba = gui_module().thumbnail_rgba
        try:
            return thumbnail_rgba(str(path), STRIP_THUMBNAIL_SIZE)
        except (OSError, ValueError, RuntimeError):
            return None

    def request_missing_strip_thumbnails(
        self, paths: tuple[Path, ...], visible_range: tuple[int, int]
    ) -> None:
        start, end = visible_range
        for index in range(start, end):
            path = paths[index]
            if self.thumbnail_cache.get(path, _MISSING) is not _MISSING:
                continue
            self.request_strip_thumbnail(path)

    def request_strip_thumbnail(self, path: Path) -> None:
        if self.destroyed or path in self.thumbnail_pending_requests:
            return
        self.thumbnail_pending_requests.add(path)
        self._ensure_thumbnail_worker()
        self.thumbnail_work_queue.put(path)
        self.schedule_thumbnail_result_poll()

    def _ensure_thumbnail_worker(self) -> None:
        if self.thumbnail_worker_thread is not None or self.destroyed:
            return
        self.thumbnail_work_queue = queue.Queue()
        self.thumbnail_result_queue = queue.Queue()
        worker = threading.Thread(
            target=self._run_thumbnail_worker,
            name="keep-or-nah-thumbnail-worker",
            daemon=True,
        )
        self.thumbnail_worker_thread = worker
        worker.start()

    def _run_thumbnail_worker(self) -> None:
        while True:
            path = self.thumbnail_work_queue.get()
            if path is None:
                return
            raw = self.decode_strip_thumbnail(path)
            burst_info = None
            if (
                raw is not None
                and hasattr(raw, "data")
                and hasattr(raw, "width")
                and hasattr(raw, "height")
            ):
                try:
                    mtime = path.stat().st_mtime
                    burst_info = self.burst_clusterer.analyze_photo(
                        path=path,
                        timestamp=mtime,
                        rgba=bytes(raw.data),
                        width=raw.width,
                        height=raw.height,
                    )
                except Exception:
                    pass
            if not self.destroyed:
                self.thumbnail_result_queue.put((path, raw, burst_info))

    def schedule_thumbnail_result_poll(self) -> None:
        if self.thumbnail_poll_job is not None or self.destroyed:
            return
        self.thumbnail_poll_job = self.after(60, self.drain_thumbnail_results)

    def drain_thumbnail_results(self) -> None:
        self.thumbnail_poll_job = None
        if self.destroyed:
            return
        updated = False
        new_bursts = False
        while True:
            try:
                item = self.thumbnail_result_queue.get_nowait()
            except queue.Empty:
                break
            path, raw = item[0], item[1]
            burst_info = item[2] if len(item) > 2 else None
            self.thumbnail_pending_requests.discard(path)
            self.thumbnail_raws[path] = raw
            if burst_info is not None:
                self.burst_info_map[path] = burst_info
                new_bursts = True
            updated = True
        if new_bursts:
            clusters = self.burst_clusterer.cluster(list(self.burst_info_map.values()))
            self.best_shots = {c.best_shot for c in clusters if c.is_burst}
            self.burst_shots = {p.path for c in clusters if c.is_burst for p in c.photos}
        if updated:
            self.prune_strip_thumbnail_state(set(preview_paths_for(self.session)))
            self.refresh_thumbnail_strip()
        if self.thumbnail_pending_requests:
            self.schedule_thumbnail_result_poll()

    def prune_strip_thumbnail_state(self, allowed_paths: set[Path]) -> None:
        evicted = False
        for path in list(self.thumbnail_raws.keys()):
            if path in allowed_paths or path in self.thumbnail_pending_requests:
                continue
            self.thumbnail_raws.pop(path, None)
            self.thumbnail_cache.pop(path, None)
            evicted = True
        if evicted and len(self.thumbnail_raws) > self.thumbnail_cache_limit:
            while len(self.thumbnail_raws) > self.thumbnail_cache_limit:
                self.thumbnail_raws.popitem(last=False)

    def refresh_thumbnail_strip(self, force_rebuild: bool = False):
        canvas_width = max(self.thumbnail_canvas.winfo_width(), 1)
        canvas_height = max(self.thumbnail_canvas.winfo_height(), 108)
        paths = preview_paths_for(self.session)
        if not paths:
            self.thumbnail_canvas.delete("all")
            self.thumbnail_refs = []
            self.thumbnail_signature = ()
            self.thumbnail_canvas_width = canvas_width
            self.thumbnail_canvas_height = canvas_height
            self.rendered_thumbnail_range = (-1, -1)
            self.rendered_active_index = None
            self.thumbnail_canvas.configure(scrollregion=(0, 0, canvas_width, canvas_height))
            return

        signature_changed = paths != self.thumbnail_signature
        width_changed = (
            canvas_width != self.thumbnail_canvas_width
            or canvas_height != self.thumbnail_canvas_height
        )
        region_width = self.get_thumbnail_region_width(len(paths), canvas_width)

        self.thumbnail_canvas.configure(scrollregion=(0, 0, region_width, canvas_height))
        self.thumbnail_signature = paths
        self.thumbnail_canvas_width = canvas_width
        self.thumbnail_canvas_height = canvas_height

        self.ensure_active_thumbnail_visible(len(paths), region_width)
        visible_range = self.get_visible_thumbnail_range(len(paths))

        if (
            force_rebuild
            or signature_changed
            or width_changed
            or visible_range != self.rendered_thumbnail_range
        ):
            self.redraw_thumbnail_strip(paths, visible_range)
        else:
            self.update_thumbnail_selection()

    def get_thumbnail_region_width(self, item_count: int, canvas_width: int | None = None) -> int:
        if canvas_width is None:
            canvas_width = max(self.thumbnail_canvas.winfo_width(), 1)
        content_width = self.thumbnail_left_padding + (item_count * self.thumbnail_pitch) + 2
        return max(canvas_width, content_width)

    def get_visible_thumbnail_range(self, item_count: int) -> tuple[int, int]:
        if item_count <= 0:
            return (0, 0)

        left_visible = self.thumbnail_canvas.canvasx(0)
        right_visible = left_visible + max(self.thumbnail_canvas.winfo_width(), 1)
        offset_left = max(left_visible - self.thumbnail_left_padding, 0)
        offset_right = max(right_visible - self.thumbnail_left_padding, 0)
        start = max(int(offset_left // self.thumbnail_pitch) - self.thumbnail_buffer, 0)
        end = min(int(offset_right // self.thumbnail_pitch) + self.thumbnail_buffer + 2, item_count)
        return (start, max(start, end))

    def redraw_thumbnail_strip(self, paths: tuple[Path, ...], visible_range: tuple[int, int]):
        self.thumbnail_canvas.delete("all")
        self.thumbnail_refs = []
        marker_color = self._apply_appearance_mode(("#111827", "#f8fafc"))
        thumb_center_y = self.thumbnail_top_padding + (self.thumbnail_size / 2)
        marker_y = self.thumbnail_top_padding + self.thumbnail_size + 10
        start, end = visible_range

        self.request_missing_strip_thumbnails(paths, visible_range)

        for index in range(start, end):
            path = paths[index]
            tag = f"thumb-{index}"
            x = self.thumbnail_left_padding + (index * self.thumbnail_pitch)
            center_x = x + (self.thumbnail_item_width / 2)

            thumbnail = self.get_thumbnail_photo(path)
            if thumbnail is not None:
                self.thumbnail_refs.append(thumbnail)
                self.thumbnail_canvas.create_image(
                    center_x,
                    thumb_center_y,
                    image=thumbnail,
                    tags=(tag, "thumbnail"),
                )
            else:
                self.thumbnail_canvas.create_text(
                    center_x,
                    thumb_center_y,
                    text="?",
                    fill=marker_color,
                    font=("SF Pro Display", 18, "bold"),
                    tags=(tag, "thumbnail"),
                )

            best_shots = getattr(self, "best_shots", ())
            if path in best_shots:
                self.thumbnail_canvas.create_text(
                    x + self.thumbnail_item_width - 8,
                    self.thumbnail_top_padding + 6,
                    text="★",
                    fill="#eab308",
                    font=("SF Pro Text", 12, "bold"),
                    anchor="ne",
                    tags=(tag, "thumbnail", "best-shot-badge"),
                )

            self.thumbnail_canvas.create_line(
                x + 18,
                marker_y,
                x + self.thumbnail_item_width - 18,
                marker_y,
                fill=marker_color,
                width=4,
                capstyle=tk.ROUND,
                state="normal" if index == self.session.active_index else "hidden",
                tags=(f"thumb-marker-{index}", tag, "thumbnail-marker"),
            )
            self.thumbnail_canvas.tag_bind(
                tag, "<Button-1>", lambda _event, i=index: self.select_photo_at_index(i)
            )
        self.rendered_thumbnail_range = visible_range
        self.rendered_active_index = self.session.active_index

    def update_thumbnail_selection(self):
        active_index = self.session.active_index if self.session.queue else None
        if active_index == self.rendered_active_index:
            return

        if self.rendered_active_index is not None:
            self.thumbnail_canvas.itemconfigure(
                f"thumb-marker-{self.rendered_active_index}", state="hidden"
            )
        if active_index is not None:
            self.thumbnail_canvas.itemconfigure(f"thumb-marker-{active_index}", state="normal")
        self.rendered_active_index = active_index

    def ensure_active_thumbnail_visible(self, item_count: int, region_width: int | None = None):
        if item_count <= 0:
            return

        if region_width is None:
            region_width = self.get_thumbnail_region_width(item_count)
        viewport_width = max(self.thumbnail_canvas.winfo_width(), 1)
        left_visible = self.thumbnail_canvas.canvasx(0)
        right_visible = left_visible + viewport_width
        item_left = self.thumbnail_left_padding + (self.session.active_index * self.thumbnail_pitch)
        item_right = item_left + self.thumbnail_item_width

        if item_left < left_visible:
            target_left = item_left
        elif item_right > right_visible:
            target_left = item_right - viewport_width
        else:
            return

        max_offset = max(region_width - viewport_width, 0)
        clamped_left = min(max(target_left, 0), max_offset)
        fraction = clamped_left / max(max_offset, 1)
        self.thumbnail_canvas.xview_moveto(min(max(fraction, 0.0), 1.0))

    def handle_thumbnail_wheel(self, event):
        steps = max(1, int(abs(event.delta) / 120)) if event.delta else 1
        direction = -1 if event.delta > 0 else 1
        self.thumbnail_canvas.xview_scroll(direction * steps * 72, "units")
        self.refresh_thumbnail_strip()
        return "break"

    def handle_thumbnail_linux_wheel(self, event):
        direction = -1 if getattr(event, "num", None) == 4 else 1
        self.thumbnail_canvas.xview_scroll(direction * 72, "units")
        self.refresh_thumbnail_strip()
        return "break"
