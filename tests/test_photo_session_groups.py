import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from photo_groups import PhotoGroup
from photo_session import PhotoSession, PhotoSessionError
from session_startup import initialize_gui_session


class PhotoSessionGroupTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.source = self.root / "source"
        self.keep = self.root / "keep"
        self.nah = self.root / "nah"
        self.source.mkdir()

    def tearDown(self):
        self.temporary_directory.cleanup()

    def make_session(self, *, action_mode="move"):
        session = PhotoSession()
        session.set_source_dir(self.source)
        session.set_keep_dir(self.keep)
        session.set_nah_dir(self.nah)
        session.set_action_mode(action_mode)
        return session

    def write(self, name, contents=b"data"):
        path = self.source / name
        path.write_bytes(contents)
        return path

    def test_load_groups_same_stem_and_enables_every_discovered_extension(self):
        raw = self.write("IMG.cr3", b"raw")
        jpg = self.write("IMG.jpg", b"jpg")
        other = self.write("OTHER.xmp", b"metadata")
        session = self.make_session()

        loaded = session.load_queue()

        self.assertEqual(loaded, 2)
        self.assertEqual(session.available_extensions, (".cr3", ".jpg", ".xmp"))
        self.assertEqual(session.enabled_extensions, {".cr3", ".jpg", ".xmp"})
        self.assertEqual(session.queue, [
            PhotoGroup("IMG", (raw, jpg), jpg),
            PhotoGroup("OTHER", (other,), other),
        ])
        self.assertEqual(session.active_group, session.queue[0])
        self.assertEqual(session.active_photo, jpg)

    def test_filter_preserves_active_stem_or_uses_nearest_earlier_group(self):
        self.write("A.jpg")
        self.write("B.jpg")
        c = self.write("C.png")
        self.write("D.jpg")
        session = self.make_session()
        session.load_queue()
        session.set_active_index(1)

        session.apply_extension_filter({".png"})
        self.assertEqual(session.active_group.stem, "C")
        self.assertEqual(session.active_photo, c)

        session.apply_extension_filter({".jpg", ".png"})
        session.set_active_index(2)
        session.apply_extension_filter({".jpg"})
        self.assertEqual(session.active_group.stem, "B")

    def test_reloading_same_source_preserves_filter_but_new_source_enables_all(self):
        self.write("A.jpg")
        self.write("B.png")
        session = self.make_session()
        session.load_queue()
        session.apply_extension_filter({".jpg"})

        session.load_queue()
        self.assertEqual(session.enabled_extensions, {".jpg"})

        new_source = self.root / "new-source"
        new_source.mkdir()
        (new_source / "C.cr3").write_bytes(b"raw")
        (new_source / "C.xmp").write_bytes(b"metadata")
        session.set_source_dir(new_source)
        session.load_queue()
        self.assertEqual(session.enabled_extensions, {".cr3", ".xmp"})

    def test_move_group_uses_one_collision_suffix_and_undoes_every_member(self):
        raw = self.write("IMG.cr3", b"raw")
        jpg = self.write("IMG.jpg", b"jpg")
        self.keep.mkdir()
        (self.keep / "IMG.jpg").write_bytes(b"occupied")
        session = self.make_session()
        session.load_queue()

        result = session.decide("keep")

        self.assertEqual([item.destination.name for item in result.files], [
            "IMG (1).cr3", "IMG (1).jpg",
        ])
        self.assertEqual(result.group.members, (raw, jpg))
        self.assertFalse(any(path.exists() for path in result.group.members))
        self.assertEqual(session.keep_count, 1)
        self.assertEqual(session.remaining_count, 0)

        undo = session.undo()

        self.assertEqual(undo.group, result.group)
        self.assertTrue(all(path.exists() for path in result.group.members))
        self.assertFalse(any(item.destination.exists() for item in result.files))
        self.assertEqual(session.queue, [result.group])
        self.assertEqual(session.keep_count, 0)

    def test_copy_group_uses_shared_suffix_when_only_one_member_collides(self):
        self.write("IMG.cr3", b"raw")
        self.write("IMG.jpg", b"jpg")
        self.keep.mkdir()
        (self.keep / "IMG.cr3").write_bytes(b"occupied")
        session = self.make_session(action_mode="copy")
        session.load_queue()

        result = session.decide("keep")

        self.assertEqual([item.destination.name for item in result.files], [
            "IMG (1).cr3", "IMG (1).jpg",
        ])
        self.assertTrue(all(item.source.exists() for item in result.files))
        self.assertTrue(all(item.destination.exists() for item in result.files))

    def test_failed_group_copy_rolls_back_completed_members(self):
        self.write("IMG.cr3", b"raw")
        self.write("IMG.jpg", b"jpg")
        session = self.make_session(action_mode="copy")
        session.load_queue()
        real_copy = shutil.copy2
        calls = 0

        def fail_second(source, destination):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("disk full")
            return real_copy(source, destination)

        with patch("photo_session.shutil.copy2", side_effect=fail_second):
            with self.assertRaisesRegex(PhotoSessionError, "disk full"):
                session.decide("keep")

        self.assertEqual(list(self.keep.iterdir()), [])
        self.assertEqual(session.remaining_count, 1)
        self.assertEqual(session.keep_count, 0)
        self.assertFalse(session.can_undo)

    def test_failed_group_move_rolls_back_completed_members(self):
        raw = self.write("IMG.cr3", b"raw")
        jpg = self.write("IMG.jpg", b"jpg")
        session = self.make_session()
        session.load_queue()
        real_move = shutil.move
        calls = 0

        def fail_second(source, destination):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("device error")
            return real_move(source, destination)

        with patch("photo_session.shutil.move", side_effect=fail_second):
            with self.assertRaisesRegex(PhotoSessionError, "device error"):
                session.decide("keep")

        self.assertTrue(raw.exists())
        self.assertTrue(jpg.exists())
        self.assertEqual(list(self.keep.iterdir()), [])
        self.assertEqual(session.remaining_count, 1)

    def test_failure_reports_primary_and_rollback_errors(self):
        self.write("IMG.cr3")
        self.write("IMG.jpg")
        session = self.make_session(action_mode="copy")
        session.load_queue()
        real_copy = shutil.copy2
        calls = 0

        def fail_second(source, destination):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("primary failure")
            return real_copy(source, destination)

        with patch("photo_session.shutil.copy2", side_effect=fail_second), patch(
            "photo_session.Path.unlink", side_effect=OSError("rollback failure")
        ):
            with self.assertRaises(PhotoSessionError) as raised:
                session.decide("keep")

        self.assertIn("primary failure", str(raised.exception))
        self.assertIn("rollback failure", str(raised.exception))

    def test_missing_members_are_pruned_before_a_group_decision(self):
        raw = self.write("IMG.cr3", b"raw")
        jpg = self.write("IMG.jpg", b"jpg")
        session = self.make_session(action_mode="copy")
        session.load_queue()
        raw.unlink()

        result = session.decide("nah")

        self.assertEqual([item.source for item in result.files], [jpg])
        self.assertEqual(result.group.members, (jpg,))
        self.assertEqual(session.nah_count, 1)

    def test_startup_projects_group_queue_to_representative_paths(self):
        jpg = self.write("IMG.jpg")
        self.write("IMG.xmp")
        session = self.make_session()
        session.load_queue()

        class Pipeline:
            queue = None

            def reset(self, queue):
                self.queue = queue

        class App:
            restored_startup_session = True
            last_browsed_dir = None
            preview_pipeline = Pipeline()

            def __init__(self, current_session):
                self.session = current_session

            def refresh_ui(self):
                pass

            def refresh_preview(self):
                pass

        app = App(session)

        initialize_gui_session(app)

        self.assertEqual(app.preview_pipeline.queue, (jpg,))
        self.assertTrue(all(isinstance(path, Path) for path in app.preview_pipeline.queue))


if __name__ == "__main__":
    unittest.main()
