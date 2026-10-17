from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

import keep_or_nah_core
from PIL import Image

from photo_groups import (
    _python_build_photo_groups,
    _python_discover_extensions,
)
from photo_session import PhotoSession


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


GROUPING_ENABLED = {".jpg", ".cr3", ".png"}
GROUPING_PREVIEWABLE = {".jpg", ".png"}


def _make_group_fixture(source: Path) -> None:
    """Known-good fixture: sidecar stems, bursts, symlinks, nested dirs, skips."""
    for name in (
        "IMG_0001.JPG",
        "IMG_0001.cr3",
        "IMG_0001.xmp",
        "beach.png",
        "beach.jpg",
        "Photo (1).jpg",
        "photo (2).png",
        "lower.jpg",
        "archive.tar.gz",
        "dot.hidden.txt",
    ):
        (source / name).write_bytes(b"data")

    nested = source / "nested"
    nested.mkdir()
    (nested / "beach.jpg").write_bytes(b"data")
    (source / "orphan_link.png").symlink_to(source / "beach.jpg")


class RustGroupingParityTests(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.source = Path(temp.name)
        _make_group_fixture(self.source)

    def test_rust_build_photo_groups_matches_known_fixture_expectations(self) -> None:
        groups = keep_or_nah_core.build_photo_groups(
            str(self.source), GROUPING_ENABLED, GROUPING_PREVIEWABLE
        )

        observed = [
            (
                group.stem,
                tuple(Path(member).name for member in group.members),
                Path(group.representative).name,
            )
            for group in groups
        ]
        self.assertEqual(
            observed,
            [
                ("beach", ("beach.jpg", "beach.png"), "beach.jpg"),
                ("IMG_0001", ("IMG_0001.cr3", "IMG_0001.JPG", "IMG_0001.xmp"), "IMG_0001.JPG"),
                ("lower", ("lower.jpg",), "lower.jpg"),
                ("Photo (1)", ("Photo (1).jpg",), "Photo (1).jpg"),
                ("photo (2)", ("photo (2).png",), "photo (2).png"),
            ],
        )

    def test_rust_skips_ineligible_stems_links_and_nested_directories(self) -> None:
        groups = keep_or_nah_core.build_photo_groups(
            str(self.source), GROUPING_ENABLED, GROUPING_PREVIEWABLE
        )

        stems = {group.stem for group in groups}
        self.assertNotIn("archive.tar", stems)
        self.assertNotIn("dot.hidden", stems)
        self.assertNotIn("nested", stems)
        self.assertNotIn("orphan_link", stems)

    def test_rust_discover_extensions_matches_fixture(self) -> None:
        self.assertEqual(
            tuple(keep_or_nah_core.discover_photo_extensions(str(self.source))),
            (".cr3", ".gz", ".jpg", ".png", ".txt", ".xmp"),
        )

    def test_rust_grouping_is_identical_to_python_implementation(self) -> None:
        reference_groups = _python_build_photo_groups(
            self.source, GROUPING_ENABLED, GROUPING_PREVIEWABLE
        )
        rust_groups = keep_or_nah_core.build_photo_groups(
            str(self.source), GROUPING_ENABLED, GROUPING_PREVIEWABLE
        )

        self.assertEqual(
            [
                (group.stem, group.members, group.representative) for group in reference_groups
            ],
            [
                (group.stem, tuple(Path(member) for member in group.members), Path(group.representative))
                for group in rust_groups
            ],
        )

        self.assertEqual(
            tuple(keep_or_nah_core.discover_photo_extensions(str(self.source))),
            _python_discover_extensions(self.source),
        )


class RustThumbnailTests(unittest.TestCase):
    def test_thumbnail_rgba_fits_within_size_box(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "photo.png"
            Image.new("RGBA", (4000, 2000), (10, 20, 30, 255)).save(str(path))

            raw = keep_or_nah_core.thumbnail_rgba(str(path), 72)

            self.assertLessEqual(max(raw.width, raw.height), 72)
            self.assertEqual(raw.width, 72)
            self.assertEqual(raw.height, 36)
            self.assertEqual(len(raw.data), raw.width * raw.height * 4)

    def test_thumbnail_rgba_applies_exif_orientation(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "oriented.jpg"
            exif = Image.Exif()
            exif[274] = 6  # Rotate 90 CW: 20x30 becomes 30x20
            Image.new("RGB", (2000, 3000), (0, 255, 0)).save(str(path), exif=exif)

            raw = keep_or_nah_core.thumbnail_rgba(str(path), 72)

            self.assertEqual((raw.width, raw.height), (72, 48))

    def test_thumbnail_rgba_surfaces_file_errors_as_oserror(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            missing = Path(temp) / "missing.png"
            with self.assertRaises(OSError):
                keep_or_nah_core.thumbnail_rgba(str(missing), 72)


class RustFileOpsTests(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.stage = self.root / "stage"
        self.stage.mkdir()

    def write_source(self, name: str, contents: bytes) -> Path:
        path = self.root / name
        path.write_bytes(contents)
        return path

    def test_stage_regular_file_copies_content_permissions_and_timestamps(self) -> None:
        import os
        import stat

        source = self.write_source("IMG.jpg", b"raw-content")
        os.chmod(source, 0o640)
        timestamp_ns = 1_700_000_000_123_456_000
        os.utime(source, ns=(timestamp_ns, timestamp_ns))

        staged = keep_or_nah_core.stage_regular_file(str(source), str(self.stage))

        staged_path = Path(staged.path)
        self.assertEqual(staged_path.parent, self.stage)
        self.assertTrue(staged_path.name.startswith(".keep-or-nah-"))
        self.assertEqual(staged_path.read_bytes(), b"raw-content")
        staged_stat = staged_path.stat()
        self.assertEqual(
            stat.S_IMODE(staged_stat.st_mode), stat.S_IMODE(source.stat().st_mode)
        )
        self.assertEqual(staged_stat.st_mtime_ns, source.stat().st_mtime_ns)
        self.assertEqual((staged.dev, staged.ino),
                         (staged_stat.st_dev, staged_stat.st_ino))

    def test_stage_regular_file_refuses_symlink_and_directory_sources(self) -> None:
        real = self.write_source("IMG.jpg", b"raw")
        link = self.root / "IMG-link.jpg"
        try:
            link.symlink_to(real)
        except OSError:
            self.skipTest("symlinks unavailable")
        with self.assertRaises(OSError):
            keep_or_nah_core.stage_regular_file(str(link), str(self.stage))
        with self.assertRaises(OSError):
            keep_or_nah_core.stage_regular_file(str(self.root), str(self.stage))
        self.assertEqual(list(self.stage.iterdir()), [])

    def test_stage_regular_file_never_overwrites_existing_entry(self) -> None:
        source = self.write_source("IMG.jpg", b"raw")
        staged = keep_or_nah_core.stage_regular_file(str(source), str(self.stage))
        import os

        (self.stage / "occupied").write_bytes(b"o")
        with self.assertRaises(OSError):
            keep_or_nah_core.stage_regular_file(str(source), str(Path(os.devnull).parent / "nonexist"))
        self.assertTrue(Path(staged.path).exists())

    def test_remove_verified_file_deletes_matching_identity_only(self) -> None:
        path = self.write_source("IMG.jpg", b"raw")
        identity = keep_or_nah_core.file_identity(str(path))
        self.assertEqual(len(identity), 2)

        keep_or_nah_core.remove_verified_file(str(path), identity[0], identity[1])
        self.assertFalse(path.exists())

        replacement = self.root / "IMG.jpg"
        replacement.write_bytes(b"replacement")
        with self.assertRaises(OSError):
            keep_or_nah_core.remove_verified_file(
                str(replacement), identity[0], identity[1]
            )
        self.assertTrue(replacement.exists())

    def test_file_identity_refuses_symlinks_and_directories(self) -> None:
        import os

        real = self.write_source("IMG.jpg", b"raw")
        link = self.root / "IMG-link.jpg"
        try:
            link.symlink_to(real)
        except OSError:
            self.skipTest("symlinks unavailable")
        with self.assertRaises(OSError):
            keep_or_nah_core.file_identity(str(link))
        with self.assertRaises(OSError):
            keep_or_nah_core.file_identity(str(self.root))
        self.assertEqual(
            tuple(keep_or_nah_core.file_identity(str(real))),
            (os.stat(real).st_dev, os.stat(real).st_ino),
        )


class RustGroupingSessionIntegrationTests(unittest.TestCase):
    def test_photo_session_consumes_rust_grouped_entries(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        source = Path(temp.name)
        _make_group_fixture(source)

        session = PhotoSession(previewable_extensions=GROUPING_PREVIEWABLE)
        session.set_source_dir(source)
        count = session.load_queue()

        self.assertEqual(count, 7)
        self.assertEqual(
            [group.stem for group in session.pending_groups],
            ["archive.tar", "beach", "dot.hidden", "IMG_0001", "lower", "Photo (1)", "photo (2)"],
        )
        self.assertEqual(
            session.pending_groups[3].representative.name, "IMG_0001.JPG"
        )
        self.assertEqual(
            tuple(member.name for member in session.pending_groups[3].members),
            ("IMG_0001.cr3", "IMG_0001.JPG", "IMG_0001.xmp"),
        )
        self.assertEqual(session.active_photo, session.pending_groups[0].representative)


if __name__ == "__main__":
    unittest.main()
