"""Architecture checks for the decomposed GUI.

`gui_app.py` used to be the largest file in the repository: one class that
built the widget tree, rendered previews, drew the Thumbnail Strip, bound
the keyboard, and ran the photo session. It is now a composition root, and
the concerns live in the `ui` package.

These tests pin the properties that make that split safe:

1. Every `ui` module stays under the 500-line architecture invariant.
2. `ui` has no circular imports and no module-level dependency on
   `gui_app`, which is what would make the mixin approach unsafe.
3. `App` still exposes every method it exposed before the split.
4. The module-level names the test suite patches by name still reach the
   code that moved into the `ui` package.
"""

from __future__ import annotations

import ast
from collections import OrderedDict
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from gui_app import App

UI_PACKAGE = Path("ui")

# The public surface of `App` before the GUI was decomposed. A method may
# live in any module of the `ui` package now, but it may not disappear:
# the GUI, the tests, and `view_filter` all call these.
APP_PUBLIC_SURFACE = (
    "__init__",
    "initialize_startup_session",
    "persist_session",
    "handle_window_close",
    "destroy",
    "cancel_preview_jobs",
    "reset_preview_request_state",
    "setup_body",
    "setup_footer",
    "setup_menu",
    "toggle_staged_mode",
    "open_review_commit_modal",
    "handle_batch_committed",
    "toggle_compare_mode",
    "pick_compare_candidate",
    "toggle_action_buttons",
    "update_action_button_visibility",
    "resolve_canvas_color",
    "folder_label",
    "update_selector_buttons",
    "open_preview_settings_dialog",
    "apply_preview_settings",
    "extension_filter_model",
    "apply_view_filter",
    "save_settings_changes",
    "initialize_drag_and_drop",
    "bind_shortcuts",
    "bind_if_supported",
    "handle_undo_shortcut",
    "handle_previous_shortcut",
    "handle_next_shortcut",
    "handle_nah_shortcut",
    "handle_keep_shortcut",
    "handle_flag_shortcut",
    "handle_space_shortcut",
    "handle_delete_shortcut",
    "handle_compare_shortcut",
    "handle_compare_pick_1_shortcut",
    "handle_compare_pick_2_shortcut",
    "handle_zoom_in_shortcut",
    "handle_zoom_out_shortcut",
    "handle_zoom_reset_shortcut",
    "handle_open_preview_settings_shortcut",
    "shortcuts_enabled",
    "choose_source_folder",
    "replace_source_folder",
    "choose_keep_folder",
    "choose_nah_folder",
    "get_initial_directory",
    "handle_action_mode_change",
    "select_photo_at_index",
    "navigate_selection",
    "load_queue",
    "sort_current_photo",
    "undo_last_action",
    "reset_zoom_state",
    "zoom_in",
    "zoom_out",
    "reset_zoom",
    "set_zoom",
    "refresh_ui",
    "schedule_preview_refresh",
    "schedule_thumbnail_strip_rebuild",
    "_flush_thumbnail_strip_rebuild",
    "handle_preview_configure",
    "scale_preview_display_to_current_canvas",
    "refresh_preview_or_placeholder",
    "clear_preview",
    "get_preview_texture",
    "prune_preview_texture_cache",
    "schedule_preview_poll",
    "poll_preview_pipeline",
    "preview_request_needs_more_work",
    "schedule_loading_overlay_delay",
    "maybe_show_loading_overlay",
    "schedule_loading_animation",
    "advance_loading_animation",
    "hide_loading_overlay",
    "render_loading_overlay",
    "display_preview_image",
    "display_compare_image",
    "clear_compare_preview",
    "restore_compare_view_center",
    "refresh_compare_preview",
    "get_thumbnail_photo",
    "make_strip_photo_from_raw",
    "decode_strip_thumbnail",
    "request_missing_strip_thumbnails",
    "request_strip_thumbnail",
    "_ensure_thumbnail_worker",
    "_run_thumbnail_worker",
    "schedule_thumbnail_result_poll",
    "drain_thumbnail_results",
    "prune_strip_thumbnail_state",
    "refresh_thumbnail_strip",
    "get_thumbnail_region_width",
    "get_visible_thumbnail_range",
    "redraw_thumbnail_strip",
    "update_thumbnail_selection",
    "ensure_active_thumbnail_visible",
    "get_view_center",
    "restore_view_center",
    "refresh_preview",
    "start_pan",
    "drag_pan",
    "handle_zoom_mousewheel",
    "handle_linux_zoom_wheel",
    "handle_magnify",
    "handle_mousewheel",
    "handle_shift_mousewheel",
    "handle_linux_wheel",
    "handle_linux_shift_wheel",
    "handle_thumbnail_wheel",
    "handle_thumbnail_linux_wheel",
)


def _ui_modules() -> list[Path]:
    return sorted(UI_PACKAGE.glob("*.py"))


def _first_party_modules() -> dict[str, Path]:
    modules = {path.stem: path for path in sorted(Path().glob("*.py"))}
    modules.update({f"ui.{path.stem}": path for path in sorted(UI_PACKAGE.glob("*.py"))})
    return modules


def _first_party_import_graph() -> dict[str, set[str]]:
    """Map every first-party module to the first-party modules it imports."""
    modules = _first_party_modules()
    graph: dict[str, set[str]] = {}
    for name, path in modules.items():
        edges: set[str] = set()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in modules:
                        edges.add(alias.name)
                    elif alias.name.split(".")[0] in modules:
                        edges.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.level or not node.module:
                    continue
                if node.module in modules:
                    edges.add(node.module)
        graph[name] = edges
    return graph


def test_ui_package_exists() -> None:
    assert UI_PACKAGE.is_dir(), "Expected the `ui` package to exist"
    assert _ui_modules(), "Expected the `ui` package to hold modules"


def test_ui_modules_under_500_lines() -> None:
    for path in _ui_modules():
        lines = path.read_text(encoding="utf-8").splitlines()
        assert len(lines) < 500, f"{path} has {len(lines)} lines; must be < 500"


def test_gui_app_is_a_thin_composition_root() -> None:
    lines = Path("gui_app.py").read_text(encoding="utf-8").splitlines()
    assert len(lines) < 500, (
        f"gui_app.py has {len(lines)} lines; it must be a thin composition root"
    )

    source = Path("gui_app.py").read_text(encoding="utf-8")
    for mixin in (
        "PreviewControllerMixin",
        "CompareControllerMixin",
        "ThumbnailStripMixin",
        "ShortcutsMixin",
        "ViewportMixin",
        "LayoutMixin",
        "SettingsDialogMixin",
        "SessionCommandsMixin",
    ):
        assert mixin in source, f"gui_app.py must wire the {mixin}"


def test_ui_modules_do_not_import_gui_app_at_module_level() -> None:
    """A module-level `gui_app` import would be a cycle.

    `gui_app` imports the `ui` package, so a `ui` module that imported
    `gui_app` back at module scope would deadlock the import. The one
    sanctioned access is the lazy lookup in `ui.gui_targets`.
    """
    for path in _ui_modules():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.Import):
                assert all(alias.name != "gui_app" for alias in node.names), (
                    f"{path} imports gui_app at module level"
                )
            elif isinstance(node, ast.ImportFrom):
                assert node.module != "gui_app", f"{path} imports gui_app at module level"


@pytest.mark.parametrize("module", [path.stem for path in _ui_modules()])
def test_ui_modules_are_reachable_without_a_cycle(module: str) -> None:
    """No `ui` module may take part in an import cycle.

    A cycle would make the mixin approach unsafe: the composition root
    imports the `ui` package, so a cycle would have to be broken at import
    time rather than at call time.
    """
    graph = _first_party_import_graph()
    start = f"ui.{module}"
    assert start in graph, f"{start} is not part of the first-party import graph"

    seen: set[str] = set()
    pending = list(graph[start])
    while pending:
        current = pending.pop()
        if current == start:
            pytest.fail(f"{start} takes part in an import cycle: {sorted(graph[current])}")
        if current in seen:
            continue
        seen.add(current)
        pending.extend(graph.get(current, ()))


def test_app_public_surface_is_preserved() -> None:
    for name in APP_PUBLIC_SURFACE:
        assert callable(getattr(App, name, None)), f"App lost the method {name}"


def test_app_is_still_importable_from_gui_app() -> None:
    from gui_app import App as ImportedApp

    assert ImportedApp is App
    assert App.__name__ == "App"


def test_thumbnail_rgba_patch_reaches_the_moved_decoder() -> None:
    native_raw = SimpleNamespace(width=72, height=48, data=bytes(72 * 48 * 4))

    with patch("gui_app.thumbnail_rgba", return_value=native_raw) as native_decode:
        result = App.decode_strip_thumbnail(Path("x.jpg"))

    native_decode.assert_called_once_with("x.jpg", 72)
    assert result is native_raw


def test_image_and_image_tk_patches_reach_the_moved_thumbnail_builder() -> None:
    raw = SimpleNamespace(width=72, height=48, data=bytes(72 * 48 * 4))
    fake = SimpleNamespace(
        thumbnail_raws=OrderedDict({Path("a.jpg"): raw}),
        thumbnail_cache=OrderedDict(),
        thumbnail_cache_limit=192,
        make_strip_photo_from_raw=App.make_strip_photo_from_raw,
    )

    with (
        patch("gui_app.Image.frombytes") as frombytes,
        patch("gui_app.ImageTk.PhotoImage") as photo_image,
    ):
        photo = App.get_thumbnail_photo(fake, Path("a.jpg"))

    frombytes.assert_called_once_with("RGBA", (72, 48), raw.data)
    photo_image.assert_called_once_with(frombytes.return_value)
    assert photo is photo_image.return_value


def test_image_tk_patch_reaches_the_moved_preview_texture_cache() -> None:
    fake = SimpleNamespace(preview_texture_cache=OrderedDict(), preview_texture_cache_limit=12)

    with patch("gui_app.ImageTk.PhotoImage") as photo_image:
        texture = App.get_preview_texture(fake, ("a.jpg", "full", 10, 10), Mock())

    photo_image.assert_called_once()
    assert texture is photo_image.return_value
    assert list(fake.preview_texture_cache) == [("a.jpg", "full", 10, 10)]


def test_choose_source_directory_patch_reaches_the_moved_command() -> None:
    fake = object()

    with patch("gui_app.choose_source_directory") as coordinator:
        App.choose_source_folder(fake)

    coordinator.assert_called_once_with(fake)
