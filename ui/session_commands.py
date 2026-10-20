"""Commands that act on the photo session.

Choosing folders, loading the queue, navigating between photo groups,
recording a triage decision, undoing one, and opening the batch review
modal are the actions the user drives the session with.

Every method here is a mixin method: it operates on `self`, which is the
`App` that owns the widget tree.
"""

from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
from tkinter import filedialog, messagebox

from app_settings import AppSettings
from photo_session import PhotoSessionError
from review_commit_modal import ReviewCommitModal
from session_startup import preview_paths_for
from ui.gui_targets import gui_module


class SessionCommandsMixin:
    """Commands that act on the photo session."""

    def toggle_staged_mode(self):
        new_val = bool(self.staged_mode_var.get())
        self.session.staged_mode = new_val
        self.settings = AppSettings(
            progressive_preview=self.settings.progressive_preview,
            loading_indicator=self.settings.loading_indicator,
            preview_cache_budget_mb=self.settings.preview_cache_budget_mb,
            staged_decisions=new_val,
        ).normalized()
        self.settings.save()
        self.refresh_ui()

    def open_review_commit_modal(self):
        if self.review_commit_modal is not None and self.review_commit_modal.winfo_exists():
            self.review_commit_modal.focus()
            self.review_commit_modal.lift()
            return
        self.review_commit_modal = ReviewCommitModal(
            self, self.session, on_committed=self.handle_batch_committed
        )

    def handle_batch_committed(self):
        self.persist_session()
        self.refresh_ui()

    def choose_source_folder(self):
        # Resolved through the composition root so a patch on
        # `gui_app.choose_source_directory` still reaches this code.
        gui_module().choose_source_directory(self)

    def replace_source_folder(self, path):
        self.reset_preview_request_state()
        self.session.set_source_dir(path)
        self.last_browsed_dir = Path(path)
        self.preview_texture_cache = OrderedDict()
        self.thumbnail_cache = OrderedDict()
        self.thumbnail_raws = OrderedDict()
        self.thumbnail_pending_requests = set()
        self.burst_info_map.clear()
        self.best_shots.clear()
        self.burst_shots.clear()
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
        path = filedialog.askdirectory(
            title="Choose Keep Folder", initialdir=self.get_initial_directory()
        )
        if not path:
            return

        self.session.set_keep_dir(path)
        self.last_browsed_dir = Path(path)
        self.persist_session()
        self.refresh_ui()

    def choose_nah_folder(self):
        path = filedialog.askdirectory(
            title="Choose Nah Folder", initialdir=self.get_initial_directory()
        )
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
