from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
from typing import Literal


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
    pass


@dataclass(frozen=True)
class DecisionResult:
    decision: Decision
    action_mode: ActionMode
    source: Path
    destination: Path
    remaining_count: int


@dataclass(frozen=True)
class UndoResult:
    decision: Decision
    action_mode: ActionMode
    source: Path
    destination: Path
    remaining_count: int


@dataclass(frozen=True)
class ActionRecord:
    decision: Decision
    action_mode: ActionMode
    source: Path
    destination: Path
    index: int


class PhotoSession:
    def __init__(self) -> None:
        self.source_dir: Path | None = None
        self.keep_dir: Path | None = None
        self.nah_dir: Path | None = None
        self.action_mode: ActionMode = "move"
        self.queue: list[Path] = []
        self.active_index = 0
        self.history: list[ActionRecord] = []
        self.total_loaded = 0
        self.keep_count = 0
        self.nah_count = 0

    @property
    def active_photo(self) -> Path | None:
        if not self.queue:
            return None
        return self.queue[self.active_index]

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
        if self.source_dir is None:
            raise PhotoSessionError("Choose a source folder before loading photos.")
        if not self.source_dir.is_dir():
            raise PhotoSessionError(f"Source folder does not exist: {self.source_dir}")

        files = [
            path
            for path in sorted(self.source_dir.iterdir(), key=lambda item: item.name.lower())
            if path.is_file() and path.suffix.lower() in SUPPORTED_IMAGE_EXTENSIONS
        ]

        self.queue = files
        self.active_index = 0
        self.history = []
        self.total_loaded = len(files)
        self.keep_count = 0
        self.nah_count = 0
        return self.total_loaded

    def set_active_index(self, index: int) -> Path | None:
        if not self.queue:
            self.active_index = 0
            return None

        self.active_index = min(max(index, 0), len(self.queue) - 1)
        return self.active_photo

    def move_active(self, offset: int) -> Path | None:
        return self.set_active_index(self.active_index + offset)

    def decide(self, decision: Decision) -> DecisionResult:
        source = self.active_photo
        if source is None:
            raise PhotoSessionError("There are no loaded photos left to sort.")
        current_index = self.active_index

        destination_dir = self.keep_dir if decision == "keep" else self.nah_dir
        if destination_dir is None:
            label = "Keep" if decision == "keep" else "Nah"
            raise PhotoSessionError(f"Choose a {label} folder before sorting.")

        destination_dir = destination_dir.expanduser()
        destination_dir.mkdir(parents=True, exist_ok=True)

        if self.action_mode == "move":
            try:
                source_parent = source.resolve().parent
                destination_parent = destination_dir.resolve()
            except FileNotFoundError:
                source_parent = source.parent
                destination_parent = destination_dir

            if source_parent == destination_parent:
                raise PhotoSessionError(
                    "Move mode requires destination folders different from the current photo folder."
                )

        destination = self._unique_destination(destination_dir, source.name)
        if self.action_mode == "move":
            shutil.move(str(source), str(destination))
        else:
            shutil.copy2(source, destination)

        self.queue.pop(current_index)
        if self.queue:
            self.active_index = min(current_index, len(self.queue) - 1)
        else:
            self.active_index = 0
        self.history.append(
            ActionRecord(
                decision=decision,
                action_mode=self.action_mode,
                source=source,
                destination=destination,
                index=current_index,
            )
        )
        if decision == "keep":
            self.keep_count += 1
        else:
            self.nah_count += 1

        return DecisionResult(
            decision=decision,
            action_mode=self.action_mode,
            source=source,
            destination=destination,
            remaining_count=self.remaining_count,
        )

    def undo(self) -> UndoResult:
        if not self.history:
            raise PhotoSessionError("There is nothing to undo.")

        record = self.history.pop()
        if record.action_mode == "move":
            if not record.destination.exists():
                raise PhotoSessionError("The moved file is missing, so the last action cannot be undone.")
            if record.source.exists():
                raise PhotoSessionError("The original file path is already occupied, so undo cannot restore it.")
            record.source.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(record.destination), str(record.source))
        else:
            if not record.destination.exists():
                raise PhotoSessionError("The copied file is missing, so the last action cannot be undone.")
            record.destination.unlink()

        restore_index = min(max(record.index, 0), len(self.queue))
        self.queue.insert(restore_index, record.source)
        self.active_index = restore_index
        if record.decision == "keep":
            self.keep_count -= 1
        else:
            self.nah_count -= 1

        return UndoResult(
            decision=record.decision,
            action_mode=record.action_mode,
            source=record.source,
            destination=record.destination,
            remaining_count=self.remaining_count,
        )

    def _unique_destination(self, destination_dir: Path, filename: str) -> Path:
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
