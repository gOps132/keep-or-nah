from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import math
import shutil
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
                destination_root = keep_dir if decision == "keep" else nah_dir
                if destination_root is None:
                    continue
                if not PhotoSession._is_direct_child(source, source_dir):
                    continue
                if not PhotoSession._is_direct_child(destination, destination_root):
                    continue
                history.append(
                    ActionRecord(
                        decision,
                        action_mode,
                        source,
                        destination,
                        PhotoSession._snapshot_int(item["index"], 0),
                    )
                )
            except (KeyError, OverflowError, TypeError, ValueError):
                continue
        return history

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

        operations = self._group_destinations(group, destination_dir)
        self._execute_operations(operations)

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
            if not any(item.destination.exists() for item in operations):
                return operations
            collision_number += 1

    def _execute_operations(
        self, operations: tuple[FileOperation, ...]
    ) -> None:
        completed: list[FileOperation] = []
        try:
            for operation in operations:
                if self.action_mode == "move":
                    shutil.move(str(operation.source), str(operation.destination))
                else:
                    shutil.copy2(operation.source, operation.destination)
                completed.append(operation)
        except Exception as primary_error:
            rollback_errors: list[BaseException] = []
            for operation in reversed(completed):
                try:
                    if self.action_mode == "move":
                        shutil.move(
                            str(operation.destination), str(operation.source)
                        )
                    else:
                        operation.destination.unlink()
                except Exception as rollback_error:
                    rollback_errors.append(rollback_error)

            message = (
                f"Could not {self.action_mode} the photo group: {primary_error}"
            )
            if rollback_errors:
                details = "; ".join(str(error) for error in rollback_errors)
                message += f". Rollback also failed: {details}"
            raise PhotoSessionError(
                message,
                primary_error=primary_error,
                rollback_errors=tuple(rollback_errors),
                completed_operations=tuple(completed),
            ) from primary_error

    def undo(self) -> UndoResult:
        if not self.history:
            raise PhotoSessionError("There is nothing to undo.")

        record = self.history[-1]
        if record.action_mode == "move":
            for operation in record.files:
                if not operation.destination.exists():
                    raise PhotoSessionError(
                        "A moved group file is missing, so the last action cannot be undone."
                    )
                if operation.source.exists():
                    raise PhotoSessionError(
                        "An original group file path is already occupied, so undo cannot restore it."
                    )
            try:
                for operation in reversed(record.files):
                    operation.source.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(
                        str(operation.destination), str(operation.source)
                    )
            except OSError as error:
                raise PhotoSessionError(
                    f"Could not undo the moved photo group: {error}",
                    primary_error=error,
                ) from error
        else:
            for operation in record.files:
                if not operation.destination.exists():
                    raise PhotoSessionError(
                        "A copied group file is missing, so the last action cannot be undone."
                    )
            try:
                for operation in reversed(record.files):
                    operation.destination.unlink()
            except OSError as error:
                raise PhotoSessionError(
                    f"Could not undo the copied photo group: {error}",
                    primary_error=error,
                ) from error

        self.history.pop()
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

    def _unique_destination(self, destination_dir: Path, filename: str) -> Path:
        """Retained for callers that still preflight a single destination."""
        candidate = destination_dir / filename
        if not candidate.exists():
            return candidate

        stem = Path(filename).stem
        suffix = Path(filename).suffix
        counter = 1
        while True:
            candidate = destination_dir / f"{stem} ({counter}){suffix}"
            if not candidate.exists():
                return candidate
            counter += 1
