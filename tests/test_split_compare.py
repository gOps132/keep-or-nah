from __future__ import annotations

from pathlib import Path
import pytest

from burst_clustering import PhotoBurstInfo
from photo_groups import PhotoGroup
from photo_session import PhotoSession
from split_compare import CompareCandidate, ComparePairSelector, SynchronizedViewTracker


def test_compare_pair_selector_next_in_queue(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    keep = tmp_path / "keep"
    keep.mkdir()
    nah = tmp_path / "nah"
    nah.mkdir()

    f1 = src / "p1.jpg"
    f1.write_bytes(b"1")
    f2 = src / "p2.jpg"
    f2.write_bytes(b"2")
    f3 = src / "p3.jpg"
    f3.write_bytes(b"3")

    session = PhotoSession(source_dir=src, keep_dir=keep, nah_dir=nah)
    session.load_queue()
    assert session.remaining_count == 3

    selector = ComparePairSelector()
    pair = selector.resolve_pair(session)
    assert pair is not None
    left, right = pair
    assert left.group.stem == "p1"
    assert right.group.stem == "p2"


def test_compare_pair_selector_last_item_in_queue(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    keep = tmp_path / "keep"
    keep.mkdir()

    f1 = src / "p1.jpg"
    f1.write_bytes(b"1")
    f2 = src / "p2.jpg"
    f2.write_bytes(b"2")

    session = PhotoSession(source_dir=src, keep_dir=keep)
    session.load_queue()
    session.set_active_index(1)  # active is p2

    selector = ComparePairSelector()
    pair = selector.resolve_pair(session)
    assert pair is not None
    left, right = pair
    assert left.group.stem == "p2"
    assert right.group.stem == "p1"


def test_compare_pair_pick_keeper_1(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    keep = tmp_path / "keep"
    keep.mkdir()
    nah = tmp_path / "nah"
    nah.mkdir()

    f1 = src / "p1.jpg"
    f1.write_bytes(b"1")
    f2 = src / "p2.jpg"
    f2.write_bytes(b"2")

    session = PhotoSession(source_dir=src, keep_dir=keep, nah_dir=nah, staged_mode=True)
    session.load_queue()

    selector = ComparePairSelector()
    pair = selector.resolve_pair(session)
    assert pair is not None

    # Pick 1 (Left keeper, Right nah)
    kept, rejected = selector.pick(pair, choice=1, session=session)
    assert kept.stem == "p1"
    assert rejected.stem == "p2"
    assert session.staged_summary.keep_count == 1
    assert session.staged_summary.nah_count == 1
    assert session.remaining_count == 0


def test_compare_pair_pick_keeper_2(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    keep = tmp_path / "keep"
    keep.mkdir()
    nah = tmp_path / "nah"
    nah.mkdir()

    f1 = src / "p1.jpg"
    f1.write_bytes(b"1")
    f2 = src / "p2.jpg"
    f2.write_bytes(b"2")

    session = PhotoSession(source_dir=src, keep_dir=keep, nah_dir=nah, staged_mode=True)
    session.load_queue()

    selector = ComparePairSelector()
    pair = selector.resolve_pair(session)
    assert pair is not None

    # Pick 2 (Right keeper, Left nah)
    kept, rejected = selector.pick(pair, choice=2, session=session)
    assert kept.stem == "p2"
    assert rejected.stem == "p1"
    assert session.staged_summary.keep_count == 1
    assert session.staged_summary.nah_count == 1
    assert session.remaining_count == 0


def test_synchronized_view_tracker() -> None:
    tracker = SynchronizedViewTracker()
    assert tracker.zoom_factor == 1.0

    tracker.set_zoom(2.5)
    assert tracker.zoom_factor == 2.5

    tracker.update_pan(0.2, 0.4)
    assert tracker.pan_x == 0.2
    assert tracker.pan_y == 0.4


def test_compare_pair_burst_partner_selection(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    f1 = src / "p1.jpg"
    f1.write_bytes(b"1")
    f2 = src / "p2.jpg"
    f2.write_bytes(b"2")
    f3 = src / "p3.jpg"
    f3.write_bytes(b"3")

    session = PhotoSession(source_dir=src)
    session.load_queue()

    burst_map = {
        f1: PhotoBurstInfo(path=f1, timestamp=100.0, image_hash=0b1111, sharpness=45.0),
        f2: PhotoBurstInfo(path=f2, timestamp=200.0, image_hash=0b0000, sharpness=10.0),
        f3: PhotoBurstInfo(path=f3, timestamp=100.2, image_hash=0b1110, sharpness=88.0),
    }
    best_shots = {f3}

    selector = ComparePairSelector()
    pair = selector.resolve_pair(session, burst_info_map=burst_map, best_shots=best_shots)
    assert pair is not None
    left, right = pair
    assert left.group.stem == "p1"
    assert right.group.stem == "p3"
    assert right.is_best_shot is True
    assert right.sharpness == 88.0


def test_compare_pair_fewer_than_two_photos(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    f1 = src / "p1.jpg"
    f1.write_bytes(b"1")

    session = PhotoSession(source_dir=src)
    session.load_queue()

    selector = ComparePairSelector()
    assert selector.resolve_pair(session) is None


def test_gui_compare_toggle_and_controls() -> None:
    from unittest.mock import Mock
    from gui_app import App

    app = Mock(spec=App)
    app.compare_mode = False
    app.compare_mode_button = Mock()
    app.preview_host = Mock()
    app.preview_canvas = Mock()
    app.compare_canvas = Mock()
    app.refresh_preview = Mock()
    app.refresh_ui = Mock()

    # Toggle On
    App.toggle_compare_mode(app)
    assert app.compare_mode is True
    app.compare_mode_button.configure.assert_called_with(text="1-Up (C)", fg_color="#3b82f6")
    app.preview_host.grid_columnconfigure.assert_any_call(1, weight=1)
    app.compare_canvas.grid.assert_called_once()
    app.refresh_preview.assert_called_once()
    app.refresh_ui.assert_called_once()

    # Toggle Off
    App.toggle_compare_mode(app)
    assert app.compare_mode is False
    app.compare_mode_button.configure.assert_called_with(text="2-Up (C)", fg_color=["#3a7ebf", "#1f538d"])
    app.compare_canvas.grid_remove.assert_called_once()


def test_gui_synchronized_pan_and_scroll() -> None:
    from unittest.mock import Mock
    from gui_app import App

    app = Mock(spec=App)
    app.compare_mode = True
    app.preview_canvas = Mock()
    app.compare_canvas = Mock()

    # Pan start
    event = Mock(x=50, y=60)
    App.start_pan(app, event)
    app.preview_canvas.scan_mark.assert_called_with(50, 60)
    app.compare_canvas.scan_mark.assert_called_with(50, 60)

    # Drag pan
    App.drag_pan(app, event)
    app.preview_canvas.scan_dragto.assert_called_with(50, 60, gain=1)
    app.compare_canvas.scan_dragto.assert_called_with(50, 60, gain=1)

    # Wheel scroll
    wheel_event = Mock(delta=120)
    res = App.handle_mousewheel(app, wheel_event)
    assert res == "break"
    app.preview_canvas.yview_scroll.assert_called_with(-1, "units")
    app.compare_canvas.yview_scroll.assert_called_with(-1, "units")

    # Shift wheel scroll
    res_shift = App.handle_shift_mousewheel(app, wheel_event)
    assert res_shift == "break"
    app.preview_canvas.xview_scroll.assert_called_with(-1, "units")
    app.compare_canvas.xview_scroll.assert_called_with(-1, "units")


def test_gui_compare_candidate_pick_shortcuts() -> None:
    from unittest.mock import Mock
    from gui_app import App

    app = Mock(spec=App)
    app.shortcuts_enabled = Mock(return_value=True)
    app.compare_mode = True
    app.pick_compare_candidate = Mock()

    # Press 1
    assert App.handle_compare_pick_1_shortcut(app) == "break"
    app.pick_compare_candidate.assert_called_with(1)

    # Press 2
    assert App.handle_compare_pick_2_shortcut(app) == "break"
    app.pick_compare_candidate.assert_called_with(2)

