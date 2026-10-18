import os
from pathlib import Path
import pytest

from photo_groups import PhotoGroup


def test_domain_modules_under_500_lines() -> None:
    modules = [
        "photo_session.py",
        "session_state.py",
        "photo_triage.py",
        "file_coordinator.py",
        "file_identity.py",
        "photo_metadata.py",
        "session_snapshot.py",
        "snapshot_validators.py",
        "legacy_snapshot.py",
    ]
    for filename in modules:
        path = Path(filename)
        assert path.exists(), f"Expected domain module {filename} to exist"
        lines = path.read_text(encoding="utf-8").splitlines()
        assert len(lines) < 500, f"{filename} has {len(lines)} lines; must be < 500"


def test_in_memory_triage_decide_and_undo() -> None:
    from photo_triage import PhotoTriage, ActionRecord, FileOperation, PhotoSessionError

    triage = PhotoTriage()
    assert not triage.can_undo
    assert triage.processed_count == 0
    assert triage.keep_count == 0
    assert triage.nah_count == 0

    group = PhotoGroup(
        stem="test_photo",
        members=(Path("/virtual/test_photo.jpg"), Path("/virtual/test_photo.raw")),
        representative=Path("/virtual/test_photo.jpg"),
    )

    # In-memory triage decision
    result = triage.decide_in_memory(
        group=group,
        decision="keep",
        action_mode="move",
        destination_dir=Path("/virtual/keep"),
    )
    assert result.decision == "keep"
    assert result.action_mode == "move"
    assert result.group == group
    assert len(result.files) == 2
    assert triage.can_undo
    assert triage.processed_count == 1
    assert triage.keep_count == 1
    assert triage.nah_count == 0

    # In-memory undo
    undo_result = triage.undo_in_memory()
    assert undo_result.decision == "keep"
    assert undo_result.group == group
    assert not triage.can_undo
    assert triage.processed_count == 0
    assert triage.keep_count == 0

    with pytest.raises(PhotoSessionError):
        triage.undo_in_memory()
