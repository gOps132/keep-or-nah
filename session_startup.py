from __future__ import annotations

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
    app.preview_pipeline.reset(app.session.queue)
    app.refresh_ui()
    app.refresh_preview()


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
