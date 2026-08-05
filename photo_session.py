from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
import errno
import math
import os
import secrets
import stat
import tempfile
from typing import Literal

from photo_groups import PhotoGroup, build_photo_groups, discover_extensions


SUPPORTED_IMAGE_EXTENSIONS = {
    ".bmp",
    ".gif",
    ".heic",
    ".jpeg",
    ".jpg",
    ".png",
    ".tif",
    ".tiff",
    ".webp",
}

Decision = Literal["keep", "nah"]
ActionMode = Literal["move", "copy"]


class PhotoSessionError(RuntimeError):
    """A recoverable problem while operating on the current photo group."""

    def __init__(
        self,
        message: str,
        *,
        primary_error: BaseException | None = None,
        rollback_errors: tuple[BaseException, ...] = (),
        completed_operations: tuple[FileOperation, ...] = (),
    ) -> None:
        super().__init__(message)
        self.primary_error = primary_error
        self.rollback_errors = rollback_errors
        self.completed_operations = completed_operations


@dataclass(frozen=True)
class FileOperation:
    source: Path
    destination: Path
    destination_identity: tuple[int, int] | None = None


@dataclass(frozen=True)
class DecisionResult:
    decision: Decision
    action_mode: ActionMode
    group: PhotoGroup
    files: tuple[FileOperation, ...]
    remaining_count: int

    @property
    def source(self) -> Path:
        return self.group.representative

    @property
    def destination(self) -> Path:
        return self._representative_operation.destination

    @property
    def _representative_operation(self) -> FileOperation:
        return next(
            (item for item in self.files if item.source == self.group.representative),
            self.files[0],
        )


@dataclass(frozen=True)
class UndoResult:
    decision: Decision
    action_mode: ActionMode
    group: PhotoGroup
    files: tuple[FileOperation, ...]
    remaining_count: int

    @property
    def source(self) -> Path:
        return self.group.representative

    @property
    def destination(self) -> Path:
        return next(
            (
                item.destination
                for item in self.files
                if item.source == self.group.representative
            ),
            self.files[0].destination,
        )


@dataclass(frozen=True, init=False)
class ActionRecord:
    decision: Decision
    action_mode: ActionMode
    group: PhotoGroup
    files: tuple[FileOperation, ...]
    index: int

    def __init__(
        self,
        decision: Decision,
        action_mode: ActionMode,
        group: PhotoGroup | Path,
        files: tuple[FileOperation, ...] | Path,
        index: int,
    ) -> None:
        # Accept the former (source, destination) arguments so existing version-1
        # snapshots and callers remain usable until the versioned migration lands.
        if isinstance(group, Path):
            source = group
            if not isinstance(files, Path):
                raise TypeError("A legacy action destination must be a path")
            group = PhotoGroup(source.stem, (source,), source)
            files = (FileOperation(source, files),)
        elif isinstance(files, Path):
            raise TypeError("Compound action files must be FileOperation objects")

        object.__setattr__(self, "decision", decision)
        object.__setattr__(self, "action_mode", action_mode)
        object.__setattr__(self, "group", group)
        object.__setattr__(self, "files", tuple(files))
        object.__setattr__(self, "index", index)

    @property
    def source(self) -> Path:
        return self.group.representative

    @property
    def destination(self) -> Path:
        return next(
            (
                item.destination
                for item in self.files
                if item.source == self.group.representative
            ),
            self.files[0].destination,
        )

    @property
    def destination_identity(self) -> tuple[int, int] | None:
        return next(
            (
                item.destination_identity
                for item in self.files
                if item.source == self.group.representative
            ),
            self.files[0].destination_identity,
        )


class PhotoSession:
    def __init__(self) -> None:
        self.source_dir: Path | None = None
        self.keep_dir: Path | None = None
        self.nah_dir: Path | None = None
        self.action_mode: ActionMode = "move"
        self.queue: list[PhotoGroup | Path] = []
        self.active_index = 0
        self.history: list[ActionRecord] = []
        self.total_loaded = 0
        self.keep_count = 0
        self.nah_count = 0
        self.available_extensions: tuple[str, ...] = ()
        self.enabled_extensions: set[str] = set()
        self._extensions_source: Path | None = None
        self._partial_copy_undo: set[FileOperation] = set()

    def to_snapshot(self) -> dict[str, object]:
        snapshot: dict[str, object] = {
            "source_dir": str(self.source_dir) if self.source_dir is not None else None,
            "keep_dir": str(self.keep_dir) if self.keep_dir is not None else None,
            "nah_dir": str(self.nah_dir) if self.nah_dir is not None else None,
            "action_mode": self.action_mode,
            # Keep the version-1 queue field compatible until Task 4 introduces
            # explicit snapshot versioning and migration.
            "queue": [str(self._as_group(item).representative) for item in self.queue],
            "active_index": self.active_index,
            "total_loaded": self.total_loaded,
            "keep_count": self.keep_count,
            "nah_count": self.nah_count,
            "history": [
                {
                    "decision": record.decision,
                    "action_mode": record.action_mode,
                    "source": str(record.source),
                    "destination": str(record.destination),
                    "destination_identity": (
                        list(record.destination_identity)
                        if record.destination_identity is not None
                        else None
                    ),
                    "index": record.index,
                }
                for record in self.history
            ],
        }
        return snapshot

    @classmethod
    def from_snapshot(cls, data: object) -> PhotoSession | None:
        if not isinstance(data, dict):
            return None
        try:
            source_value = data.get("source_dir")
            source_dir = (
                Path(source_value).expanduser() if isinstance(source_value, str) else None
            )
            if source_dir is None or not source_dir.is_dir():
                return None

            raw_queue = data.get("queue", [])
            if not isinstance(raw_queue, list):
                return None
            source_root = source_dir.resolve()
            valid_queue_items: list[tuple[int, Path]] = []
            for index, value in enumerate(raw_queue):
                if not isinstance(value, str):
                    continue
                path = Path(value).expanduser()
                if path.resolve(strict=False).parent != source_root:
                    return None
                if path.is_file() and path.suffix.lower() in SUPPORTED_IMAGE_EXTENSIONS:
                    valid_queue_items.append((index, path))
            if not valid_queue_items:
                return None
            queue = [path for _, path in valid_queue_items]
            original_active_index = min(
                cls._snapshot_int(data.get("active_index", 0), 0),
                len(raw_queue) - 1,
            )
            nearest_original_index, _ = min(
                valid_queue_items,
                key=lambda item: (abs(item[0] - original_active_index), item[0]),
            )

            mode = data.get("action_mode", "move")
            if mode not in {"move", "copy"}:
                return None

            session = cls()
            session.source_dir = source_dir
            session.keep_dir = cls._optional_path(data.get("keep_dir"))
            session.nah_dir = cls._optional_path(data.get("nah_dir"))
            session.action_mode = mode
            session.queue = queue
            session.active_index = next(
                index
                for index, (original_index, _) in enumerate(valid_queue_items)
                if original_index == nearest_original_index
            )
            session.total_loaded = max(
                cls._snapshot_int(data.get("total_loaded", len(queue)), len(queue)),
                len(queue),
            )
            session.keep_count = cls._snapshot_int(data.get("keep_count", 0), 0)
            session.nah_count = cls._snapshot_int(data.get("nah_count", 0), 0)
            session.history = cls._history_from_snapshot(
                data.get("history", []),
                source_dir=source_dir,
                keep_dir=session.keep_dir,
                nah_dir=session.nah_dir,
            )
            session.available_extensions = discover_extensions(source_dir)
            session.enabled_extensions = set(session.available_extensions)
            session._extensions_source = source_dir.resolve()
            return session
        except (OSError, OverflowError, TypeError, ValueError):
            return None

    @staticmethod
    def _snapshot_int(value: object, minimum: int) -> int:
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("Snapshot number must be finite")
        return max(int(value), minimum)

    @staticmethod
    def _optional_path(value: object) -> Path | None:
        return Path(value).expanduser() if isinstance(value, str) and value else None

    @staticmethod
    def _history_from_snapshot(
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
                if decision not in {"keep", "nah"} or action_mode not in {
                    "move",
                    "copy",
                }:
                    continue
                source = Path(item["source"]).expanduser()
                destination = Path(item["destination"]).expanduser()
                destination_identity = PhotoSession._snapshot_identity(
                    item["destination_identity"]
                )
                destination_root = keep_dir if decision == "keep" else nah_dir
                if destination_root is None:
                    continue
                if not PhotoSession._is_direct_child(source, source_dir):
                    continue
                if not PhotoSession._is_direct_child(destination, destination_root):
                    continue
                if PhotoSession._path_identity(destination) != destination_identity:
                    continue
                group = PhotoGroup(source.stem, (source,), source)
                history.append(
                    ActionRecord(
                        decision,
                        action_mode,
                        group,
                        (
                            FileOperation(
                                source,
                                destination,
                                destination_identity,
                            ),
                        ),
                        PhotoSession._snapshot_int(item["index"], 0),
                    )
                )
            except (KeyError, OSError, OverflowError, TypeError, ValueError):
                continue
        return history

    @staticmethod
    def _snapshot_identity(value: object) -> tuple[int, int]:
        if (
            not isinstance(value, (list, tuple))
            or len(value) != 2
            or any(type(part) is not int or part < 0 for part in value)
        ):
            raise ValueError("Snapshot destination identity must contain two integers")
        return value[0], value[1]

    @staticmethod
    def _is_direct_child(path: Path, root: Path) -> bool:
        return path.resolve(strict=False).parent == root.resolve(strict=False)

    @staticmethod
    def _as_group(item: PhotoGroup | Path) -> PhotoGroup:
        if isinstance(item, PhotoGroup):
            return item
        return PhotoGroup(item.stem, (item,), item)

    @property
    def active_group(self) -> PhotoGroup | None:
        if not self.queue:
            return None
        return self._as_group(self.queue[self.active_index])

    @property
    def active_photo(self) -> Path | None:
        group = self.active_group
        return group.representative if group is not None else None

    @property
    def preview_paths(self) -> tuple[Path, ...]:
        """Representatives suitable for preview and thumbnail infrastructure."""
        return tuple(self._as_group(item).representative for item in self.queue)

    @property
    def remaining_count(self) -> int:
        return len(self.queue)

    @property
    def processed_count(self) -> int:
        if not self.total_loaded:
            return 0
        return self.total_loaded - self.remaining_count

    @property
    def current_position(self) -> int:
        if not self.remaining_count:
            return 0
        return self.active_index + 1

    @property
    def can_undo(self) -> bool:
        return bool(self.history)

    def set_source_dir(self, path: str | Path | None) -> None:
        self.source_dir = Path(path).expanduser() if path else None

    def set_keep_dir(self, path: str | Path | None) -> None:
        self.keep_dir = Path(path).expanduser() if path else None

    def set_nah_dir(self, path: str | Path | None) -> None:
        self.nah_dir = Path(path).expanduser() if path else None

    def set_action_mode(self, mode: str) -> None:
        if mode not in {"move", "copy"}:
            raise PhotoSessionError(f"Unsupported action mode: {mode}")
        self.action_mode = mode

    def reset_queue(self) -> None:
        self.queue = []
        self.active_index = 0
        self.history = []
        self.total_loaded = 0
        self.keep_count = 0
        self.nah_count = 0
        self._partial_copy_undo.clear()

    def load_queue(self) -> int:
        source_dir = self._validated_source_dir()
        source_identity = source_dir.resolve()
        available = discover_extensions(source_dir)
        if self._extensions_source != source_identity:
            self.enabled_extensions = set(available)
        else:
            self.enabled_extensions.intersection_update(available)

        self.available_extensions = available
        self._extensions_source = source_identity
        self.queue = build_photo_groups(
            source_dir,
            self.enabled_extensions,
            SUPPORTED_IMAGE_EXTENSIONS,
        )
        self.active_index = 0
        self.history = []
        self.total_loaded = len(self.queue)
        self.keep_count = 0
        self.nah_count = 0
        self._partial_copy_undo.clear()
        return self.total_loaded

    def apply_extension_filter(self, enabled: set[str]) -> int:
        source_dir = self._validated_source_dir()
        previous_group = self.active_group
        previous_stem = previous_group.stem if previous_group is not None else None
        available = discover_extensions(source_dir)
        self.available_extensions = available
        self.enabled_extensions = {
            extension.lower()
            for extension in enabled
            if extension.lower() in set(available)
        }

        all_groups = build_photo_groups(
            source_dir,
            set(available),
            SUPPORTED_IMAGE_EXTENSIONS,
        )
        processed_stems = {record.group.stem for record in self.history}
        rebuilt = [
            group
            for group in build_photo_groups(
                source_dir,
                self.enabled_extensions,
                SUPPORTED_IMAGE_EXTENSIONS,
            )
            if group.stem not in processed_stems
        ]
        self.queue = rebuilt

        if not rebuilt:
            self.active_index = 0
        else:
            retained_index = next(
                (
                    index
                    for index, group in enumerate(rebuilt)
                    if group.stem == previous_stem
                ),
                None,
            )
            if retained_index is not None:
                self.active_index = retained_index
            else:
                all_positions = {
                    group.stem: index for index, group in enumerate(all_groups)
                }
                previous_position = all_positions.get(previous_stem, self.active_index)
                self.active_index = min(
                    range(len(rebuilt)),
                    key=lambda index: (
                        abs(all_positions.get(rebuilt[index].stem, index) - previous_position),
                        all_positions.get(rebuilt[index].stem, index),
                    ),
                )

        self.total_loaded = self.keep_count + self.nah_count + len(self.queue)
        return len(self.queue)

    def _validated_source_dir(self) -> Path:
        if self.source_dir is None:
            raise PhotoSessionError("Choose a source folder before loading photos.")
        if not self.source_dir.is_dir():
            raise PhotoSessionError(
                f"Source folder does not exist: {self.source_dir}"
            )
        return self.source_dir

    def set_active_index(self, index: int) -> Path | None:
        if not self.queue:
            self.active_index = 0
            return None

        self.active_index = min(max(index, 0), len(self.queue) - 1)
        return self.active_photo

    def move_active(self, offset: int) -> Path | None:
        return self.set_active_index(self.active_index + offset)

    def decide(self, decision: Decision) -> DecisionResult:
        if decision not in {"keep", "nah"}:
            raise PhotoSessionError(f"Unsupported decision: {decision}")
        group = self.active_group
        if group is None:
            raise PhotoSessionError("There are no loaded photos left to sort.")
        current_index = self.active_index

        remaining_members = tuple(path for path in group.members if path.is_file())
        if not remaining_members:
            self._remove_queue_item(current_index)
            self.total_loaded = self.keep_count + self.nah_count + len(self.queue)
            raise PhotoSessionError(
                "The current photo group's files are missing, so it was removed from the queue."
            )
        if remaining_members != group.members:
            representative = (
                group.representative
                if group.representative in remaining_members
                else self._representative_for(remaining_members)
            )
            group = PhotoGroup(group.stem, remaining_members, representative)

        destination_dir = self.keep_dir if decision == "keep" else self.nah_dir
        if destination_dir is None:
            label = "Keep" if decision == "keep" else "Nah"
            raise PhotoSessionError(f"Choose a {label} folder before sorting.")

        destination_dir = destination_dir.expanduser()
        try:
            destination_dir.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise PhotoSessionError(
                f"Could not prepare the destination folder: {error}",
                primary_error=error,
            ) from error

        if self.action_mode == "move":
            try:
                source_parent = group.members[0].resolve().parent
                destination_parent = destination_dir.resolve()
            except FileNotFoundError:
                source_parent = group.members[0].parent
                destination_parent = destination_dir

            if source_parent == destination_parent:
                raise PhotoSessionError(
                    "Move mode requires destination folders different from the current photo folder."
                )

        operations = self._execute_group_operations(
            group, group.members[0].parent, destination_dir
        )

        self._remove_queue_item(current_index)
        self.history.append(
            ActionRecord(
                decision,
                self.action_mode,
                group,
                operations,
                current_index,
            )
        )
        if decision == "keep":
            self.keep_count += 1
        else:
            self.nah_count += 1

        return DecisionResult(
            decision,
            self.action_mode,
            group,
            operations,
            self.remaining_count,
        )

    def _remove_queue_item(self, index: int) -> None:
        self.queue.pop(index)
        if self.queue:
            self.active_index = min(index, len(self.queue) - 1)
        else:
            self.active_index = 0

    def _representative_for(self, members: tuple[Path, ...]) -> Path:
        return min(
            members,
            key=lambda path: (
                path.suffix.lower() not in SUPPORTED_IMAGE_EXTENSIONS,
                path.suffix.lower(),
                path.name.lower(),
                path.name,
            ),
        )

    def _group_destinations(
        self,
        group: PhotoGroup,
        destination_dir: Path,
        destination_fd: int,
    ) -> tuple[FileOperation, ...]:
        collision_number = 0
        while True:
            operations = tuple(
                FileOperation(
                    member,
                    destination_dir
                    / (
                        member.name
                        if collision_number == 0
                        else f"{member.stem} ({collision_number}){member.suffix}"
                    ),
                )
                for member in group.members
            )
            if not any(
                self._entry_occupied(destination_fd, item.destination.name)
                for item in operations
            ):
                return operations
            collision_number += 1

    def _execute_group_operations(
        self,
        group: PhotoGroup,
        source_root: Path,
        destination_root: Path,
    ) -> tuple[FileOperation, ...]:
        if not self._supports_rooted_dir_fd():
            return self._execute_group_operations_fallback(
                group, source_root, destination_root
            )
        try:
            resolved_source_root = source_root.resolve(strict=True)
            resolved_destination_root = destination_root.resolve(strict=True)
            with self._open_directory_fd(source_root) as source_fd, self._open_directory_fd(
                destination_root
            ) as destination_fd:
                operations = self._group_destinations(
                    group, destination_root, destination_fd
                )
                return self._execute_operations(
                    operations,
                    source_fd,
                    destination_fd,
                    resolved_source_root,
                    resolved_destination_root,
                )
        except PhotoSessionError:
            raise
        except Exception as error:
            raise PhotoSessionError(
                f"Could not open a photo group folder safely: {error}",
                primary_error=error,
            ) from error

    @staticmethod
    def _supports_rooted_dir_fd() -> bool:
        return (
            hasattr(os, "O_DIRECTORY")
            and hasattr(os, "O_NOFOLLOW")
            and os.open in os.supports_dir_fd
            and os.stat in os.supports_dir_fd
            and os.unlink in os.supports_dir_fd
            and os.link in os.supports_dir_fd
            and os.link in os.supports_follow_symlinks
            and os.chmod in os.supports_fd
            and os.utime in os.supports_fd
        )

    def _execute_group_operations_fallback(
        self,
        group: PhotoGroup,
        source_root: Path,
        destination_root: Path,
    ) -> tuple[FileOperation, ...]:
        resolved_destination_root = destination_root.resolve(strict=True)
        destination_root_identity = self._directory_identity(
            resolved_destination_root
        )
        operations = self._group_destinations_fallback(
            group, resolved_destination_root
        )
        completed: list[FileOperation] = []
        resolved_source_root = source_root.resolve(strict=True)
        source_root_identity = self._directory_identity(resolved_source_root)
        try:
            for operation in operations:
                if self.action_mode == "move":
                    identity = self._move_path_exclusive_fallback(
                        operation.source,
                        operation.destination,
                        resolved_destination_root,
                        expected_destination_root_identity=destination_root_identity,
                    )
                else:
                    identity = self._copy_path_exclusive_fallback(
                        operation.source,
                        operation.destination,
                        resolved_destination_root,
                        expected_destination_root_identity=destination_root_identity,
                    )
                completed.append(
                    FileOperation(
                        operation.source,
                        operation.destination,
                        identity,
                    )
                )
        except Exception as primary_error:
            rollback_errors: list[BaseException] = []
            for operation in reversed(completed):
                try:
                    if self.action_mode == "move":
                        self._move_path_exclusive_fallback(
                            operation.destination,
                            operation.source,
                            resolved_source_root,
                            expected_source_identity=operation.destination_identity,
                            expected_destination_root_identity=source_root_identity,
                        )
                    else:
                        self._remove_owned_path(
                            operation.destination,
                            operation.destination_identity,
                        )
                except Exception as rollback_error:
                    rollback_errors.append(rollback_error)
            message = f"Could not {self.action_mode} the photo group: {primary_error}"
            if rollback_errors:
                details = "; ".join(str(error) for error in rollback_errors)
                message += f". Rollback also failed: {details}"
            raise PhotoSessionError(
                message,
                primary_error=primary_error,
                rollback_errors=tuple(rollback_errors),
                completed_operations=tuple(completed),
            ) from primary_error
        return tuple(completed)

    def _group_destinations_fallback(
        self, group: PhotoGroup, destination_dir: Path
    ) -> tuple[FileOperation, ...]:
        collision_number = 0
        while True:
            operations = tuple(
                FileOperation(
                    member,
                    destination_dir
                    / (
                        member.name
                        if collision_number == 0
                        else f"{member.stem} ({collision_number}){member.suffix}"
                    ),
                )
                for member in group.members
            )
            if not any(self._path_occupied(item.destination) for item in operations):
                return operations
            collision_number += 1

    def _execute_operations(
        self,
        operations: tuple[FileOperation, ...],
        source_fd: int,
        destination_fd: int,
        resolved_source_root: Path,
        resolved_destination_root: Path,
    ) -> tuple[FileOperation, ...]:
        completed: list[FileOperation] = []
        try:
            for operation in operations:
                if self.action_mode == "move":
                    identity = self._move_at_exclusive(
                        operation.source.name,
                        source_fd,
                        operation.destination,
                        destination_fd,
                        resolved_destination_root,
                    )
                else:
                    identity = self._copy_at_exclusive(
                        operation.source.name,
                        source_fd,
                        operation.destination,
                        destination_fd,
                        resolved_destination_root,
                    )
                completed.append(
                    FileOperation(
                        operation.source,
                        operation.destination,
                        identity,
                    )
                )
        except Exception as primary_error:
            rollback_errors: list[BaseException] = []
            for operation in reversed(completed):
                try:
                    if self.action_mode == "move":
                        self._move_at_exclusive(
                            operation.destination.name,
                            destination_fd,
                            operation.source,
                            source_fd,
                            resolved_source_root,
                            operation.destination_identity,
                        )
                    else:
                        self._remove_owned_at(
                            operation.destination.name,
                            destination_fd,
                            operation.destination_identity,
                        )
                except Exception as rollback_error:
                    rollback_errors.append(rollback_error)

            message = f"Could not {self.action_mode} the photo group: {primary_error}"
            if rollback_errors:
                details = "; ".join(str(error) for error in rollback_errors)
                message += f". Rollback also failed: {details}"
            raise PhotoSessionError(
                message,
                primary_error=primary_error,
                rollback_errors=tuple(rollback_errors),
                completed_operations=tuple(completed),
            ) from primary_error
        return tuple(completed)

    @staticmethod
    @contextmanager
    def _open_directory_fd(path: Path):
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        directory_fd = os.open(path, flags)
        try:
            yield directory_fd
        finally:
            os.close(directory_fd)

    @staticmethod
    def _entry_occupied(directory_fd: int, name: str) -> bool:
        try:
            os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        except FileNotFoundError:
            return False
        return True

    def _copy_at_exclusive(
        self,
        source_name: str,
        source_root_fd: int,
        destination: Path,
        destination_root_fd: int,
        destination_root: Path,
    ) -> tuple[int, int]:
        self._validate_basename(source_name)
        self._validate_basename(destination.name)
        source_flags = os.O_RDONLY | os.O_NOFOLLOW
        source_fd = os.open(source_name, source_flags, dir_fd=source_root_fd)
        try:
            return self._copy_open_source_exclusive(
                source_fd,
                destination,
                destination_root_fd,
                destination_root,
            )
        finally:
            os.close(source_fd)

    def _copy_open_source_exclusive(
        self,
        source_fd: int,
        destination: Path,
        destination_root_fd: int,
        destination_root: Path,
    ) -> tuple[int, int]:
        self._validate_destination(destination, destination_root)
        temporary_fd, temporary_name = self._open_temporary_at(
            destination_root_fd
        )
        temporary_identity = self._fd_identity(temporary_fd)
        published_identity: tuple[int, int] | None = None
        temporary_removed = False
        try:
            self._copy_fd_data_and_metadata(source_fd, temporary_fd)
            os.close(temporary_fd)
            temporary_fd = -1
            self._validate_destination(destination, destination_root)
            self._publish_hard_link_at(
                temporary_name,
                destination.name,
                destination_root_fd,
            )
            published_identity = temporary_identity
            self._require_owned_entry(
                destination_root_fd,
                destination.name,
                published_identity,
            )
            self._remove_owned_at(
                temporary_name,
                destination_root_fd,
                temporary_identity,
            )
            temporary_removed = True
            self._require_owned_entry(
                destination_root_fd,
                destination.name,
                published_identity,
            )
            return published_identity
        except Exception as primary_error:
            cleanup_errors: list[BaseException] = []
            if published_identity is not None:
                try:
                    self._remove_owned_at(
                        destination.name,
                        destination_root_fd,
                        published_identity,
                    )
                except Exception as cleanup_error:
                    cleanup_errors.append(cleanup_error)
            if temporary_fd >= 0:
                try:
                    os.close(temporary_fd)
                except OSError as cleanup_error:
                    cleanup_errors.append(cleanup_error)
            if not temporary_removed:
                try:
                    self._remove_owned_at(
                        temporary_name,
                        destination_root_fd,
                        temporary_identity,
                    )
                except Exception as cleanup_error:
                    cleanup_errors.append(cleanup_error)
            if cleanup_errors:
                details = "; ".join(str(error) for error in cleanup_errors)
                raise OSError(
                    f"{primary_error}; staged destination cleanup failed: {details}"
                ) from primary_error
            raise

    @staticmethod
    def _open_temporary_at(directory_fd: int) -> tuple[int, str]:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
        for _attempt in range(100):
            name = f".keep-or-nah-{secrets.token_hex(12)}.tmp"
            try:
                return os.open(name, flags, 0o600, dir_fd=directory_fd), name
            except FileExistsError:
                continue
        raise FileExistsError("Could not allocate a unique staging file")

    @staticmethod
    def _publish_hard_link_at(
        source_name: str,
        destination_name: str,
        directory_fd: int,
    ) -> None:
        PhotoSession._validate_basename(source_name)
        PhotoSession._validate_basename(destination_name)
        os.link(
            source_name,
            destination_name,
            src_dir_fd=directory_fd,
            dst_dir_fd=directory_fd,
            follow_symlinks=False,
        )

    def _move_at_exclusive(
        self,
        source_name: str,
        source_root_fd: int,
        destination: Path,
        destination_root_fd: int,
        destination_root: Path,
        expected_source_identity: tuple[int, int] | None = None,
    ) -> tuple[int, int]:
        self._validate_basename(source_name)
        source_fd = os.open(
            source_name,
            os.O_RDONLY | os.O_NOFOLLOW,
            dir_fd=source_root_fd,
        )
        source_identity = self._fd_identity(source_fd)
        published_identity: tuple[int, int] | None = None
        try:
            if (
                expected_source_identity is not None
                and source_identity != expected_source_identity
            ):
                raise OSError(
                    f"Source path identity changed unexpectedly: {source_name}"
                )
            published_identity = self._copy_open_source_exclusive(
                source_fd,
                destination,
                destination_root_fd,
                destination_root,
            )
            if self._entry_identity(source_root_fd, source_name) != source_identity:
                raise OSError(f"Source path identity changed before unlink: {source_name}")
            self._unlink_at(source_name, source_root_fd)
        except Exception as primary_error:
            if published_identity is not None:
                try:
                    self._remove_owned_at(
                        destination.name,
                        destination_root_fd,
                        published_identity,
                    )
                except Exception as cleanup_error:
                    raise OSError(
                        f"{primary_error}; copied destination cleanup failed: {cleanup_error}"
                    ) from primary_error
            raise
        finally:
            os.close(source_fd)
        return published_identity

    @staticmethod
    def _entry_identity(directory_fd: int, name: str) -> tuple[int, int]:
        entry_stat = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        return entry_stat.st_dev, entry_stat.st_ino

    @classmethod
    def _require_owned_entry(
        cls,
        directory_fd: int,
        name: str,
        expected_identity: tuple[int, int],
    ) -> None:
        if cls._entry_identity(directory_fd, name) != expected_identity:
            raise OSError(f"Refusing to remove a replaced path: {name}")

    def _remove_owned_at(
        self,
        name: str,
        directory_fd: int,
        expected_identity: tuple[int, int],
    ) -> None:
        self._require_owned_entry(directory_fd, name, expected_identity)
        self._unlink_at(name, directory_fd)

    @staticmethod
    def _unlink_at(name: str, directory_fd: int) -> None:
        PhotoSession._validate_basename(name)
        os.unlink(name, dir_fd=directory_fd)

    @staticmethod
    def _validate_basename(name: str) -> None:
        if not name or Path(name).name != name or name in {".", ".."}:
            raise OSError(f"Unsafe direct-child filename: {name!r}")

    @staticmethod
    def _copy_fd_data_and_metadata(
        source_fd: int,
        destination_fd: int,
        owned_destination_path: Path | None = None,
    ) -> None:
        source_stat = os.fstat(source_fd)
        while True:
            chunk = os.read(source_fd, 1024 * 1024)
            if not chunk:
                break
            view = memoryview(chunk)
            while view:
                written = os.write(destination_fd, view)
                if written == 0:
                    raise OSError("Destination write made no progress")
                view = view[written:]
        mode = stat.S_IMODE(source_stat.st_mode)
        timestamps = (source_stat.st_atime_ns, source_stat.st_mtime_ns)
        if hasattr(os, "fchmod") and os.chmod in os.supports_fd:
            os.fchmod(destination_fd, mode)
        elif owned_destination_path is not None:
            os.chmod(owned_destination_path, mode)
        else:
            raise OSError("This platform cannot apply destination permissions safely")
        if os.utime in os.supports_fd:
            os.utime(destination_fd, ns=timestamps)
        elif owned_destination_path is not None:
            os.utime(owned_destination_path, ns=timestamps)
        else:
            raise OSError("This platform cannot apply destination timestamps safely")

    def _copy_path_exclusive_fallback(
        self,
        source: Path,
        destination: Path,
        destination_root: Path,
        *,
        expected_source_identity: tuple[int, int] | None = None,
        expected_destination_root_identity: tuple[int, int] | None = None,
    ) -> tuple[int, int]:
        if expected_destination_root_identity is None:
            expected_destination_root_identity = self._directory_identity(
                destination_root
            )
        self._require_directory_identity(
            destination_root, expected_destination_root_identity
        )
        self._validate_destination(destination, destination_root)
        temporary_fd, temporary_name = tempfile.mkstemp(
            prefix=".keep-or-nah-", dir=destination_root
        )
        temporary_path = Path(temporary_name)
        temporary_identity = self._fd_identity(temporary_fd)
        published_identity: tuple[int, int] | None = None
        temporary_consumed = False
        source_fd: int | None = None
        try:
            source_flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            source_fd = os.open(source, source_flags)
            if (
                expected_source_identity is not None
                and self._fd_identity(source_fd) != expected_source_identity
            ):
                raise OSError(f"Source path identity changed unexpectedly: {source}")
            self._copy_fd_data_and_metadata(
                source_fd, temporary_fd, temporary_path
            )
            os.close(temporary_fd)
            temporary_fd = -1
            self._require_owned_path(temporary_path, temporary_identity)
            self._require_directory_identity(
                destination_root, expected_destination_root_identity
            )
            self._validate_destination(destination, destination_root)
            temporary_consumed = self._publish_staged_fallback(
                temporary_path,
                destination,
            )
            published_identity = temporary_identity
            self._require_owned_path(destination, published_identity)
            self._require_directory_identity(
                destination_root, expected_destination_root_identity
            )
            self._validate_destination_parent(destination, destination_root)
        except Exception as primary_error:
            cleanup_errors: list[BaseException] = []
            if published_identity is not None:
                try:
                    self._remove_owned_path(destination, published_identity)
                except Exception as cleanup_error:
                    cleanup_errors.append(cleanup_error)
            if temporary_fd >= 0:
                try:
                    os.close(temporary_fd)
                except OSError as cleanup_error:
                    cleanup_errors.append(cleanup_error)
            if source_fd is not None:
                try:
                    os.close(source_fd)
                except OSError as cleanup_error:
                    cleanup_errors.append(cleanup_error)
            if not temporary_consumed:
                try:
                    self._remove_owned_path(temporary_path, temporary_identity)
                except Exception as cleanup_error:
                    cleanup_errors.append(cleanup_error)
            if cleanup_errors:
                details = "; ".join(str(error) for error in cleanup_errors)
                raise OSError(
                    f"{primary_error}; fallback cleanup failed: {details}"
                ) from primary_error
            raise
        else:
            if source_fd is not None:
                os.close(source_fd)
            if not temporary_consumed:
                self._remove_owned_path(temporary_path, temporary_identity)
            return published_identity

    def _publish_staged_fallback(
        self,
        source: Path,
        destination: Path,
    ) -> bool:
        try:
            self._publish_hard_link(source, destination)
            return False
        except OSError as error:
            unsupported_errors = {
                errno.ENOSYS,
                errno.ENOTSUP,
                errno.EOPNOTSUPP,
                errno.EPERM,
                errno.EXDEV,
                errno.EINVAL,
            }
            if (
                not self._is_windows_fallback()
                or error.errno not in unsupported_errors
            ):
                raise
        if self._path_occupied(destination):
            raise FileExistsError(f"Destination became occupied: {destination}")
        os.rename(source, destination)
        return True

    @staticmethod
    def _is_windows_fallback() -> bool:
        return os.name == "nt"

    def _move_path_exclusive_fallback(
        self,
        source: Path,
        destination: Path,
        destination_root: Path,
        *,
        expected_source_identity: tuple[int, int] | None = None,
        expected_destination_root_identity: tuple[int, int] | None = None,
    ) -> tuple[int, int]:
        if expected_source_identity is None:
            expected_source_identity = self._path_identity(source)
        self._require_owned_path(source, expected_source_identity)
        published_identity = self._copy_path_exclusive_fallback(
            source,
            destination,
            destination_root,
            expected_source_identity=expected_source_identity,
            expected_destination_root_identity=expected_destination_root_identity,
        )
        try:
            self._remove_owned_path(source, expected_source_identity)
        except Exception as primary_error:
            try:
                self._remove_owned_path(destination, published_identity)
            except Exception as cleanup_error:
                raise OSError(
                    f"{primary_error}; published destination cleanup failed: {cleanup_error}"
                ) from primary_error
            raise
        return published_identity

    @staticmethod
    def _publish_hard_link(source: Path, destination: Path) -> None:
        if os.link in os.supports_follow_symlinks:
            os.link(source, destination, follow_symlinks=False)
        else:
            os.link(source, destination)

    @staticmethod
    def _fd_identity(file_descriptor: int) -> tuple[int, int]:
        file_stat = os.fstat(file_descriptor)
        return file_stat.st_dev, file_stat.st_ino

    @staticmethod
    def _path_identity(path: Path) -> tuple[int, int]:
        path_stat = path.lstat()
        if path.is_symlink() or not stat.S_ISREG(path_stat.st_mode):
            raise OSError(f"Owned path is no longer a regular file: {path}")
        return path_stat.st_dev, path_stat.st_ino

    @staticmethod
    def _directory_identity(path: Path) -> tuple[int, int]:
        path_stat = path.lstat()
        if path.is_symlink() or not stat.S_ISDIR(path_stat.st_mode):
            raise OSError(f"Destination root is no longer a directory: {path}")
        return path_stat.st_dev, path_stat.st_ino

    @classmethod
    def _require_directory_identity(
        cls, path: Path, expected_identity: tuple[int, int]
    ) -> None:
        if cls._directory_identity(path) != expected_identity:
            raise OSError(f"Destination root identity changed: {path}")

    @classmethod
    def _require_owned_path(
        cls, path: Path, expected_identity: tuple[int, int]
    ) -> None:
        if cls._path_identity(path) != expected_identity:
            raise OSError(f"Refusing to remove a replaced path: {path}")

    @classmethod
    def _remove_owned_path(
        cls, path: Path, expected_identity: tuple[int, int]
    ) -> None:
        cls._require_owned_path(path, expected_identity)
        path.unlink()

    @staticmethod
    def _path_occupied(path: Path) -> bool:
        """Return true for every directory entry, including dangling symlinks."""
        try:
            path.lstat()
        except FileNotFoundError:
            return False
        return True

    @classmethod
    def _validate_destination(cls, path: Path, destination_root: Path) -> None:
        cls._validate_destination_parent(path, destination_root)
        if cls._path_occupied(path):
            raise FileExistsError(f"Destination became occupied: {path}")

    @staticmethod
    def _validate_destination_parent(path: Path, destination_root: Path) -> None:
        try:
            resolved_parent = path.parent.resolve(strict=True)
        except OSError as error:
            raise OSError(
                f"Destination parent cannot be resolved safely: {path.parent}"
            ) from error
        if resolved_parent != destination_root:
            raise OSError(
                f"Destination parent escapes the selected folder: {path.parent}"
            )

    def undo(self) -> UndoResult:
        if not self.history:
            raise PhotoSessionError("There is nothing to undo.")

        record = self.history[-1]
        destination_root = self._recorded_destination_root(record)
        if record.action_mode == "move":
            self._undo_move_record(record, destination_root)
        else:
            self._undo_copy_record(record, destination_root)

        self.history.pop()
        self._partial_copy_undo.difference_update(record.files)
        restore_index = min(max(record.index, 0), len(self.queue))
        self.queue.insert(restore_index, record.group)
        self.active_index = restore_index
        if record.decision == "keep":
            self.keep_count -= 1
        else:
            self.nah_count -= 1

        return UndoResult(
            record.decision,
            record.action_mode,
            record.group,
            record.files,
            self.remaining_count,
        )

    @classmethod
    def _recorded_destination_root(cls, record: ActionRecord) -> Path:
        if not record.files:
            raise PhotoSessionError(
                "The recorded action has no destination files, so it cannot be undone."
            )
        recorded_parent = record.files[0].destination.parent
        for operation in record.files:
            if operation.destination_identity is None:
                raise PhotoSessionError(
                    "A recorded action is missing its destination identity, so it cannot be undone."
                )
            if operation.destination.parent != recorded_parent:
                raise PhotoSessionError(
                    "All files in an action must share the same recorded destination folder."
                )
            try:
                cls._validate_basename(operation.destination.name)
            except OSError as error:
                raise PhotoSessionError(
                    f"A recorded undo destination is unsafe: {error}",
                    primary_error=error,
                ) from error
        try:
            destination_root = recorded_parent.resolve(strict=True)
            cls._directory_identity(destination_root)
            for operation in record.files:
                cls._validate_destination_parent(
                    operation.destination, destination_root
                )
                recorded_destination = (
                    destination_root / operation.destination.name
                )
                if (
                    cls._path_occupied(recorded_destination)
                    and cls._path_identity(recorded_destination)
                    != operation.destination_identity
                ):
                    raise PhotoSessionError(
                        "A recorded destination identity no longer matches the action-owned file."
                    )
        except PhotoSessionError:
            raise
        except OSError as error:
            raise PhotoSessionError(
                f"Could not validate the recorded undo destination folder: {error}",
                primary_error=error,
            ) from error
        return destination_root

    def _undo_move_record(
        self, record: ActionRecord, destination_root: Path
    ) -> None:
        if not self._supports_rooted_dir_fd():
            self._undo_move_record_fallback(record, destination_root)
            return
        if self.source_dir is None:
            raise PhotoSessionError("The source folder is unavailable, so undo cannot restore files.")
        try:
            source_root = self.source_dir.resolve(strict=True)
            with self._open_directory_fd(self.source_dir) as source_fd, self._open_directory_fd(
                destination_root
            ) as destination_fd:
                pending: list[FileOperation] = []
                for operation in reversed(record.files):
                    source_occupied = self._entry_occupied(
                        source_fd, operation.source.name
                    )
                    destination_occupied = self._entry_occupied(
                        destination_fd, operation.destination.name
                    )
                    if destination_occupied:
                        self._require_owned_entry(
                            destination_fd,
                            operation.destination.name,
                            operation.destination_identity,
                        )
                    if destination_occupied and not source_occupied:
                        pending.append(operation)
                    elif source_occupied and not destination_occupied:
                        continue
                    elif source_occupied:
                        raise PhotoSessionError(
                            "An original group file path is already occupied, so undo cannot restore it."
                        )
                    else:
                        raise PhotoSessionError(
                            "A moved group file is missing, so the last action cannot be undone."
                        )

                completed: list[tuple[FileOperation, tuple[int, int]]] = []
                try:
                    for operation in pending:
                        restored_identity = self._move_at_exclusive(
                            operation.destination.name,
                            destination_fd,
                            operation.source,
                            source_fd,
                            source_root,
                            operation.destination_identity,
                        )
                        completed.append((operation, restored_identity))
                except Exception as primary_error:
                    rollback_errors: list[BaseException] = []
                    identity_updates: dict[FileOperation, tuple[int, int]] = {}
                    for operation, restored_identity in reversed(completed):
                        try:
                            identity_updates[operation] = self._move_at_exclusive(
                                operation.source.name,
                                source_fd,
                                destination_root / operation.destination.name,
                                destination_fd,
                                destination_root,
                                restored_identity,
                            )
                        except Exception as rollback_error:
                            rollback_errors.append(rollback_error)
                    self._refresh_record_identities(record, identity_updates)
                    self._raise_undo_failure(
                        "moved",
                        primary_error,
                        tuple(rollback_errors),
                        [operation for operation, _identity in completed],
                    )
        except PhotoSessionError:
            raise
        except Exception as error:
            raise PhotoSessionError(
                f"Could not open an undo folder safely: {error}",
                primary_error=error,
            ) from error

    def _undo_move_record_fallback(
        self, record: ActionRecord, destination_root: Path
    ) -> None:
        if self.source_dir is None:
            raise PhotoSessionError("The source folder is unavailable, so undo cannot restore files.")
        source_root = self.source_dir.resolve(strict=True)
        source_root_identity = self._directory_identity(source_root)
        destination_root_identity = self._directory_identity(destination_root)
        pending: list[tuple[FileOperation, tuple[int, int]]] = []
        for operation in reversed(record.files):
            recorded_destination = destination_root / operation.destination.name
            source_occupied = self._path_occupied(operation.source)
            destination_occupied = self._path_occupied(recorded_destination)
            if destination_occupied:
                self._require_owned_path(
                    recorded_destination,
                    operation.destination_identity,
                )
            if destination_occupied and not source_occupied:
                pending.append(
                    (operation, self._path_identity(recorded_destination))
                )
            elif source_occupied and not destination_occupied:
                continue
            elif source_occupied:
                raise PhotoSessionError(
                    "An original group file path is already occupied, so undo cannot restore it."
                )
            else:
                raise PhotoSessionError(
                    "A moved group file is missing, so the last action cannot be undone."
                )

        completed: list[tuple[FileOperation, tuple[int, int]]] = []
        try:
            for operation, destination_identity in pending:
                restored_identity = self._move_path_exclusive_fallback(
                    destination_root / operation.destination.name,
                    operation.source,
                    source_root,
                    expected_source_identity=destination_identity,
                    expected_destination_root_identity=source_root_identity,
                )
                completed.append((operation, restored_identity))
        except Exception as primary_error:
            rollback_errors: list[BaseException] = []
            identity_updates: dict[FileOperation, tuple[int, int]] = {}
            for operation, restored_identity in reversed(completed):
                try:
                    identity_updates[operation] = self._move_path_exclusive_fallback(
                        operation.source,
                        destination_root / operation.destination.name,
                        destination_root,
                        expected_source_identity=restored_identity,
                        expected_destination_root_identity=destination_root_identity,
                    )
                except Exception as rollback_error:
                    rollback_errors.append(rollback_error)
            self._refresh_record_identities(record, identity_updates)
            self._raise_undo_failure(
                "moved",
                primary_error,
                tuple(rollback_errors),
                [operation for operation, _identity in completed],
            )

    def _undo_copy_record(
        self, record: ActionRecord, destination_root: Path
    ) -> None:
        if not self._supports_rooted_dir_fd():
            self._undo_copy_record_fallback(record, destination_root)
            return
        if self.source_dir is None:
            raise PhotoSessionError("The source folder is unavailable, so undo cannot restore files.")
        try:
            with self._open_directory_fd(self.source_dir) as source_fd, self._open_directory_fd(
                destination_root
            ) as destination_fd:
                pending: list[FileOperation] = []
                for operation in reversed(record.files):
                    destination_occupied = self._entry_occupied(
                        destination_fd, operation.destination.name
                    )
                    if destination_occupied:
                        self._require_owned_entry(
                            destination_fd,
                            operation.destination.name,
                            operation.destination_identity,
                        )
                        pending.append(operation)
                    elif operation not in self._partial_copy_undo:
                        raise PhotoSessionError(
                            "A copied group file is missing, so the last action cannot be undone."
                        )

                completed: list[FileOperation] = []
                try:
                    for operation in pending:
                        self._remove_owned_at(
                            operation.destination.name,
                            destination_fd,
                            operation.destination_identity,
                        )
                        completed.append(operation)
                        self._partial_copy_undo.add(operation)
                except Exception as primary_error:
                    rollback_errors: list[BaseException] = []
                    identity_updates: dict[FileOperation, tuple[int, int]] = {}
                    for operation in reversed(completed):
                        try:
                            identity_updates[operation] = self._copy_at_exclusive(
                                operation.source.name,
                                source_fd,
                                destination_root / operation.destination.name,
                                destination_fd,
                                destination_root,
                            )
                            self._partial_copy_undo.discard(operation)
                        except Exception as rollback_error:
                            rollback_errors.append(rollback_error)
                    self._refresh_record_identities(record, identity_updates)
                    self._raise_undo_failure(
                        "copied",
                        primary_error,
                        tuple(rollback_errors),
                        completed,
                    )
        except PhotoSessionError:
            raise
        except Exception as error:
            raise PhotoSessionError(
                f"Could not open an undo folder safely: {error}",
                primary_error=error,
            ) from error

    def _undo_copy_record_fallback(
        self, record: ActionRecord, destination_root: Path
    ) -> None:
        if self.source_dir is None:
            raise PhotoSessionError("The source folder is unavailable, so undo cannot restore files.")
        destination_root_identity = self._directory_identity(destination_root)
        pending: list[tuple[FileOperation, tuple[int, int]]] = []
        for operation in reversed(record.files):
            recorded_destination = destination_root / operation.destination.name
            if self._path_occupied(recorded_destination):
                self._require_owned_path(
                    recorded_destination,
                    operation.destination_identity,
                )
                pending.append(
                    (operation, self._path_identity(recorded_destination))
                )
            elif operation not in self._partial_copy_undo:
                raise PhotoSessionError(
                    "A copied group file is missing, so the last action cannot be undone."
                )

        completed: list[FileOperation] = []
        try:
            for operation, destination_identity in pending:
                self._remove_owned_path(
                    destination_root / operation.destination.name,
                    destination_identity,
                )
                completed.append(operation)
                self._partial_copy_undo.add(operation)
        except Exception as primary_error:
            rollback_errors: list[BaseException] = []
            identity_updates: dict[FileOperation, tuple[int, int]] = {}
            for operation in reversed(completed):
                try:
                    identity_updates[operation] = self._copy_path_exclusive_fallback(
                        operation.source,
                        destination_root / operation.destination.name,
                        destination_root,
                        expected_destination_root_identity=destination_root_identity,
                    )
                    self._partial_copy_undo.discard(operation)
                except Exception as rollback_error:
                    rollback_errors.append(rollback_error)
            self._refresh_record_identities(record, identity_updates)
            self._raise_undo_failure(
                "copied", primary_error, tuple(rollback_errors), completed
            )

    def _refresh_record_identities(
        self,
        record: ActionRecord,
        updates: dict[FileOperation, tuple[int, int]],
    ) -> None:
        if not updates:
            return
        refreshed_files = tuple(
            FileOperation(
                operation.source,
                operation.destination,
                updates.get(operation, operation.destination_identity),
            )
            for operation in record.files
        )
        self.history[-1] = ActionRecord(
            record.decision,
            record.action_mode,
            record.group,
            refreshed_files,
            record.index,
        )

    def _destination_dir_for(self, decision: Decision) -> Path:
        destination_dir = self.keep_dir if decision == "keep" else self.nah_dir
        if destination_dir is None:
            raise OSError("The action destination folder is unavailable")
        return destination_dir

    @staticmethod
    def _raise_undo_failure(
        operation_label: str,
        primary_error: BaseException,
        rollback_errors: tuple[BaseException, ...],
        completed: list[FileOperation],
    ) -> None:
        message = f"Could not undo the {operation_label} photo group: {primary_error}"
        if rollback_errors:
            details = "; ".join(str(error) for error in rollback_errors)
            message += f". Undo rollback also failed: {details}"
        raise PhotoSessionError(
            message,
            primary_error=primary_error,
            rollback_errors=rollback_errors,
            completed_operations=tuple(completed),
        ) from primary_error

    def _unique_destination(self, destination_dir: Path, filename: str) -> Path:
        """Retained for callers that still preflight a single destination."""
        candidate = destination_dir / filename
        if not self._path_occupied(candidate):
            return candidate

        stem = Path(filename).stem
        suffix = Path(filename).suffix
        counter = 1
        while True:
            candidate = destination_dir / f"{stem} ({counter}){suffix}"
            if not self._path_occupied(candidate):
                return candidate
            counter += 1
