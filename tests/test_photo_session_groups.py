import os
import stat
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

    def force_fallback(self, session):
        session._supports_rooted_dir_fd = lambda: False
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

    def test_copy_treats_dangling_destination_symlink_as_occupied(self):
        self.write("IMG.cr3", b"raw")
        self.write("IMG.jpg", b"jpg")
        self.keep.mkdir()
        outside_target = self.root / "outside" / "target.cr3"
        dangling = self.keep / "IMG.cr3"
        try:
            dangling.symlink_to(outside_target)
        except OSError:
            self.skipTest("symlinks unavailable")
        session = self.make_session(action_mode="copy")
        session.load_queue()

        result = session.decide("keep")

        self.assertEqual(
            [item.destination.name for item in result.files],
            ["IMG (1).cr3", "IMG (1).jpg"],
        )
        self.assertTrue(dangling.is_symlink())
        self.assertFalse(outside_target.exists())

    def test_copy_revalidates_each_destination_before_writing(self):
        self.write("IMG.cr3", b"raw")
        self.write("IMG.jpg", b"jpg")
        outside_target = self.root / "outside.jpg"
        outside_target.write_bytes(b"outside")
        session = self.make_session(action_mode="copy")
        session.load_queue()
        real_copy = session._copy_at_exclusive
        calls = 0

        def create_racing_symlink(*args):
            nonlocal calls
            calls += 1
            result = real_copy(*args)
            if calls == 1:
                (self.keep / "IMG.jpg").symlink_to(outside_target)
            return result

        with patch.object(
            session, "_copy_at_exclusive", side_effect=create_racing_symlink
        ):
            with self.assertRaisesRegex(PhotoSessionError, "occupied"):
                session.decide("keep")

        self.assertEqual(outside_target.read_bytes(), b"outside")
        self.assertFalse((self.keep / "IMG.cr3").exists())
        self.assertTrue((self.keep / "IMG.jpg").is_symlink())
        self.assertEqual(session.remaining_count, 1)

    def test_symlink_swap_immediately_after_validation_cannot_redirect_copy(self):
        self.write("IMG.cr3", b"raw")
        self.write("IMG.jpg", b"jpg")
        outside_target = self.root / "outside.cr3"
        outside_target.write_bytes(b"outside")
        session = self.make_session(action_mode="copy")
        session.load_queue()
        real_validate = session._validate_destination
        swapped = False

        def swap_after_validation(path, destination_root):
            nonlocal swapped
            real_validate(path, destination_root)
            if not swapped:
                swapped = True
                path.symlink_to(outside_target)

        with patch.object(
            session, "_validate_destination", side_effect=swap_after_validation
        ):
            with self.assertRaisesRegex(PhotoSessionError, "exist|occupied"):
                session.decide("keep")

        self.assertEqual(outside_target.read_bytes(), b"outside")
        self.assertTrue((self.keep / "IMG.cr3").is_symlink())
        self.assertFalse((self.keep / "IMG.jpg").exists())
        self.assertEqual(session.remaining_count, 1)

    def test_copy_uses_exclusive_fd_writer_and_preserves_content_and_metadata(self):
        raw = self.write("IMG.cr3", b"raw-content")
        jpg = self.write("IMG.jpg", b"jpg-content")
        os.chmod(raw, 0o640)
        os.chmod(jpg, 0o604)
        timestamp_ns = 1_700_000_000_123_456_000
        os.utime(raw, ns=(timestamp_ns, timestamp_ns))
        os.utime(jpg, ns=(timestamp_ns + 1_000, timestamp_ns + 1_000))
        self.keep.mkdir()
        (self.keep / "IMG.jpg").write_bytes(b"occupied")
        session = self.make_session(action_mode="copy")
        session.load_queue()

        with patch(
            "shutil.copy2",
            side_effect=AssertionError("copy2 destination path must not be used"),
        ):
            result = session.decide("keep")

        self.assertEqual(
            [item.destination.name for item in result.files],
            ["IMG (1).cr3", "IMG (1).jpg"],
        )
        for operation in result.files:
            source_stat = operation.source.stat()
            destination_stat = operation.destination.stat()
            self.assertEqual(
                operation.destination.read_bytes(), operation.source.read_bytes()
            )
            self.assertEqual(
                stat.S_IMODE(destination_stat.st_mode),
                stat.S_IMODE(source_stat.st_mode),
            )
            self.assertEqual(destination_stat.st_mtime_ns, source_stat.st_mtime_ns)

    def test_move_and_undo_do_not_use_path_based_shutil_move(self):
        raw = self.write("IMG.cr3", b"raw")
        jpg = self.write("IMG.jpg", b"jpg")
        session = self.make_session()
        session.load_queue()

        with patch(
            "shutil.move",
            side_effect=AssertionError("path-based destination move must not be used"),
        ):
            result = session.decide("keep")
            session.undo()

        self.assertTrue(raw.exists())
        self.assertTrue(jpg.exists())
        self.assertFalse(any(item.destination.exists() for item in result.files))

    def test_fallback_copy_preserves_metadata_and_shared_collision_suffix(self):
        raw = self.write("IMG.cr3", b"raw-content")
        jpg = self.write("IMG.jpg", b"jpg-content")
        os.chmod(raw, 0o640)
        os.chmod(jpg, 0o604)
        timestamp_ns = 1_700_000_000_123_456_000
        os.utime(raw, ns=(timestamp_ns, timestamp_ns))
        os.utime(jpg, ns=(timestamp_ns + 1_000, timestamp_ns + 1_000))
        self.keep.mkdir()
        (self.keep / "IMG.jpg").write_bytes(b"occupied")
        session = self.force_fallback(self.make_session(action_mode="copy"))
        session.load_queue()

        with patch("photo_session.os.supports_fd", set()), patch.object(
            session,
            "_open_directory_fd",
            side_effect=AssertionError("POSIX adapter used"),
        ):
            result = session.decide("keep")

        self.assertEqual(
            [item.destination.name for item in result.files],
            ["IMG (1).cr3", "IMG (1).jpg"],
        )
        for operation in result.files:
            source_stat = operation.source.stat()
            destination_stat = operation.destination.stat()
            self.assertEqual(
                operation.destination.read_bytes(), operation.source.read_bytes()
            )
            self.assertEqual(
                stat.S_IMODE(destination_stat.st_mode),
                stat.S_IMODE(source_stat.st_mode),
            )
            self.assertEqual(destination_stat.st_mtime_ns, source_stat.st_mtime_ns)

    def test_fallback_move_and_undo_use_atomic_publication(self):
        raw = self.write("IMG.cr3", b"raw")
        jpg = self.write("IMG.jpg", b"jpg")
        session = self.force_fallback(self.make_session())
        session.load_queue()

        with patch.object(
            session,
            "_open_directory_fd",
            side_effect=AssertionError("POSIX adapter used"),
        ):
            result = session.decide("keep")
            session.undo()

        self.assertTrue(raw.exists())
        self.assertTrue(jpg.exists())
        self.assertFalse(any(item.destination.exists() for item in result.files))

    def test_fallback_dangling_symlink_does_not_touch_outside_target(self):
        self.write("IMG.cr3", b"raw")
        self.write("IMG.jpg", b"jpg")
        self.keep.mkdir()
        outside_target = self.root / "outside" / "target.cr3"
        dangling = self.keep / "IMG.cr3"
        try:
            dangling.symlink_to(outside_target)
        except OSError:
            self.skipTest("symlinks unavailable")
        session = self.force_fallback(self.make_session(action_mode="copy"))
        session.load_queue()

        with patch.object(
            session,
            "_open_directory_fd",
            side_effect=AssertionError("POSIX adapter used"),
        ):
            result = session.decide("keep")

        self.assertEqual(
            [item.destination.name for item in result.files],
            ["IMG (1).cr3", "IMG (1).jpg"],
        )
        self.assertTrue(dangling.is_symlink())
        self.assertFalse(outside_target.exists())

    def test_fallback_publish_failure_cleans_owned_temporary_file(self):
        self.write("IMG.jpg", b"jpg")
        session = self.force_fallback(self.make_session(action_mode="copy"))
        session.load_queue()

        with patch("photo_session.os.link", side_effect=OSError("link failure")):
            with self.assertRaisesRegex(PhotoSessionError, "link failure"):
                session.decide("keep")

        self.assertEqual(list(self.keep.iterdir()), [])
        self.assertEqual(session.remaining_count, 1)

    def test_failed_group_copy_rolls_back_completed_members(self):
        self.write("IMG.cr3", b"raw")
        self.write("IMG.jpg", b"jpg")
        session = self.make_session(action_mode="copy")
        session.load_queue()
        real_copy = session._copy_at_exclusive
        calls = 0

        def fail_second(*args):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("disk full")
            return real_copy(*args)

        with patch.object(session, "_copy_at_exclusive", side_effect=fail_second):
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
        real_move = session._move_at_exclusive
        calls = 0

        def fail_second(*args):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("device error")
            return real_move(*args)

        with patch.object(session, "_move_at_exclusive", side_effect=fail_second):
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
        real_copy = session._copy_at_exclusive
        calls = 0

        def fail_second(*args):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("primary failure")
            return real_copy(*args)

        with patch.object(
            session, "_copy_at_exclusive", side_effect=fail_second
        ), patch.object(
            session, "_unlink_at", side_effect=OSError("rollback failure")
        ):
            with self.assertRaises(PhotoSessionError) as raised:
                session.decide("keep")

        self.assertIn("primary failure", str(raised.exception))
        self.assertIn("rollback failure", str(raised.exception))

    def test_failed_move_undo_rolls_forward_and_can_be_retried(self):
        raw = self.write("IMG.cr3", b"raw")
        jpg = self.write("IMG.jpg", b"jpg")
        session = self.make_session()
        session.load_queue()
        result = session.decide("keep")
        real_move = session._move_at_exclusive
        calls = 0

        def fail_second_reverse(*args):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("transient undo failure")
            return real_move(*args)

        with patch.object(
            session, "_move_at_exclusive", side_effect=fail_second_reverse
        ):
            with self.assertRaisesRegex(PhotoSessionError, "transient undo failure"):
                session.undo()

        self.assertFalse(raw.exists())
        self.assertFalse(jpg.exists())
        self.assertTrue(all(item.destination.exists() for item in result.files))
        self.assertTrue(session.can_undo)
        self.assertEqual(session.remaining_count, 0)
        self.assertEqual(session.keep_count, 1)

        session.undo()

        self.assertTrue(raw.exists())
        self.assertTrue(jpg.exists())
        self.assertFalse(session.can_undo)
        self.assertEqual(session.remaining_count, 1)
        self.assertEqual(session.keep_count, 0)

    def test_move_undo_reports_rollback_failure_and_preserves_retry_state(self):
        raw = self.write("IMG.cr3", b"raw")
        jpg = self.write("IMG.jpg", b"jpg")
        session = self.make_session()
        session.load_queue()
        session.decide("keep")
        real_move = session._move_at_exclusive
        calls = 0

        def fail_reverse_and_rollback(*args):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("undo failure")
            if calls == 3:
                raise OSError("undo rollback failure")
            return real_move(*args)

        with patch.object(
            session,
            "_move_at_exclusive",
            side_effect=fail_reverse_and_rollback,
        ):
            with self.assertRaises(PhotoSessionError) as raised:
                session.undo()

        self.assertIn("undo failure", str(raised.exception))
        self.assertIn("undo rollback failure", str(raised.exception))
        self.assertTrue(session.can_undo)
        self.assertEqual(session.remaining_count, 0)
        self.assertEqual(session.keep_count, 1)

        session.undo()

        self.assertTrue(raw.exists())
        self.assertTrue(jpg.exists())
        self.assertFalse(session.can_undo)

    def test_copy_undo_rollback_failure_preserves_retry_state(self):
        self.write("IMG.cr3", b"raw")
        self.write("IMG.jpg", b"jpg")
        session = self.make_session(action_mode="copy")
        session.load_queue()
        result = session.decide("keep")
        real_unlink = session._unlink_at
        calls = 0

        def fail_second_unlink(*args):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("copy undo failure")
            return real_unlink(*args)

        with patch.object(
            session, "_unlink_at", side_effect=fail_second_unlink
        ), patch.object(
            session,
            "_copy_at_exclusive",
            side_effect=OSError("copy rollback failure"),
        ):
            with self.assertRaises(PhotoSessionError) as raised:
                session.undo()

        self.assertIn("copy undo failure", str(raised.exception))
        self.assertIn("copy rollback failure", str(raised.exception))
        self.assertTrue(session.can_undo)
        self.assertEqual(session.remaining_count, 0)
        self.assertEqual(session.keep_count, 1)

        session.undo()

        self.assertTrue(all(item.source.exists() for item in result.files))
        self.assertFalse(any(item.destination.exists() for item in result.files))
        self.assertFalse(session.can_undo)

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
