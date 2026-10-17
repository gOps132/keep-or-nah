from __future__ import annotations

from pathlib import Path
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PIL import Image

from gui_app import App
from preview_pipeline import PreviewPipeline
from preview_pipeline import PreviewLookup
from preview_strategies import (
    PillowPreviewStrategy,
    PreviewStrategyRegistry,
    UnavailablePreviewStrategy,
)
from photo_session import PhotoSession, pillow_previewable_extensions


class PreviewStrategyRegistryTests(unittest.TestCase):
    def test_pillow_extensions_require_an_installed_open_handler(self) -> None:
        with (
            patch("photo_session.Image.init"),
            patch(
                "photo_session.Image.registered_extensions",
                return_value={".jpg": "JPEG", ".heic": "HEIF"},
            ),
            patch.dict("photo_session.Image.OPEN", {"JPEG": object()}, clear=True),
        ):
            self.assertEqual(pillow_previewable_extensions(), frozenset({".jpg"}))

    def test_session_prefers_runtime_previewable_jpg_over_unavailable_heic(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp)
            jpg = source / "A.jpg"
            heic = source / "A.heic"
            jpg.write_bytes(b"jpg")
            heic.write_bytes(b"heic")

            session = PhotoSession(previewable_extensions={".jpg"})
            session.set_source_dir(source)
            session.load_queue()

            self.assertEqual(session.active_photo, jpg)
            self.assertEqual(session.active_group.members, (heic, jpg))

    def test_runtime_unsupported_heic_uses_unavailable_strategy(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp)
            heic = source / "A.heic"
            heic.write_bytes(b"heic")
            session = PhotoSession(previewable_extensions=set())
            session.set_source_dir(source)
            session.load_queue()
            registry = PreviewStrategyRegistry(
                [PillowPreviewStrategy(extensions={".jpg"})]
            )

            self.assertEqual(session.active_photo, heic)
            self.assertIsInstance(registry.for_path(heic), UnavailablePreviewStrategy)

    def test_registry_selects_pillow_or_unavailable_case_insensitively(self) -> None:
        registry = PreviewStrategyRegistry([PillowPreviewStrategy()])

        self.assertTrue(registry.supports_extension(".JPG"))
        self.assertFalse(registry.supports_extension(".cr3"))
        self.assertIsInstance(registry.for_path(Path("A.JPG")), PillowPreviewStrategy)
        self.assertIsInstance(registry.for_path(Path("A.cr3")), UnavailablePreviewStrategy)

    def test_pillow_strategy_transposes_exif_and_converts_to_rgba(self) -> None:
        path = Path(self._testMethodName).with_suffix(".jpg")
        self.addCleanup(path.unlink, missing_ok=True)
        exif = Image.Exif()
        exif[274] = 6
        Image.new("L", (2, 3), 128).save(path, exif=exif)

        image = PillowPreviewStrategy().load(path)

        self.assertEqual(image.mode, "RGBA")
        self.assertEqual(image.size, (3, 2))

    def test_pillow_strategy_preserves_transparent_png_alpha(self) -> None:
        path = Path(self._testMethodName).with_suffix(".png")
        self.addCleanup(path.unlink, missing_ok=True)
        Image.new("RGBA", (2, 3), (255, 0, 0, 128)).save(path)

        image = PillowPreviewStrategy().load(path)

        self.assertEqual(image.mode, "RGBA")
        self.assertEqual(image.getpixel((0, 0))[3], 128)


class PreviewPipelineUnavailableTests(unittest.TestCase):
    def test_unsupported_path_completes_as_unavailable_not_error(self) -> None:
        pipeline = PreviewPipeline(max_workers=1)
        path = Path("unsupported.cr3")
        try:
            pipeline.reset([path])
            pipeline.set_viewport(100, 100)
            request_id = pipeline.start_preview_request(path, active_index=0)

            completed = self._wait_for_completion(pipeline)
            lookup = pipeline.get_best_preview(path)

            self.assertIn(
                (path, request_id, "unavailable"),
                [(event.path, event.request_id, event.stage) for event in completed],
            )
            self.assertTrue(lookup.unavailable)
            self.assertFalse(lookup.failed)
            self.assertIsNone(lookup.image)
        finally:
            pipeline.shutdown()

    def _wait_for_completion(self, pipeline: PreviewPipeline):
        deadline = time.monotonic() + 1
        completed = []
        while time.monotonic() < deadline:
            completed.extend(pipeline.drain_completed())
            if completed:
                return completed
            time.sleep(0.01)
        self.fail("Preview pipeline did not report a completion")

    def test_reset_discards_in_flight_cache_writes_and_completion_from_old_generation(self) -> None:
        entered = threading.Event()
        release = threading.Event()

        class BlockingStrategy:
            extensions = frozenset({".slow"})

            def load(self, _path):
                entered.set()
                release.wait(timeout=1)
                return Image.new("RGBA", (20, 20), "red")

        old_path = Path("old.slow")
        new_path = Path("new.slow")
        registry = PreviewStrategyRegistry([BlockingStrategy()])
        pipeline = PreviewPipeline(max_workers=1, preview_registry=registry)
        try:
            pipeline.reset([old_path])
            pipeline.set_viewport(100, 100)
            pipeline.start_preview_request(old_path, active_index=0)
            self.assertTrue(entered.wait(timeout=1))

            pipeline.reset([new_path])
            release.set()
            deadline = time.monotonic() + 1
            while time.monotonic() < deadline and pipeline._pending_keys:
                time.sleep(0.01)

            self.assertFalse(pipeline.has_source(old_path))
            self.assertIsNone(pipeline.get_best_preview(old_path).image)
            self.assertNotIn(old_path, [event.path for event in pipeline.drain_completed()])
        finally:
            release.set()
            pipeline.shutdown()


class UnavailablePreviewFrontendTests(unittest.TestCase):
    def test_both_frontends_stop_requesting_unavailable_previews(self) -> None:
        path = Path("A.cr3")
        pipeline = SimpleNamespace(
            get_best_preview=lambda _path: PreviewLookup(None, None, unavailable=True),
            has_source=lambda _path: False,
        )

        for frontend in (App,):
            for zoom_factor in (1.0, 2.0):
                with self.subTest(frontend=frontend.__name__, zoom_factor=zoom_factor):
                    fake = SimpleNamespace(zoom_factor=zoom_factor, preview_pipeline=pipeline)
                    self.assertFalse(frontend.preview_request_needs_more_work(fake, path))

    def test_both_frontends_render_unavailable_message_in_fit_and_zoom_modes(self) -> None:
        path = Path("A.cr3")
        for frontend in (App,):
            for preserve_view in (False, True):
                with self.subTest(frontend=frontend.__name__, preserve_view=preserve_view):
                    fake = self._refresh_fake(path, preserve_view)

                    frontend.refresh_preview(fake, preserve_view=preserve_view)

                    fake.hide_loading_overlay.assert_called_once_with()
                    fake.clear_preview.assert_called_once_with(
                        "Preview not available\nA.cr3\n.cr3"
                    )
                    fake.schedule_preview_poll.assert_not_called()
                    fake.schedule_loading_overlay_delay.assert_not_called()

    @staticmethod
    def _refresh_fake(path: Path, preserve_view: bool) -> SimpleNamespace:
        mode = "zoom" if preserve_view else "fit"
        pipeline = SimpleNamespace(
            set_viewport=Mock(),
            get_best_preview=lambda _path: PreviewLookup(None, None, unavailable=True),
            has_source=lambda _path: False,
        )
        return SimpleNamespace(
            preview_refresh_job="pending",
            session=SimpleNamespace(active_photo=path, active_index=0),
            preview_canvas=SimpleNamespace(winfo_width=lambda: 100, winfo_height=lambda: 100),
            preview_pipeline=pipeline,
            get_view_center=lambda: (0.5, 0.5),
            zoom_factor=2.0 if preserve_view else 1.0,
            settings=SimpleNamespace(progressive_preview=True),
            preview_request_key=(path, 100, 100, mode, True),
            preview_source_path=None,
            preview_source_image=None,
            hide_loading_overlay=Mock(),
            clear_preview=Mock(),
            schedule_preview_poll=Mock(),
            schedule_loading_overlay_delay=Mock(),
        )


if __name__ == "__main__":
    unittest.main()
