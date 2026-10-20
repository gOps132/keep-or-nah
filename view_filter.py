from __future__ import annotations

import contextlib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from photo_groups import PhotoGroup, build_photo_groups, discover_extensions
from photo_session import (
    EMPTY_EXTENSION_SELECTION_MESSAGE,
    SUPPORTED_IMAGE_EXTENSIONS,
    PhotoSession,
)
from session_startup import preview_paths_for

EMPTY_SELECTION_MESSAGE = EMPTY_EXTENSION_SELECTION_MESSAGE


class ViewFilterError(RuntimeError):
    """A settings error that should be shown without closing the dialog."""


@dataclass(frozen=True)
class PreparedViewFilter:
    source_identity: Path
    available_extensions: tuple[str, ...]
    enabled_extensions: frozenset[str]
    reconciled_groups: tuple[PhotoGroup, ...]


@dataclass(frozen=True)
class _SessionFilterState:
    available_extensions: tuple[str, ...]
    enabled_extensions: frozenset[str]
    pending_groups: tuple[PhotoGroup, ...]
    queue: tuple[object, ...]
    active_index: int
    total_loaded: int


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
    return frozenset(extension for extension, variable in variables.items() if variable.get())


class ExtensionFilterApp(Protocol):
    session: PhotoSession


def prepare_view_filter(
    session: PhotoSession,
    extensions: Iterable[str],
) -> PreparedViewFilter:
    selected = validate_extension_selection(extensions)
    source_dir = session.source_dir
    if source_dir is None:
        raise ViewFilterError("Choose a source folder before loading photos.")
    try:
        source_identity = source_dir.resolve(strict=True)
        discovered = discover_extensions(source_dir)
    except OSError as error:
        raise ViewFilterError(str(error)) from error
    available = set(discovered)
    effective = {extension.lower() for extension in selected} & available
    if not effective:
        raise ViewFilterError(EMPTY_SELECTION_MESSAGE)
    return PreparedViewFilter(
        source_identity,
        discovered,
        frozenset(effective),
        tuple(
            build_photo_groups(
                source_dir,
                set(discovered),
                getattr(
                    session,
                    "previewable_extensions",
                    SUPPORTED_IMAGE_EXTENSIONS,
                ),
            )
        ),
    )


def apply_prepared_view_filter(
    app: ExtensionFilterApp,
    plan: PreparedViewFilter,
) -> int:
    source_dir = app.session.source_dir
    try:
        current_identity = source_dir.resolve(strict=True) if source_dir else None
    except OSError as error:
        raise ViewFilterError(str(error)) from error
    if current_identity != plan.source_identity:
        raise ViewFilterError("The source folder changed while settings were open.")
    count = app.session.apply_prepared_extension_filter(
        plan.available_extensions,
        set(plan.enabled_extensions),
        plan.reconciled_groups,
    )
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


def apply_extension_filter(app: ExtensionFilterApp, extensions: Iterable[str]) -> int:
    return apply_prepared_view_filter(
        app,
        prepare_view_filter(app.session, extensions),
    )


def save_view_filter_settings(
    app: ExtensionFilterApp,
    settings,
    extensions: Iterable[str] | None,
    show_error,
) -> bool:
    plan = None
    old_settings = None
    try:
        if extensions is not None:
            plan = prepare_view_filter(app.session, extensions)
        old_settings = app.settings
        normalized = settings.normalized()
        normalized.save()
    except Exception as error:
        show_error("Keep or Nah", str(error))
        return False

    filter_state = _capture_filter_state(app.session) if plan is not None else None
    try:
        app.apply_preview_settings(normalized, persist=False)
        if plan is not None:
            apply_prepared_view_filter(app, plan)
        return True
    except Exception as error:
        if filter_state is not None:
            _restore_filter_state(app.session, filter_state)
        if old_settings is not None:
            app.settings = old_settings
            with contextlib.suppress(OSError):
                old_settings.save()
            with contextlib.suppress(Exception):
                app.apply_preview_settings(old_settings, persist=False)
            app.settings = old_settings
        if filter_state is not None:
            try:
                app.preview_pipeline.reset(preview_paths_for(app.session))
                app.persist_session()
                app.refresh_ui()
                app.refresh_preview()
            except Exception:
                pass
        show_error("Keep or Nah", str(error))
        return False


def _capture_filter_state(session: PhotoSession) -> _SessionFilterState:
    return _SessionFilterState(
        session.available_extensions,
        frozenset(session.enabled_extensions),
        tuple(session.pending_groups),
        tuple(session.queue),
        session.active_index,
        session.total_loaded,
    )


def _restore_filter_state(
    session: PhotoSession,
    state: _SessionFilterState,
) -> None:
    session.available_extensions = state.available_extensions
    session.enabled_extensions = set(state.enabled_extensions)
    session.pending_groups = list(state.pending_groups)
    session.queue = list(state.queue)
    session.active_index = state.active_index
    session.total_loaded = state.total_loaded


def unavailable_preview_message(path: Path) -> str:
    return f"Preview not available\n{path.name}\n{path.suffix}"


def empty_preview_message(session: PhotoSession) -> str:
    if getattr(session, "pending_count", 0):
        return "No Photo\nNo pending photos match the extension filter."
    return "Done" if session.total_loaded else "No Photo"
