from __future__ import annotations

from pathlib import Path
import threading
import time
import pytest

from photo_session import PhotoSession
from review_commit_modal import ReviewCommitController


def test_controller_revise_and_unstage(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    keep = tmp_path / "keep"
    keep.mkdir()
    nah = tmp_path / "nah"
    nah.mkdir()

    p1 = src / "p1.jpg"
    p1.write_bytes(b"111")
    p2 = src / "p2.jpg"
    p2.write_bytes(b"222")

    session = PhotoSession(source_dir=src, keep_dir=keep, nah_dir=nah, staged_mode=True)
    session.load_queue()
    session.decide("keep")
    session.decide("nah")

    controller = ReviewCommitController(session)
    assert len(controller.staged) == 2
    assert controller.summary.keep_count == 1
    assert controller.summary.nah_count == 1

    # Revise p1 to nah
    controller.revise_decision("p1", "nah")
    assert controller.summary.nah_count == 2
    assert controller.summary.keep_count == 0

    # Unstage p2
    unstage_res = controller.unstage_item("p2")
    assert unstage_res is not None
    assert unstage_res.stem == "p2"
    assert len(controller.staged) == 1
    assert session.remaining_count == 1


def test_controller_discard_all(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    keep = tmp_path / "keep"
    keep.mkdir()

    p1 = src / "p1.jpg"
    p1.write_bytes(b"111")
    p2 = src / "p2.jpg"
    p2.write_bytes(b"222")

    session = PhotoSession(source_dir=src, keep_dir=keep, staged_mode=True)
    session.load_queue()
    session.decide("keep")
    session.decide("keep")

    controller = ReviewCommitController(session)
    assert len(controller.staged) == 2

    discarded = controller.discard_all()
    assert discarded == 2
    assert len(controller.staged) == 0
    assert session.remaining_count == 2


def test_controller_start_commit_success(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    keep = tmp_path / "keep"
    keep.mkdir()

    p1 = src / "p1.jpg"
    p1.write_bytes(b"111")

    session = PhotoSession(source_dir=src, keep_dir=keep, staged_mode=True)
    session.load_queue()
    session.decide("keep")

    callback_called = threading.Event()
    progress_calls = []

    def on_prog(done: int, total: int, stem: str) -> None:
        progress_calls.append((done, total, stem))

    def on_done(count: int) -> None:
        callback_called.set()

    def on_err(msg: str) -> None:
        pass

    controller = ReviewCommitController(session)
    controller.start_commit(on_prog, on_done, on_err)

    assert callback_called.wait(timeout=2.0)
    assert len(progress_calls) == 1
    assert (keep / "p1.jpg").exists()
    assert not p1.exists()
