"""Property accessors for the photo triage session.

Every accessor here is a forwarder: the real state lives in `SessionState`
(session shape), `PhotoTriage` (decision history), and `StagedTriageManager`
(staged decisions). The forwarding layer used to live inside `PhotoSession`,
which pushed that module past the 500-line architecture invariant. Splitting it
out keeps the session module about behaviour and this module about shape.

The mixin deliberately declares the collaborators it needs as annotations
rather than importing `PhotoSession`, which would be circular: `PhotoSession`
inherits from this mixin.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from photo_groups import PhotoGroup
from photo_triage import ActionMode, ActionRecord, FileOperation

if TYPE_CHECKING:
    from photo_triage import PhotoTriage
    from session_state import SessionState
    from staged_triage import StagedBatchSummary, StagedDecision, StagedTriageManager


class PhotoSessionProperties:
    """Forwarding accessors onto the session's composed state objects."""

    _state: SessionState
    _triage: PhotoTriage
    _staged_manager: StagedTriageManager
    keep_count: int
    nah_count: int

    # --- Properties delegating to SessionState ---

    @property
    def source_dir(self) -> Path | None:
        return self._state.source_dir

    @source_dir.setter
    def source_dir(self, value: Path | None) -> None:
        self._state.source_dir = value

    @property
    def keep_dir(self) -> Path | None:
        return self._state.keep_dir

    @keep_dir.setter
    def keep_dir(self, value: Path | None) -> None:
        self._state.keep_dir = value

    @property
    def nah_dir(self) -> Path | None:
        return self._state.nah_dir

    @nah_dir.setter
    def nah_dir(self, value: Path | None) -> None:
        self._state.nah_dir = value

    @property
    def action_mode(self) -> ActionMode:
        return self._state.action_mode

    @action_mode.setter
    def action_mode(self, value: ActionMode) -> None:
        self._state.action_mode = value

    @property
    def previewable_extensions(self) -> frozenset[str]:
        return self._state.previewable_extensions

    @property
    def available_extensions(self) -> tuple[str, ...]:
        return self._state.available_extensions

    @available_extensions.setter
    def available_extensions(self, value: tuple[str, ...]) -> None:
        self._state.available_extensions = value

    @property
    def enabled_extensions(self) -> set[str]:
        return self._state.enabled_extensions

    @enabled_extensions.setter
    def enabled_extensions(self, value: set[str]) -> None:
        self._state.enabled_extensions = value

    @property
    def pending_groups(self) -> list[PhotoGroup]:
        return self._state.pending_groups

    @pending_groups.setter
    def pending_groups(self, value: list[PhotoGroup]) -> None:
        self._state.pending_groups = value

    @property
    def completed_stems(self) -> set[str]:
        return self._state.completed_stems

    @completed_stems.setter
    def completed_stems(self, value: set[str]) -> None:
        self._state.completed_stems = value

    @property
    def queue(self) -> list[PhotoGroup]:
        return self._state.queue

    @queue.setter
    def queue(self, value: list[PhotoGroup]) -> None:
        self._state.queue = value

    @property
    def active_index(self) -> int:
        return self._state.active_index

    @active_index.setter
    def active_index(self, value: int) -> None:
        self._state.active_index = value

    @property
    def total_loaded(self) -> int:
        return self._state.total_loaded

    @total_loaded.setter
    def total_loaded(self, value: int) -> None:
        self._state.total_loaded = value

    @property
    def _extensions_source(self) -> Path | None:
        return self._state._extensions_source

    @_extensions_source.setter
    def _extensions_source(self, value: Path | None) -> None:
        self._state._extensions_source = value

    @property
    def active_group(self) -> PhotoGroup | None:
        return self._state.active_group

    @property
    def active_photo(self) -> Path | None:
        return self._state.active_photo

    @property
    def preview_paths(self) -> tuple[Path, ...]:
        return self._state.preview_paths

    @property
    def remaining_count(self) -> int:
        return self._state.remaining_count

    @property
    def pending_count(self) -> int:
        return self._state.pending_count

    @property
    def visible_count(self) -> int:
        return self._state.visible_count

    @property
    def current_position(self) -> int:
        return self._state.current_position

    # --- Properties delegating to PhotoTriage ---

    @property
    def history(self) -> list[ActionRecord]:
        return self._triage.history

    @history.setter
    def history(self, value: list[ActionRecord]) -> None:
        self._triage.history = value

    @property
    def _partial_copy_undo(self) -> set[FileOperation]:
        return self._triage.partial_copy_undo

    @property
    def can_undo(self) -> bool:
        return bool(self.history) or not self._staged_manager.is_empty

    @property
    def staged_decisions(self) -> list[StagedDecision]:
        return self._staged_manager.staged

    @property
    def staged_summary(self) -> StagedBatchSummary:
        return self._staged_manager.summary()

    @property
    def flag_count(self) -> int:
        return (
            sum(1 for r in self._triage.history if r.decision == "flag")
            + self.staged_summary.flag_count
        )

    @property
    def processed_count(self) -> int:
        return self.keep_count + self.nah_count
