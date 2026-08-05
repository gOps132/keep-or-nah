from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Protocol

from photo_groups import discover_extensions
from photo_session import (
    EMPTY_EXTENSION_SELECTION_MESSAGE,
    PhotoSession,
    PhotoSessionError,
)
from session_startup import preview_paths_for


EMPTY_SELECTION_MESSAGE = EMPTY_EXTENSION_SELECTION_MESSAGE


class ViewFilterError(RuntimeError):
    """A settings error that should be shown without closing the dialog."""


@dataclass(frozen=True)
class ExtensionFilterModel:
    options: tuple[str, ...]
    selected: frozenset[str]

    @classmethod
    def from_session(cls, session: PhotoSession) -> ExtensionFilterModel:
        return cls(
            tuple(sorted(session.available_extensions)),
            frozenset(session.enabled_extensions),
        )


def validate_extension_selection(extensions: Iterable[str]) -> frozenset[str]:
    selected = frozenset(extensions)
    if not selected:
        raise ValueError(EMPTY_SELECTION_MESSAGE)
    return selected


def selected_extensions(variables: Mapping[str, object]) -> frozenset[str]:
    return frozenset(
        extension for extension, variable in variables.items() if variable.get()
    )


class ExtensionFilterApp(Protocol):
    session: PhotoSession


def apply_extension_filter(app: ExtensionFilterApp, extensions: Iterable[str]) -> int:
    selected = validate_extension_selection(extensions)
    source_dir = app.session.source_dir
    if source_dir is None:
        raise ViewFilterError("Choose a source folder before loading photos.")
    try:
        available = set(discover_extensions(source_dir))
    except OSError as error:
        raise ViewFilterError(str(error)) from error
    effective = {extension.lower() for extension in selected} & available
    if not effective:
        raise ViewFilterError(EMPTY_SELECTION_MESSAGE)

    count = app.session.apply_extension_filter(effective)
    paths = preview_paths_for(app.session)
    app.preview_pipeline.reset(paths)
    app.preview_texture_cache.clear()
    app.thumbnail_cache.clear()
    app.thumbnail_refs = []
    app.thumbnail_signature = ()
    app.rendered_thumbnail_range = (-1, -1)
    app.rendered_active_index = None
    app.preview_source_path = None
    app.preview_source_image = None
    app.reset_zoom_state()
    app.reset_preview_request_state()
    app.persist_session()
    app.refresh_ui()
    app.refresh_preview()
    return count


def save_view_filter_settings(
    app: ExtensionFilterApp,
    settings,
    extensions: Iterable[str] | None,
    show_error,
) -> bool:
    try:
        if extensions is not None:
            apply_extension_filter(app, extensions)
    except (ViewFilterError, PhotoSessionError, OSError) as error:
        show_error("Keep or Nah", str(error))
        return False
    app.apply_preview_settings(settings)
    return True


def unavailable_preview_message(path: Path) -> str:
    return f"Preview not available\n{path.name}\n{path.suffix}"


def empty_preview_message(session: PhotoSession) -> str:
    if getattr(session, "pending_count", 0):
        return "No Photo\nNo pending photos match the extension filter."
    return "Done" if session.total_loaded else "No Photo"
