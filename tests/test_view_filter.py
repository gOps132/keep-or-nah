from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock

from classic_gui import ClassicApp
from gui_app import App
from photo_session import PhotoSession
from view_filter import (
    EMPTY_SELECTION_MESSAGE,
    ExtensionFilterModel,
    apply_extension_filter,
    selected_extensions,
    unavailable_preview_message,
    validate_extension_selection,
)


class ExtensionFilterModelTests(unittest.TestCase):
    def test_model_lists_discovered_extensions_and_current_selection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            for name in ("IMG.cr3", "IMG.jpg", "IMG.xmp"):
                (source / name).write_bytes(b"data")
            session = PhotoSession()
            session.set_source_dir(source)
            session.load_queue()

            model = ExtensionFilterModel.from_session(session)

        self.assertEqual(model.options, (".cr3", ".jpg", ".xmp"))
        self.assertEqual(model.selected, frozenset({".cr3", ".jpg", ".xmp"}))

    def test_empty_selection_is_rejected_with_settings_message(self) -> None:
        with self.assertRaisesRegex(ValueError, f"^{EMPTY_SELECTION_MESSAGE}$"):
            validate_extension_selection(set())

    def test_settings_selection_reads_only_checked_discovered_options(self) -> None:
        variables = {
            ".cr3": SimpleNamespace(get=lambda: True),
            ".jpg": SimpleNamespace(get=lambda: False),
            ".xmp": SimpleNamespace(get=lambda: True),
        }

        self.assertEqual(selected_extensions(variables), frozenset({".cr3", ".xmp"}))


class ViewFilterApplicationTests(unittest.TestCase):
    def test_shared_coordinator_applies_filter_resets_and_refreshes(self) -> None:
        session = SimpleNamespace(
            preview_paths=(Path("IMG.cr3"),),
            apply_extension_filter=Mock(return_value=1),
        )
        app = SimpleNamespace(
            session=session,
            preview_pipeline=SimpleNamespace(reset=Mock()),
            preview_texture_cache=OrderedDict({("old",): object()}),
            thumbnail_cache=OrderedDict({Path("old.jpg"): object()}),
            thumbnail_refs=[object()],
            thumbnail_signature=(Path("old.jpg"),),
            rendered_thumbnail_range=(0, 1),
            rendered_active_index=0,
            preview_source_path=Path("old.jpg"),
            preview_source_image=object(),
            reset_zoom_state=Mock(),
            reset_preview_request_state=Mock(),
            persist_session=Mock(),
            refresh_ui=Mock(),
            refresh_preview=Mock(),
        )

        count = apply_extension_filter(app, {".cr3"})

        self.assertEqual(count, 1)
        session.apply_extension_filter.assert_called_once_with({".cr3"})
        app.preview_pipeline.reset.assert_called_once_with((Path("IMG.cr3"),))
        self.assertEqual(app.preview_texture_cache, OrderedDict())
        self.assertEqual(app.thumbnail_cache, OrderedDict())
        self.assertEqual(app.thumbnail_refs, [])
        self.assertEqual(app.thumbnail_signature, ())
        self.assertEqual(app.rendered_thumbnail_range, (-1, -1))
        self.assertIsNone(app.rendered_active_index)
        self.assertIsNone(app.preview_source_path)
        self.assertIsNone(app.preview_source_image)
        app.reset_zoom_state.assert_called_once_with()
        app.reset_preview_request_state.assert_called_once_with()
        app.persist_session.assert_called_once_with()
        app.refresh_ui.assert_called_once_with()
        app.refresh_preview.assert_called_once_with()

    def test_both_frontends_delegate_filter_application_to_shared_coordinator(self) -> None:
        for frontend in (App, ClassicApp):
            fake = SimpleNamespace()
            with self.subTest(frontend=frontend.__name__), unittest.mock.patch(
                f"{frontend.__module__}.apply_extension_filter"
            ) as coordinator:
                frontend.apply_view_filter(fake, {".jpg"})
                coordinator.assert_called_once_with(fake, {".jpg"})

    def test_both_frontends_expose_the_shared_settings_model(self) -> None:
        session = SimpleNamespace(
            available_extensions=(".cr3", ".jpg"),
            enabled_extensions={".jpg"},
        )
        for frontend in (App, ClassicApp):
            with self.subTest(frontend=frontend.__name__):
                model = frontend.extension_filter_model(SimpleNamespace(session=session))
                self.assertEqual(model.options, (".cr3", ".jpg"))
                self.assertEqual(model.selected, frozenset({".jpg"}))

    def test_both_frontends_apply_filter_persist_and_refresh_unsupported_preview(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            (source / "IMG_1.jpg").write_bytes(b"jpg")
            (source / "IMG_1.cr3").write_bytes(b"raw")

            for frontend in (App, ClassicApp):
                session = PhotoSession()
                session.set_source_dir(source)
                session.load_queue()
                preview_messages = []
                fake = SimpleNamespace(
                    session=session,
                    preview_pipeline=SimpleNamespace(reset=Mock()),
                    preview_texture_cache=OrderedDict(),
                    thumbnail_cache=OrderedDict(),
                    thumbnail_refs=[],
                    thumbnail_signature=(),
                    rendered_thumbnail_range=(-1, -1),
                    rendered_active_index=None,
                    preview_source_path=None,
                    preview_source_image=None,
                    reset_zoom_state=Mock(),
                    reset_preview_request_state=Mock(),
                    persist_session=Mock(),
                    refresh_ui=Mock(),
                    refresh_preview=lambda: preview_messages.append(
                        unavailable_preview_message(session.active_photo)
                    ),
                )

                with self.subTest(frontend=frontend.__name__):
                    frontend.apply_view_filter(fake, {".cr3"})
                    self.assertEqual(session.enabled_extensions, {".cr3"})
                    self.assertEqual(session.active_group.stem, "IMG_1")
                    self.assertEqual(session.active_photo.name, "IMG_1.cr3")
                    fake.persist_session.assert_called_once_with()
                    self.assertEqual(
                        preview_messages[-1],
                        "Preview not available\nIMG_1.cr3\n.cr3",
                    )


class UnsupportedPreviewControlTests(unittest.TestCase):
    def test_both_frontends_keep_sorting_controls_enabled_for_unsupported_path(self) -> None:
        session = SimpleNamespace(
            active_photo=Path("IMG.cr3"),
            source_dir=Path("source"),
            can_undo=False,
            total_loaded=1,
        )
        common = dict(
            session=session,
            update_selector_buttons=Mock(),
            update_action_button_visibility=Mock(),
            refresh_thumbnail_strip=Mock(),
            focus_set=Mock(),
            reset_preview_request_state=Mock(),
            clear_preview=Mock(),
        )

        custom = SimpleNamespace(
            **common,
            load_button=Mock(),
            undo_button=Mock(),
            zoom_in_button=Mock(),
            zoom_out_button=Mock(),
            zoom_fit_button=Mock(),
            keep_button=Mock(),
            nah_button=Mock(),
        )
        App.refresh_ui(custom)
        custom.keep_button.configure.assert_called_with(state="normal")
        custom.nah_button.configure.assert_called_with(state="normal")

        classic = SimpleNamespace(
            **common,
            load_button=Mock(),
            undo_button=Mock(),
            zoom_in_button=Mock(),
            zoom_out_button=Mock(),
            zoom_fit_button=Mock(),
            keep_button=Mock(),
            nah_button=Mock(),
        )
        ClassicApp.refresh_ui(classic)
        classic.keep_button.state.assert_called_with(["!disabled"])
        classic.nah_button.state.assert_called_with(["!disabled"])


class UnavailablePreviewMessageTests(unittest.TestCase):
    def test_message_has_clear_heading_filename_and_extension(self) -> None:
        self.assertEqual(
            unavailable_preview_message(Path("IMG_1.CR3")),
            "Preview not available\nIMG_1.CR3\n.CR3",
        )


if __name__ == "__main__":
    unittest.main()
