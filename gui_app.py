from __future__ import annotations

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
        self.geometry("1080x720")
        self.minsize(920, 620)
        self.dnd_enabled = False
        self.session = PhotoSession()
        self.preview_photo = None
        self.preview_source_image = None
        self.preview_source_path = None
        self.preview_refresh_job = None
        self.path_vars = {
            "source": tk.StringVar(value="No source folder selected"),
            "keep": tk.StringVar(value="No Keep folder selected"),
            "nah": tk.StringVar(value="No Nah folder selected"),
        }
        self.action_mode_var = tk.StringVar(value="move")

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self.header_frame = ctk.CTkFrame(self)
        self.header_frame.grid(row=0, column=0, padx=18, pady=(18, 10), sticky="ew")
        self.header_frame.grid_columnconfigure(0, weight=1)

        self.body_frame = ctk.CTkFrame(self)
        self.body_frame.grid(row=1, column=0, padx=18, pady=10, sticky="nsew")
        self.body_frame.grid_columnconfigure((0, 1), weight=1)
        self.body_frame.grid_rowconfigure(1, weight=1)

        self.footer_frame = ctk.CTkFrame(self)
        self.footer_frame.grid(row=2, column=0, padx=18, pady=(10, 18), sticky="ew")

        self.setup_header()
        self.setup_body()
        self.setup_footer()
        self.initialize_drag_and_drop()
        self.bind_shortcuts()
        self.update_runtime_notice()
        self.refresh_ui()

    def setup_header(self):
        ctk.CTkLabel(
            self.header_frame,
            text="Keep or Nah",
            font=ctk.CTkFont(size=32, weight="bold"),
            anchor="w",
        ).grid(row=0, column=0, padx=18, pady=(18, 6), sticky="ew")

        ctk.CTkLabel(
            self.header_frame,
            text="Triage photos quickly with a left-or-right decision workflow.",
            anchor="w",
            justify="left",
            text_color=("gray35", "gray74"),
        ).grid(row=1, column=0, padx=18, pady=(0, 18), sticky="ew")

    def setup_body(self):
        self.runtime_notice = ctk.CTkLabel(
            self.body_frame,
            text="",
            justify="left",
            wraplength=940,
            text_color=("gray40", "gray72"),
            anchor="w",
        )
        self.runtime_notice.grid(row=0, column=0, columnspan=2, padx=18, pady=(18, 8), sticky="ew")

        self.preview_card = ctk.CTkFrame(self.body_frame, corner_radius=18)
        self.preview_card.grid(row=1, column=0, padx=(18, 9), pady=(8, 18), sticky="nsew")
        self.preview_card.grid_columnconfigure(0, weight=1)
        self.preview_card.grid_rowconfigure(2, weight=1)

        ctk.CTkLabel(
            self.preview_card,
            text="Current Photo",
            font=ctk.CTkFont(size=22, weight="bold"),
            anchor="w",
        ).grid(row=0, column=0, padx=18, pady=(18, 4), sticky="ew")

        self.progress_label = ctk.CTkLabel(
            self.preview_card,
            text="Load a folder of images to begin.",
            justify="left",
            anchor="w",
            text_color=("gray40", "gray72"),
        )
        self.progress_label.grid(row=1, column=0, padx=18, pady=(0, 12), sticky="ew")

        self.preview_stage = ctk.CTkFrame(
            self.preview_card,
            corner_radius=16,
            fg_color=("gray92", "gray14"),
        )
        self.preview_stage.grid(row=2, column=0, padx=18, pady=(0, 12), sticky="nsew")
        self.preview_stage.grid_columnconfigure(0, weight=1)
        self.preview_stage.grid_rowconfigure(0, weight=1)
        self.preview_stage.bind("<Configure>", self.schedule_preview_refresh)

        self.preview_label = ctk.CTkLabel(
            self.preview_stage,
            text="No photos loaded yet.",
            justify="center",
            anchor="center",
            font=ctk.CTkFont(size=18, weight="bold"),
        )
        self.preview_label.grid(row=0, column=0, padx=18, pady=18, sticky="nsew")

        self.metadata_label = ctk.CTkLabel(
            self.preview_card,
            text="Supported formats: JPG, PNG, GIF, WEBP, TIFF, BMP, HEIC.",
            justify="left",
            anchor="w",
            text_color=("gray40", "gray72"),
        )
        self.metadata_label.grid(row=3, column=0, padx=18, pady=(0, 18), sticky="ew")

        controls_card = ctk.CTkFrame(self.body_frame, corner_radius=18)
        controls_card.grid(row=1, column=1, padx=(9, 18), pady=(8, 18), sticky="nsew")
        controls_card.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            controls_card,
            text="Sorting Setup",
            font=ctk.CTkFont(size=22, weight="bold"),
            anchor="w",
        ).grid(row=0, column=0, padx=18, pady=(18, 8), sticky="ew")

        self.instructions_label = ctk.CTkLabel(
            controls_card,
            text=(
                "Pick a source folder, choose destination folders for Keep and Nah, "
                "then review each image with buttons or the arrow keys."
            ),
            justify="left",
            anchor="w",
            wraplength=420,
        )
        self.instructions_label.grid(row=1, column=0, padx=18, pady=(0, 16), sticky="ew")

        self.add_folder_selector(
            parent=controls_card,
            row=2,
            label="Source Folder",
            key="source",
            button_text="Choose Source",
            command=self.choose_source_folder,
        )
        self.add_folder_selector(
            parent=controls_card,
            row=3,
            label="Keep Folder",
            key="keep",
            button_text="Choose Keep",
            command=self.choose_keep_folder,
        )
        self.add_folder_selector(
            parent=controls_card,
            row=4,
            label="Nah Folder",
            key="nah",
            button_text="Choose Nah",
            command=self.choose_nah_folder,
        )

        ctk.CTkLabel(
            controls_card,
            text="File Handling",
            font=ctk.CTkFont(size=16, weight="bold"),
            anchor="w",
        ).grid(row=5, column=0, padx=18, pady=(4, 8), sticky="ew")

        self.action_mode = ctk.CTkSegmentedButton(
            controls_card,
            values=["move", "copy"],
            variable=self.action_mode_var,
            command=self.handle_action_mode_change,
        )
        self.action_mode.grid(row=6, column=0, padx=18, pady=(0, 12), sticky="ew")

        self.load_button = ctk.CTkButton(
            controls_card,
            text="Load Photos",
            command=self.load_queue,
        )
        self.load_button.grid(row=7, column=0, padx=18, pady=(0, 12), sticky="ew")

        actions = ctk.CTkFrame(controls_card, fg_color="transparent")
        actions.grid(row=8, column=0, padx=18, pady=(0, 12), sticky="ew")
        actions.grid_columnconfigure((0, 1), weight=1)

        self.nah_button = ctk.CTkButton(
            actions,
            text="Nah  (Left)",
            fg_color="#b42318",
            hover_color="#912018",
            command=lambda: self.sort_current_photo("nah"),
        )
        self.nah_button.grid(row=0, column=0, padx=(0, 8), sticky="ew")

        self.keep_button = ctk.CTkButton(
            actions,
            text="Keep  (Right)",
            fg_color="#157f3b",
            hover_color="#126532",
            command=lambda: self.sort_current_photo("keep"),
        )
        self.keep_button.grid(row=0, column=1, padx=(8, 0), sticky="ew")

        self.status_label = ctk.CTkLabel(
            controls_card,
            text="Nothing loaded yet.",
            justify="left",
            wraplength=420,
            anchor="w",
            text_color=("gray40", "gray72"),
        )
        self.status_label.grid(row=9, column=0, padx=18, pady=(0, 8), sticky="ew")

        self.shortcut_hint = ctk.CTkLabel(
            controls_card,
            text="Shortcuts: Left / A = Nah, Right / D = Keep.",
            justify="left",
            anchor="w",
            text_color=("gray40", "gray72"),
        )
        self.shortcut_hint.grid(row=10, column=0, padx=18, pady=(0, 18), sticky="ew")

    def setup_footer(self):
        self.summary_label = ctk.CTkLabel(
            self.footer_frame,
            text="0 kept • 0 nah • 0 remaining",
            anchor="w",
            text_color=("gray40", "gray72"),
        )
        self.summary_label.pack(side="left", padx=12, pady=12)

        ctk.CTkButton(self.footer_frame, text="About", command=self.show_about).pack(
            side="right", padx=12, pady=12
        )

    def add_folder_selector(self, parent, row, label, key, button_text, command):
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.grid(row=row, column=0, padx=18, pady=(0, 12), sticky="ew")
        frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            frame,
            text=label,
            font=ctk.CTkFont(size=16, weight="bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="w")

        ctk.CTkButton(
            frame,
            text=button_text,
            width=132,
            command=command,
        ).grid(row=0, column=1, padx=(12, 0), sticky="e")

        ctk.CTkLabel(
            frame,
            textvariable=self.path_vars[key],
            justify="left",
            anchor="w",
            wraplength=290,
            text_color=("gray40", "gray72"),
        ).grid(row=1, column=0, columnspan=2, pady=(6, 0), sticky="ew")

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
        notes = []
        if tk.TkVersion < 8.6:
            notes.append(
                f"This Python build uses Tk {tk.TkVersion:.1f}. macOS compatibility is best with Tk 8.6+."
            )
        if self.dnd_enabled:
            notes.append("TkDnD runtime detected and ready for future drag-and-drop photo import.")
        else:
            notes.append("TkDnD runtime is not active on this build. File-picker workflows will still work.")

        self.runtime_notice.configure(text=" ".join(notes))

    def bind_shortcuts(self):
        self.bind("<Left>", lambda _event: self.sort_current_photo("nah"))
        self.bind("<Right>", lambda _event: self.sort_current_photo("keep"))
        self.bind("<KeyPress-a>", lambda _event: self.sort_current_photo("nah"))
        self.bind("<KeyPress-d>", lambda _event: self.sort_current_photo("keep"))

    def choose_source_folder(self):
        path = filedialog.askdirectory(title="Choose Source Folder")
        if not path:
            return
        self.session.set_source_dir(path)
        self.session.reset_queue()
        self.path_vars["source"].set(path)
        self.clear_preview()
        self.refresh_ui()
        self.status_label.configure(text="Source folder updated. Load photos to refresh the queue.")

    def choose_keep_folder(self):
        path = filedialog.askdirectory(title="Choose Keep Folder")
        if not path:
            return
        self.session.set_keep_dir(path)
        self.path_vars["keep"].set(path)
        self.refresh_ui()

    def choose_nah_folder(self):
        path = filedialog.askdirectory(title="Choose Nah Folder")
        if not path:
            return
        self.session.set_nah_dir(path)
        self.path_vars["nah"].set(path)
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
            self.status_label.configure(text="No supported images were found in the selected source folder.")
            self.clear_preview()
            self.refresh_ui()
            return

        self.status_label.configure(
            text=f"Loaded {count} image{'s' if count != 1 else ''} from the source folder."
        )
        self.preview_source_path = None
        self.refresh_ui()
        self.refresh_preview(reload_image=True)

    def sort_current_photo(self, decision):
        try:
            result = self.session.decide(decision)
        except PhotoSessionError as error:
            messagebox.showerror("Keep or Nah", str(error))
            return
        except OSError as error:
            messagebox.showerror("Keep or Nah", f"Could not process the file.\n\n{error}")
            return

        verb = "Moved" if result.action_mode == "move" else "Copied"
        label = "Keep" if result.decision == "keep" else "Nah"
        self.status_label.configure(
            text=f'{verb} "{result.source.name}" to {label}. {result.remaining_count} remaining.'
        )
        self.preview_source_path = None
        self.refresh_ui()
        self.refresh_preview(reload_image=True)
        if result.remaining_count == 0:
            messagebox.showinfo("Keep or Nah", "Queue complete.")

    def refresh_ui(self):
        current = self.session.active_photo
        if current is None:
            if self.session.total_loaded:
                self.progress_label.configure(text=f"Queue complete. {self.session.total_loaded} processed.")
            else:
                self.progress_label.configure(text="Load a folder of images to begin.")
        else:
            self.progress_label.configure(
                text=f"Photo {self.session.current_position} of {self.session.total_loaded}"
            )

        if current is None:
            self.metadata_label.configure(text="Supported formats: JPG, PNG, GIF, WEBP, TIFF, BMP, HEIC.")
        else:
            self.metadata_label.configure(text=current.name)

        button_state = "normal" if current is not None else "disabled"
        self.keep_button.configure(state=button_state)
        self.nah_button.configure(state=button_state)

        action_label = "Move" if self.session.action_mode == "move" else "Copy"
        self.instructions_label.configure(
            text=(
                f"{action_label} each reviewed image into the Keep or Nah folder. "
                "Use the buttons or arrow keys to work through the queue quickly."
            )
        )
        self.summary_label.configure(
            text=(
                f"{self.session.keep_count} kept • {self.session.nah_count} nah • "
                f"{self.session.remaining_count} remaining"
            )
        )
        self.focus_set()

    def schedule_preview_refresh(self, _event=None):
        if self.preview_refresh_job is not None:
            self.after_cancel(self.preview_refresh_job)
        self.preview_refresh_job = self.after(100, self.refresh_preview)

    def clear_preview(self, message="No photos loaded yet."):
        self.preview_source_image = None
        self.preview_source_path = None
        self.preview_photo = None
        self.preview_label.configure(text=message, image=None)

    def refresh_preview(self, reload_image=False):
        self.preview_refresh_job = None
        current = self.session.active_photo
        if current is None:
            self.clear_preview("No photos loaded yet.")
            return

        if reload_image or self.preview_source_path != current:
            try:
                with Image.open(current) as image:
                    prepared = ImageOps.exif_transpose(image).convert("RGBA")
                    self.preview_source_image = prepared.copy()
            except OSError as error:
                self.clear_preview("Preview unavailable for this image.")
                self.metadata_label.configure(text=f"{current.name} • preview error")
                self.status_label.configure(text=f"Could not load preview for {current.name}: {error}")
                return
            self.preview_source_path = current

        width = max(self.preview_stage.winfo_width() - 36, 260)
        height = max(self.preview_stage.winfo_height() - 36, 260)
        preview_image = self.preview_source_image.copy()
        preview_image.thumbnail((width, height), Image.Resampling.LANCZOS)
        self.preview_photo = ImageTk.PhotoImage(preview_image)
        self.preview_label.configure(text="", image=self.preview_photo)
        self.metadata_label.configure(text=self.describe_current_photo())

    def describe_current_photo(self):
        current = self.session.active_photo
        if current is None:
            return "Supported formats: JPG, PNG, GIF, WEBP, TIFF, BMP, HEIC."

        details = [current.name]
        if self.preview_source_image is not None:
            details.append(f"{self.preview_source_image.width} x {self.preview_source_image.height}")
        try:
            details.append(self.format_bytes(current.stat().st_size))
        except OSError:
            pass
        return " • ".join(details)

    def format_bytes(self, size):
        units = ["B", "KB", "MB", "GB"]
        value = float(size)
        for unit in units:
            if value < 1024 or unit == units[-1]:
                if unit == "B":
                    return f"{int(value)} {unit}"
                return f"{value:.1f} {unit}"
            value /= 1024
        return f"{value:.1f} GB"

    def show_about(self):
        messagebox.showinfo(
            "Keep or Nah",
            "Review one image at a time, then route it to Keep or Nah with keyboard shortcuts or buttons. "
            "This runtime uses CustomTkinter with automatic fallback to classic tkinter on older Tk builds.",
        )
