from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from photo_groups import PhotoGroup, build_photo_groups, discover_extensions
from photo_metadata import SUPPORTED_IMAGE_EXTENSIONS, pillow_previewable_extensions
from photo_triage import ActionRecord

if TYPE_CHECKING:
    from photo_session import PhotoSession


def from_legacy_snapshot(
    data: dict[object, object],
    session_factory: Callable[..., PhotoSession],
    snapshot_helpers: object,
) -> PhotoSession | None:
    previewable_extensions = pillow_previewable_extensions()
    source_dir = snapshot_helpers._snapshot_source_root(data.get("source_dir"))
    keep_dir = snapshot_helpers._optional_path(data.get("keep_dir"))
    nah_dir = snapshot_helpers._optional_path(data.get("nah_dir"))
    mode = snapshot_helpers._snapshot_mode(data.get("action_mode", "move"))
    raw_queue = data.get("queue", [])
    if not isinstance(raw_queue, list) or not raw_queue:
        return None
    original_active_index = min(
        snapshot_helpers._snapshot_int(data.get("active_index", 0)),
        len(raw_queue) - 1,
    )

    valid_queue_items: list[tuple[int, Path]] = []
    active_stem: str | None = None
    for index, value in enumerate(raw_queue):
        path = snapshot_helpers._source_path_from_snapshot(
            value,
            source_dir=source_dir,
            require_existing=False,
        )
        if index == original_active_index:
            active_stem = path.stem
        if (
            snapshot_helpers._is_regular_file(path)
            and path.suffix.lower() in SUPPORTED_IMAGE_EXTENSIONS
        ):
            valid_queue_items.append((index, path))
    if not valid_queue_items:
        return None

    enabled = {path.suffix.lower() for _, path in valid_queue_items}
    pending_stems = {path.stem for _, path in valid_queue_items}
    queue = [
        group
        for group in build_photo_groups(
            source_dir,
            enabled,
            previewable_extensions,
        )
        if group.stem in pending_stems
    ]
    if not queue:
        return None

    active_index = next(
        (index for index, group in enumerate(queue) if group.stem == active_stem),
        None,
    )
    if active_index is None:
        _, nearest_path = min(
            valid_queue_items,
            key=lambda item: (
                abs(item[0] - original_active_index),
                item[0],
            ),
        )
        active_index = next(
            index for index, group in enumerate(queue) if group.stem == nearest_path.stem
        )

    total_loaded = snapshot_helpers._snapshot_int(
        data.get("total_loaded", len(queue)),
    )
    keep_count = snapshot_helpers._snapshot_int(data.get("keep_count", 0))
    nah_count = snapshot_helpers._snapshot_int(data.get("nah_count", 0))
    total_loaded = max(total_loaded, keep_count + nah_count + len(queue))

    session = session_factory(previewable_extensions=previewable_extensions)
    session.source_dir = source_dir
    session.keep_dir = keep_dir
    session.nah_dir = nah_dir
    session.action_mode = mode
    session.pending_groups = queue
    session.queue = queue
    session.active_index = active_index
    session.total_loaded = total_loaded
    session.available_extensions = discover_extensions(source_dir)
    session.enabled_extensions = enabled
    session._extensions_source = source_dir.resolve(strict=True)
    session.history = legacy_history_from_snapshot(
        data.get("history", []),
        source_dir=source_dir,
        keep_dir=keep_dir,
        nah_dir=nah_dir,
        snapshot_helpers=snapshot_helpers,
    )
    session.completed_stems = {record.group.stem for record in session.history}
    return session


def legacy_history_from_snapshot(
    value: object,
    *,
    source_dir: Path,
    keep_dir: Path | None,
    nah_dir: Path | None,
    snapshot_helpers: object,
) -> list[ActionRecord]:
    if not isinstance(value, list):
        return []
    history: list[ActionRecord] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        try:
            decision = item["decision"]
            if type(decision) is not str or decision not in {"keep", "nah"}:
                raise ValueError("Snapshot decision is invalid")
            action_mode = snapshot_helpers._snapshot_mode(item["action_mode"])
            destination_root = keep_dir if decision == "keep" else nah_dir
            if destination_root is None:
                raise ValueError("Snapshot action destination root is unavailable")
            operation = snapshot_helpers._file_operation_from_snapshot(
                item,
                source_dir=source_dir,
                destination_root=destination_root,
            )
            group = PhotoGroup(
                operation.source.stem,
                (operation.source,),
                operation.source,
            )
            history.append(
                ActionRecord(
                    decision,
                    action_mode,
                    group,
                    (operation,),
                    snapshot_helpers._snapshot_int(item["index"]),
                )
            )
        except (KeyError, OSError, OverflowError, TypeError, ValueError):
            continue
    return history
