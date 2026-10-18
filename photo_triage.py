from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from photo_groups import PhotoGroup

Decision = Literal["keep", "nah"]
ActionMode = Literal["move", "copy"]
EMPTY_EXTENSION_SELECTION_MESSAGE = "Choose at least one file extension."


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


class PhotoTriage:
    """Manages triage decisions, undo stack, and decision history."""

    def __init__(self, history: list[ActionRecord] | None = None) -> None:
        self.history: list[ActionRecord] = list(history) if history is not None else []
        self.partial_copy_undo: set[FileOperation] = set()

    @property
    def can_undo(self) -> bool:
        return bool(self.history)

    @property
    def processed_count(self) -> int:
        return len(self.history)

    @property
    def keep_count(self) -> int:
        return sum(1 for record in self.history if record.decision == "keep")

    @property
    def nah_count(self) -> int:
        return sum(1 for record in self.history if record.decision == "nah")

    def decide_in_memory(
        self,
        group: PhotoGroup,
        decision: Decision,
        action_mode: ActionMode = "move",
        destination_dir: Path | None = None,
        index: int = 0,
        remaining_count: int = 0,
    ) -> DecisionResult:
        """Execute a purely in-memory triage decision without disk operations."""
        dest_dir = destination_dir or Path(f"/{decision}")
        files = tuple(
            FileOperation(member, dest_dir / member.name)
            for member in group.members
        )
        record = ActionRecord(
            decision=decision,
            action_mode=action_mode,
            group=group,
            files=files,
            index=index,
        )
        self.history.append(record)
        return DecisionResult(
            decision=decision,
            action_mode=action_mode,
            group=group,
            files=files,
            remaining_count=remaining_count,
        )

    def undo_in_memory(self, remaining_count: int = 0) -> UndoResult:
        """Pop the last triage decision purely in memory without disk operations."""
        if not self.history:
            raise PhotoSessionError("Nothing to undo.")
        record = self.history.pop()
        return UndoResult(
            decision=record.decision,
            action_mode=record.action_mode,
            group=record.group,
            files=record.files,
            remaining_count=remaining_count,
        )
