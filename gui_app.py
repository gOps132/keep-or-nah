from __future__ import annotations

from pathlib import Path
import sys
import tkinter as tk
from tkinter import filedialog, messagebox

import customtkinter as ctk
from PIL import Image, ImageOps, ImageTk

from photo_session import PhotoSession, PhotoSessionError

try:
    from tkinterdnd2 import TkinterDnD
except ImportError:
    TkinterDnD = None


if TkinterDnD is not None:
    class DnDCTk(ctk.CTk, TkinterDnD.DnDWrapper):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
else:
    DnDCTk = ctk.CTk


class App(DnDCTk):
    def __init__(self):
        super().__init__()

        ctk.set_appearance_mode("System")
        ctk.set_default_color_theme("blue")

        self.title("Keep or Nah")
        self.geometry("1180x820")
        self.minsize(960, 700)
        self.dnd_enabled = False
        self.session = PhotoSession()
        self.preview_photo = None
        self.preview_source_image = None
        self.preview_source_path = None
        self.preview_refresh_job = None
        self.action_mode_var = tk.StringVar(value="move")

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self.header_frame = ctk.CTkFrame(self)
        self.header_frame.grid(row=0, column=0, padx=18, pady=(18, 10), sticky="ew")
        self.header_frame.grid_columnconfigure(0, weight=1)

        self.body_frame = ctk.CTkFrame(self)
        self.body_frame.grid(row=1, column=0, padx=18, pady=(0, 18), sticky="nsew")
        self.body_frame.grid_columnconfigure(0, weight=1)
        self.body_frame.grid_rowconfigure(1, weight=1)

        self.setup_header()
        self.setup_body()
        self.initialize_drag_and_drop()
        self.bind_shortcuts()
        self.update_runtime_notice()
        self.refresh_ui()

    def setup_header(self):
        ctk.CTkLabel(
            self.header_frame,
            text="Keep or Nah",
            font=ctk.CTkFont(size=30, weight="bold"),
            anchor="center",
        ).grid(row=0, column=0, padx=18, pady=16)

    def setup_body(self):
        self.control_bar = ctk.CTkFrame(self.body_frame, fg_color="transparent")
        self.control_bar.grid(row=0, column=0, padx=18, pady=(18, 12), sticky="ew")
        self.control_bar.grid_columnconfigure((0, 1, 2, 3, 4, 5), weight=1)

        self.source_button = ctk.CTkButton(self.control_bar, text="Source", command=self.choose_source_folder)
        self.source_button.grid(row=0, column=0, padx=(0, 8), sticky="ew")

        self.keep_folder_button = ctk.CTkButton(self.control_bar, text="Keep", command=self.choose_keep_folder)
        self.keep_folder_button.grid(row=0, column=1, padx=8, sticky="ew")

        self.nah_folder_button = ctk.CTkButton(self.control_bar, text="Nah", command=self.choose_nah_folder)
        self.nah_folder_button.grid(row=0, column=2, padx=8, sticky="ew")

        self.action_mode = ctk.CTkSegmentedButton(
            self.control_bar,
            values=["move", "copy"],
            variable=self.action_mode_var,
            command=self.handle_action_mode_change,
        )
        self.action_mode.grid(row=0, column=3, padx=8, sticky="ew")

        self.undo_button = ctk.CTkButton(self.control_bar, text="Undo", command=self.undo_last_action)
        self.undo_button.grid(row=0, column=4, padx=8, sticky="ew")

        self.load_button = ctk.CTkButton(self.control_bar, text="Load", command=self.load_queue)
        self.load_button.grid(row=0, column=5, padx=(8, 0), sticky="ew")

        center_frame = ctk.CTkFrame(self.body_frame, fg_color="transparent")
        center_frame.grid(row=1, column=0, padx=18, pady=(0, 18), sticky="nsew")
        center_frame.grid_columnconfigure(0, weight=1)
        center_frame.grid_rowconfigure(0, weight=1)

        self.preview_card = ctk.CTkFrame(center_frame, corner_radius=20, width=860, height=620)
        self.preview_card.grid(row=0, column=0)
        self.preview_card.grid_propagate(False)
        self.preview_card.grid_columnconfigure(0, weight=1)
        self.preview_card.grid_rowconfigure(0, weight=1)

        self.preview_stage = ctk.CTkFrame(
            self.preview_card,
            corner_radius=18,
            fg_color=("gray92", "gray14"),
        )
        self.preview_stage.grid(row=0, column=0, padx=24, pady=(24, 18), sticky="nsew")
        self.preview_stage.grid_columnconfigure(0, weight=1)
        self.preview_stage.grid_rowconfigure(0, weight=1)
        self.preview_stage.bind("<Configure>", self.schedule_preview_refresh)

        self.preview_label = ctk.CTkLabel(
            self.preview_stage,
            text="No Photo",
            justify="center",
            anchor="center",
            font=ctk.CTkFont(size=22, weight="bold"),
        )
        self.preview_label.grid(row=0, column=0, padx=24, pady=24, sticky="nsew")

        action_bar = ctk.CTkFrame(self.preview_card, fg_color="transparent")
        action_bar.grid(row=1, column=0, padx=24, pady=(0, 24), sticky="ew")
        action_bar.grid_columnconfigure((0, 1), weight=1)

        self.nah_button = ctk.CTkButton(
            action_bar,
            text="Nah",
            fg_color="#b42318",
            hover_color="#912018",
            height=48,
            command=lambda: self.sort_current_photo("nah"),
        )
        self.nah_button.grid(row=0, column=0, padx=(0, 8), sticky="ew")

        self.keep_button = ctk.CTkButton(
            action_bar,
            text="Keep",
            fg_color="#157f3b",
            hover_color="#126532",
            height=48,
            command=lambda: self.sort_current_photo("keep"),
        )
        self.keep_button.grid(row=0, column=1, padx=(8, 0), sticky="ew")

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

    def initialize_drag_and_drop(self):
        if TkinterDnD is None:
            self.dnd_enabled = False
            return

        try:
            self.TkdndVersion = TkinterDnD._require(self)
            self.dnd_enabled = True
        except Exception:
            self.dnd_enabled = False

    def update_runtime_notice(self):
        return

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

    def handle_action_mode_change(self, value):
        self.session.set_action_mode(value)
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

        self.load_button.configure(state="normal" if self.session.source_dir is not None else "disabled")
        self.undo_button.configure(state="normal" if self.session.can_undo else "disabled")
        button_state = "normal" if current is not None else "disabled"
        self.keep_button.configure(state=button_state)
        self.nah_button.configure(state=button_state)

        if current is None:
            if self.session.total_loaded:
                self.clear_preview("Done")
            else:
                self.clear_preview("No Photo")

        self.focus_set()

    def schedule_preview_refresh(self, _event=None):
        if self.preview_refresh_job is not None:
            self.after_cancel(self.preview_refresh_job)
        self.preview_refresh_job = self.after(100, self.refresh_preview)

    def clear_preview(self, message="No Photo"):
        self.preview_source_image = None
        self.preview_source_path = None
        self.preview_photo = None
        self.preview_label.configure(text=message, image=None)

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

        width = max(self.preview_stage.winfo_width() - 48, 280)
        height = max(self.preview_stage.winfo_height() - 48, 280)
        preview_image = self.preview_source_image.copy()
        preview_image.thumbnail((width, height), Image.Resampling.LANCZOS)
        self.preview_photo = ImageTk.PhotoImage(preview_image)
        self.preview_label.configure(text="", image=self.preview_photo)
