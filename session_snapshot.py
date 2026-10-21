from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

import legacy_snapshot
import snapshot_validators
from photo_groups import PhotoGroup
from photo_metadata import pillow_previewable_extensions
from photo_triage import DECISIONS, FileOperation
from staged_triage import StagedDecision, StagedTriageManager

if TYPE_CHECKING:
    from photo_session import PhotoSession
    from photo_triage import PhotoTriage
    from session_state import SessionState

SNAPSHOT_VERSION = 2


def _group_to_snapshot(group: PhotoGroup) -> dict[str, object]:
    return {
        "stem": group.stem,
        "members": [str(member) for member in group.members],
        "representative": str(group.representative),
    }


def to_snapshot(
    state: SessionState,
    triage: PhotoTriage,
    staged_mode: bool = False,
    staged_decisions: tuple[StagedDecision, ...] | list[StagedDecision] = (),
) -> dict[str, object]:
    snapshot = {
        "snapshot_version": SNAPSHOT_VERSION,
        "source_dir": str(state.source_dir) if state.source_dir is not None else None,
        "keep_dir": str(state.keep_dir) if state.keep_dir is not None else None,
        "nah_dir": str(state.nah_dir) if state.nah_dir is not None else None,
        "action_mode": state.action_mode,
        "queue": [_group_to_snapshot(state._as_group(item)) for item in state.queue],
        "pending_groups": [_group_to_snapshot(group) for group in state.pending_groups],
        "completed_stems": sorted(state.completed_stems),
        "active_index": state.active_index,
        "active_stem": (state.active_group.stem if state.active_group is not None else None),
        "total_loaded": state.total_loaded,
        "keep_count": triage.keep_count,
        "nah_count": triage.nah_count,
        "available_extensions": list(state.available_extensions),
        "enabled_extensions": sorted(state.enabled_extensions),
        "history": [
            {
                "decision": record.decision,
                "action_mode": record.action_mode,
                "group": _group_to_snapshot(record.group),
                "files": [
                    {
                        "source": str(operation.source),
                        "destination": str(operation.destination),
                        "destination_identity": (
                            list(operation.destination_identity)
                            if operation.destination_identity is not None
                            else None
                        ),
                    }
                    for operation in record.files
                ],
                "index": record.index,
            }
            for record in triage.history
        ],
    }
    if staged_mode or staged_decisions:
        snapshot["staged_mode"] = staged_mode
        snapshot["staged_decisions"] = [
            {
                "stem": item.stem,
                "group": _group_to_snapshot(item.group),
                "decision": item.decision,
                "action_mode": item.action_mode,
                "destination_dir": (
                    str(item.destination_dir) if item.destination_dir is not None else None
                ),
                "index": item.index,
                "bytes_size": item.bytes_size,
            }
            for item in staged_decisions
        ]
    return snapshot


def from_snapshot(
    data: object,
    session_factory: Callable[..., PhotoSession],
) -> PhotoSession | None:
    if not isinstance(data, dict):
        return None
    try:
        version = data.get("snapshot_version", 1)
        if type(version) is not int:
            return None
        if version == SNAPSHOT_VERSION:
            return _from_grouped_snapshot(data, session_factory)
        if version == 1:
            return legacy_snapshot.from_legacy_snapshot(data, session_factory, snapshot_validators)
        return None
    except (OSError, OverflowError, TypeError, ValueError):
        return None


def _from_grouped_snapshot(
    data: dict[object, object],
    session_factory: Callable[..., PhotoSession],
) -> PhotoSession | None:
    previewable_extensions = pillow_previewable_extensions()
    source_dir = snapshot_validators._snapshot_source_root(data.get("source_dir"))
    keep_dir = snapshot_validators._optional_path(data.get("keep_dir"))
    nah_dir = snapshot_validators._optional_path(data.get("nah_dir"))
    mode = snapshot_validators._snapshot_mode(data.get("action_mode"))
    available = snapshot_validators._snapshot_extensions(data.get("available_extensions"))
    enabled = set(snapshot_validators._snapshot_extensions(data.get("enabled_extensions")))
    if not enabled.issubset(available):
        return None
    raw_completed = data.get("completed_stems")
    if raw_completed is not None:
        if (
            not isinstance(raw_completed, list)
            or any(not snapshot_validators._is_safe_completed_stem(stem) for stem in raw_completed)
            or len(set(raw_completed)) != len(raw_completed)
        ):
            return None
        declared_completed = set(raw_completed)
    else:
        declared_completed = snapshot_validators._safe_raw_history_stems(
            data.get("history"),
            source_dir=source_dir,
        )

    raw_queue = data.get("queue")
    if not isinstance(raw_queue, list):
        return None
    raw_pending = data.get("pending_groups", raw_queue)
    if not isinstance(raw_pending, list) or not raw_pending:
        return None
    active_index = snapshot_validators._snapshot_int(data.get("active_index"))
    active_stem = data.get("active_stem")
    if raw_queue:
        if active_index >= len(raw_queue) or type(active_stem) is not str:
            return None
    elif active_index != 0 or active_stem is not None:
        return None

    restored_visible = [
        (
            index,
            snapshot_validators._queue_group_from_snapshot(
                item,
                source_dir=source_dir,
                enabled_extensions=enabled,
                previewable_extensions=previewable_extensions,
            ),
        )
        for index, item in enumerate(raw_queue)
    ]
    declared_visible_stems = [
        item.get("stem") if isinstance(item, dict) else None for item in raw_queue
    ]
    if raw_queue and active_stem != declared_visible_stems[active_index]:
        return None
    if len(set(declared_visible_stems)) != len(declared_visible_stems):
        return None

    surviving_visible = [
        (original_index, group) for original_index, group in restored_visible if group is not None
    ]
    restored_pending = [
        snapshot_validators._queue_group_from_snapshot(
            item,
            source_dir=source_dir,
            enabled_extensions=set(available),
            previewable_extensions=previewable_extensions,
        )
        for item in raw_pending
    ]
    pending_groups = [group for group in restored_pending if group is not None]
    if not pending_groups:
        return None
    pending_stems = [item.get("stem") if isinstance(item, dict) else None for item in raw_pending]
    if len(set(pending_stems)) != len(pending_stems):
        return None
    all_members = [member for group in pending_groups for member in group.members]
    if len(set(all_members)) != len(all_members):
        return None

    total_loaded = snapshot_validators._snapshot_int(data.get("total_loaded"))
    keep_count = snapshot_validators._snapshot_int(data.get("keep_count"))
    nah_count = snapshot_validators._snapshot_int(data.get("nah_count"))
    if total_loaded < keep_count + nah_count + len(raw_pending):
        return None

    session = session_factory(previewable_extensions=previewable_extensions)
    session.source_dir = source_dir
    session.keep_dir = keep_dir
    session.nah_dir = nah_dir
    session.action_mode = mode
    session.pending_groups = pending_groups
    session.total_loaded = total_loaded
    session.keep_count = keep_count
    session.nah_count = nah_count
    session.available_extensions = tuple(available)
    session.enabled_extensions = enabled
    session._extensions_source = source_dir.resolve(strict=True)
    session.queue = session._project_pending_groups()
    parsed_visible = [group for _, group in surviving_visible]
    if session.queue != parsed_visible:
        return None
    if session.queue:
        retained_active_index = next(
            (index for index, group in enumerate(session.queue) if group.stem == active_stem),
            None,
        )
        if retained_active_index is None:
            nearest_original_index, _ = min(
                surviving_visible,
                key=lambda item: (abs(item[0] - active_index), item[0]),
            )
            retained_active_index = next(
                index
                for index, (original_index, _group) in enumerate(surviving_visible)
                if original_index == nearest_original_index
            )
        session.active_index = retained_active_index
    else:
        session.active_index = 0
    session.history = snapshot_validators._grouped_history_from_snapshot(
        data.get("history"),
        source_dir=source_dir,
        keep_dir=keep_dir,
        nah_dir=nah_dir,
    )
    history_stems = {record.group.stem for record in session.history}
    staged_mode = bool(data.get("staged_mode", False))
    raw_staged = data.get("staged_decisions", [])
    restored_staged: list[StagedDecision] = []
    if isinstance(raw_staged, list):
        for item in raw_staged:
            if not isinstance(item, dict):
                continue
            group_dict = item.get("group")
            if not isinstance(group_dict, dict):
                continue
            staged_group = snapshot_validators._queue_group_from_snapshot(
                group_dict,
                source_dir=source_dir,
                enabled_extensions=enabled,
                previewable_extensions=previewable_extensions,
            )
            if staged_group is None:
                continue
            decision = item.get("decision", "keep")
            if decision not in DECISIONS:
                continue
            action_mode = item.get("action_mode", "move")
            dest_dir = Path(item["destination_dir"]) if item.get("destination_dir") else None
            idx = int(item.get("index", 0))
            bytes_size = int(item.get("bytes_size", 0))
            files = (
                tuple(FileOperation(m, dest_dir / m.name) for m in staged_group.members)
                if dest_dir is not None
                else ()
            )
            restored_staged.append(
                StagedDecision(
                    group=staged_group,
                    decision=decision,
                    action_mode=action_mode,
                    destination_dir=dest_dir,
                    files=files,
                    index=idx,
                    bytes_size=bytes_size,
                )
            )

    session.completed_stems = declared_completed
    # A Photo Group that carries a Staged Decision is a pending Photo Group: it
    # is still in the source folder, and the Thumbnail Strip shows what was
    # decided about it. Only a decision that reached the disk completes one.
    if not history_stems.issubset(session.completed_stems):
        return None
    if {group.stem for group in session.pending_groups} & session.completed_stems:
        return None
    session.staged_mode = staged_mode
    if hasattr(session, "_staged_manager"):
        session._staged_manager = StagedTriageManager(staged=restored_staged)
    return session
