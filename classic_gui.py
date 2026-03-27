from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageOps, ImageTk

from photo_session import PhotoSession, PhotoSessionError


class ClassicApp(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title("Keep or Nah")
        self.geometry("1020x680")
        self.minsize(860, 560)
        self.session = PhotoSession()
        self.action_mode_var = tk.StringVar(value="move")
        self.path_vars = {
            "source": tk.StringVar(value="No source folder selected"),
            "keep": tk.StringVar(value="No Keep folder selected"),
            "nah": tk.StringVar(value="No Nah folder selected"),
        }
        self.preview_photo = None
        self.preview_source_image = None
        self.preview_source_path = None
        self.preview_refresh_job = None

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
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            frame,
            text=(
                "Compatibility mode is active because this Python build is using classic tkinter. "
                "The sorting workflow stays the same."
            ),
            wraplength=860,
            justify="left",
        ).grid(row=1, column=0, pady=(8, 0), sticky="w")

    def setup_body(self):
        frame = ttk.Frame(self, padding=(16, 0, 16, 16))
        frame.grid(row=1, column=0, sticky="nsew")
        frame.columnconfigure((0, 1), weight=1)
        frame.rowconfigure(1, weight=1)

        ttk.Label(
            frame,
            text=(
                f"This Python build uses Tk {tk.TkVersion:.1f}. "
                "The project falls back to classic tkinter automatically on older runtimes."
            ),
            wraplength=860,
            justify="left",
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 12))

        preview_card = ttk.LabelFrame(frame, text="Current Photo", padding=16)
        preview_card.grid(row=1, column=0, padx=(0, 8), sticky="nsew")
        preview_card.columnconfigure(0, weight=1)
        preview_card.rowconfigure(1, weight=1)

        self.progress_label = ttk.Label(preview_card, text="Load a folder of images to begin.")
        self.progress_label.grid(row=0, column=0, sticky="w")

        self.preview_stage = ttk.Frame(preview_card, padding=6)
        self.preview_stage.grid(row=1, column=0, pady=(10, 10), sticky="nsew")
        self.preview_stage.columnconfigure(0, weight=1)
        self.preview_stage.rowconfigure(0, weight=1)
        self.preview_stage.bind("<Configure>", self.schedule_preview_refresh)

        self.preview_label = tk.Label(
            self.preview_stage,
            text="No photos loaded yet.",
            anchor="center",
            justify="center",
            bg="#f3f3f3",
        )
        self.preview_label.grid(row=0, column=0, sticky="nsew")

        self.metadata_label = ttk.Label(
            preview_card,
            text="Supported formats: JPG, PNG, GIF, WEBP, TIFF, BMP, HEIC.",
            justify="left",
        )
        self.metadata_label.grid(row=2, column=0, sticky="ew")

        controls_card = ttk.LabelFrame(frame, text="Sorting Setup", padding=16)
        controls_card.grid(row=1, column=1, padx=(8, 0), sticky="nsew")
        controls_card.columnconfigure(0, weight=1)

        self.instructions_label = ttk.Label(
            controls_card,
            text=(
                "Pick a source folder, choose destination folders for Keep and Nah, "
                "then review each image with buttons or the arrow keys."
            ),
            wraplength=360,
            justify="left",
        )
        self.instructions_label.grid(row=0, column=0, sticky="w", pady=(0, 12))

        self.add_folder_selector(
            parent=controls_card,
            row=1,
            label="Source Folder",
            key="source",
            button_text="Choose Source",
            command=self.choose_source_folder,
        )
        self.add_folder_selector(
            parent=controls_card,
            row=2,
            label="Keep Folder",
            key="keep",
            button_text="Choose Keep",
            command=self.choose_keep_folder,
        )
        self.add_folder_selector(
            parent=controls_card,
            row=3,
            label="Nah Folder",
            key="nah",
            button_text="Choose Nah",
            command=self.choose_nah_folder,
        )

        mode_frame = ttk.LabelFrame(controls_card, text="File Handling", padding=10)
        mode_frame.grid(row=4, column=0, sticky="ew", pady=(0, 12))
        mode_frame.columnconfigure((0, 1), weight=1)

        ttk.Radiobutton(
            mode_frame,
            text="Move",
            value="move",
            variable=self.action_mode_var,
            command=self.handle_action_mode_change,
        ).grid(row=0, column=0, sticky="w")
        ttk.Radiobutton(
            mode_frame,
            text="Copy",
            value="copy",
            variable=self.action_mode_var,
            command=self.handle_action_mode_change,
        ).grid(row=0, column=1, sticky="w")

        self.load_button = ttk.Button(controls_card, text="Load Photos", command=self.load_queue)
        self.load_button.grid(row=5, column=0, sticky="ew", pady=(0, 12))

        buttons = ttk.Frame(controls_card)
        buttons.grid(row=6, column=0, sticky="ew", pady=(0, 12))
        buttons.columnconfigure((0, 1), weight=1)

        self.nah_button = ttk.Button(buttons, text="Nah (Left)", command=lambda: self.sort_current_photo("nah"))
        self.nah_button.grid(row=0, column=0, padx=(0, 6), sticky="ew")
        self.keep_button = ttk.Button(
            buttons,
            text="Keep (Right)",
            command=lambda: self.sort_current_photo("keep"),
        )
        self.keep_button.grid(row=0, column=1, padx=(6, 0), sticky="ew")

        self.status_label = ttk.Label(
            controls_card,
            text="Nothing loaded yet.",
            wraplength=360,
            justify="left",
        )
        self.status_label.grid(row=7, column=0, sticky="ew", pady=(0, 8))

        ttk.Label(
            controls_card,
            text="Shortcuts: Left / A = Nah, Right / D = Keep.",
            wraplength=360,
            justify="left",
        ).grid(row=8, column=0, sticky="w")

    def setup_footer(self):
        frame = ttk.Frame(self, padding=(16, 0, 16, 16))
        frame.grid(row=2, column=0, sticky="ew")
        frame.columnconfigure(0, weight=1)
        self.summary_label = ttk.Label(frame, text="0 kept • 0 nah • 0 remaining")
        self.summary_label.grid(row=0, column=0, sticky="w")
        ttk.Button(frame, text="About", command=self.show_about).grid(row=0, column=1, sticky="e")

    def add_folder_selector(self, parent, row, label, key, button_text, command):
        frame = ttk.Frame(parent)
        frame.grid(row=row, column=0, sticky="ew", pady=(0, 12))
        frame.columnconfigure(0, weight=1)

        ttk.Label(frame, text=label).grid(row=0, column=0, sticky="w")
        ttk.Button(frame, text=button_text, command=command).grid(row=0, column=1, padx=(8, 0), sticky="e")
        ttk.Label(
            frame,
            textvariable=self.path_vars[key],
            wraplength=270,
            justify="left",
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 0))

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
            self.status_label.configure(text="No supported images were found in the selected source folder.")
            self.clear_preview()
            self.refresh_ui()
            return

        self.status_label.configure(text=f"Loaded {count} image{'s' if count != 1 else ''} from the source folder.")
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
            self.progress_label.configure(text=f"Photo {self.session.current_position} of {self.session.total_loaded}")

        if current is None:
            self.metadata_label.configure(text="Supported formats: JPG, PNG, GIF, WEBP, TIFF, BMP, HEIC.")
            self.keep_button.state(["disabled"])
            self.nah_button.state(["disabled"])
        else:
            self.metadata_label.configure(text=current.name)
            self.keep_button.state(["!disabled"])
            self.nah_button.state(["!disabled"])

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
        self.preview_label.configure(text=message, image="")

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

        width = max(self.preview_stage.winfo_width() - 24, 240)
        height = max(self.preview_stage.winfo_height() - 24, 240)
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
            "This compatibility mode uses classic tkinter for older Tk runtimes.",
        )
