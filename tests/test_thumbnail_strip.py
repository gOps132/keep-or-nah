"""The Thumbnail Strip renders the Staged Decision of every decided Photo Group.

ADR-0004 requires a Staged Decision to be "rendered visually on the thumbnail
strip". The strip draws one entry per Photo Group in the active Photo Session,
so the indicator is drawn from the session's live Staged Decisions: a decision
that is revised changes the indicator, and a decision that is unstaged removes
it.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

import pytest

from photo_session import PhotoSession
from ui.thumbnail_strip import ThumbnailStripMixin

STAGED_TAG = "staged-decision"


class RecordingCanvas:
    """A Canvas that records everything the Thumbnail Strip draws on it."""

    def __init__(self, width: int = 800, height: int = 120) -> None:
        self.width = width
        self.height = height
        self.texts: list[dict] = []
        self.rectangles: list[dict] = []
        self.images: list[dict] = []
        self.lines: list[dict] = []
        self.deleted: list[tuple] = []

    def delete(self, *args):
        self.deleted.append(args)
        self.texts.clear()
        self.rectangles.clear()
        self.images.clear()
        self.lines.clear()

    def create_text(self, x, y, **kwargs):
        self.texts.append({"x": x, "y": y, **kwargs})
        return len(self.texts)

    def create_rectangle(self, x0, y0, x1, y1, **kwargs):
        self.rectangles.append({"x0": x0, "y0": y0, "x1": x1, "y1": y1, **kwargs})
        return len(self.rectangles)

    def create_image(self, x, y, **kwargs):
        self.images.append({"x": x, "y": y, **kwargs})
        return len(self.images)

    def create_line(self, *args, **kwargs):
        self.lines.append({"args": args, **kwargs})
        return len(self.lines)

    def tag_bind(self, *args, **kwargs):
        return None

    def configure(self, **kwargs):
        return None

    def winfo_width(self):
        return self.width

    def winfo_height(self):
        return self.height

    def canvasx(self, _offset):
        return 0.0

    def xview_moveto(self, _fraction):
        return None

    def xview_scroll(self, _amount, _units):
        return None


class _Strip(ThumbnailStripMixin):
    """The minimal App the Thumbnail Strip needs to draw itself."""

    def __init__(self, session: PhotoSession, canvas: RecordingCanvas) -> None:
        self.session = session
        self.thumbnail_canvas = canvas
        self.thumbnail_refs: list[object] = []
        self.thumbnail_signature: tuple = ()
        self.thumbnail_canvas_width = 0
        self.thumbnail_canvas_height = 0
        self.rendered_thumbnail_range = (-1, -1)
        self.rendered_active_index: int | None = None
        self.thumbnail_left_padding = 12
        self.thumbnail_top_padding = 10
        self.thumbnail_item_width = 84
        self.thumbnail_item_gap = 10
        self.thumbnail_pitch = 94
        self.thumbnail_size = 72
        self.thumbnail_buffer = 4
        self.best_shots: set[Path] = set()
        self.destroyed = False
        self.request_missing_strip_thumbnails = Mock()
        self.get_thumbnail_photo = Mock(return_value=None)
        self.select_photo_at_index = Mock()

    def _apply_appearance_mode(self, value):
        return value[0]


def _make_strip(session: PhotoSession, canvas: RecordingCanvas) -> _Strip:
    """The state the Thumbnail Strip reads off the App that owns it."""
    return _Strip(session, canvas)


def _make_session(tmp_path: Path, stems: tuple[str, ...] = ("a", "b", "c")) -> PhotoSession:
    source = tmp_path / "src"
    source.mkdir()
    for stem in stems:
        (source / f"{stem}.jpg").write_bytes(b"data")
    keep = tmp_path / "keep"
    keep.mkdir()
    nah = tmp_path / "nah"
    nah.mkdir()
    session = PhotoSession(
        source_dir=source,
        keep_dir=keep,
        nah_dir=nah,
        staged_mode=True,
    )
    session.load_queue()
    return session


def _staged_badges(canvas: RecordingCanvas) -> list[dict]:
    return [item for item in canvas.texts if STAGED_TAG in item.get("tags", ())]


def _draw(fake: _Strip) -> None:
    fake.refresh_thumbnail_strip()


def test_a_staged_decision_is_rendered_on_the_photo_group(tmp_path: Path) -> None:
    session = _make_session(tmp_path)
    session.decide("keep")
    canvas = RecordingCanvas()
    fake = _make_strip(session, canvas)

    _draw(fake)

    badges = _staged_badges(canvas)
    assert len(badges) == 1
    assert badges[0]["text"] == "K"


def test_no_badge_is_rendered_for_a_photo_group_without_a_decision(tmp_path: Path) -> None:
    session = _make_session(tmp_path)
    canvas = RecordingCanvas()
    fake = _make_strip(session, canvas)

    _draw(fake)

    assert _staged_badges(canvas) == []


def test_each_decision_renders_its_own_indicator(tmp_path: Path) -> None:
    session = _make_session(tmp_path)
    session.set_active_index(0)
    session.decide("keep")
    session.set_active_index(1)
    session.decide("nah")
    session.set_active_index(2)
    session.decide("flag")
    canvas = RecordingCanvas()
    fake = _make_strip(session, canvas)

    _draw(fake)

    assert [badge["text"] for badge in _staged_badges(canvas)] == ["K", "N", "F"]


def test_the_indicator_is_removed_when_the_decision_is_unstaged(tmp_path: Path) -> None:
    session = _make_session(tmp_path)
    session.decide("keep")
    canvas = RecordingCanvas()
    fake = _make_strip(session, canvas)
    _draw(fake)
    assert len(_staged_badges(canvas)) == 1

    session.unstage("a")
    _draw(fake)

    assert _staged_badges(canvas) == []


def test_revising_a_decision_changes_the_indicator(tmp_path: Path) -> None:
    session = _make_session(tmp_path)
    session.decide("keep")
    canvas = RecordingCanvas()
    fake = _make_strip(session, canvas)
    _draw(fake)
    assert [badge["text"] for badge in _staged_badges(canvas)] == ["K"]

    session.revise_staged_decision("a", "nah")
    _draw(fake)

    assert [badge["text"] for badge in _staged_badges(canvas)] == ["N"]


def test_the_indicator_is_drawn_on_the_photo_group_that_was_decided(tmp_path: Path) -> None:
    session = _make_session(tmp_path)
    session.set_active_index(0)
    session.decide("keep")
    session.set_active_index(1)
    session.decide("nah")
    canvas = RecordingCanvas()
    fake = _make_strip(session, canvas)

    _draw(fake)

    first, second = _staged_badges(canvas)
    assert second["x"] - first["x"] == pytest.approx(fake.thumbnail_pitch)


def test_the_best_shot_badge_and_the_selection_indicator_still_render(tmp_path: Path) -> None:
    session = _make_session(tmp_path)
    session.decide("keep")
    canvas = RecordingCanvas()
    fake = _make_strip(session, canvas)
    # The same Photo Group carries the Staged Decision and the Best Shot badge.
    fake.best_shots = {session.queue[0].representative}

    _draw(fake)

    stars = [item for item in canvas.texts if item.get("text") == "★"]
    assert len(stars) == 1
    assert "best-shot-badge" in stars[0]["tags"]
    badges = _staged_badges(canvas)
    assert len(badges) == 1
    # Both sit on the same thumbnail, at opposite corners.
    assert stars[0]["x"] > badges[0]["x"]
    markers = [line for line in canvas.lines if "thumbnail-marker" in line.get("tags", ())]
    assert len(markers) == 3
    visible = [line for line in markers if line.get("state") == "normal"]
    assert len(visible) == 1
