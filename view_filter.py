from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Protocol

from photo_session import PhotoSession
from session_startup import preview_paths_for


EMPTY_SELECTION_MESSAGE = "Choose at least one file extension."


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
    count = app.session.apply_extension_filter(set(selected))
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


def unavailable_preview_message(path: Path) -> str:
    return f"Preview not available\n{path.name}\n{path.suffix}"
