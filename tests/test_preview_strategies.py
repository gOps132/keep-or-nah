from __future__ import annotations

from pathlib import Path
import time
import unittest

from PIL import Image

from preview_pipeline import PreviewPipeline
from preview_strategies import (
    PillowPreviewStrategy,
    PreviewStrategyRegistry,
    UnavailablePreviewStrategy,
)


class PreviewStrategyRegistryTests(unittest.TestCase):
    def test_registry_selects_pillow_or_unavailable_case_insensitively(self) -> None:
        registry = PreviewStrategyRegistry([PillowPreviewStrategy()])

        self.assertTrue(registry.supports_extension(".JPG"))
        self.assertFalse(registry.supports_extension(".cr3"))
        self.assertIsInstance(registry.for_path(Path("A.JPG")), PillowPreviewStrategy)
        self.assertIsInstance(registry.for_path(Path("A.cr3")), UnavailablePreviewStrategy)

    def test_pillow_strategy_transposes_exif_and_converts_to_rgb(self) -> None:
        path = Path(self._testMethodName).with_suffix(".jpg")
        self.addCleanup(path.unlink, missing_ok=True)
        exif = Image.Exif()
        exif[274] = 6
        Image.new("L", (2, 3), 128).save(path, exif=exif)

        image = PillowPreviewStrategy().load(path)

        self.assertEqual(image.mode, "RGB")
        self.assertEqual(image.size, (3, 2))


class PreviewPipelineUnavailableTests(unittest.TestCase):
    def test_unsupported_path_completes_as_unavailable_not_error(self) -> None:
        pipeline = PreviewPipeline(max_workers=1)
        path = Path("unsupported.cr3")
        try:
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


if __name__ == "__main__":
    unittest.main()
