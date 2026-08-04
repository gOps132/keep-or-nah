from pathlib import Path
import tempfile
import unittest

from photo_groups import PhotoGroup, build_photo_groups, discover_extensions


class PhotoGroupTests(unittest.TestCase):
    def test_build_groups_uses_one_item_per_exact_stem(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp)
            jpg = source / "IMG_1.jpg"
            raw = source / "IMG_1.cr3"
            other = source / "IMG_10.jpg"
            jpg.write_bytes(b"jpg")
            raw.write_bytes(b"raw")
            other.write_bytes(b"other")

            groups = build_photo_groups(source, {".jpg", ".cr3"}, {".jpg"})

            self.assertEqual(
                [(group.stem, group.members, group.representative) for group in groups],
                [
                    ("IMG_1", (raw, jpg), jpg),
                    ("IMG_10", (other,), other),
                ],
            )

    def test_groups_require_an_enabled_extension(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp)
            cr3 = source / "A.cr3"
            xmp = source / "A.xmp"
            cr3.write_bytes(b"raw")
            xmp.write_bytes(b"metadata")

            self.assertEqual(build_photo_groups(source, {".cr3"}, set())[0].representative, cr3)
            self.assertEqual(build_photo_groups(source, {".xmp"}, set())[0].representative, xmp)
            self.assertEqual(build_photo_groups(source, set(), set()), [])

    def test_extension_matching_is_case_insensitive_and_stem_matching_is_exact(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp)
            upper = source / "Photo.JPG"
            lower = source / "photo.cr3"
            upper.write_bytes(b"jpg")
            lower.write_bytes(b"raw")

            groups = build_photo_groups(source, {".jpg"}, {".JPG"})

            self.assertEqual([(group.stem, group.representative) for group in groups], [("Photo", upper)])

    def test_representative_prefers_previewable_enabled_member_then_extension_and_filename(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp)
            raw = source / "A.cr3"
            png = source / "A.png"
            jpg = source / "A.jpg"
            raw.write_bytes(b"raw")
            png.write_bytes(b"png")
            jpg.write_bytes(b"jpg")

            preferred = build_photo_groups(source, {".CR3", ".PNG", ".JPG"}, {".png"})[0]
            fallback = build_photo_groups(source, {".CR3", ".PNG", ".JPG"}, set())[0]

            self.assertEqual(preferred.representative, png)
            self.assertEqual(fallback.representative, raw)

    def test_discover_extensions_lists_nonempty_direct_file_extensions_in_order(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp)
            (source / "photo.JPG").write_bytes(b"jpg")
            (source / "sidecar.xmp").write_bytes(b"xmp")
            (source / "README").write_bytes(b"text")
            nested = source / "nested"
            nested.mkdir()
            (nested / "ignored.png").write_bytes(b"png")

            self.assertEqual(discover_extensions(source), (".jpg", ".xmp"))

    def test_groups_and_extensions_exclude_direct_child_file_symlinks(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "source"
            outside = Path(temp) / "outside.jpg"
            source.mkdir()
            (source / "photo.jpg").write_bytes(b"photo")
            outside.write_bytes(b"outside")
            alias = source / "photo.cr3"
            try:
                alias.symlink_to(outside)
            except OSError:
                self.skipTest("symlinks unavailable")

            groups = build_photo_groups(source, {".jpg", ".cr3"}, {".jpg"})

            self.assertEqual(discover_extensions(source), (".jpg",))
            self.assertEqual(groups, [PhotoGroup("photo", (source / "photo.jpg",), source / "photo.jpg")])

    def test_photo_group_is_immutable(self):
        group = PhotoGroup("A", (Path("A.jpg"),), Path("A.jpg"))

        with self.assertRaises(AttributeError):
            group.stem = "B"


if __name__ == "__main__":
    unittest.main()
