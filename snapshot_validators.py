from __future__ import annotations

from pathlib import Path
import stat

from photo_groups import PhotoGroup
from photo_metadata import pillow_previewable_extensions
from photo_triage import (
    ActionMode,
    ActionRecord,
    FileOperation,
)
import file_identity


def _snapshot_int(value: object) -> int:
    if type(value) is not int or value < 0:
        raise ValueError("Snapshot number must be a non-negative integer")
    return value


def _snapshot_mode(value: object) -> ActionMode:
    if value not in {"move", "copy"} or type(value) is not str:
        raise ValueError("Snapshot action mode is invalid")
    return value


def _snapshot_source_root(value: object) -> Path:
    if type(value) is not str or not value:
        raise ValueError("Snapshot source folder is invalid")
    source_dir = Path(value).expanduser()
    if not source_dir.is_dir():
        raise ValueError("Snapshot source folder is unavailable")
    source_dir.resolve(strict=True)
    return source_dir


def _optional_path(value: object) -> Path | None:
    if value is None:
        return None
    if type(value) is not str or not value:
        raise ValueError("Snapshot destination folder is invalid")
    return Path(value).expanduser()


def _snapshot_extensions(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValueError("Snapshot extensions must be a list")
    extensions: list[str] = []
    for extension in value:
        if (
            type(extension) is not str
            or len(extension) < 2
            or not extension.startswith(".")
            or extension != extension.lower()
            or "/" in extension
            or "\\" in extension
            or extension.strip() != extension
        ):
            raise ValueError("Snapshot extension is invalid")
        extensions.append(extension)
    if len(set(extensions)) != len(extensions):
        raise ValueError("Snapshot extensions must be unique")
    return tuple(extensions)


def _is_safe_completed_stem(value: object) -> bool:
    return (
        type(value) is str
        and bool(value)
        and value not in {".", ".."}
        and "/" not in value
        and "\\" not in value
        and "\x00" not in value
    )


def _safe_raw_history_stems(raw_history: object, *, source_dir: Path) -> set[str]:
    if not isinstance(raw_history, list):
        return set()
    stems: set[str] = set()
    for item in raw_history:
        if not isinstance(item, dict):
            continue
        group_item = item.get("group")
        if isinstance(group_item, dict):
            stem = group_item.get("stem")
            if _is_safe_completed_stem(stem):
                assert isinstance(stem, str)
                stems.add(stem)
            continue
        legacy_source = item.get("source")
        if type(legacy_source) is str and _is_safe_completed_stem(Path(legacy_source).stem):
            source_path = Path(legacy_source).expanduser()
            if _is_direct_child(source_path, source_dir):
                stems.add(source_path.stem)
    return stems


def _is_direct_child(path: Path, root: Path) -> bool:
    return file_identity.is_direct_child(path, root)


def _is_regular_file(path: Path) -> bool:
    try:
        return stat.S_ISREG(path.lstat().st_mode)
    except FileNotFoundError:
        return False


def _path_identity(path: Path) -> tuple[int, int]:
    return file_identity.path_identity(path)


def _source_path_from_snapshot(
    value: object,
    *,
    source_dir: Path,
    require_existing: bool,
) -> Path:
    if type(value) is not str or not value:
        raise ValueError("Snapshot source path is invalid")
    path = Path(value).expanduser()
    if ".." in path.parts or not _is_direct_child(path, source_dir):
        raise ValueError("Snapshot source path escapes its source folder")
    if path.is_symlink():
        raise ValueError("Snapshot source path cannot be a symbolic link")
    if require_existing and not _is_regular_file(path):
        raise ValueError("Snapshot source path is not a regular file")
    return path


def _snapshot_identity(value: object) -> tuple[int, int]:
    if (
        not isinstance(value, (list, tuple))
        or len(value) != 2
        or any(type(part) is not int or part < 0 for part in value)
    ):
        raise ValueError("Snapshot destination identity must contain two integers")
    return value[0], value[1]


def _file_operation_from_snapshot(
    value: object,
    *,
    source_dir: Path,
    destination_root: Path,
) -> FileOperation:
    if not isinstance(value, dict):
        raise ValueError("Snapshot file operation is invalid")
    source = _source_path_from_snapshot(
        value["source"],
        source_dir=source_dir,
        require_existing=False,
    )
    destination_value = value["destination"]
    if type(destination_value) is not str or not destination_value:
        raise ValueError("Snapshot destination path is invalid")
    destination = Path(destination_value).expanduser()
    if ".." in destination.parts or not _is_direct_child(
        destination, destination_root
    ):
        raise ValueError("Snapshot destination escapes its action folder")
    if destination.is_symlink() or not _is_regular_file(destination):
        raise ValueError("Snapshot destination is not an owned regular file")
    destination_identity = _snapshot_identity(value["destination_identity"])
    if _path_identity(destination) != destination_identity:
        raise ValueError("Snapshot destination ownership has changed")
    return FileOperation(source, destination, destination_identity)


def _group_from_snapshot(
    value: object,
    *,
    source_dir: Path,
    require_existing: bool,
) -> PhotoGroup:
    if not isinstance(value, dict):
        raise ValueError("Snapshot photo group is invalid")
    stem = value.get("stem")
    raw_members = value.get("members")
    if type(stem) is not str or not stem or not isinstance(raw_members, list):
        raise ValueError("Snapshot photo group fields are invalid")
    if not raw_members:
        raise ValueError("Snapshot photo group has no members")
    members = tuple(
        _source_path_from_snapshot(
            item,
            source_dir=source_dir,
            require_existing=require_existing,
        )
        for item in raw_members
    )
    if len(set(members)) != len(members):
        raise ValueError("Snapshot photo group has duplicate members")
    representative = _source_path_from_snapshot(
        value.get("representative"),
        source_dir=source_dir,
        require_existing=require_existing,
    )
    if representative not in members:
        raise ValueError("Snapshot representative is not a group member")
    if any(member.stem != stem for member in members):
        raise ValueError("Snapshot photo group stem does not match its members")
    return PhotoGroup(stem, members, representative)


def _queue_group_from_snapshot(
    value: object,
    *,
    source_dir: Path,
    enabled_extensions: set[str],
    previewable_extensions: frozenset[str],
) -> PhotoGroup | None:
    if not isinstance(value, dict):
        raise ValueError("Snapshot photo group is invalid")
    stem = value.get("stem")
    raw_members = value.get("members")
    if type(stem) is not str or not stem or not isinstance(raw_members, list):
        raise ValueError("Snapshot photo group fields are invalid")
    if not raw_members:
        raise ValueError("Snapshot photo group has no members")
    declared_members = tuple(
        _source_path_from_snapshot(
            item,
            source_dir=source_dir,
            require_existing=False,
        )
        for item in raw_members
    )
    if len(set(declared_members)) != len(declared_members):
        raise ValueError("Snapshot photo group has duplicate members")
    persisted_representative = _source_path_from_snapshot(
        value.get("representative"),
        source_dir=source_dir,
        require_existing=False,
    )
    if persisted_representative not in declared_members:
        raise ValueError("Snapshot representative is not a group member")
    if any(member.stem != stem for member in declared_members):
        raise ValueError("Snapshot photo group stem does not match its members")

    members: list[Path] = []
    for member in declared_members:
        if _is_regular_file(member):
            members.append(member)
        elif member.exists():
            raise ValueError("Snapshot source path is not a regular file")
    if not members:
        return None

    eligible = [
        member
        for member in members
        if member.suffix.lower() in enabled_extensions
    ]
    if not eligible:
        return None
    representative = min(
        eligible,
        key=lambda path: (
            path.suffix.lower() not in previewable_extensions,
            path.suffix.lower(),
            path.name.lower(),
            path.name,
        ),
    )
    return PhotoGroup(stem, tuple(members), representative)


def _grouped_history_from_snapshot(
    value: object,
    *,
    source_dir: Path,
    keep_dir: Path | None,
    nah_dir: Path | None,
) -> list[ActionRecord]:
    if not isinstance(value, list):
        return []
    history: list[ActionRecord] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        try:
            decision = item["decision"]
            action_mode = item["action_mode"]
            if type(decision) is not str or decision not in {"keep", "nah"}:
                raise ValueError("Snapshot decision is invalid")
            action_mode = _snapshot_mode(action_mode)
            destination_root = keep_dir if decision == "keep" else nah_dir
            if destination_root is None:
                raise ValueError("Snapshot action destination root is unavailable")
            group = _group_from_snapshot(
                item["group"],
                source_dir=source_dir,
                require_existing=False,
            )
            raw_files = item["files"]
            if not isinstance(raw_files, list) or not raw_files:
                raise ValueError("Snapshot action files are invalid")
            files = tuple(
                _file_operation_from_snapshot(
                    operation,
                    source_dir=source_dir,
                    destination_root=destination_root,
                )
                for operation in raw_files
            )
            sources = [operation.source for operation in files]
            destinations = [operation.destination for operation in files]
            destination_identities = [
                operation.destination_identity for operation in files
            ]
            if (
                len(set(sources)) != len(sources)
                or len(set(destinations)) != len(destinations)
                or len(set(destination_identities))
                != len(destination_identities)
            ):
                raise ValueError("Snapshot action files contain duplicates")
            if tuple(operation.source for operation in files) != group.members:
                raise ValueError("Snapshot action files do not match its group")
            history.append(
                ActionRecord(
                    decision,
                    action_mode,
                    group,
                    files,
                    _snapshot_int(item["index"]),
                )
            )
        except (KeyError, OSError, OverflowError, TypeError, ValueError):
            continue
    return history
