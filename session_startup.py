from __future__ import annotations

from pathlib import Path
from typing import Protocol
from tkinter import filedialog
import sys


class StartupSessionApp(Protocol):
    restored_startup_session: bool

    def choose_source_folder(self) -> None: ...


def initialize_gui_session(app: StartupSessionApp) -> None:
    """Apply common post-window startup behavior to either GUI frontend."""
    if not app.restored_startup_session:
        app.choose_source_folder()
        return

    app.last_browsed_dir = app.session.source_dir
    app.preview_pipeline.reset(preview_paths_for(app.session))
    app.refresh_ui()
    app.refresh_preview()


def session_has_pending_photos(session) -> bool:
    """Return whether recovery has pending work, even when the filter hides it."""
    pending_count = getattr(session, "pending_count", None)
    if pending_count is not None:
        return bool(pending_count)
    return bool(session.queue)


def preview_paths_for(session):
    """Project a session queue to paths, including legacy test/session objects."""
    if hasattr(session, "preview_paths"):
        return session.preview_paths
    if all(isinstance(item, Path) for item in session.queue):
        return session.queue
    return tuple(getattr(item, "representative", item) for item in session.queue)


def choose_source_directory(app, dialog=None) -> bool:
    """Run native folder picker, then replace and automatically load its source."""
    ask_directory = dialog or filedialog.askdirectory
    path = ask_directory(title="Choose Source Folder", initialdir=app.get_initial_directory())
    if not path:
        return False
    app.replace_source_folder(path)
    app.load_queue()
    return True


def show_session_warning(app, message: str) -> None:
    """Surface recovery failure without blocking the current photo action."""
    app.title("Keep or Nah — Session recovery unavailable")
    print(message, file=sys.stderr)
