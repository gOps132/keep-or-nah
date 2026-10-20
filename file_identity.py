from __future__ import annotations

import os
import stat
import sys
from collections.abc import Callable
from pathlib import Path

from keep_or_nah_core import remove_verified_file


def _get_os() -> object:
    mod = sys.modules.get("photo_session")
    if mod and hasattr(mod, "os"):
        return mod.os
    return os


def _get_remove_fn() -> Callable[..., object]:
    mod = sys.modules.get("photo_session")
    if mod and hasattr(mod, "remove_verified_file"):
        return mod.remove_verified_file
    return remove_verified_file


def path_occupied(path: Path) -> bool:
    """Return true for every directory entry, including dangling symlinks."""
    try:
        path.lstat()
    except FileNotFoundError:
        return False
    return True


def validate_basename(name: str) -> None:
    if not name or Path(name).name != name or name in {".", ".."}:
        raise OSError(f"Unsafe direct-child filename: {name!r}")


def path_identity(path: Path) -> tuple[int, int]:
    path_stat = path.lstat()
    if path.is_symlink() or not stat.S_ISREG(path_stat.st_mode):
        raise OSError(f"Owned path is no longer a regular file: {path}")
    return path_stat.st_dev, path_stat.st_ino


def directory_identity(path: Path) -> tuple[int, int]:
    path_stat = path.lstat()
    if path.is_symlink() or not stat.S_ISDIR(path_stat.st_mode):
        raise OSError(f"Destination root is no longer a directory: {path}")
    return path_stat.st_dev, path_stat.st_ino


def require_directory_identity(path: Path, expected_identity: tuple[int, int]) -> None:
    if directory_identity(path) != expected_identity:
        raise OSError(f"Destination root identity changed: {path}")


def require_owned_path(path: Path, expected_identity: tuple[int, int]) -> None:
    if path_identity(path) != expected_identity:
        raise OSError(f"Refusing to remove a replaced path: {path}")


def remove_owned_path(path: Path, expected_identity: tuple[int, int]) -> None:
    remove_fn = _get_remove_fn()
    remove_fn(str(path), expected_identity[0], expected_identity[1])


def is_direct_child(path: Path, root: Path) -> bool:
    return path.resolve(strict=False).parent == root.resolve(strict=False)


def validate_destination_parent(path: Path, destination_root: Path) -> None:
    try:
        resolved_parent = path.parent.resolve(strict=True)
    except OSError as error:
        raise OSError(f"Destination parent cannot be resolved safely: {path.parent}") from error
    if resolved_parent != destination_root:
        raise OSError(f"Destination parent escapes the selected folder: {path.parent}")


def validate_destination(path: Path, destination_root: Path) -> None:
    validate_destination_parent(path, destination_root)
    if path_occupied(path):
        raise FileExistsError(f"Destination became occupied: {path}")
