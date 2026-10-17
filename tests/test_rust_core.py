from __future__ import annotations

from pathlib import Path
import tempfile
import time
import unittest

from PIL import Image

import keep_or_nah_core


class RustCoreTests(unittest.TestCase):
    def test_version_string(self) -> None:
        version = keep_or_nah_core.version()
        self.assertIsInstance(version, str)
        self.assertTrue(len(version) > 0)

    def test_load_and_orient_rgba_image(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "test.png"
            Image.new("RGBA", (30, 20), (255, 0, 0, 255)).save(path)

            raw = keep_or_nah_core.load_image_rgba(str(path))
            self.assertEqual(raw.width, 30)
            self.assertEqual(raw.height, 20)
            self.assertEqual(len(raw.data), 30 * 20 * 4)

    def test_load_applies_exif_orientation_transposition(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "oriented.jpg"
            exif = Image.Exif()
            exif[274] = 6  # Rotate 90 CW: 20x30 becomes 30x20
            Image.new("RGB", (20, 30), (0, 255, 0)).save(path, exif=exif)

            raw = keep_or_nah_core.load_image_rgba(str(path))
            self.assertEqual(raw.width, 30)
            self.assertEqual(raw.height, 20)
            self.assertEqual(len(raw.data), 30 * 20 * 4)

    def test_resize_image_rgba_fast_and_full(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "test.png"
            Image.new("RGBA", (400, 200), (0, 0, 255, 255)).save(path)
            raw = keep_or_nah_core.load_image_rgba(str(path))

            # Viewport 100x100 -> aspect ratio preserves 400x200 to 100x50
            fast = keep_or_nah_core.resize_image_rgba(
                raw.data, raw.width, raw.height, 100, 100, "fast"
            )
            self.assertEqual((fast.width, fast.height), (100, 50))
            self.assertEqual(len(fast.data), 100 * 50 * 4)

            full = keep_or_nah_core.resize_image_rgba(
                raw.data, raw.width, raw.height, 100, 100, "full"
            )
            self.assertEqual((full.width, full.height), (100, 50))
            self.assertEqual(len(full.data), 100 * 50 * 4)

    def test_rust_preview_pipeline_lifecycle_and_prefetch(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            temp_dir = Path(temp)
            p1 = temp_dir / "img1.png"
            p2 = temp_dir / "img2.png"
            Image.new("RGBA", (200, 200), (255, 0, 0, 255)).save(p1)
            Image.new("RGBA", (200, 200), (0, 255, 0, 255)).save(p2)

            pipeline = keep_or_nah_core.RustPreviewPipeline(
                window_radius=2, cache_budget_mb=128, max_workers=2
            )
            try:
                pipeline.reset([str(p1), str(p2)])
                pipeline.set_viewport(100, 100)

                req_id = pipeline.start_preview_request(str(p1), active_index=0, progressive=True)
                self.assertGreaterEqual(req_id, 1)

                deadline = time.monotonic() + 2.0
                best = None
                while time.monotonic() < deadline:
                    best = pipeline.get_best_preview(str(p1))
                    if best.data is not None and best.stage == "full":
                        break
                    time.sleep(0.02)

                self.assertIsNotNone(best)
                self.assertIsNotNone(best.data)
                self.assertEqual(best.stage, "full")
                self.assertEqual((best.width, best.height), (100, 100))
                self.assertFalse(best.failed)
                self.assertFalse(best.unavailable)

                # Check cached source
                self.assertTrue(pipeline.has_source(str(p1)))
                cached_src = pipeline.get_cached_source(str(p1))
                self.assertIsNotNone(cached_src)
                self.assertEqual((cached_src.width, cached_src.height), (200, 200))

                # Prefetch should also have processed p2
                deadline = time.monotonic() + 2.0
                while time.monotonic() < deadline:
                    if pipeline.has_source(str(p2)):
                        break
                    time.sleep(0.02)
                self.assertTrue(pipeline.has_source(str(p2)))

                # Drain completions
                events = pipeline.drain_completed()
                self.assertTrue(len(events) > 0)
                stages = [e.stage for e in events]
                self.assertIn("source", stages)
            finally:
                pipeline.shutdown()

    def test_unsupported_extension_handling(self) -> None:
        pipeline = keep_or_nah_core.RustPreviewPipeline(1, 64)
        try:
            bad_path = "photo.raw_mystery"
            pipeline.reset([bad_path])
            pipeline.set_viewport(100, 100)
            pipeline.start_preview_request(bad_path, 0, True)

            deadline = time.monotonic() + 1.0
            completed = []
            while time.monotonic() < deadline:
                completed.extend(pipeline.drain_completed())
                if completed:
                    break
                time.sleep(0.02)

            lookup = pipeline.get_best_preview(bad_path)
            self.assertTrue(lookup.unavailable)
            self.assertFalse(lookup.failed)
            self.assertIsNone(lookup.data)
        finally:
            pipeline.shutdown()


if __name__ == "__main__":
    unittest.main()
