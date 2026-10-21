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
from photo_groups import PhotoGroup, stem_order
from photo_metadata import SUPPORTED_IMAGE_EXTENSIONS as SUPPORTED_IMAGE_EXTENSIONS
from photo_metadata import pillow_previewable_extensions as pillow_previewable_extensions
from photo_session_properties import PhotoSessionProperties
from photo_triage import (
    DECISIONS,
    ActionMode,
    ActionRecord,
    Decision,
    DecisionResult,
    FileOperation,
    PhotoSessionError,
    PhotoTriage,
    UndoResult,
)
from photo_triage import EMPTY_EXTENSION_SELECTION_MESSAGE as EMPTY_EXTENSION_SELECTION_MESSAGE
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
        # A Staged Decision has not been executed yet, so it is not counted
        # here. The count is the number of decisions that reached the disk.
        self.keep_count: int = sum(1 for r in self._triage.history if r.decision == "keep")
        self.nah_count: int = sum(1 for r in self._triage.history if r.decision == "nah")

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
        if decision not in DECISIONS:
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

        destination_dir = self.destination_dir_for(decision)

        if self.staged_mode:
            staged = self._stage_decision(group, decision, current_index)
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

    def destination_dir_for(self, decision: Decision) -> Path | None:
        """The folder a decision sends its Photo Group to."""
        if decision == "keep":
            return self.keep_dir
        if decision == "nah":
            return self.nah_dir
        return self.flag_dir

    def _stage_decision(
        self,
        group: PhotoGroup,
        decision: Decision,
        index: int,
    ) -> StagedDecision:
        """Record the decision for a Photo Group, revising it if it already has one.

        A staged Photo Group stays in the queue: it is still in the source
        folder, and the Thumbnail Strip shows what was decided about it. The
        focus moves on to the next Photo Group that is still waiting for a
        decision.
        """
        destination_dir = self.destination_dir_for(decision)
        if self._staged_manager.decision_for(group.stem) is not None:
            staged = self._staged_manager.revise(group.stem, decision, destination_dir)
        else:
            staged = self._staged_manager.stage(
                group,
                decision,
                self.action_mode,
                destination_dir,
                index,
            )
        self._focus_next_undecided(index)
        return staged

    def _focus_next_undecided(self, current_index: int) -> None:
        """Move the focus to the next Photo Group that is waiting for a decision."""
        queue = self._state.queue
        if len(queue) < 2:
            return
        decided = {item.stem for item in self._staged_manager.staged}
        for offset in range(1, len(queue)):
            candidate = (current_index + offset) % len(queue)
            if queue[candidate].stem not in decided:
                self.active_index = candidate
                return

    def revise_staged_decision(self, stem: str, decision: Decision) -> StagedDecision | None:
        """Change the Staged Decision of a Photo Group that already carries one."""
        try:
            return self._staged_manager.revise(stem, decision, self.destination_dir_for(decision))
        except KeyError:
            return None

    def unstage(self, stem: str) -> StagedDecision | None:
        """Drop the Staged Decision of a Photo Group so it waits for one again."""
        staged = self._staged_manager.unstage(stem)
        if staged is None:
            return None
        self._restore_pending_group(staged.group)
        self._focus_group(staged.stem)
        return staged

    def _restore_pending_group(self, group: PhotoGroup) -> None:
        """Put a Photo Group back in the pending list if it is not there already.

        A staged Photo Group stays in the pending list, so this only has work
        to do for a session that was saved before it did.
        """
        if any(item.stem == group.stem for item in self.pending_groups):
            return
        self.pending_groups.append(group)
        self.pending_groups.sort(key=stem_order)
        self.queue = self._project_pending_groups()

    def _focus_group(self, stem: str) -> None:
        """Move the focus to the Photo Group with this stem."""
        self.active_index = next((i for i, group in enumerate(self.queue) if group.stem == stem), 0)

    def undo(self) -> UndoResult:
        if self.staged_mode and not self._staged_manager.is_empty:
            staged = self._staged_manager.undo()
            if staged is None:
                raise PhotoSessionError("There is nothing to undo.")
            self._restore_pending_group(staged.group)
            self._focus_group(staged.stem)
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
        self._retire_committed_groups(records)
        return records

    def _retire_committed_groups(self, records: tuple[ActionRecord, ...]) -> None:
        """Take the committed Photo Groups out of the pending list.

        Their decision has been carried out, so the Thumbnail Strip must not
        keep offering them for triage.
        """
        for record in records:
            self.completed_stems.add(record.group.stem)
            if record.decision == "keep":
                self.keep_count += 1
            elif record.decision == "nah":
                self.nah_count += 1
        if not records:
            return
        committed = {record.group.stem for record in records}
        self.pending_groups = [
            group for group in self.pending_groups if group.stem not in committed
        ]
        self._restore_active_group()

    def _restore_active_group(self) -> None:
        """Keep the focus on the same Photo Group after the queue is rebuilt."""
        previous_index = self.active_index
        active_stem = self.active_group.stem if self.active_group is not None else None
        self.queue = self._project_pending_groups()
        self.active_index = next(
            (i for i, group in enumerate(self.queue) if group.stem == active_stem),
            min(previous_index, max(len(self.queue) - 1, 0)),
        )

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
        session = session_snapshot.from_snapshot(data, cls._from_snapshot_factory)
        if session is not None:
            session._adopt_staged_groups()
        return session

    def _adopt_staged_groups(self) -> None:
        """Bring the Photo Groups that carry a Staged Decision back into the pending list.

        A session saved before the Thumbnail Strip rendered Staged Decisions
        took a staged Photo Group out of the pending list, because the group
        left the queue the moment it was staged. A staged Photo Group is still
        in the source folder, so it is a pending Photo Group that carries a
        decision.
        """
        adopted = [
            item.group
            for item in self._staged_manager.staged
            if not any(group.stem == item.stem for group in self.pending_groups)
        ]
        if not adopted:
            return
        self.pending_groups.extend(adopted)
        self.pending_groups.sort(key=stem_order)
        self.completed_stems.difference_update(item.stem for item in self._staged_manager.staged)
        self._restore_active_group()

    @classmethod
    def _from_snapshot_factory(cls, **kwargs: object) -> PhotoSession:
        return cls(**kwargs)
