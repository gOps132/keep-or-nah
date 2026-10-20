from __future__ import annotations

import os as os
import threading
from collections.abc import Callable
from pathlib import Path

from PIL import Image as Image

import session_snapshot
from file_coordinator import FileCoordinator
from file_identity import FileIdentity
from keep_or_nah_core import remove_verified_file as remove_verified_file
from keep_or_nah_core import stage_regular_file as stage_regular_file
from photo_groups import PhotoGroup
from photo_metadata import SUPPORTED_IMAGE_EXTENSIONS as SUPPORTED_IMAGE_EXTENSIONS
from photo_metadata import pillow_previewable_extensions as pillow_previewable_extensions
from photo_session_properties import PhotoSessionProperties
from photo_triage import EMPTY_EXTENSION_SELECTION_MESSAGE as EMPTY_EXTENSION_SELECTION_MESSAGE
from photo_triage import (
    ActionMode,
    ActionRecord,
    Decision,
    DecisionResult,
    FileOperation,
    PhotoSessionError,
    PhotoTriage,
    UndoResult,
)
from session_state import SessionState
from staged_triage import (
    StagedDecision,
    StagedTriageManager,
)

# `photo_session` is the public facade of the photo triage core. The re-exports
# above are load-bearing, not incidental: `file_coordinator` and
# `file_identity` resolve `os`, `stage_regular_file`, and
# `remove_verified_file` through `sys.modules["photo_session"]` at call time,
# so those names must stay bound on this module. `view_filter`,
# `preview_strategies`, and the test suite import the extension constants and
# `pillow_previewable_extensions` from here. The redundant `as` aliases mark
# them as intentional re-exports so the linter does not prune them as unused.


class PhotoSession(PhotoSessionProperties, FileCoordinator):
    snapshot_version = 2

    def __init__(
        self,
        source_dir: str | Path | None = None,
        keep_dir: str | Path | None = None,
        nah_dir: str | Path | None = None,
        action_mode: ActionMode = "move",
        *,
        previewable_extensions: frozenset[str] | None = None,
        pending_groups: list[PhotoGroup] | None = None,
        available_extensions: tuple[str, ...] = (),
        enabled_extensions: set[str] | None = None,
        active_index: int = 0,
        history: list[ActionRecord] | None = None,
        completed_stems: set[str] | None = None,
        total_loaded: int = 0,
        staged_mode: bool = False,
        flag_dir: str | Path | None = None,
        staged_decisions: list[StagedDecision] | None = None,
    ) -> None:
        self._state = SessionState(
            source_dir=source_dir,
            keep_dir=keep_dir,
            nah_dir=nah_dir,
            action_mode=action_mode,
            previewable_extensions=previewable_extensions,
            pending_groups=pending_groups,
            available_extensions=available_extensions,
            enabled_extensions=enabled_extensions,
            active_index=active_index,
            completed_stems=completed_stems,
            total_loaded=total_loaded,
        )
        self._triage = PhotoTriage(history=history)
        self.staged_mode: bool = staged_mode
        self.flag_dir: Path | None = Path(flag_dir) if flag_dir is not None else None
        self._staged_manager = StagedTriageManager(staged=staged_decisions)
        self.keep_count: int = (
            sum(1 for r in self._triage.history if r.decision == "keep")
            + self.staged_summary.keep_count
        )
        self.nah_count: int = (
            sum(1 for r in self._triage.history if r.decision == "nah")
            + self.staged_summary.nah_count
        )

    # --- Navigation & Queue Methods ---

    def set_source_dir(self, path: str | Path | None) -> None:
        self._state.set_source_dir(path)

    def set_keep_dir(self, path: str | Path | None) -> None:
        self._state.set_keep_dir(path)

    def set_nah_dir(self, path: str | Path | None) -> None:
        self._state.set_nah_dir(path)

    def set_action_mode(self, mode: str) -> None:
        self._state.set_action_mode(mode)

    def reset_queue(self) -> None:
        self._state.reset_queue()
        self.history.clear()
        self._partial_copy_undo.clear()
        self._staged_manager.clear()
        self.keep_count = 0
        self.nah_count = 0

    def load_queue(self) -> int:
        result = self._state.load_queue()
        self.history.clear()
        self._partial_copy_undo.clear()
        self._staged_manager.clear()
        self.keep_count = 0
        self.nah_count = 0
        return result

    def apply_extension_filter(self, enabled: set[str]) -> int:
        return self._state.apply_extension_filter(enabled, processed_count=self.processed_count)

    def apply_prepared_extension_filter(
        self,
        available: tuple[str, ...],
        enabled: set[str],
        reconciled_groups: list[PhotoGroup] | tuple[PhotoGroup, ...] | None = None,
    ) -> int:
        result = self._state.apply_prepared_extension_filter(
            available,
            enabled,
            reconciled_groups,
            processed_count=self.processed_count,
        )
        self.total_loaded = self.keep_count + self.nah_count + len(self.pending_groups)
        return result

    def set_active_index(self, index: int) -> Path | None:
        return self._state.set_active_index(index)

    def move_active(self, offset: int) -> Path | None:
        return self._state.move_active(offset)

    def _project_pending_groups(self) -> list[PhotoGroup]:
        return self._state._project_pending_groups()

    def _validated_source_dir(self) -> Path:
        return self._state._validated_source_dir()

    def _remove_queue_item(self, index: int) -> PhotoGroup:
        return self._state.remove_queue_item(index)

    def _representative_for(self, members: tuple[Path, ...]) -> Path:
        return self._state._representative_for(members)

    @staticmethod
    def _as_group(item: PhotoGroup | Path) -> PhotoGroup:
        return SessionState._as_group(item)

    def _refresh_record_identities(
        self,
        record: ActionRecord,
        updates: dict[FileOperation, FileIdentity],
    ) -> None:
        if updates:
            refreshed_files = tuple(
                FileOperation(op.source, op.destination, updates.get(op, op.destination_identity))
                for op in record.files
            )
            self.history[-1] = ActionRecord(
                record.decision, record.action_mode, record.group, refreshed_files, record.index
            )

    # --- Triage Actions: decide and undo ---

    def decide(self, decision: Decision) -> DecisionResult:
        if decision not in {"keep", "nah", "flag"}:
            raise PhotoSessionError(f"Unsupported decision: {decision}")
        group = self.active_group
        if group is None:
            raise PhotoSessionError("There are no loaded photos left to sort.")
        current_index = self.active_index

        remaining_members = tuple(path for path in group.members if path.is_file())
        if not remaining_members:
            self._remove_queue_item(current_index)
            self.total_loaded = self.keep_count + self.nah_count + len(self.pending_groups)
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

        if decision == "keep":
            destination_dir = self.keep_dir
        elif decision == "nah":
            destination_dir = self.nah_dir
        else:
            destination_dir = self.flag_dir

        if self.staged_mode:
            staged = self._staged_manager.stage(
                group,
                decision,
                self.action_mode,
                destination_dir,
                current_index,
            )
            self._remove_queue_item(current_index)
            self.completed_stems.add(group.stem)
            if decision == "keep":
                self.keep_count += 1
            elif decision == "nah":
                self.nah_count += 1
            return DecisionResult(
                decision,
                self.action_mode,
                group,
                staged.files,
                self.remaining_count,
            )

        if destination_dir is None:
            label = "Keep" if decision == "keep" else ("Nah" if decision == "nah" else "Flag")
            raise PhotoSessionError(f"Choose a {label} folder before sorting.")

        destination_dir = destination_dir.expanduser()
        try:
            destination_dir.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise PhotoSessionError(
                f"Could not prepare the destination folder: {error}", primary_error=error
            ) from error

        if self.action_mode == "move":
            try:
                source_parent = group.members[0].resolve().parent
                dest_parent = destination_dir.resolve()
            except FileNotFoundError:
                source_parent = group.members[0].parent
                dest_parent = destination_dir
            if source_parent == dest_parent:
                raise PhotoSessionError(
                    "Move mode requires destination folders different from the current photo folder."
                )

        operations = self.execute_group_operations(
            group, group.members[0].parent, destination_dir, self.action_mode
        )
        self._remove_queue_item(current_index)
        self.history.append(
            ActionRecord(decision, self.action_mode, group, operations, current_index)
        )
        self.completed_stems.add(group.stem)
        if decision == "keep":
            self.keep_count += 1
        elif decision == "nah":
            self.nah_count += 1

        return DecisionResult(decision, self.action_mode, group, operations, self.remaining_count)

    def undo(self) -> UndoResult:
        if self.staged_mode and not self._staged_manager.is_empty:
            staged = self._staged_manager.undo()
            if staged is None:
                raise PhotoSessionError("There is nothing to undo.")
            self.completed_stems.discard(staged.stem)
            self.pending_groups.append(staged.group)
            self.pending_groups.sort(key=lambda group: (group.stem.lower(), group.stem))
            self.queue = self._project_pending_groups()
            self.active_index = next(
                (i for i, g in enumerate(self.queue) if g.stem == staged.stem), 0
            )
            if staged.decision == "keep":
                self.keep_count -= 1
            elif staged.decision == "nah":
                self.nah_count -= 1
            return UndoResult(
                staged.decision,
                staged.action_mode,
                staged.group,
                staged.files,
                self.remaining_count,
            )

        if not self.history:
            raise PhotoSessionError("There is nothing to undo.")

        record = self.history[-1]
        destination_root = self.recorded_destination_root(record)
        if record.action_mode == "move":
            self.undo_move_record(
                record, destination_root, self.source_dir, self._refresh_record_identities
            )
        else:
            self.undo_copy_record(
                record, destination_root, self._partial_copy_undo, self._refresh_record_identities
            )

        self.history.pop()
        self.completed_stems.discard(record.group.stem)
        self._partial_copy_undo.difference_update(record.files)
        self.pending_groups.append(record.group)
        self.pending_groups.sort(key=lambda group: (group.stem.lower(), group.stem))
        self.queue = self._project_pending_groups()
        self.active_index = next(
            (i for i, g in enumerate(self.queue) if g.stem == record.group.stem), 0
        )
        if record.decision == "keep":
            self.keep_count -= 1
        elif record.decision == "nah":
            self.nah_count -= 1

        return UndoResult(
            record.decision, record.action_mode, record.group, record.files, self.remaining_count
        )

    def commit_staged_batch(
        self,
        on_progress: Callable[[int, int, str], None] | None = None,
        cancel_token: threading.Event | None = None,
    ) -> tuple[ActionRecord, ...]:
        records = self._staged_manager.execute_batch(
            self, on_progress=on_progress, cancel_token=cancel_token
        )
        self.history.extend(records)
        return records

    def undo_all_staged(self) -> int:
        count = 0
        while not self._staged_manager.is_empty:
            self.undo()
            count += 1
        return count

    # --- Snapshot Serialization and Loading ---

    def to_snapshot(self) -> dict[str, object]:
        return session_snapshot.to_snapshot(
            self._state,
            self._triage,
            staged_mode=self.staged_mode,
            staged_decisions=self.staged_decisions,
        )

    @classmethod
    def from_snapshot(cls, data: object) -> PhotoSession | None:
        return session_snapshot.from_snapshot(data, cls._from_snapshot_factory)

    @classmethod
    def _from_snapshot_factory(cls, **kwargs: object) -> PhotoSession:
        return cls(**kwargs)
