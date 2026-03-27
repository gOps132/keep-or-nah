from __future__ import annotations

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
        self.zoom_factor = 1.0
        self.min_zoom_factor = 0.25
        self.max_zoom_factor = 8.0
        self.last_browsed_dir: Path | None = None

        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        self.setup_styles()
        self.setup_header()
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

    def setup_header(self):
        frame = ttk.Frame(self, padding=16)
        frame.grid(row=0, column=0, sticky="ew")
        frame.columnconfigure(0, weight=1)

        ttk.Label(frame, text="Keep or Nah", font=("TkDefaultFont", 18, "bold")).grid(
            row=0,
            column=0,
            sticky="n",
        )

    def setup_body(self):
        self.main_frame = ttk.Frame(self, padding=(16, 0, 16, 0))
        self.main_frame.grid(row=1, column=0, sticky="nsew")
        self.main_frame.columnconfigure(0, weight=1)
        self.main_frame.rowconfigure(1, weight=1)

        control_bar = ttk.Frame(self.main_frame)
        control_bar.grid(row=0, column=0, sticky="ew", pady=(16, 10))
        control_bar.columnconfigure((0, 1, 2, 3, 4, 5, 6, 7, 8), weight=1)

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

        self.zoom_out_button = ttk.Button(control_bar, text="-", command=self.zoom_out)
        self.zoom_out_button.grid(row=0, column=6, padx=(6, 3), sticky="ew")

        self.zoom_fit_button = ttk.Button(control_bar, text="Fit", command=self.reset_zoom)
        self.zoom_fit_button.grid(row=0, column=7, padx=3, sticky="ew")

        self.zoom_in_button = ttk.Button(control_bar, text="+", command=self.zoom_in)
        self.zoom_in_button.grid(row=0, column=8, padx=(3, 0), sticky="ew")

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

    def setup_footer(self):
        footer = ttk.Frame(self, padding=(16, 0, 16, 16))
        footer.grid(row=2, column=0, sticky="ew")
        footer.columnconfigure((0, 1), weight=1)

        self.nah_button = ttk.Button(footer, text="Nah", command=lambda: self.sort_current_photo("nah"))
        self.nah_button.grid(row=0, column=0, padx=(0, 6), sticky="ew")

        self.keep_button = ttk.Button(footer, text="Keep", command=lambda: self.sort_current_photo("keep"))
        self.keep_button.grid(row=0, column=1, padx=(6, 0), sticky="ew")

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
        self.bind("<Left>", lambda _event: self.sort_current_photo("nah"))
        self.bind("<Right>", lambda _event: self.sort_current_photo("keep"))
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
