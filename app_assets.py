from __future__ import annotations

from pathlib import Path
import sys
import tkinter as tk


def bundle_root() -> Path:
    if hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent


def resource_path(*parts: str) -> Path:
    return bundle_root().joinpath(*parts)


def logo_path() -> Path:
    return resource_path("public", "logo.png")


def apply_window_icon(window: tk.Misc) -> None:
    path = logo_path()
    if not path.is_file():
        return

    try:
        icon_image = tk.PhotoImage(file=str(path))
    except tk.TclError:
        return

    try:
        window.iconphoto(True, icon_image)
    except tk.TclError:
        return

    setattr(window, "_app_icon_image", icon_image)
