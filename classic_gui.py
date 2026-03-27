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

        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        self.setup_styles()
        self.setup_header()
        self.setup_body()
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
            row=0, column=0, sticky="n"
        )

    def setup_body(self):
        frame = ttk.Frame(self, padding=(16, 0, 16, 16))
        frame.grid(row=1, column=0, sticky="nsew")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(1, weight=1)

        control_bar = ttk.Frame(frame)
        control_bar.grid(row=0, column=0, sticky="ew", pady=(16, 12))
        control_bar.columnconfigure((0, 1, 2, 3, 4, 5), weight=1)

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
        self.load_button.grid(row=0, column=5, padx=(6, 0), sticky="ew")

        center_frame = ttk.Frame(frame)
        center_frame.grid(row=1, column=0, sticky="nsew")
        center_frame.columnconfigure(0, weight=1)
        center_frame.rowconfigure(0, weight=1)

        self.preview_card = ttk.Frame(center_frame, padding=20)
        self.preview_card.grid(row=0, column=0)
        self.preview_card.columnconfigure(0, weight=1)
        self.preview_card.rowconfigure(0, weight=1)

        self.preview_stage = ttk.Frame(self.preview_card, padding=10)
        self.preview_stage.grid(row=0, column=0, sticky="nsew")
        self.preview_stage.columnconfigure(0, weight=1)
        self.preview_stage.rowconfigure(0, weight=1)
        self.preview_stage.bind("<Configure>", self.schedule_preview_refresh)

        self.preview_label = tk.Label(
            self.preview_stage,
            text="No Photo",
            anchor="center",
            justify="center",
            bg="#f3f3f3",
            width=72,
            height=30,
        )
        self.preview_label.grid(row=0, column=0, sticky="nsew")

        action_bar = ttk.Frame(self.preview_card)
        action_bar.grid(row=1, column=0, sticky="ew", pady=(14, 0))
        action_bar.columnconfigure((0, 1), weight=1)

        self.nah_button = ttk.Button(action_bar, text="Nah", command=lambda: self.sort_current_photo("nah"))
        self.nah_button.grid(row=0, column=0, padx=(0, 6), sticky="ew")

        self.keep_button = ttk.Button(action_bar, text="Keep", command=lambda: self.sort_current_photo("keep"))
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

    def handle_undo_shortcut(self, _event=None):
        self.undo_last_action()

    def choose_source_folder(self):
        path = filedialog.askdirectory(title="Choose Source Folder")
        if not path:
            return

        self.session.set_source_dir(path)
        self.session.reset_queue()
        self.clear_preview()
        self.refresh_ui()

    def choose_keep_folder(self):
        path = filedialog.askdirectory(title="Choose Keep Folder")
        if not path:
            return

        self.session.set_keep_dir(path)
        self.refresh_ui()

    def choose_nah_folder(self):
        path = filedialog.askdirectory(title="Choose Nah Folder")
        if not path:
            return

        self.session.set_nah_dir(path)
        self.refresh_ui()

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
            self.clear_preview("No Photo")
            self.refresh_ui()
            messagebox.showinfo("Keep or Nah", "No supported images found.")
            return

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

        self.preview_source_path = None
        self.refresh_ui()
        self.refresh_preview(reload_image=True)

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

        if current is None:
            self.keep_button.state(["disabled"])
            self.nah_button.state(["disabled"])
            if self.session.total_loaded:
                self.clear_preview("Done")
            else:
                self.clear_preview("No Photo")
        else:
            self.keep_button.state(["!disabled"])
            self.nah_button.state(["!disabled"])

        self.focus_set()

    def schedule_preview_refresh(self, _event=None):
        if self.preview_refresh_job is not None:
            self.after_cancel(self.preview_refresh_job)
        self.preview_refresh_job = self.after(100, self.refresh_preview)

    def clear_preview(self, message="No Photo"):
        self.preview_source_image = None
        self.preview_source_path = None
        self.preview_photo = None
        self.preview_label.configure(text=message, image="")

    def refresh_preview(self, reload_image=False):
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

        width = max(self.preview_stage.winfo_width() - 32, 280)
        height = max(self.preview_stage.winfo_height() - 32, 280)
        preview_image = self.preview_source_image.copy()
        preview_image.thumbnail((width, height), Image.Resampling.LANCZOS)
        self.preview_photo = ImageTk.PhotoImage(preview_image)
        self.preview_label.configure(text="", image=self.preview_photo)
