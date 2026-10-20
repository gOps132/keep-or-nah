from __future__ import annotations

import os
import stat
import sys
from collections.abc import Callable
from pathlib import Path

from keep_or_nah_core import file_identity as native_file_identity
from keep_or_nah_core import remove_verified_file

# The components of a file identity, in the canonical order: the device, the
# inode, the size, and the change time of the inode in seconds and
# nanoseconds.
#
# The device and the inode alone are not enough. Filesystems recycle inode
# numbers, so a replacement published at the same path can carry the inode
# of the file it replaced. The size and the change time are not recycled,
# so the identity of a replacement never matches the identity that was
# recorded for the file it replaced.
IDENTITY_COMPONENT_COUNT = 5

# The components a legacy identity records: the device and the inode. A
# session saved before the identity was extended records those two, and it
# is verified under exactly the guarantee it was recorded under, rather
# than being discarded.
LEGACY_IDENTITY_COMPONENT_COUNT = 2

# The components of a file identity that publishing cannot change: the
# device, the inode, and the size. The change time of the inode moves when
# a file is published, because publishing changes the file itself: a hard
# link changes the link count of the inode, and a rename changes the inode
# on the filesystems that track the change of a moved file.
PUBLISHED_COMPONENT_COUNT = 3

# The names the native module expects the components under.
IDENTITY_COMPONENT_NAMES = ("dev", "ino", "size", "ctime_sec", "ctime_nsec")

FileIdentity = tuple[int, ...]


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


def path_identity(path: Path) -> FileIdentity:
    """The identity of a regular, non-symlink file entry."""
    path_stat = path.lstat()
    if path.is_symlink() or not stat.S_ISREG(path_stat.st_mode):
        raise OSError(f"Owned path is no longer a regular file: {path}")
    return tuple(native_file_identity(str(path)))


def legacy_path_identity(path: Path) -> tuple[int, int]:
    """The identity of a path in the terms a legacy identity was recorded in.

    A session saved before the identity was extended holds the device and
    the inode that `os.lstat` reports. On Windows the native core reports
    the volume serial number and the file index from the Windows API, and
    the volume serial number is not the drive number that `os.lstat`
    reports: the two are different numbers in different namespaces. A
    legacy identity therefore has to be compared against a legacy reading,
    or a session saved on Windows would lose its history for no good reason.
    """
    path_stat = path.lstat()
    if path.is_symlink() or not stat.S_ISREG(path_stat.st_mode):
        raise OSError(f"Owned path is no longer a regular file: {path}")
    return path_stat.st_dev, path_stat.st_ino


def read_identity(path: Path, expected: FileIdentity | None = None) -> FileIdentity:
    """The identity of a path, read in the terms the expected identity uses.

    A legacy identity is read the legacy way. A full identity is read the
    native way.
    """
    if expected is not None and len(expected) == LEGACY_IDENTITY_COMPONENT_COUNT:
        return legacy_path_identity(path)
    return path_identity(path)


def directory_identity(path: Path) -> tuple[int, int]:
    path_stat = path.lstat()
    if path.is_symlink() or not stat.S_ISDIR(path_stat.st_mode):
        raise OSError(f"Destination root is no longer a directory: {path}")
    return path_stat.st_dev, path_stat.st_ino


def require_directory_identity(path: Path, expected_identity: tuple[int, int]) -> None:
    if directory_identity(path) != expected_identity:
        raise OSError(f"Destination root identity changed: {path}")


def identity_matches(current: FileIdentity, expected: FileIdentity) -> bool:
    """Whether a freshly read identity still carries the recorded one.

    Only the components that were recorded are compared. A session saved
    before the identity was extended records the device and the inode
    only, and it is verified under exactly the guarantee it was recorded
    under.
    """
    if len(expected) < LEGACY_IDENTITY_COMPONENT_COUNT:
        return False
    if len(expected) > len(current):
        return False
    return current[: len(expected)] == tuple(expected)


def require_owned_path(path: Path, expected_identity: FileIdentity) -> None:
    if not identity_matches(read_identity(path, expected_identity), expected_identity):
        raise OSError(f"Refusing to remove a replaced path: {path}")


def remove_owned_path(path: Path, expected_identity: FileIdentity) -> None:
    remove_fn = _get_remove_fn()
    if len(expected_identity) == LEGACY_IDENTITY_COMPONENT_COUNT:
        # A legacy identity is verified in the namespace it was recorded in,
        # and the native removal is handed the identity it can check for
        # itself. The native removal re-reads the identity and refuses to
        # remove a path that changed in between.
        if not identity_matches(legacy_path_identity(path), expected_identity):
            raise OSError(f"Refusing to remove a replaced path: {path}")
        remove_fn(str(path), *path_identity(path))
        return
    remove_fn(str(path), *expected_identity)


def published_identity(path: Path, recorded_identity: FileIdentity) -> FileIdentity:
    """The identity of a published file whose change time has moved.

    Publishing changes the file itself: creating a hard link changes the
    link count of the inode, and removing the staged entry changes it
    again. The link count is part of the change time, so the change time
    of a published file moves while the operation runs. The components a
    publish cannot change decide whether the entry still is the file that
    was published.
    """
    current = path_identity(path)
    if current[:PUBLISHED_COMPONENT_COUNT] != recorded_identity[:PUBLISHED_COMPONENT_COUNT]:
        raise OSError(f"The published file was replaced: {path}")
    return current


def remove_published_entry(path: Path, recorded_identity: FileIdentity) -> None:
    """Remove an entry this operation published, if it still is ours.

    The staged entry and the published file share their inode, so
    removing one of them moves the change time of the other. The entry is
    matched against the recorded identity on the components a publish
    cannot change, and its identity is read again so that the native
    removal verifies it a second time.
    """
    current = path_identity(path)
    if current[:PUBLISHED_COMPONENT_COUNT] != recorded_identity[:PUBLISHED_COMPONENT_COUNT]:
        raise OSError(f"Refusing to remove a replaced path: {path}")
    remove_owned_path(path, current)


def identity_matches_recorded(path: Path, expected: FileIdentity) -> bool:
    """Whether a path still carries the recorded identity."""
    return identity_matches(read_identity(path, expected), expected)


def expected_identity_arguments(identity: FileIdentity | None) -> dict[str, int]:
    """The native stage function's expected-identity keywords for a record."""
    if identity is None:
        return {}
    if len(identity) not in (LEGACY_IDENTITY_COMPONENT_COUNT, IDENTITY_COMPONENT_COUNT):
        raise OSError(f"Recorded file identity is not usable: {identity!r}")
    return {
        f"expected_{name}": value
        for name, value in zip(IDENTITY_COMPONENT_NAMES, identity, strict=False)
    }


def native_expected_arguments(path: Path, identity: FileIdentity | None) -> dict[str, int]:
    """The expected-identity keywords for a record, in the native namespace.

    A legacy identity was recorded in the namespace `os.lstat` reports,
    which is not the native namespace on every platform: on Windows the
    native core reports the volume serial number and `os.lstat` reports the
    drive number. The legacy identity is verified by the caller, in the
    namespace it was recorded in, and the native function is handed the
    identity it can check for itself, so a path replaced in between is
    still caught.
    """
    if identity is None:
        return {}
    if len(identity) == LEGACY_IDENTITY_COMPONENT_COUNT:
        return expected_identity_arguments(path_identity(path))
    return expected_identity_arguments(identity)


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
