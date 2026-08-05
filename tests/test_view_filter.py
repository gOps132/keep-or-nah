from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock

from app_settings import AppSettings
from classic_gui import ClassicApp
from gui_app import App
from photo_session import PhotoSession
from view_filter import (
    EMPTY_SELECTION_MESSAGE,
    ExtensionFilterModel,
    ViewFilterError,
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
    def test_unexpected_filter_apply_failure_rolls_back_settings_and_session(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            (source / "A.jpg").write_bytes(b"jpg")
            (source / "B.png").write_bytes(b"png")
            session = PhotoSession()
            session.set_source_dir(source)
            session.load_queue()
            old_settings = AppSettings(True, True, 256)
            new_settings = AppSettings(False, False, 128)
            fake = SimpleNamespace(
                session=session,
                settings=old_settings,
                preview_pipeline=SimpleNamespace(
                    reset=Mock(side_effect=RuntimeError("pipeline reset failed")),
                    configure_cache_budget=Mock(),
                ),
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
                refresh_preview=Mock(),
                prune_preview_texture_cache=Mock(),
            )
            fake.apply_preview_settings = lambda settings, **kwargs: App.apply_preview_settings(
                fake,
                settings,
                **kwargs,
            )
            old_queue = list(session.queue)
            show_error = Mock()

            with unittest.mock.patch.object(AppSettings, "save"):
                saved = App.save_settings_changes(
                    fake,
                    new_settings,
                    {".jpg"},
                    show_error,
                )

            self.assertFalse(saved)
            show_error.assert_called_once_with("Keep or Nah", "pipeline reset failed")
            self.assertIs(fake.settings, old_settings)
            self.assertEqual(session.enabled_extensions, {".jpg", ".png"})
            self.assertEqual(session.queue, old_queue)

    def test_both_frontend_settings_saves_are_atomic_when_settings_write_fails(self) -> None:
        for frontend in (App, ClassicApp):
            with tempfile.TemporaryDirectory() as directory:
                source = Path(directory)
                (source / "A.jpg").write_bytes(b"jpg")
                (source / "B.png").write_bytes(b"png")
                session = PhotoSession()
                session.set_source_dir(source)
                session.load_queue()
                old_settings = AppSettings(True, True, 256)
                new_settings = AppSettings(False, False, 128)
                show_error = Mock()
                fake = SimpleNamespace(
                    session=session,
                    settings=old_settings,
                    preview_pipeline=SimpleNamespace(
                        reset=Mock(),
                        configure_cache_budget=Mock(),
                    ),
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
                    prune_preview_texture_cache=Mock(),
                )
                fake.apply_preview_settings = lambda settings, **kwargs: frontend.apply_preview_settings(
                    fake,
                    settings,
                    **kwargs,
                )
                old_queue = list(session.queue)

                with self.subTest(frontend=frontend.__name__), unittest.mock.patch.object(
                    AppSettings,
                    "save",
                    side_effect=OSError("settings disk full"),
                ):
                    saved = frontend.save_settings_changes(
                        fake,
                        new_settings,
                        {".jpg"},
                        show_error,
                    )

                    self.assertFalse(saved)
                    show_error.assert_called_once_with(
                        "Keep or Nah",
                        "settings disk full",
                    )
                    self.assertIs(fake.settings, old_settings)
                    self.assertEqual(session.enabled_extensions, {".jpg", ".png"})
                    self.assertEqual(session.queue, old_queue)
                    fake.preview_pipeline.reset.assert_not_called()
                    fake.preview_pipeline.configure_cache_budget.assert_not_called()
                    fake.prune_preview_texture_cache.assert_not_called()
                    self.assertEqual(list(fake.preview_texture_cache), [("old",)])
                    self.assertEqual(list(fake.thumbnail_cache), [Path("old.jpg")])
                    fake.persist_session.assert_not_called()
                    fake.refresh_ui.assert_not_called()
                    fake.refresh_preview.assert_not_called()

    def test_source_drift_to_no_effective_selection_is_atomic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            jpg = source / "IMG.jpg"
            jpg.write_bytes(b"jpg")
            session = PhotoSession()
            session.set_source_dir(source)
            session.load_queue()
            old_queue = list(session.queue)

            jpg.unlink()
            (source / "IMG.png").write_bytes(b"png")
            app = SimpleNamespace(session=session)

            with self.assertRaisesRegex(
                ViewFilterError,
                f"^{EMPTY_SELECTION_MESSAGE}$",
            ):
                apply_extension_filter(app, {".jpg"})

            self.assertEqual(session.available_extensions, (".jpg",))
            self.assertEqual(session.enabled_extensions, {".jpg"})
            self.assertEqual(session.queue, old_queue)

    def test_shared_coordinator_applies_filter_resets_and_refreshes(self) -> None:
        session = SimpleNamespace(
            source_dir=Path.cwd(),
            preview_paths=(Path("IMG.cr3"),),
            apply_prepared_extension_filter=Mock(return_value=1),
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

        with unittest.mock.patch(
            "view_filter.discover_extensions",
            return_value=(".cr3",),
        ):
            count = apply_extension_filter(app, {".cr3"})

        self.assertEqual(count, 1)
        session.apply_prepared_extension_filter.assert_called_once_with(
            (".cr3",),
            {".cr3"},
        )
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

    def test_both_frontend_settings_saves_catch_filter_drift_before_preview_mutation(self) -> None:
        for frontend in (App, ClassicApp):
            with tempfile.TemporaryDirectory() as directory:
                source = Path(directory)
                jpg = source / "IMG.jpg"
                jpg.write_bytes(b"jpg")
                session = PhotoSession()
                session.set_source_dir(source)
                session.load_queue()
                jpg.unlink()
                (source / "IMG.png").write_bytes(b"png")
                show_error = Mock()
                fake = SimpleNamespace(
                    session=session,
                    apply_preview_settings=Mock(),
                )

                with self.subTest(frontend=frontend.__name__):
                    saved = frontend.save_settings_changes(
                        fake,
                        SimpleNamespace(),
                        {".jpg"},
                        show_error,
                    )
                    self.assertFalse(saved)
                    show_error.assert_called_once_with(
                        "Keep or Nah",
                        EMPTY_SELECTION_MESSAGE,
                    )
                    fake.apply_preview_settings.assert_not_called()

    def test_both_frontend_settings_saves_catch_missing_source(self) -> None:
        for frontend in (App, ClassicApp):
            with tempfile.TemporaryDirectory() as directory:
                source = Path(directory) / "source"
                source.mkdir()
                (source / "IMG.jpg").write_bytes(b"jpg")
                session = PhotoSession()
                session.set_source_dir(source)
                session.load_queue()
                source.rename(source.with_name("moved"))
                show_error = Mock()
                fake = SimpleNamespace(
                    session=session,
                    apply_preview_settings=Mock(),
                )

                with self.subTest(frontend=frontend.__name__):
                    saved = frontend.save_settings_changes(
                        fake,
                        SimpleNamespace(),
                        {".jpg"},
                        show_error,
                    )
                    self.assertFalse(saved)
                    self.assertIn("No such file", show_error.call_args.args[1])
                    fake.apply_preview_settings.assert_not_called()


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

    def test_both_frontends_show_filtered_empty_state_with_pending_groups(self) -> None:
        session = SimpleNamespace(
            active_photo=None,
            source_dir=Path("source"),
            can_undo=True,
            total_loaded=2,
            pending_count=1,
        )
        for frontend in (App, ClassicApp):
            fake = SimpleNamespace(
                session=session,
                update_selector_buttons=Mock(),
                update_action_button_visibility=Mock(),
                refresh_thumbnail_strip=Mock(),
                focus_set=Mock(),
                reset_preview_request_state=Mock(),
                clear_preview=Mock(),
                load_button=Mock(),
                undo_button=Mock(),
                zoom_in_button=Mock(),
                zoom_out_button=Mock(),
                zoom_fit_button=Mock(),
                keep_button=Mock(),
                nah_button=Mock(),
            )

            with self.subTest(frontend=frontend.__name__):
                frontend.refresh_ui(fake)
                fake.clear_preview.assert_called_once_with(
                    "No Photo\nNo pending photos match the extension filter."
                )


class UnavailablePreviewMessageTests(unittest.TestCase):
    def test_message_has_clear_heading_filename_and_extension(self) -> None:
        self.assertEqual(
            unavailable_preview_message(Path("IMG_1.CR3")),
            "Preview not available\nIMG_1.CR3\n.CR3",
        )


if __name__ == "__main__":
    unittest.main()
