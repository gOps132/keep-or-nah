from __future__ import annotations

import threading
from pathlib import Path

import pytest

from file_coordinator import FileCoordinator
from photo_groups import PhotoGroup
from photo_triage import FileOperation, PhotoSessionError
from staged_triage import (
    StagedBatchSummary,
    StagedDecision,
    StagedTriageManager,
    format_bytes,
)


def test_format_bytes() -> None:
    assert format_bytes(500) == "500 B"
    assert format_bytes(1024) == "1.0 KB"
    assert format_bytes(1024 * 1024 * 15) == "15.0 MB"
    assert format_bytes(int(1024 * 1024 * 1024 * 2.5)) == "2.5 GB"


def test_stage_decision_records_virtual_action(tmp_path: Path) -> None:
    src_file = tmp_path / "img1.jpg"
    src_file.write_bytes(b"x" * 2048)
    group = PhotoGroup("img1", (src_file,), src_file)
    dest_dir = tmp_path / "keep"

    manager = StagedTriageManager()
    staged = manager.stage(
        group=group,
        decision="keep",
        action_mode="move",
        destination_dir=dest_dir,
        index=0,
    )

    assert staged.stem == "img1"
    assert staged.decision == "keep"
    assert staged.bytes_size == 2048
    assert len(manager.staged) == 1
    # File should not have moved!
    assert src_file.exists()
    assert not (dest_dir / "img1.jpg").exists()


def test_staged_summary_and_reclaimed_space(tmp_path: Path) -> None:
    f1 = tmp_path / "k1.jpg"
    f1.write_bytes(b"a" * 1000)
    g1 = PhotoGroup("k1", (f1,), f1)

    f2 = tmp_path / "n1.jpg"
    f2.write_bytes(b"b" * 5000)
    g2 = PhotoGroup("n1", (f2,), f2)

    f3 = tmp_path / "flag1.jpg"
    f3.write_bytes(b"c" * 2000)
    g3 = PhotoGroup("flag1", (f3,), f3)

    manager = StagedTriageManager()
    manager.stage(g1, "keep", "move", tmp_path / "keep", 0)
    manager.stage(g2, "nah", "move", tmp_path / "nah", 1)
    manager.stage(g3, "flag", "move", tmp_path / "flag", 2)

    summary = manager.summary()
    assert summary.total_count == 3
    assert summary.keep_count == 1
    assert summary.nah_count == 1
    assert summary.flag_count == 1
    assert summary.total_bytes == 8000
    assert summary.reclaimed_bytes == 5000


def test_revise_and_unstage(tmp_path: Path) -> None:
    f1 = tmp_path / "photo.jpg"
    f1.write_bytes(b"test")
    group = PhotoGroup("photo", (f1,), f1)

    manager = StagedTriageManager()
    manager.stage(group, "keep", "move", tmp_path / "keep", 0)

    # Revise to nah
    revised = manager.revise("photo", "nah", tmp_path / "nah")
    assert revised.decision == "nah"
    assert manager.summary().nah_count == 1
    assert manager.summary().keep_count == 0

    # Unstage
    unstage_result = manager.unstage("photo")
    assert unstage_result is not None
    assert unstage_result.stem == "photo"
    assert len(manager.staged) == 0


def test_undo_staged(tmp_path: Path) -> None:
    f1 = tmp_path / "p1.jpg"
    f1.write_bytes(b"1")
    f2 = tmp_path / "p2.jpg"
    f2.write_bytes(b"2")

    manager = StagedTriageManager()
    manager.stage(PhotoGroup("p1", (f1,), f1), "keep", "move", tmp_path / "keep", 0)
    manager.stage(PhotoGroup("p2", (f2,), f2), "nah", "move", tmp_path / "nah", 1)

    popped = manager.undo()
    assert popped is not None
    assert popped.stem == "p2"
    assert len(manager.staged) == 1
    assert manager.summary().keep_count == 1


def test_batch_execution_success(tmp_path: Path) -> None:
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    keep_dir = tmp_path / "keep"
    keep_dir.mkdir()
    nah_dir = tmp_path / "nah"
    nah_dir.mkdir()

    f1 = src_dir / "p1.jpg"
    f1.write_bytes(b"p1-data")
    f2 = src_dir / "p2.jpg"
    f2.write_bytes(b"p2-data")

    coordinator = FileCoordinator()
    manager = StagedTriageManager()
    manager.stage(PhotoGroup("p1", (f1,), f1), "keep", "move", keep_dir, 0)
    manager.stage(PhotoGroup("p2", (f2,), f2), "nah", "move", nah_dir, 1)

    progress_events: list[tuple[int, int, str]] = []

    def on_progress(done: int, total: int, stem: str) -> None:
        progress_events.append((done, total, stem))

    records = manager.execute_batch(coordinator, on_progress=on_progress)

    assert len(records) == 2
    assert (keep_dir / "p1.jpg").exists()
    assert (nah_dir / "p2.jpg").exists()
    assert not f1.exists()
    assert not f2.exists()
    assert len(manager.staged) == 0
    assert len(progress_events) == 2


def test_batch_execution_cancellation_rolls_back(tmp_path: Path) -> None:
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    keep_dir = tmp_path / "keep"
    keep_dir.mkdir()

    f1 = src_dir / "p1.jpg"
    f1.write_bytes(b"p1-data")
    f2 = src_dir / "p2.jpg"
    f2.write_bytes(b"p2-data")

    coordinator = FileCoordinator()
    manager = StagedTriageManager()
    manager.stage(PhotoGroup("p1", (f1,), f1), "keep", "move", keep_dir, 0)
    manager.stage(PhotoGroup("p2", (f2,), f2), "keep", "move", keep_dir, 1)

    cancel_token = threading.Event()

    def on_progress(done: int, total: int, stem: str) -> None:
        # Cancel immediately after first item
        cancel_token.set()

    with pytest.raises(PhotoSessionError, match="cancelled"):
        manager.execute_batch(coordinator, on_progress=on_progress, cancel_token=cancel_token)

    # Rollback should ensure original files are restored in src_dir!
    assert f1.exists()
    assert f2.exists()
    assert not (keep_dir / "p1.jpg").exists()


def test_photo_session_staged_mode(tmp_path: Path) -> None:
    from photo_session import PhotoSession

    src_dir = tmp_path / "src"
    src_dir.mkdir()
    keep_dir = tmp_path / "keep"
    keep_dir.mkdir()
    nah_dir = tmp_path / "nah"
    nah_dir.mkdir()

    p1 = src_dir / "a.jpg"
    p1.write_bytes(b"data-a")
    p2 = src_dir / "b.jpg"
    p2.write_bytes(b"data-b")

    session = PhotoSession(
        source_dir=src_dir,
        keep_dir=keep_dir,
        nah_dir=nah_dir,
        staged_mode=True,
    )
    session.load_queue()
    assert session.remaining_count == 2
    assert session.staged_mode is True

    # Decide keep on first photo
    res1 = session.decide("keep")
    assert res1.decision == "keep"
    assert session.remaining_count == 1
    assert session.staged_summary.keep_count == 1
    # Virtual stage: file still in src_dir!
    assert p1.exists()
    assert not (keep_dir / "a.jpg").exists()

    # Decide nah on second photo
    res2 = session.decide("nah")
    assert res2.decision == "nah"
    assert session.remaining_count == 0
    assert session.staged_summary.nah_count == 1
    assert p2.exists()

    # Undo last staged decision
    undo_res = session.undo()
    assert undo_res.decision == "nah"
    assert session.remaining_count == 1
    assert session.staged_summary.nah_count == 0

    # Commit batch
    records = session.commit_staged_batch()
    assert len(records) == 1
    assert (keep_dir / "a.jpg").exists()
    assert not p1.exists()
    assert session.staged_summary.total_count == 0


def test_photo_session_staged_snapshot_persistence(tmp_path: Path) -> None:
    from photo_session import PhotoSession

    src_dir = tmp_path / "src"
    src_dir.mkdir()
    keep_dir = tmp_path / "keep"
    keep_dir.mkdir()

    p1 = src_dir / "p1.jpg"
    p1.write_bytes(b"p1")
    p2 = src_dir / "p2.jpg"
    p2.write_bytes(b"p2")

    session = PhotoSession(
        source_dir=src_dir,
        keep_dir=keep_dir,
        staged_mode=True,
    )
    session.load_queue()
    session.decide("keep")
    assert len(session.staged_decisions) == 1

    snapshot = session.to_snapshot()
    assert snapshot["staged_mode"] is True
    assert len(snapshot["staged_decisions"]) == 1

    restored = PhotoSession.from_snapshot(snapshot)
    assert restored is not None
    assert restored.staged_mode is True
    assert len(restored.staged_decisions) == 1
    assert restored.staged_decisions[0].stem == "p1"
    assert restored.remaining_count == 1
