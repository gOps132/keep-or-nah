from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageOps, ImageTk

from photo_session import PhotoSession, PhotoSessionError


class ClassicApp(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title("Keep or Nah")
        self.geometry("1100x780")
        self.minsize(920, 660)
        self.session = PhotoSession()
        self.action_mode_var = tk.StringVar(value="move")
        self.preview_photo = None
        self.preview_source_image = None
        self.preview_source_path = None
        self.preview_refresh_job = None
        self.thumbnail_refs: list[ImageTk.PhotoImage] = []
        self.thumbnail_cache: OrderedDict[Path, ImageTk.PhotoImage | None] = OrderedDict()
        self.thumbnail_cache_limit = 192
        self.thumbnail_signature: tuple[Path, ...] = ()
        self.thumbnail_canvas_width = 0
        self.thumbnail_canvas_height = 108
        self.rendered_thumbnail_range = (-1, -1)
        self.rendered_active_index: int | None = None
        self.thumbnail_left_padding = 12
        self.thumbnail_top_padding = 10
        self.thumbnail_item_width = 84
        self.thumbnail_item_gap = 10
        self.thumbnail_pitch = self.thumbnail_item_width + self.thumbnail_item_gap
        self.thumbnail_size = 72
        self.thumbnail_buffer = 4
        self.zoom_factor = 1.0
        self.min_zoom_factor = 0.25
        self.max_zoom_factor = 8.0
        self.show_action_buttons = True
        self.last_browsed_dir: Path | None = None

        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        self.setup_styles()
        self.setup_body()
        self.setup_footer()
        self.bind_shortcuts()
        self.refresh_ui()

    def setup_styles(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

    def setup_body(self):
        self.main_frame = ttk.Frame(self, padding=(16, 0, 16, 0))
        self.main_frame.grid(row=0, column=0, sticky="nsew", pady=(16, 0))
        self.main_frame.columnconfigure(0, weight=1)
        self.main_frame.rowconfigure(1, weight=1)

        control_bar = ttk.Frame(self.main_frame)
        control_bar.grid(row=0, column=0, sticky="ew", pady=(16, 10))
        control_bar.columnconfigure((0, 1, 2, 3, 4, 5, 6, 7, 8, 9), weight=1)

        self.source_button = ttk.Button(control_bar, text="Source", command=self.choose_source_folder)
        self.source_button.grid(row=0, column=0, padx=(0, 6), sticky="ew")

        self.keep_folder_button = ttk.Button(control_bar, text="Keep", command=self.choose_keep_folder)
        self.keep_folder_button.grid(row=0, column=1, padx=6, sticky="ew")

        self.nah_folder_button = ttk.Button(control_bar, text="Nah", command=self.choose_nah_folder)
        self.nah_folder_button.grid(row=0, column=2, padx=6, sticky="ew")

        mode_frame = ttk.Frame(control_bar)
        mode_frame.grid(row=0, column=3, padx=6)
        ttk.Radiobutton(
            mode_frame,
            text="Move",
            value="move",
            variable=self.action_mode_var,
            command=self.handle_action_mode_change,
        ).grid(row=0, column=0, padx=(0, 4))
        ttk.Radiobutton(
            mode_frame,
            text="Copy",
            value="copy",
            variable=self.action_mode_var,
            command=self.handle_action_mode_change,
        ).grid(row=0, column=1)

        self.undo_button = ttk.Button(control_bar, text="Undo", command=self.undo_last_action)
        self.undo_button.grid(row=0, column=4, padx=6, sticky="ew")

        self.load_button = ttk.Button(control_bar, text="Load", command=self.load_queue)
        self.load_button.grid(row=0, column=5, padx=6, sticky="ew")

        self.toggle_actions_button = ttk.Button(
            control_bar,
            text="Hide Buttons",
            command=self.toggle_action_buttons,
        )
        self.toggle_actions_button.grid(row=0, column=6, padx=6, sticky="ew")

        self.zoom_out_button = ttk.Button(control_bar, text="-", command=self.zoom_out)
        self.zoom_out_button.grid(row=0, column=7, padx=(6, 3), sticky="ew")

        self.zoom_fit_button = ttk.Button(control_bar, text="Fit", command=self.reset_zoom)
        self.zoom_fit_button.grid(row=0, column=8, padx=3, sticky="ew")

        self.zoom_in_button = ttk.Button(control_bar, text="+", command=self.zoom_in)
        self.zoom_in_button.grid(row=0, column=9, padx=(3, 0), sticky="ew")

        preview_host = ttk.Frame(self.main_frame)
        preview_host.grid(row=1, column=0, sticky="nsew", pady=(0, 12))
        preview_host.columnconfigure(0, weight=1)
        preview_host.rowconfigure(0, weight=1)

        self.preview_canvas = tk.Canvas(
            preview_host,
            bg=self.cget("background"),
            bd=0,
            highlightthickness=0,
            xscrollincrement=1,
            yscrollincrement=1,
        )
        self.preview_canvas.grid(row=0, column=0, sticky="nsew")
        self.preview_canvas.bind("<Configure>", self.schedule_preview_refresh)
        self.preview_canvas.bind("<MouseWheel>", self.handle_mousewheel)
        self.preview_canvas.bind("<Shift-MouseWheel>", self.handle_shift_mousewheel)
        self.preview_canvas.bind("<Button-4>", self.handle_linux_wheel)
        self.preview_canvas.bind("<Button-5>", self.handle_linux_wheel)
        self.preview_canvas.bind("<Shift-Button-4>", self.handle_linux_shift_wheel)
        self.preview_canvas.bind("<Shift-Button-5>", self.handle_linux_shift_wheel)
        self.preview_canvas.bind("<ButtonPress-1>", self.start_pan)
        self.preview_canvas.bind("<B1-Motion>", self.drag_pan)

        self.bind_if_supported(self.preview_canvas, "<Command-MouseWheel>", self.handle_zoom_mousewheel)
        self.bind_if_supported(self.preview_canvas, "<Control-MouseWheel>", self.handle_zoom_mousewheel)
        self.bind_if_supported(self.preview_canvas, "<Control-Button-4>", self.handle_linux_zoom_wheel)
        self.bind_if_supported(self.preview_canvas, "<Control-Button-5>", self.handle_linux_zoom_wheel)
        self.bind_if_supported(self.preview_canvas, "<Command-Button-4>", self.handle_linux_zoom_wheel)
        self.bind_if_supported(self.preview_canvas, "<Command-Button-5>", self.handle_linux_zoom_wheel)
        self.bind_if_supported(self.preview_canvas, "<Magnify>", self.handle_magnify)

        self.queue_host = ttk.Frame(self.main_frame)
        self.queue_host.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        self.queue_host.columnconfigure(0, weight=1)

        self.thumbnail_canvas = tk.Canvas(
            self.queue_host,
            bg=self.cget("background"),
            bd=0,
            highlightthickness=0,
            height=108,
            xscrollincrement=1,
        )
        self.thumbnail_canvas.grid(row=0, column=0, sticky="ew")
        self.thumbnail_canvas.bind("<Configure>", lambda _event: self.refresh_thumbnail_strip(force_rebuild=True))
        self.thumbnail_canvas.bind("<MouseWheel>", self.handle_thumbnail_wheel)
        self.thumbnail_canvas.bind("<Button-4>", self.handle_thumbnail_linux_wheel)
        self.thumbnail_canvas.bind("<Button-5>", self.handle_thumbnail_linux_wheel)

    def setup_footer(self):
        self.footer_frame = ttk.Frame(self, padding=(16, 0, 16, 16))
        self.footer_frame.grid(row=1, column=0, sticky="ew")
        self.footer_frame.columnconfigure((0, 1), weight=1)

        self.nah_button = ttk.Button(self.footer_frame, text="Nah", command=lambda: self.sort_current_photo("nah"))
        self.nah_button.grid(row=0, column=0, padx=(0, 6), sticky="ew")

        self.keep_button = ttk.Button(self.footer_frame, text="Keep", command=lambda: self.sort_current_photo("keep"))
        self.keep_button.grid(row=0, column=1, padx=(6, 0), sticky="ew")

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

    def folder_label(self, label: str, path: Path | None) -> str:
        if path is None:
            return label

        name = path.name or str(path)
        if len(name) > 18:
            name = f"{name[:15]}..."
        return f"{label}: {name}"

    def update_selector_buttons(self):
        self.source_button.configure(text=self.folder_label("Source", self.session.source_dir))
        self.keep_folder_button.configure(text=self.folder_label("Keep", self.session.keep_dir))
        self.nah_folder_button.configure(text=self.folder_label("Nah", self.session.nah_dir))

    def bind_shortcuts(self):
        self.bind("<Left>", lambda _event: self.navigate_selection(-1))
        self.bind("<Right>", lambda _event: self.navigate_selection(1))
        self.bind("<KeyPress-a>", lambda _event: self.sort_current_photo("nah"))
        self.bind("<KeyPress-d>", lambda _event: self.sort_current_photo("keep"))

        modifier = "Command" if sys.platform == "darwin" else "Control"
        self.bind(f"<{modifier}-z>", self.handle_undo_shortcut)
        self.bind(f"<{modifier}-Z>", self.handle_undo_shortcut)
        self.bind(f"<{modifier}-minus>", self.handle_zoom_out_shortcut)
        self.bind(f"<{modifier}-equal>", self.handle_zoom_in_shortcut)
        self.bind(f"<{modifier}-plus>", self.handle_zoom_in_shortcut)
        self.bind(f"<{modifier}-0>", self.handle_zoom_reset_shortcut)

    def bind_if_supported(self, widget, sequence: str, handler):
        try:
            widget.bind(sequence, handler)
        except tk.TclError:
            return

    def handle_undo_shortcut(self, _event=None):
        self.undo_last_action()

    def handle_zoom_in_shortcut(self, _event=None):
        self.zoom_in()

    def handle_zoom_out_shortcut(self, _event=None):
        self.zoom_out()

    def handle_zoom_reset_shortcut(self, _event=None):
        self.reset_zoom()

    def choose_source_folder(self):
        path = filedialog.askdirectory(title="Choose Source Folder", initialdir=self.get_initial_directory())
        if not path:
            return

        self.session.set_source_dir(path)
        self.last_browsed_dir = Path(path)
        self.thumbnail_cache = OrderedDict()
        self.thumbnail_refs = []
        self.thumbnail_signature = ()
        self.thumbnail_canvas_width = 0
        self.thumbnail_canvas_height = 108
        self.rendered_thumbnail_range = (-1, -1)
        self.rendered_active_index = None
        self.session.reset_queue()
        self.reset_zoom_state()
        self.clear_preview()
        self.refresh_ui()

    def choose_keep_folder(self):
        path = filedialog.askdirectory(title="Choose Keep Folder", initialdir=self.get_initial_directory())
        if not path:
            return

        self.session.set_keep_dir(path)
        self.last_browsed_dir = Path(path)
        self.refresh_ui()

    def choose_nah_folder(self):
        path = filedialog.askdirectory(title="Choose Nah Folder", initialdir=self.get_initial_directory())
        if not path:
            return

        self.session.set_nah_dir(path)
        self.last_browsed_dir = Path(path)
        self.refresh_ui()

    def get_initial_directory(self) -> str | None:
        candidates = [
            self.last_browsed_dir,
            self.session.source_dir,
            self.session.keep_dir,
            self.session.nah_dir,
        ]
        for candidate in candidates:
            if candidate is not None and candidate.exists():
                return str(candidate)
        return None

    def handle_action_mode_change(self):
        self.session.set_action_mode(self.action_mode_var.get())
        self.refresh_ui()

    def select_photo_at_index(self, index: int):
        if self.session.set_active_index(index) is None:
            return

        self.reset_zoom_state()
        self.preview_source_path = None
        self.refresh_ui()
        self.refresh_preview(reload_image=True)

    def navigate_selection(self, offset: int):
        if self.session.move_active(offset) is None:
            return

        self.reset_zoom_state()
        self.preview_source_path = None
        self.refresh_ui()
        self.refresh_preview(reload_image=True)

    def load_queue(self):
        try:
            count = self.session.load_queue()
        except PhotoSessionError as error:
            messagebox.showerror("Keep or Nah", str(error))
            return

        if count == 0:
            self.reset_zoom_state()
            self.clear_preview("No Photo")
            self.refresh_ui()
            messagebox.showinfo("Keep or Nah", "No supported images found.")
            return

        self.reset_zoom_state()
        self.preview_source_path = None
        self.refresh_ui()
        self.refresh_preview(reload_image=True)

    def sort_current_photo(self, decision):
        try:
            self.session.decide(decision)
        except PhotoSessionError as error:
            messagebox.showerror("Keep or Nah", str(error))
            return
        except OSError as error:
            messagebox.showerror("Keep or Nah", f"Could not process the file.\n\n{error}")
            return

        self.reset_zoom_state()
        self.preview_source_path = None
        self.refresh_ui()
        self.refresh_preview(reload_image=True)

    def undo_last_action(self):
        try:
            self.session.undo()
        except PhotoSessionError as error:
            if not self.session.can_undo and str(error) == "There is nothing to undo.":
                return
            messagebox.showerror("Keep or Nah", str(error))
            return
        except OSError as error:
            messagebox.showerror("Keep or Nah", f"Could not undo the last action.\n\n{error}")
            return

        self.reset_zoom_state()
        self.preview_source_path = None
        self.refresh_ui()
        self.refresh_preview(reload_image=True)

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

    def refresh_ui(self):
        current = self.session.active_photo
        self.update_selector_buttons()
        self.update_action_button_visibility()

        if self.session.source_dir is None:
            self.load_button.state(["disabled"])
        else:
            self.load_button.state(["!disabled"])

        if self.session.can_undo:
            self.undo_button.state(["!disabled"])
        else:
            self.undo_button.state(["disabled"])

        zoom_state = ["!disabled"] if current is not None else ["disabled"]
        self.zoom_in_button.state(zoom_state)
        self.zoom_out_button.state(zoom_state)
        self.zoom_fit_button.state(zoom_state)

        action_state = ["!disabled"] if current is not None else ["disabled"]
        self.keep_button.state(action_state)
        self.nah_button.state(action_state)
        self.refresh_thumbnail_strip()

        if current is None:
            if self.session.total_loaded:
                self.clear_preview("Done")
            else:
                self.clear_preview("No Photo")

        self.focus_set()

    def schedule_preview_refresh(self, _event=None):
        if self.preview_refresh_job is not None:
            self.after_cancel(self.preview_refresh_job)
        self.preview_refresh_job = self.after(80, self.refresh_preview_or_placeholder)

    def refresh_preview_or_placeholder(self):
        current = self.session.active_photo
        if current is None:
            if self.session.total_loaded:
                self.clear_preview("Done")
            else:
                self.clear_preview("No Photo")
            self.preview_refresh_job = None
            return
        self.refresh_preview()

    def clear_preview(self, message="No Photo"):
        self.preview_source_image = None
        self.preview_source_path = None
        self.preview_photo = None
        self.preview_canvas.delete("all")
        width = max(self.preview_canvas.winfo_width(), 320)
        height = max(self.preview_canvas.winfo_height(), 240)
        self.preview_canvas.configure(scrollregion=(0, 0, width, height))
        self.preview_canvas.create_text(
            width / 2,
            height / 2,
            text=message,
            fill="#6b7280",
            font=("Helvetica", 20, "bold"),
        )

    def get_thumbnail_photo(self, path: Path) -> ImageTk.PhotoImage | None:
        if path in self.thumbnail_cache:
            cached = self.thumbnail_cache[path]
            self.thumbnail_cache.move_to_end(path)
            return cached

        try:
            with Image.open(path) as image:
                prepared = ImageOps.exif_transpose(image).convert("RGBA")
                prepared.thumbnail((72, 72), Image.Resampling.LANCZOS)
                thumbnail = ImageTk.PhotoImage(prepared)
        except OSError:
            thumbnail = None

        self.thumbnail_cache[path] = thumbnail
        if len(self.thumbnail_cache) > self.thumbnail_cache_limit:
            self.thumbnail_cache.popitem(last=False)
        return thumbnail

    def refresh_thumbnail_strip(self, force_rebuild: bool = False):
        canvas_width = max(self.thumbnail_canvas.winfo_width(), 1)
        canvas_height = max(self.thumbnail_canvas.winfo_height(), 108)
        paths = tuple(self.session.queue)
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
        width_changed = canvas_width != self.thumbnail_canvas_width or canvas_height != self.thumbnail_canvas_height
        region_width = self.get_thumbnail_region_width(len(paths), canvas_width)

        self.thumbnail_canvas.configure(scrollregion=(0, 0, region_width, canvas_height))
        self.thumbnail_signature = paths
        self.thumbnail_canvas_width = canvas_width
        self.thumbnail_canvas_height = canvas_height

        self.ensure_active_thumbnail_visible(len(paths), region_width)
        visible_range = self.get_visible_thumbnail_range(len(paths))

        if force_rebuild or signature_changed or width_changed or visible_range != self.rendered_thumbnail_range:
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
        marker_color = "#111827"
        thumb_center_y = self.thumbnail_top_padding + (self.thumbnail_size / 2)
        marker_y = self.thumbnail_top_padding + self.thumbnail_size + 10
        start, end = visible_range

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
                    font=("Helvetica", 18, "bold"),
                    tags=(tag, "thumbnail"),
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
            self.thumbnail_canvas.tag_bind(tag, "<Button-1>", lambda _event, i=index: self.select_photo_at_index(i))
        self.rendered_thumbnail_range = visible_range
        self.rendered_active_index = self.session.active_index

    def update_thumbnail_selection(self):
        active_index = self.session.active_index if self.session.queue else None
        if active_index == self.rendered_active_index:
            return

        if self.rendered_active_index is not None:
            self.thumbnail_canvas.itemconfigure(f"thumb-marker-{self.rendered_active_index}", state="hidden")
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

    def refresh_preview(self, reload_image=False, preserve_view=False):
        self.preview_refresh_job = None
        current = self.session.active_photo
        if current is None:
            return

        if reload_image or self.preview_source_path != current:
            try:
                with Image.open(current) as image:
                    prepared = ImageOps.exif_transpose(image).convert("RGBA")
                    self.preview_source_image = prepared.copy()
            except OSError:
                self.clear_preview("Preview Error")
                return
            self.preview_source_path = current

        canvas_width = self.preview_canvas.winfo_width()
        canvas_height = self.preview_canvas.winfo_height()
        if canvas_width < 8 or canvas_height < 8:
            self.schedule_preview_refresh()
            return

        rel_x, rel_y = self.get_view_center() if preserve_view else (0.5, 0.5)

        image_width = self.preview_source_image.width
        image_height = self.preview_source_image.height
        fit_scale = min(canvas_width / image_width, canvas_height / image_height)
        display_scale = max(fit_scale * self.zoom_factor, 0.01)
        display_width = max(int(round(image_width * display_scale)), 1)
        display_height = max(int(round(image_height * display_scale)), 1)

        resized = self.preview_source_image.resize((display_width, display_height), Image.Resampling.LANCZOS)
        self.preview_photo = ImageTk.PhotoImage(resized)

        region_width = max(canvas_width, display_width)
        region_height = max(canvas_height, display_height)
        origin_x = max((region_width - display_width) / 2, 0)
        origin_y = max((region_height - display_height) / 2, 0)

        self.preview_canvas.delete("all")
        self.preview_canvas.configure(scrollregion=(0, 0, region_width, region_height))
        self.preview_canvas.create_image(origin_x, origin_y, anchor="nw", image=self.preview_photo)
        self.restore_view_center(rel_x, rel_y)

    def start_pan(self, event):
        self.preview_canvas.scan_mark(event.x, event.y)

    def drag_pan(self, event):
        self.preview_canvas.scan_dragto(event.x, event.y, gain=1)

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
        self.preview_canvas.yview_scroll(direction * steps, "units")
        return "break"

    def handle_shift_mousewheel(self, event):
        steps = max(1, int(abs(event.delta) / 120)) if event.delta else 1
        direction = -1 if event.delta > 0 else 1
        self.preview_canvas.xview_scroll(direction * steps, "units")
        return "break"

    def handle_linux_wheel(self, event):
        direction = -1 if getattr(event, "num", None) == 4 else 1
        self.preview_canvas.yview_scroll(direction, "units")
        return "break"

    def handle_linux_shift_wheel(self, event):
        direction = -1 if getattr(event, "num", None) == 4 else 1
        self.preview_canvas.xview_scroll(direction, "units")
        return "break"

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
