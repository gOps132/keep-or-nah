"""Zoom, pan, and viewport centering for the preview canvases.

The preview canvas is a scrollable viewport over a photo that is usually
larger than the window. This module owns the zoom factor, the pan gestures,
and the relative viewport position that survives a zoom change.

Every method here is a mixin method: it operates on `self`, which is the
`App` that owns the widget tree.
"""

from __future__ import annotations

import contextlib


class ViewportMixin:
    """Zoom, pan, and viewport centering."""

    def reset_zoom_state(self):
        self.zoom_factor = 1.0

    def zoom_in(self):
        self.set_zoom(self.zoom_factor * 1.2)

    def zoom_out(self):
        self.set_zoom(self.zoom_factor / 1.2)

    def reset_zoom(self):
        self.set_zoom(1.0)

    def set_zoom(self, value: float):
        current = self.session.active_photo
        if current is None:
            return

        clamped = min(max(value, self.min_zoom_factor), self.max_zoom_factor)
        if abs(clamped - self.zoom_factor) < 0.001:
            return

        self.zoom_factor = clamped
        self.refresh_preview(preserve_view=True)
        self.refresh_ui()

    def get_view_center(self) -> tuple[float, float]:
        bbox = self.preview_canvas.bbox("all")
        if not bbox:
            return (0.5, 0.5)

        left, top, right, bottom = bbox
        total_width = max(right - left, 1)
        total_height = max(bottom - top, 1)
        viewport_width = max(self.preview_canvas.winfo_width(), 1)
        viewport_height = max(self.preview_canvas.winfo_height(), 1)
        center_x = self.preview_canvas.canvasx(viewport_width / 2)
        center_y = self.preview_canvas.canvasy(viewport_height / 2)
        rel_x = min(max((center_x - left) / total_width, 0.0), 1.0)
        rel_y = min(max((center_y - top) / total_height, 0.0), 1.0)
        return (rel_x, rel_y)

    def restore_view_center(self, rel_x: float, rel_y: float):
        bbox = self.preview_canvas.bbox("all")
        if not bbox:
            return

        left, top, right, bottom = bbox
        total_width = max(right - left, 1)
        total_height = max(bottom - top, 1)
        viewport_width = max(self.preview_canvas.winfo_width(), 1)
        viewport_height = max(self.preview_canvas.winfo_height(), 1)

        if total_width <= viewport_width:
            self.preview_canvas.xview_moveto(0)
        else:
            center_x = left + rel_x * total_width
            left_target = center_x - (viewport_width / 2)
            fraction = (left_target - left) / max(total_width - viewport_width, 1)
            self.preview_canvas.xview_moveto(min(max(fraction, 0.0), 1.0))

        if total_height <= viewport_height:
            self.preview_canvas.yview_moveto(0)
        else:
            center_y = top + rel_y * total_height
            top_target = center_y - (viewport_height / 2)
            fraction = (top_target - top) / max(total_height - viewport_height, 1)
            self.preview_canvas.yview_moveto(min(max(fraction, 0.0), 1.0))

    def start_pan(self, event):
        if hasattr(self, "preview_canvas") and hasattr(self.preview_canvas, "scan_mark"):
            self.preview_canvas.scan_mark(event.x, event.y)
        if (
            getattr(self, "compare_mode", False)
            and hasattr(self, "compare_canvas")
            and hasattr(self.compare_canvas, "scan_mark")
        ):
            with contextlib.suppress(Exception):
                self.compare_canvas.scan_mark(event.x, event.y)

    def drag_pan(self, event):
        if hasattr(self, "preview_canvas") and hasattr(self.preview_canvas, "scan_dragto"):
            self.preview_canvas.scan_dragto(event.x, event.y, gain=1)
        if (
            getattr(self, "compare_mode", False)
            and hasattr(self, "compare_canvas")
            and hasattr(self.compare_canvas, "scan_dragto")
        ):
            with contextlib.suppress(Exception):
                self.compare_canvas.scan_dragto(event.x, event.y, gain=1)

    def handle_zoom_mousewheel(self, event):
        if event.delta > 0:
            self.zoom_in()
        elif event.delta < 0:
            self.zoom_out()
        return "break"

    def handle_linux_zoom_wheel(self, event):
        if getattr(event, "num", None) == 4:
            self.zoom_in()
        elif getattr(event, "num", None) == 5:
            self.zoom_out()
        return "break"

    def handle_magnify(self, event):
        delta = getattr(event, "delta", 0)
        if delta > 0:
            self.zoom_in()
        elif delta < 0:
            self.zoom_out()
        return "break"

    def handle_mousewheel(self, event):
        steps = max(1, int(abs(event.delta) / 120)) if event.delta else 1
        direction = -1 if event.delta > 0 else 1
        if hasattr(self, "preview_canvas") and hasattr(self.preview_canvas, "yview_scroll"):
            self.preview_canvas.yview_scroll(direction * steps, "units")
        if (
            getattr(self, "compare_mode", False)
            and hasattr(self, "compare_canvas")
            and hasattr(self.compare_canvas, "yview_scroll")
        ):
            with contextlib.suppress(Exception):
                self.compare_canvas.yview_scroll(direction * steps, "units")
        return "break"

    def handle_shift_mousewheel(self, event):
        steps = max(1, int(abs(event.delta) / 120)) if event.delta else 1
        direction = -1 if event.delta > 0 else 1
        if hasattr(self, "preview_canvas") and hasattr(self.preview_canvas, "xview_scroll"):
            self.preview_canvas.xview_scroll(direction * steps, "units")
        if (
            getattr(self, "compare_mode", False)
            and hasattr(self, "compare_canvas")
            and hasattr(self.compare_canvas, "xview_scroll")
        ):
            with contextlib.suppress(Exception):
                self.compare_canvas.xview_scroll(direction * steps, "units")
        return "break"

    def handle_linux_wheel(self, event):
        direction = -1 if getattr(event, "num", None) == 4 else 1
        if hasattr(self, "preview_canvas") and hasattr(self.preview_canvas, "yview_scroll"):
            self.preview_canvas.yview_scroll(direction, "units")
        if (
            getattr(self, "compare_mode", False)
            and hasattr(self, "compare_canvas")
            and hasattr(self.compare_canvas, "yview_scroll")
        ):
            with contextlib.suppress(Exception):
                self.compare_canvas.yview_scroll(direction, "units")
        return "break"

    def handle_linux_shift_wheel(self, event):
        direction = -1 if getattr(event, "num", None) == 4 else 1
        if hasattr(self, "preview_canvas") and hasattr(self.preview_canvas, "xview_scroll"):
            self.preview_canvas.xview_scroll(direction, "units")
        if (
            getattr(self, "compare_mode", False)
            and hasattr(self, "compare_canvas")
            and hasattr(self.compare_canvas, "xview_scroll")
        ):
            with contextlib.suppress(Exception):
                self.compare_canvas.xview_scroll(direction, "units")
        return "break"
