from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
import sys
import tkinter as tk
from tkinter import filedialog, messagebox

import customtkinter as ctk
from PIL import Image, ImageOps, ImageTk

from app_assets import apply_window_icon
from app_settings import AppSettings, MAX_PREVIEW_CACHE_BUDGET_MB, MIN_PREVIEW_CACHE_BUDGET_MB
from photo_session import PhotoSession, PhotoSessionError
from preview_pipeline import PreviewPipeline
from session_persistence import SessionLifecycle
from session_startup import (
    choose_source_directory,
    initialize_gui_session,
    preview_paths_for,
    session_has_pending_photos,
    show_session_warning,
)
from view_filter import (
    EMPTY_SELECTION_MESSAGE,
    ExtensionFilterModel,
    apply_extension_filter,
    empty_preview_message,
    selected_extensions,
    save_view_filter_settings,
    unavailable_preview_message,
    validate_extension_selection,
)

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
        apply_window_icon(self)
        self.dnd_enabled = False
        self.settings = AppSettings.load()
        self.session_lifecycle = SessionLifecycle(
            error_handler=lambda message: show_session_warning(self, message)
        )
        self.session = self.session_lifecycle.restore() or PhotoSession()
        self.restored_startup_session = session_has_pending_photos(self.session)
        self.preview_pipeline = PreviewPipeline(cache_budget_mb=self.settings.preview_cache_budget_mb)
        self.preview_photo = None
        self.preview_source_image = None
        self.preview_source_path = None
        self.preview_refresh_job = None
        self.preview_poll_job = None
        self.thumbnail_rebuild_job = None
        self.rendered_preview_size: tuple[int, int] | None = None
        self.rendered_preview_scrollregion: tuple[int, int, int, int] | None = None
        self.preview_request_id = 0
        self.preview_request_key: tuple[Path, int, int, str, bool] | None = None
        self.loading_overlay_delay_job = None
        self.loading_animation_job = None
        self.loading_overlay_visible = False
        self.loading_overlay_angle = 0
        self.preview_settings_dialog = None
        self.destroyed = False
        self.preview_texture_cache: OrderedDict[tuple[object, ...], ImageTk.PhotoImage] = OrderedDict()
        self.preview_texture_cache_limit = 12
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
        self.action_mode_var = tk.StringVar(value=self.session.action_mode)
        self.last_browsed_dir: Path | None = None

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.main_frame = ctk.CTkFrame(self)
        self.main_frame.grid(row=0, column=0, padx=18, pady=(18, 0), sticky="nsew")
        self.main_frame.grid_columnconfigure(0, weight=1)
        self.main_frame.grid_rowconfigure(1, weight=1)

        self.footer_frame = ctk.CTkFrame(self)
        self.footer_frame.grid(row=1, column=0, padx=18, pady=(10, 18), sticky="ew")
        self.footer_frame.grid_columnconfigure((0, 1), weight=1)

        self.setup_body()
        self.setup_footer()
        self.setup_menu()
        self.initialize_drag_and_drop()
        self.bind_shortcuts()
        self.protocol("WM_DELETE_WINDOW", self.handle_window_close)
        self.refresh_ui()
        self.after_idle(self.initialize_startup_session)

    def initialize_startup_session(self):
        initialize_gui_session(self)

    def persist_session(self):
        return self.session_lifecycle.persist(self.session)

    def handle_window_close(self):
        self.persist_session()
        self.destroy()

    def destroy(self):
        if self.destroyed:
            return
        self.destroyed = True
        self.cancel_preview_jobs()
        if self.preview_settings_dialog is not None and self.preview_settings_dialog.winfo_exists():
            self.preview_settings_dialog.destroy()
        self.preview_pipeline.shutdown()
        super().destroy()

    def cancel_preview_jobs(self):
        if self.thumbnail_rebuild_job is not None:
            self.after_cancel(self.thumbnail_rebuild_job)
            self.thumbnail_rebuild_job = None
        if self.preview_refresh_job is not None:
            self.after_cancel(self.preview_refresh_job)
            self.preview_refresh_job = None
        if self.preview_poll_job is not None:
            self.after_cancel(self.preview_poll_job)
            self.preview_poll_job = None
        if self.loading_overlay_delay_job is not None:
            self.after_cancel(self.loading_overlay_delay_job)
            self.loading_overlay_delay_job = None
        if self.loading_animation_job is not None:
            self.after_cancel(self.loading_animation_job)
            self.loading_animation_job = None
        self.loading_overlay_visible = False
        self.preview_canvas.delete("preview-loading")

    def reset_preview_request_state(self):
        self.cancel_preview_jobs()
        self.preview_request_id = 0
        self.preview_request_key = None

    def setup_body(self):
        self.control_bar = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        self.control_bar.grid(row=0, column=0, padx=18, pady=(18, 10), sticky="ew")
        self.control_bar.grid_columnconfigure((0, 1, 2, 3, 4, 5, 6, 7, 8, 9), weight=1)

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
        self.load_button.grid(row=0, column=5, padx=8, sticky="ew")

        self.toggle_actions_button = ctk.CTkButton(
            self.control_bar,
            text="Hide Buttons",
            command=self.toggle_action_buttons,
        )
        self.toggle_actions_button.grid(row=0, column=6, padx=8, sticky="ew")

        self.zoom_out_button = ctk.CTkButton(self.control_bar, text="-", width=44, command=self.zoom_out)
        self.zoom_out_button.grid(row=0, column=7, padx=(8, 4), sticky="ew")

        self.zoom_fit_button = ctk.CTkButton(self.control_bar, text="Fit", width=60, command=self.reset_zoom)
        self.zoom_fit_button.grid(row=0, column=8, padx=4, sticky="ew")

        self.zoom_in_button = ctk.CTkButton(self.control_bar, text="+", width=44, command=self.zoom_in)
        self.zoom_in_button.grid(row=0, column=9, padx=(4, 0), sticky="ew")

        preview_host = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        preview_host.grid(row=1, column=0, padx=18, pady=(0, 12), sticky="nsew")
        preview_host.grid_columnconfigure(0, weight=1)
        preview_host.grid_rowconfigure(0, weight=1)

        canvas_color = self.resolve_canvas_color()
        self.preview_canvas = tk.Canvas(
            preview_host,
            bg=canvas_color,
            bd=0,
            highlightthickness=0,
            xscrollincrement=1,
            yscrollincrement=1,
        )
        self.preview_canvas.grid(row=0, column=0, sticky="nsew")
        self.preview_canvas.bind("<Configure>", self.handle_preview_configure)
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

        self.queue_host = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        self.queue_host.grid(row=2, column=0, padx=18, pady=(0, 8), sticky="ew")
        self.queue_host.grid_columnconfigure(0, weight=1)
        self.queue_host.grid_rowconfigure(0, weight=1)

        self.thumbnail_canvas = tk.Canvas(
            self.queue_host,
            bg=canvas_color,
            bd=0,
            highlightthickness=0,
            height=108,
            xscrollincrement=1,
        )
        self.thumbnail_canvas.grid(row=0, column=0, sticky="ew")
        self.thumbnail_canvas.bind("<Configure>", self.schedule_thumbnail_strip_rebuild)
        self.thumbnail_canvas.bind("<MouseWheel>", self.handle_thumbnail_wheel)
        self.thumbnail_canvas.bind("<Button-4>", self.handle_thumbnail_linux_wheel)
        self.thumbnail_canvas.bind("<Button-5>", self.handle_thumbnail_linux_wheel)

    def setup_footer(self):
        self.nah_button = ctk.CTkButton(
            self.footer_frame,
            text="Nah",
            fg_color="#b42318",
            hover_color="#912018",
            height=54,
            command=lambda: self.sort_current_photo("nah"),
        )
        self.nah_button.grid(row=0, column=0, padx=(18, 8), pady=18, sticky="ew")

        self.keep_button = ctk.CTkButton(
            self.footer_frame,
            text="Keep",
            fg_color="#157f3b",
            hover_color="#126532",
            height=54,
            command=lambda: self.sort_current_photo("keep"),
        )
        self.keep_button.grid(row=0, column=1, padx=(8, 18), pady=18, sticky="ew")

    def setup_menu(self):
        menubar = tk.Menu(self)
        settings_label = "Settings..." if sys.platform == "darwin" else "Preview Settings..."
        accelerator = "Cmd+," if sys.platform == "darwin" else "Ctrl+,"

        file_menu = tk.Menu(menubar, tearoff=False)
        file_menu.add_command(label=settings_label, accelerator=accelerator, command=self.open_preview_settings_dialog)
        file_menu.add_separator()
        file_menu.add_command(label="Exit" if sys.platform != "darwin" else "Quit Keep or Nah", command=self.handle_window_close)
        menubar.add_cascade(label="Keep or Nah" if sys.platform == "darwin" else "File", menu=file_menu)

        view_menu = tk.Menu(menubar, tearoff=False)
        view_menu.add_command(label="Preview Settings...", accelerator=accelerator, command=self.open_preview_settings_dialog)
        menubar.add_cascade(label="View", menu=view_menu)

        self.configure(menu=menubar)
        self.menubar = menubar

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

    def resolve_canvas_color(self) -> str:
        raw_color = self.main_frame.cget("fg_color")
        return self._apply_appearance_mode(raw_color)

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

    def open_preview_settings_dialog(self):
        if self.preview_settings_dialog is not None and self.preview_settings_dialog.winfo_exists():
            self.preview_settings_dialog.focus()
            self.preview_settings_dialog.lift()
            return

        dialog = ctk.CTkToplevel(self)
        dialog.title("Preview Settings")
        dialog.geometry("460x510")
        dialog.resizable(False, False)
        dialog.transient(self)
        dialog.configure(fg_color=self.main_frame.cget("fg_color"))
        dialog.grid_columnconfigure(0, weight=1)
        dialog.grid_rowconfigure(0, weight=1)

        progressive_var = tk.BooleanVar(value=self.settings.progressive_preview)
        loading_var = tk.BooleanVar(value=self.settings.loading_indicator)
        budget_var = tk.StringVar(value=str(self.settings.preview_cache_budget_mb))
        filter_model = self.extension_filter_model()
        extension_vars = {
            extension: tk.BooleanVar(value=extension in filter_model.selected)
            for extension in filter_model.options
        }

        container = ctk.CTkFrame(dialog, fg_color="transparent")
        container.grid(row=0, column=0, sticky="nsew", padx=20, pady=20)
        container.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            container,
            text="Preview Performance",
            font=ctk.CTkFont(size=18, weight="bold"),
        ).grid(row=0, column=0, sticky="w", pady=(2, 14))

        ctk.CTkSwitch(container, text="Progressive Preview", variable=progressive_var).grid(
            row=1,
            column=0,
            sticky="w",
            pady=6,
        )
        ctk.CTkSwitch(container, text="Loading Indicator", variable=loading_var).grid(
            row=2,
            column=0,
            sticky="w",
            pady=6,
        )

        ctk.CTkLabel(container, text="Preview Cache Budget (MB)").grid(row=3, column=0, sticky="w", pady=(18, 6))
        ctk.CTkEntry(container, textvariable=budget_var).grid(row=4, column=0, sticky="ew")

        helper_text = f"Allowed range: {MIN_PREVIEW_CACHE_BUDGET_MB}-{MAX_PREVIEW_CACHE_BUDGET_MB} MB."
        ctk.CTkLabel(
            container,
            text=helper_text,
            text_color=self._apply_appearance_mode(("gray45", "gray65")),
            justify="left",
            wraplength=360,
        ).grid(row=5, column=0, sticky="w", pady=(8, 14))

        filter_frame = ctk.CTkScrollableFrame(
            container,
            label_text="Extension View Filter",
            height=110,
        )
        filter_frame.grid(row=6, column=0, sticky="ew", pady=(0, 16))
        filter_frame.grid_columnconfigure((0, 1, 2), weight=1)
        if extension_vars:
            for index, (extension, variable) in enumerate(extension_vars.items()):
                ctk.CTkCheckBox(
                    filter_frame,
                    text=extension,
                    variable=variable,
                ).grid(row=index // 3, column=index % 3, sticky="w", padx=6, pady=4)
        else:
            ctk.CTkLabel(
                filter_frame,
                text="Choose a source folder to discover extensions.",
                text_color=self._apply_appearance_mode(("gray45", "gray65")),
            ).grid(row=0, column=0, columnspan=3, sticky="w", padx=6, pady=4)

        button_row = ctk.CTkFrame(container, fg_color="transparent")
        button_row.grid(row=7, column=0, sticky="ew")
        button_row.grid_columnconfigure((0, 1), weight=1)

        def close_dialog():
            if dialog.winfo_exists():
                dialog.destroy()
            self.preview_settings_dialog = None

        def save_settings():
            selected = selected_extensions(extension_vars)
            if filter_model.options:
                try:
                    validate_extension_selection(selected)
                except ValueError:
                    messagebox.showerror("Keep or Nah", EMPTY_SELECTION_MESSAGE)
                    return

            try:
                budget = int(budget_var.get().strip())
            except ValueError:
                messagebox.showerror("Keep or Nah", "Preview cache budget must be a whole number.")
                return

            if budget < MIN_PREVIEW_CACHE_BUDGET_MB or budget > MAX_PREVIEW_CACHE_BUDGET_MB:
                messagebox.showerror(
                    "Keep or Nah",
                    f"Preview cache budget must be between {MIN_PREVIEW_CACHE_BUDGET_MB} and {MAX_PREVIEW_CACHE_BUDGET_MB} MB.",
                )
                return

            settings = AppSettings(
                progressive_preview=progressive_var.get(),
                loading_indicator=loading_var.get(),
                preview_cache_budget_mb=budget,
            )
            if not self.save_settings_changes(
                settings,
                set(selected) if filter_model.options else None,
                messagebox.showerror,
            ):
                return
            close_dialog()

        ctk.CTkButton(button_row, text="Cancel", command=close_dialog).grid(row=0, column=0, padx=(0, 6), sticky="ew")
        save_button = ctk.CTkButton(button_row, text="Save", command=save_settings)
        save_button.grid(row=0, column=1, padx=(6, 0), sticky="ew")

        def update_save_state(*_args):
            disabled = bool(filter_model.options) and not selected_extensions(extension_vars)
            save_button.configure(state="disabled" if disabled else "normal")

        for variable in extension_vars.values():
            variable.trace_add("write", update_save_state)
        update_save_state()

        dialog.protocol("WM_DELETE_WINDOW", close_dialog)
        dialog.after(0, dialog.grab_set)
        self.preview_settings_dialog = dialog

    def apply_preview_settings(self, settings: AppSettings, *, persist: bool = True):
        normalized = settings.normalized()
        if persist:
            normalized.save()
        self.settings = normalized
        self.preview_pipeline.configure_cache_budget(normalized.preview_cache_budget_mb)
        self.prune_preview_texture_cache(set(preview_paths_for(self.session)))
        self.preview_source_path = None
        self.preview_source_image = None
        self.reset_preview_request_state()
        self.refresh_preview(reload_image=True)

    def extension_filter_model(self) -> ExtensionFilterModel:
        return ExtensionFilterModel.from_session(self.session)

    def apply_view_filter(self, enabled_extensions: set[str]) -> int:
        return apply_extension_filter(self, enabled_extensions)

    def save_settings_changes(
        self,
        settings: AppSettings,
        enabled_extensions: set[str] | None,
        show_error=messagebox.showerror,
    ) -> bool:
        return save_view_filter_settings(
            self,
            settings,
            enabled_extensions,
            show_error,
        )

    def initialize_drag_and_drop(self):
        if TkinterDnD is None:
            self.dnd_enabled = False
            return

        try:
            self.TkdndVersion = TkinterDnD._require(self)
            self.dnd_enabled = True
        except Exception:
            self.dnd_enabled = False

    def bind_shortcuts(self):
        self.bind_all("<Left>", self.handle_previous_shortcut)
        self.bind_all("<Right>", self.handle_next_shortcut)
        self.bind_all("<KeyPress-a>", self.handle_nah_shortcut)
        self.bind_all("<KeyPress-d>", self.handle_keep_shortcut)
        self.bind_all("<space>", self.handle_space_shortcut)
        self.bind_all("<Delete>", self.handle_delete_shortcut)

        modifier = "Command" if sys.platform == "darwin" else "Control"
        self.bind(f"<{modifier}-z>", self.handle_undo_shortcut)
        self.bind(f"<{modifier}-Z>", self.handle_undo_shortcut)
        self.bind(f"<{modifier}-minus>", self.handle_zoom_out_shortcut)
        self.bind(f"<{modifier}-equal>", self.handle_zoom_in_shortcut)
        self.bind(f"<{modifier}-plus>", self.handle_zoom_in_shortcut)
        self.bind(f"<{modifier}-0>", self.handle_zoom_reset_shortcut)
        self.bind(f"<{modifier}-comma>", self.handle_open_preview_settings_shortcut)

    def bind_if_supported(self, widget, sequence: str, handler):
        try:
            widget.bind(sequence, handler)
        except tk.TclError:
            return

    def handle_undo_shortcut(self, _event=None):
        self.undo_last_action()

    def handle_previous_shortcut(self, _event=None):
        if not self.shortcuts_enabled():
            return None
        self.navigate_selection(-1)
        return "break"

    def handle_next_shortcut(self, _event=None):
        if not self.shortcuts_enabled():
            return None
        self.navigate_selection(1)
        return "break"

    def handle_nah_shortcut(self, _event=None):
        if not self.shortcuts_enabled():
            return None
        self.sort_current_photo("nah")
        return "break"

    def handle_keep_shortcut(self, _event=None):
        if not self.shortcuts_enabled():
            return None
        self.sort_current_photo("keep")
        return "break"

    def handle_space_shortcut(self, _event=None):
        if not self.shortcuts_enabled():
            return None
        self.sort_current_photo("keep")
        return "break"

    def handle_delete_shortcut(self, _event=None):
        if not self.shortcuts_enabled():
            return None
        self.sort_current_photo("nah")
        return "break"

    def handle_zoom_in_shortcut(self, _event=None):
        self.zoom_in()

    def handle_zoom_out_shortcut(self, _event=None):
        self.zoom_out()

    def handle_zoom_reset_shortcut(self, _event=None):
        self.reset_zoom()

    def handle_open_preview_settings_shortcut(self, _event=None):
        self.open_preview_settings_dialog()
        return "break"

    def shortcuts_enabled(self) -> bool:
        focused = self.focus_get()
        if focused is None:
            return True
        widget_class = focused.winfo_class()
        return widget_class not in {"Entry", "TEntry", "Text", "Spinbox", "TSpinbox"}

    def choose_source_folder(self):
        choose_source_directory(self)

    def replace_source_folder(self, path):
        self.reset_preview_request_state()
        self.session.set_source_dir(path)
        self.last_browsed_dir = Path(path)
        self.preview_texture_cache = OrderedDict()
        self.thumbnail_cache = OrderedDict()
        self.thumbnail_refs = []
        self.thumbnail_signature = ()
        self.thumbnail_canvas_width = 0
        self.thumbnail_canvas_height = 108
        self.rendered_thumbnail_range = (-1, -1)
        self.rendered_active_index = None
        self.session.reset_queue()
        self.session_lifecycle.clear()
        self.preview_pipeline.reset(preview_paths_for(self.session))
        self.reset_zoom_state()
        self.clear_preview()
        self.refresh_ui()

    def choose_keep_folder(self):
        path = filedialog.askdirectory(title="Choose Keep Folder", initialdir=self.get_initial_directory())
        if not path:
            return

        self.session.set_keep_dir(path)
        self.last_browsed_dir = Path(path)
        self.persist_session()
        self.refresh_ui()

    def choose_nah_folder(self):
        path = filedialog.askdirectory(title="Choose Nah Folder", initialdir=self.get_initial_directory())
        if not path:
            return

        self.session.set_nah_dir(path)
        self.last_browsed_dir = Path(path)
        self.persist_session()
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

    def handle_action_mode_change(self, value):
        self.session.set_action_mode(value)
        self.persist_session()
        self.refresh_ui()

    def select_photo_at_index(self, index: int):
        if self.session.set_active_index(index) is None:
            return

        self.reset_zoom_state()
        self.preview_source_path = None
        self.preview_source_image = None
        self.reset_preview_request_state()
        self.persist_session()
        self.refresh_ui()
        self.refresh_preview()

    def navigate_selection(self, offset: int):
        if self.session.move_active(offset) is None:
            return

        self.reset_zoom_state()
        self.preview_source_path = None
        self.preview_source_image = None
        self.reset_preview_request_state()
        self.persist_session()
        self.refresh_ui()
        self.refresh_preview()

    def load_queue(self):
        try:
            count = self.session.load_queue()
        except PhotoSessionError as error:
            messagebox.showerror("Keep or Nah", str(error))
            return
        self.preview_pipeline.reset(preview_paths_for(self.session))
        self.prune_preview_texture_cache(set(preview_paths_for(self.session)))
        self.reset_preview_request_state()
        self.persist_session()

        if count == 0:
            self.reset_zoom_state()
            self.clear_preview("No Photo")
            self.refresh_ui()
            messagebox.showinfo("Keep or Nah", "No supported images found.")
            return

        self.reset_zoom_state()
        self.preview_source_path = None
        self.preview_source_image = None
        self.refresh_ui()
        self.refresh_preview()

    def sort_current_photo(self, decision):
        try:
            self.session.decide(decision)
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
        self.reset_preview_request_state()
        self.persist_session()
        self.refresh_ui()
        self.refresh_preview()

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

        self.preview_pipeline.reset(preview_paths_for(self.session))
        self.prune_preview_texture_cache(set(preview_paths_for(self.session)))
        self.reset_zoom_state()
        self.preview_source_path = None
        self.preview_source_image = None
        self.reset_preview_request_state()
        self.persist_session()
        self.refresh_ui()
        self.refresh_preview()

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

        self.load_button.configure(state="normal" if self.session.source_dir is not None else "disabled")
        self.undo_button.configure(state="normal" if self.session.can_undo else "disabled")

        zoom_state = "normal" if current is not None else "disabled"
        self.zoom_in_button.configure(state=zoom_state)
        self.zoom_out_button.configure(state=zoom_state)
        self.zoom_fit_button.configure(state=zoom_state)

        action_state = "normal" if current is not None else "disabled"
        self.keep_button.configure(state=action_state)
        self.nah_button.configure(state=action_state)
        self.refresh_thumbnail_strip()

        if current is None:
            self.reset_preview_request_state()
            self.clear_preview(empty_preview_message(self.session))

        self.focus_set()

    def schedule_preview_refresh(self, _event=None):
        if self.preview_refresh_job is not None:
            self.after_cancel(self.preview_refresh_job)
        self.preview_refresh_job = self.after(80, self.refresh_preview_or_placeholder)

    def schedule_thumbnail_strip_rebuild(self, _event=None):
        if self.destroyed:
            return
        if self.thumbnail_rebuild_job is not None:
            self.after_cancel(self.thumbnail_rebuild_job)
        self.thumbnail_rebuild_job = self.after(60, self._flush_thumbnail_strip_rebuild)

    def _flush_thumbnail_strip_rebuild(self):
        self.thumbnail_rebuild_job = None
        self.refresh_thumbnail_strip(force_rebuild=True)

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

    def refresh_preview_or_placeholder(self):
        current = self.session.active_photo
        if current is None:
            self.reset_preview_request_state()
            self.clear_preview(empty_preview_message(self.session))
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

    def get_preview_texture(self, cache_key: tuple[object, ...] | None, image: Image.Image) -> ImageTk.PhotoImage:
        if cache_key is None:
            return ImageTk.PhotoImage(image)

        cached = self.preview_texture_cache.get(cache_key)
        if cached is not None:
            self.preview_texture_cache.move_to_end(cache_key)
            return cached

        texture = ImageTk.PhotoImage(image)
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

    def schedule_loading_overlay_delay(self, request_key: tuple[Path, int, int, str, bool]):
        if not self.settings.loading_indicator or self.destroyed:
            return
        if self.loading_overlay_delay_job is not None:
            self.after_cancel(self.loading_overlay_delay_job)
        self.loading_overlay_delay_job = self.after(140, lambda: self.maybe_show_loading_overlay(request_key))

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
        if self.loading_animation_job is not None or not self.loading_overlay_visible or self.destroyed:
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
        self.rendered_preview_size = (canvas_width, canvas_height)
        self.rendered_preview_scrollregion = (0, 0, region_width, region_height)
        self.restore_view_center(rel_x, rel_y)
        if self.loading_overlay_visible:
            self.render_loading_overlay()

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
        marker_color = self._apply_appearance_mode(("#111827", "#f8fafc"))
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
                    font=("SF Pro Display", 18, "bold"),
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

        canvas_width = self.preview_canvas.winfo_width()
        canvas_height = self.preview_canvas.winfo_height()
        if canvas_width < 8 or canvas_height < 8:
            self.schedule_preview_refresh()
            return

        self.preview_pipeline.set_viewport(canvas_width, canvas_height)
        rel_x, rel_y = self.get_view_center() if preserve_view else (0.5, 0.5)
        mode = "fit" if self.zoom_factor == 1.0 and not preserve_view else "zoom"
        request_key = (current, canvas_width, canvas_height, mode, self.settings.progressive_preview)
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
                self.display_preview_image(lookup.image, rel_x=rel_x, rel_y=rel_y, cache_key=texture_key)
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
                self.preview_source_path = current if self.preview_source_image is not None else None
            else:
                if lookup.image is not None and lookup.stage is not None and self.settings.progressive_preview:
                    texture_key = (current, lookup.stage, lookup.image.width, lookup.image.height)
                    self.display_preview_image(lookup.image, rel_x=rel_x, rel_y=rel_y, cache_key=texture_key)
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
        display_width = max(int(round(image_width * display_scale)), 1)
        display_height = max(int(round(image_height * display_scale)), 1)

        resized = self.preview_source_image.resize((display_width, display_height), Image.Resampling.LANCZOS)
        texture_key = (current, "zoom", display_width, display_height, round(self.zoom_factor, 3))
        self.display_preview_image(resized, rel_x=rel_x, rel_y=rel_y, cache_key=texture_key)
        self.hide_loading_overlay()

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
