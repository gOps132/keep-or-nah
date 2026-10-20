from __future__ import annotations

import contextlib
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from file_coordinator import FileCoordinator
from photo_groups import PhotoGroup
from photo_triage import (
    ActionMode,
    ActionRecord,
    Decision,
    FileOperation,
    PhotoSessionError,
)


def format_bytes(bytes_count: int) -> str:
    """Format a byte count into a readable human string (B, KB, MB, GB)."""
    if bytes_count < 1024:
        return f"{bytes_count} B"
    units = ["KB", "MB", "GB", "TB"]
    val = float(bytes_count)
    for unit in units:
        val /= 1024.0
        if val < 1024.0 or unit == units[-1]:
            return f"{val:.1f} {unit}"
    return f"{val:.1f} TB"


@dataclass(frozen=True)
class StagedDecision:
    group: PhotoGroup
    decision: Decision
    action_mode: ActionMode
    destination_dir: Path | None
    files: tuple[FileOperation, ...]
    index: int
    bytes_size: int

    @property
    def stem(self) -> str:
        return self.group.stem

    @property
    def source(self) -> Path:
        return self.group.representative


@dataclass(frozen=True)
class StagedBatchSummary:
    total_count: int
    keep_count: int
    nah_count: int
    flag_count: int
    total_bytes: int
    reclaimed_bytes: int

    @property
    def reclaimed_bytes_human(self) -> str:
        return format_bytes(self.reclaimed_bytes)

    @property
    def total_bytes_human(self) -> str:
        return format_bytes(self.total_bytes)


class StagedTriageManager:
    """Manages virtual staged triage decisions and handles batch execution and rollback."""

    def __init__(self, staged: list[StagedDecision] | None = None) -> None:
        self.staged: list[StagedDecision] = list(staged) if staged is not None else []

    @property
    def is_empty(self) -> bool:
        return not bool(self.staged)

    def stage(
        self,
        group: PhotoGroup,
        decision: Decision,
        action_mode: ActionMode,
        destination_dir: Path | None,
        index: int,
    ) -> StagedDecision:
        total_bytes = 0
        for member in group.members:
            with contextlib.suppress(OSError):
                total_bytes += member.stat().st_size

        if destination_dir is not None:
            files = tuple(
                FileOperation(member, destination_dir / member.name) for member in group.members
            )
        else:
            files = ()

        staged_item = StagedDecision(
            group=group,
            decision=decision,
            action_mode=action_mode,
            destination_dir=destination_dir,
            files=files,
            index=index,
            bytes_size=total_bytes,
        )
        self.staged.append(staged_item)
        return staged_item

    def unstage(self, stem: str) -> StagedDecision | None:
        for idx, item in enumerate(self.staged):
            if item.stem == stem:
                return self.staged.pop(idx)
        return None

    def undo(self) -> StagedDecision | None:
        if not self.staged:
            return None
        return self.staged.pop()

    def clear(self) -> list[StagedDecision]:
        items = list(self.staged)
        self.staged.clear()
        return items

    def revise(
        self,
        stem: str,
        new_decision: Decision,
        new_destination_dir: Path | None,
    ) -> StagedDecision:
        idx = next((i for i, item in enumerate(self.staged) if item.stem == stem), None)
        if idx is None:
            raise KeyError(f"No staged decision for stem: {stem}")

        old_item = self.staged[idx]
        if new_destination_dir is not None:
            files = tuple(
                FileOperation(member, new_destination_dir / member.name)
                for member in old_item.group.members
            )
        else:
            files = ()

        new_item = StagedDecision(
            group=old_item.group,
            decision=new_decision,
            action_mode=old_item.action_mode,
            destination_dir=new_destination_dir,
            files=files,
            index=old_item.index,
            bytes_size=old_item.bytes_size,
        )
        self.staged[idx] = new_item
        return new_item

    def summary(self) -> StagedBatchSummary:
        keep = 0
        nah = 0
        flag = 0
        total_bytes = 0
        reclaimed_bytes = 0

        for item in self.staged:
            total_bytes += item.bytes_size
            if item.decision == "keep":
                keep += 1
            elif item.decision == "nah":
                nah += 1
                reclaimed_bytes += item.bytes_size
            elif item.decision == "flag":
                flag += 1

        return StagedBatchSummary(
            total_count=len(self.staged),
            keep_count=keep,
            nah_count=nah,
            flag_count=flag,
            total_bytes=total_bytes,
            reclaimed_bytes=reclaimed_bytes,
        )

    def execute_batch(
        self,
        coordinator: FileCoordinator,
        on_progress: Callable[[int, int, str], None] | None = None,
        cancel_token: threading.Event | None = None,
    ) -> tuple[ActionRecord, ...]:
        completed_records: list[ActionRecord] = []
        total = len(self.staged)

        for i, item in enumerate(list(self.staged)):
            if cancel_token is not None and cancel_token.is_set():
                self._rollback_batch(coordinator, completed_records)
                raise PhotoSessionError("Batch commit cancelled by user.")

            if item.destination_dir is not None:
                item.destination_dir.mkdir(parents=True, exist_ok=True)
                source_parent = (
                    item.group.members[0].resolve().parent if item.group.members else Path(".")
                )
                try:
                    executed_files = coordinator.execute_group_operations(
                        item.group,
                        source_parent,
                        item.destination_dir,
                        item.action_mode,
                    )
                except Exception as err:
                    self._rollback_batch(coordinator, completed_records)
                    raise PhotoSessionError(
                        f"Batch commit failed at {item.stem}: {err}",
                        primary_error=err,
                    ) from err
            else:
                executed_files = ()

            record = ActionRecord(
                decision=item.decision,
                action_mode=item.action_mode,
                group=item.group,
                files=executed_files,
                index=item.index,
            )
            completed_records.append(record)

            if on_progress is not None:
                on_progress(i + 1, total, item.stem)

            if cancel_token is not None and cancel_token.is_set():
                self._rollback_batch(coordinator, completed_records)
                raise PhotoSessionError("Batch commit cancelled by user.")

        self.staged.clear()
        return tuple(completed_records)

    def _rollback_batch(
        self,
        coordinator: FileCoordinator,
        completed_records: list[ActionRecord],
    ) -> None:
        """Rolls back all completed records in reverse order."""
        for record in reversed(completed_records):
            if not record.files:
                continue
            dest_root = coordinator.recorded_destination_root(record)
            src_root = record.group.members[0].parent if record.group.members else None
            try:
                if record.action_mode == "move":
                    coordinator.undo_move_record(
                        record,
                        dest_root,
                        src_root,
                        lambda r, u: None,
                    )
                else:
                    coordinator.undo_copy_record(
                        record,
                        dest_root,
                        set(),
                        lambda r, u: None,
                    )
            except Exception:
                pass
