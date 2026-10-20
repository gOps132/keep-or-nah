"""The composition root of the desktop GUI.

`gui_app.py` owns the `App` class, the application state, and the widget
tree. Everything else was extracted into the `ui` package, one cohesive
concern per module, and is mixed into `App` here:

| Module                  | Responsibility                                        |
| ----------------------- | ----------------------------------------------------- |
| `ui.preview_controller` | Preview rendering, texture caching, loading overlay   |
| `ui.compare_controller` | Split Comparison and the action buttons               |
| `ui.thumbnail_strip`    | The Thumbnail Strip and its decoding worker           |
| `ui.shortcuts`          | Keyboard bindings and their handlers                  |
| `ui.viewport`           | Zoom, pan, and viewport centering                     |
| `ui.layout`             | Construction of the `App` widget tree                 |
| `ui.settings_dialog`    | The Preview Settings dialog                           |
| `ui.session_commands`   | Commands that act on the photo session                |

The mixins are mixins, not collaborators: their methods operate on `self`,
so the `App` stays the single owner of the widget tree. A Tk widget has
exactly one parent, and nothing in the `ui` package ever creates one.

The module-level names `Image`, `ImageTk`, and `thumbnail_rgba` are
published here on purpose. The test suite patches them by name, and the
code that uses them resolves them through this module at call time, so a
patch reaches the code that moved into the `ui` package (see
`ui.gui_targets`).
"""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from collections import OrderedDict
from pathlib import Path
from tkinter import messagebox

import customtkinter as ctk
from PIL import Image, ImageTk

from app_assets import apply_window_icon
from app_settings import AppSettings
from burst_clustering import BurstClusterer, PhotoBurstInfo
from keep_or_nah_core import thumbnail_rgba as thumbnail_rgba
from photo_session import PhotoSession
from preview_pipeline import PreviewPipeline
from session_persistence import SessionLifecycle
from session_startup import (
    choose_source_directory as choose_source_directory,
)
from session_startup import (
    initialize_gui_session,
    session_has_pending_photos,
    show_session_warning,
)
from split_compare import CompareCandidate, ComparePairSelector
from ui.compare_controller import CompareControllerMixin
from ui.layout import LayoutMixin
from ui.preview_controller import PreviewControllerMixin
from ui.session_commands import SessionCommandsMixin
from ui.settings_dialog import SettingsDialogMixin
from ui.shortcuts import ShortcutsMixin
from ui.thumbnail_strip import STRIP_THUMBNAIL_SIZE as STRIP_THUMBNAIL_SIZE
from ui.thumbnail_strip import ThumbnailStripMixin
from ui.viewport import ViewportMixin
from view_filter import (
    ExtensionFilterModel,
    empty_preview_message,
)
from view_filter import (
    apply_extension_filter as apply_extension_filter,
)
from view_filter import (
    save_view_filter_settings as save_view_filter_settings,
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


class App(
    PreviewControllerMixin,
    CompareControllerMixin,
    ThumbnailStripMixin,
    ShortcutsMixin,
    ViewportMixin,
    LayoutMixin,
    SettingsDialogMixin,
    SessionCommandsMixin,
    DnDCTk,
):
    """The desktop photo culling and triage window."""

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
        self.session.staged_mode = self.settings.staged_decisions
        self.restored_startup_session = session_has_pending_photos(self.session)
        self.preview_pipeline = PreviewPipeline(
            cache_budget_mb=self.settings.preview_cache_budget_mb
        )
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
        self.review_commit_modal = None
        self.staged_mode_var = tk.BooleanVar(value=self.settings.staged_decisions)
        self.destroyed = False
        self.preview_texture_cache: OrderedDict[tuple[object, ...], ImageTk.PhotoImage] = (
            OrderedDict()
        )
        self.preview_texture_cache_limit = 12
        self.thumbnail_refs: list[ImageTk.PhotoImage] = []
        self.thumbnail_cache: OrderedDict[Path, ImageTk.PhotoImage | None] = OrderedDict()
        self.thumbnail_cache_limit = 192
        self.thumbnail_raws: OrderedDict[Path, object] = OrderedDict()
        self.thumbnail_pending_requests: set[Path] = set()
        self.burst_clusterer = BurstClusterer()
        self.burst_info_map: dict[Path, PhotoBurstInfo] = {}
        self.best_shots: set[Path] = set()
        self.burst_shots: set[Path] = set()
        self.thumbnail_worker_thread: threading.Thread | None = None
        self.thumbnail_work_queue: queue.Queue | None = None
        self.thumbnail_result_queue: queue.Queue | None = None
        self.thumbnail_poll_job = None
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
        self.compare_mode = False
        self.compare_pair_selector = ComparePairSelector()
        self.compare_candidate_offset = 1
        self.compare_pair: tuple[CompareCandidate, CompareCandidate] | None = None
        self.compare_photo: ImageTk.PhotoImage | None = None
        self.compare_source_image: Image.Image | None = None
        self.compare_source_path: Path | None = None
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
        self.footer_frame.grid_columnconfigure((0, 1, 2, 3), weight=1)

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
        if self.thumbnail_poll_job is not None:
            self.after_cancel(self.thumbnail_poll_job)
            self.thumbnail_poll_job = None
        if self.thumbnail_work_queue is not None:
            self.thumbnail_work_queue.put(None)
        self.thumbnail_work_queue = None
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

    def initialize_drag_and_drop(self):
        if TkinterDnD is None:
            self.dnd_enabled = False
            return

        try:
            self.TkdndVersion = TkinterDnD._require(self)
            self.dnd_enabled = True
        except Exception:
            self.dnd_enabled = False

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

    def refresh_ui(self):
        current = self.session.active_photo
        self.update_selector_buttons()
        self.update_action_button_visibility()

        self.load_button.configure(
            state="normal" if self.session.source_dir is not None else "disabled"
        )
        self.undo_button.configure(state="normal" if self.session.can_undo else "disabled")

        zoom_state = "normal" if current is not None else "disabled"
        self.zoom_in_button.configure(state=zoom_state)
        self.zoom_out_button.configure(state=zoom_state)
        self.zoom_fit_button.configure(state=zoom_state)

        action_state = "normal" if current is not None else "disabled"
        self.keep_button.configure(state=action_state)
        self.nah_button.configure(state=action_state)
        if hasattr(self, "flag_button"):
            self.flag_button.configure(state=action_state)
        if hasattr(self, "review_button"):
            staged_count = self.session.staged_summary.total_count
            btn_text = f"Review Batch ({staged_count})" if staged_count > 0 else "Review Batch"
            self.review_button.configure(
                text=btn_text,
                state="normal" if staged_count > 0 or self.session.staged_mode else "disabled",
            )
        if hasattr(self, "compare_mode_button"):
            can_compare = len(getattr(self.session, "queue", ())) >= 2
            self.compare_mode_button.configure(
                state="normal" if can_compare else "disabled",
                text="1-Up (C)" if getattr(self, "compare_mode", False) else "2-Up (C)",
                fg_color="#3b82f6"
                if getattr(self, "compare_mode", False)
                else ["#3a7ebf", "#1f538d"],
            )
        self.refresh_thumbnail_strip()

        if current is None:
            self.reset_preview_request_state()
            self.clear_preview(empty_preview_message(self.session))

        self.focus_set()
