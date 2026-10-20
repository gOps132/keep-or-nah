import errno
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import photo_session
from photo_groups import PhotoGroup
from photo_session import ActionRecord, FileOperation, PhotoSession, PhotoSessionError
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
        # Both variants now exercise the same universal path-based engine.
        return session

    def write(self, name, contents=b"data"):
        path = self.source / name
        path.write_bytes(contents)
        return path

    def assert_undo_uses_recorded_destination(self, *, action_mode, decision, force_fallback):
        case = self.root / f"{decision}-{action_mode}-{'fallback' if force_fallback else 'posix'}"
        source = case / "source"
        recorded_destination = case / "recorded-destination"
        current_destination = case / "current-destination"
        other_destination = case / "other-destination"
        source.mkdir(parents=True)
        current_destination.mkdir()
        (source / "IMG.cr3").write_bytes(b"raw")
        (source / "IMG.jpg").write_bytes(b"jpg")
        session = PhotoSession()
        session.set_source_dir(source)
        session.set_keep_dir(recorded_destination if decision == "keep" else other_destination)
        session.set_nah_dir(recorded_destination if decision == "nah" else other_destination)
        session.set_action_mode(action_mode)
        if force_fallback:
            self.force_fallback(session)
        session.load_queue()
        result = session.decide(decision)
        if decision == "keep":
            session.set_keep_dir(current_destination)
        else:
            session.set_nah_dir(current_destination)

        session.undo()

        self.assertEqual((source / "IMG.cr3").read_bytes(), b"raw")
        self.assertEqual((source / "IMG.jpg").read_bytes(), b"jpg")
        self.assertFalse(any(item.destination.exists() for item in result.files))
        self.assertEqual(list(current_destination.iterdir()), [])

    def test_posix_move_undo_uses_recorded_keep_and_nah_destination(self):
        for decision in ("keep", "nah"):
            with self.subTest(decision=decision):
                self.assert_undo_uses_recorded_destination(
                    action_mode="move", decision=decision, force_fallback=False
                )

    def test_posix_copy_undo_uses_recorded_keep_and_nah_destination(self):
        for decision in ("keep", "nah"):
            with self.subTest(decision=decision):
                self.assert_undo_uses_recorded_destination(
                    action_mode="copy", decision=decision, force_fallback=False
                )

    def test_fallback_move_undo_uses_recorded_keep_and_nah_destination(self):
        for decision in ("keep", "nah"):
            with self.subTest(decision=decision):
                self.assert_undo_uses_recorded_destination(
                    action_mode="move", decision=decision, force_fallback=True
                )

    def test_fallback_copy_undo_uses_recorded_keep_and_nah_destination(self):
        for decision in ("keep", "nah"):
            with self.subTest(decision=decision):
                self.assert_undo_uses_recorded_destination(
                    action_mode="copy", decision=decision, force_fallback=True
                )

    def test_undo_rejects_compound_record_with_mixed_destination_parents(self):
        for action_mode in ("move", "copy"):
            for force_fallback in (False, True):
                with self.subTest(action_mode=action_mode, force_fallback=force_fallback):
                    case = self.root / f"mixed-{action_mode}-{force_fallback}"
                    source = case / "source"
                    destination = case / "destination"
                    outside = case / "outside"
                    source.mkdir(parents=True)
                    outside.mkdir()
                    (source / "IMG.cr3").write_bytes(b"raw")
                    (source / "IMG.jpg").write_bytes(b"jpg")
                    session = PhotoSession()
                    session.set_source_dir(source)
                    session.set_keep_dir(destination)
                    session.set_action_mode(action_mode)
                    if force_fallback:
                        self.force_fallback(session)
                    session.load_queue()
                    result = session.decide("keep")
                    record = session.history[-1]
                    mixed_files = (
                        record.files[0],
                        FileOperation(
                            record.files[1].source,
                            outside / record.files[1].destination.name,
                            record.files[1].destination_identity,
                        ),
                    )
                    session.history[-1] = ActionRecord(
                        record.decision,
                        record.action_mode,
                        record.group,
                        mixed_files,
                        record.index,
                    )

                    with self.assertRaisesRegex(
                        PhotoSessionError, "same recorded destination folder"
                    ):
                        session.undo()

                    self.assertTrue(
                        all(operation.destination.exists() for operation in result.files)
                    )
                    self.assertEqual(list(outside.iterdir()), [])

    def test_undo_does_not_touch_unrelated_files_in_recreated_destination_root(self):
        for action_mode in ("move", "copy"):
            for force_fallback in (False, True):
                with self.subTest(action_mode=action_mode, force_fallback=force_fallback):
                    case = self.root / f"recreated-{action_mode}-{force_fallback}"
                    source = case / "source"
                    destination = case / "keep"
                    archived_destination = case / "archived-keep"
                    source.mkdir(parents=True)
                    (source / "IMG.cr3").write_bytes(b"raw")
                    (source / "IMG.jpg").write_bytes(b"jpg")
                    session = PhotoSession()
                    session.set_source_dir(source)
                    session.set_keep_dir(destination)
                    session.set_action_mode(action_mode)
                    if force_fallback:
                        self.force_fallback(session)
                    session.load_queue()
                    result = session.decide("keep")
                    self.assertTrue(
                        all(
                            getattr(operation, "destination_identity", None) is not None
                            for operation in result.files
                        )
                    )
                    destination.rename(archived_destination)
                    destination.mkdir()
                    for operation in result.files:
                        (destination / operation.destination.name).write_bytes(b"unrelated")

                    with self.assertRaisesRegex(PhotoSessionError, "identity|owned"):
                        session.undo()

                    self.assertTrue(session.can_undo)
                    for operation in result.files:
                        self.assertEqual(
                            (destination / operation.destination.name).read_bytes(),
                            b"unrelated",
                        )
                        self.assertTrue(
                            (archived_destination / operation.destination.name).exists()
                        )

    def test_posix_copy_rollback_does_not_delete_replacement_created_before_failure(self):
        self.write("IMG.cr3", b"raw")
        self.write("IMG.jpg", b"jpg")
        session = self.make_session(action_mode="copy")
        session.load_queue()
        real_copy = session._copy_path_exclusive
        calls = 0

        def replace_first_before_second_fails(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                first_destination = self.keep / "IMG.cr3"
                first_destination.unlink()
                first_destination.write_bytes(b"replacement")
                raise OSError("second copy failed")
            return real_copy(*args)

        with patch.object(
            session,
            "_copy_path_exclusive",
            side_effect=replace_first_before_second_fails,
        ):
            with self.assertRaisesRegex(PhotoSessionError, "second copy failed"):
                session.decide("keep")

        self.assertTrue((self.keep / "IMG.cr3").exists())
        self.assertEqual((self.keep / "IMG.cr3").read_bytes(), b"replacement")
        self.assertEqual(session.remaining_count, 1)

    def test_posix_copy_stages_complete_file_before_final_path_is_visible(self):
        self.write("IMG.jpg", b"jpg")
        session = self.make_session(action_mode="copy")
        session.load_queue()
        real_stage = photo_session.stage_regular_file
        observed_temporary_names = []

        def inspect_staging(*args, **kwargs):
            staged = real_stage(*args, **kwargs)
            self.assertFalse((self.keep / "IMG.jpg").exists())
            observed_temporary_names.extend(
                path.name for path in self.keep.iterdir() if path.name.startswith(".keep-or-nah-")
            )
            return staged

        with patch.object(
            photo_session,
            "stage_regular_file",
            side_effect=inspect_staging,
        ):
            try:
                session.decide("keep")
            except PhotoSessionError as error:
                self.fail(str(error))

        self.assertEqual(len(observed_temporary_names), 1)
        self.assertEqual([path.name for path in self.keep.iterdir()], ["IMG.jpg"])

    def test_windows_fallback_renames_when_hard_links_are_unsupported(self):
        for action_mode in ("move", "copy"):
            with self.subTest(action_mode=action_mode):
                case = self.root / f"windows-{action_mode}"
                source = case / "source"
                keep = case / "keep"
                source.mkdir(parents=True)
                keep.mkdir()
                (source / "IMG.cr3").write_bytes(b"raw")
                (source / "IMG.jpg").write_bytes(b"jpg")
                (keep / "IMG.jpg").write_bytes(b"occupied")
                session = PhotoSession()
                session.set_source_dir(source)
                session.set_keep_dir(keep)
                session.set_action_mode(action_mode)
                self.force_fallback(session)
                session.load_queue()

                with (
                    patch.object(
                        session,
                        "_publish_hard_link",
                        side_effect=OSError(errno.EOPNOTSUPP, "unsupported"),
                    ),
                    patch.object(
                        session,
                        "_is_windows_fallback",
                        return_value=True,
                        create=True,
                    ),
                ):
                    try:
                        result = session.decide("keep")
                    except PhotoSessionError as error:
                        self.fail(str(error))

                self.assertEqual(
                    [operation.destination.name for operation in result.files],
                    ["IMG (1).cr3", "IMG (1).jpg"],
                )
                self.assertEqual(
                    all(operation.source.exists() for operation in result.files),
                    action_mode == "copy",
                )
                self.assertTrue(all(operation.destination.exists() for operation in result.files))
                self.assertEqual((keep / "IMG.jpg").read_bytes(), b"occupied")
                self.assertFalse(
                    any(path.name.startswith(".keep-or-nah-") for path in keep.iterdir())
                )

    def test_windows_fallback_collision_keeps_racer_and_cleans_temporary(self):
        self.write("IMG.jpg", b"jpg")
        session = self.force_fallback(self.make_session(action_mode="copy"))
        session.load_queue()

        def collide(_source, destination):
            destination.write_bytes(b"racer")
            raise FileExistsError("rename collision")

        with (
            patch.object(
                session,
                "_publish_hard_link",
                side_effect=OSError(errno.EOPNOTSUPP, "unsupported"),
            ),
            patch.object(
                session,
                "_is_windows_fallback",
                return_value=True,
                create=True,
            ),
            patch("photo_session.os.rename", side_effect=collide),
        ):
            with self.assertRaisesRegex(PhotoSessionError, "rename collision"):
                session.decide("keep")

        self.assertEqual((self.keep / "IMG.jpg").read_bytes(), b"racer")
        self.assertFalse(any(path.name.startswith(".keep-or-nah-") for path in self.keep.iterdir()))

    def test_load_groups_same_stem_and_enables_every_discovered_extension(self):
        raw = self.write("IMG.cr3", b"raw")
        jpg = self.write("IMG.jpg", b"jpg")
        other = self.write("OTHER.xmp", b"metadata")
        session = self.make_session()

        loaded = session.load_queue()

        self.assertEqual(loaded, 2)
        self.assertEqual(session.available_extensions, (".cr3", ".jpg", ".xmp"))
        self.assertEqual(session.enabled_extensions, {".cr3", ".jpg", ".xmp"})
        self.assertEqual(
            session.queue,
            [
                PhotoGroup("IMG", (raw, jpg), jpg),
                PhotoGroup("OTHER", (other,), other),
            ],
        )
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

    def test_filter_reconciles_new_same_stem_companion_into_group_decision(self):
        for action_mode in ("copy", "move"):
            with self.subTest(action_mode=action_mode):
                case = self.root / action_mode
                source = case / "source"
                keep = case / "keep"
                source.mkdir(parents=True)
                keep.mkdir()
                jpg = source / "IMG.jpg"
                jpg.write_bytes(b"jpg")
                session = PhotoSession()
                session.set_source_dir(source)
                session.set_keep_dir(keep)
                session.set_action_mode(action_mode)
                session.load_queue()
                xmp = source / "IMG.xmp"
                xmp.write_bytes(b"metadata")

                session.apply_extension_filter({".xmp"})

                self.assertEqual(session.active_photo, xmp)
                self.assertEqual(session.active_group.members, (jpg, xmp))
                result = session.decide("keep")
                self.assertEqual([item.source for item in result.files], [jpg, xmp])
                self.assertTrue((keep / "IMG.jpg").is_file())
                self.assertTrue((keep / "IMG.xmp").is_file())

    def test_filter_reconciliation_adds_new_stem_but_not_completed_copy_stem(self):
        self.write("A.jpg", b"a")
        self.keep.mkdir()
        session = self.make_session(action_mode="copy")
        session.load_queue()
        session.decide("keep")
        self.write("B.jpg", b"b")

        session.apply_extension_filter({".jpg"})

        self.assertEqual(session.completed_stems, {"A"})
        self.assertEqual([group.stem for group in session.pending_groups], ["B"])
        self.assertEqual([group.stem for group in session.queue], ["B"])

    def test_undo_and_reload_clear_completed_stem_tracking(self):
        self.write("A.jpg")
        self.keep.mkdir()
        session = self.make_session(action_mode="copy")
        session.load_queue()
        session.decide("keep")

        self.assertEqual(session.completed_stems, {"A"})
        session.undo()
        self.assertEqual(session.completed_stems, set())

        session.decide("keep")
        session.load_queue()
        self.assertEqual(session.completed_stems, set())
        self.assertEqual([group.stem for group in session.queue], ["A"])

    def test_move_group_uses_one_collision_suffix_and_undoes_every_member(self):
        raw = self.write("IMG.cr3", b"raw")
        jpg = self.write("IMG.jpg", b"jpg")
        self.keep.mkdir()
        (self.keep / "IMG.jpg").write_bytes(b"occupied")
        session = self.make_session()
        session.load_queue()

        result = session.decide("keep")

        self.assertEqual(
            [item.destination.name for item in result.files],
            [
                "IMG (1).cr3",
                "IMG (1).jpg",
            ],
        )
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

        self.assertEqual(
            [item.destination.name for item in result.files],
            [
                "IMG (1).cr3",
                "IMG (1).jpg",
            ],
        )
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
        real_copy = session._copy_path_exclusive
        calls = 0

        def create_racing_symlink(*args, **kwargs):
            nonlocal calls
            calls += 1
            result = real_copy(*args)
            if calls == 1:
                (self.keep / "IMG.jpg").symlink_to(outside_target)
            return result

        with patch.object(session, "_copy_path_exclusive", side_effect=create_racing_symlink):
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

        with patch.object(session, "_validate_destination", side_effect=swap_after_validation):
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
            self.assertEqual(operation.destination.read_bytes(), operation.source.read_bytes())
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

        result = session.decide("keep")

        self.assertEqual(
            [item.destination.name for item in result.files],
            ["IMG (1).cr3", "IMG (1).jpg"],
        )
        for operation in result.files:
            source_stat = operation.source.stat()
            destination_stat = operation.destination.stat()
            self.assertEqual(operation.destination.read_bytes(), operation.source.read_bytes())
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

    def test_fallback_uses_canonical_root_after_destination_alias_repoints(self):
        photo = self.write("IMG.jpg", b"jpg")
        real_keep = self.root / "real-keep"
        outside = self.root / "outside"
        alias = self.root / "keep-alias"
        real_keep.mkdir()
        outside.mkdir()
        try:
            alias.symlink_to(real_keep, target_is_directory=True)
        except OSError:
            self.skipTest("directory symlinks unavailable")
        session = self.force_fallback(self.make_session(action_mode="copy"))
        session.set_keep_dir(alias)
        session.load_queue()
        real_publish = session._publish_hard_link
        published_destinations = []

        def repoint_alias_before_publish(source, destination):
            published_destinations.append(destination)
            alias.unlink()
            alias.symlink_to(outside, target_is_directory=True)
            return real_publish(source, destination)

        with patch.object(
            session,
            "_publish_hard_link",
            side_effect=repoint_alias_before_publish,
        ):
            result = session.decide("keep")

        canonical_destination = real_keep.resolve() / "IMG.jpg"
        self.assertEqual(published_destinations, [canonical_destination])
        self.assertEqual(result.files[0].destination, canonical_destination)
        self.assertEqual((real_keep / "IMG.jpg").read_bytes(), photo.read_bytes())
        self.assertEqual(list(outside.iterdir()), [])

    def test_posix_move_does_not_unlink_replaced_source_name(self):
        raw = self.write("IMG.cr3", b"raw")
        self.write("IMG.jpg", b"jpg")
        session = self.make_session()
        session.load_queue()
        real_copy = session._copy_path_exclusive
        replaced = False

        def replace_source_after_copy(*args, **kwargs):
            nonlocal replaced
            result = real_copy(*args)
            if not replaced:
                replaced = True
                raw.unlink()
                raw.write_bytes(b"replacement")
            return result

        with patch.object(
            session,
            "_copy_path_exclusive",
            side_effect=replace_source_after_copy,
        ):
            with self.assertRaisesRegex(PhotoSessionError, "identity|replaced"):
                session.decide("keep")

        self.assertEqual(raw.read_bytes(), b"replacement")
        self.assertEqual(list(self.keep.iterdir()), [])
        self.assertEqual(session.remaining_count, 1)

    def test_fallback_move_does_not_unlink_replaced_source_name(self):
        raw = self.write("IMG.cr3", b"raw")
        self.write("IMG.jpg", b"jpg")
        session = self.force_fallback(self.make_session())
        session.load_queue()
        real_copy = session._copy_path_exclusive
        replaced = False

        def replace_source_after_copy(source, *args, **kwargs):
            nonlocal replaced
            result = real_copy(source, *args, **kwargs)
            if not replaced:
                replaced = True
                raw.unlink()
                raw.write_bytes(b"replacement")
            return result

        with patch.object(
            session,
            "_copy_path_exclusive",
            side_effect=replace_source_after_copy,
        ):
            with self.assertRaisesRegex(PhotoSessionError, "identity|replaced"):
                session.decide("keep")

        self.assertEqual(raw.read_bytes(), b"replacement")
        self.assertEqual(list(self.keep.iterdir()), [])
        self.assertEqual(session.remaining_count, 1)

    def test_posix_move_undo_does_not_unlink_replaced_action_destination(self):
        self.write("IMG.cr3", b"raw")
        self.write("IMG.jpg", b"jpg")
        session = self.make_session()
        session.load_queue()
        result = session.decide("keep")
        first_reverse = result.files[-1]
        real_copy = session._copy_path_exclusive
        replaced = False

        def replace_action_destination_after_copy(*args, **kwargs):
            nonlocal replaced
            copied = real_copy(*args)
            if not replaced:
                replaced = True
                first_reverse.destination.unlink()
                first_reverse.destination.write_bytes(b"replacement")
            return copied

        with patch.object(
            session,
            "_copy_path_exclusive",
            side_effect=replace_action_destination_after_copy,
        ):
            with self.assertRaisesRegex(PhotoSessionError, "identity|replaced"):
                session.undo()

        self.assertEqual(first_reverse.destination.read_bytes(), b"replacement")
        self.assertFalse(first_reverse.source.exists())
        self.assertTrue(session.can_undo)
        self.assertEqual(session.keep_count, 1)

    def test_fallback_move_undo_does_not_unlink_replaced_action_destination(self):
        self.write("IMG.cr3", b"raw")
        self.write("IMG.jpg", b"jpg")
        session = self.force_fallback(self.make_session())
        session.load_queue()
        result = session.decide("keep")
        first_reverse = result.files[-1]
        real_copy = session._copy_path_exclusive
        replaced = False

        def replace_action_destination_after_copy(source, *args, **kwargs):
            nonlocal replaced
            copied = real_copy(source, *args, **kwargs)
            if not replaced:
                replaced = True
                first_reverse.destination.unlink()
                first_reverse.destination.write_bytes(b"replacement")
            return copied

        with patch.object(
            session,
            "_copy_path_exclusive",
            side_effect=replace_action_destination_after_copy,
        ):
            with self.assertRaisesRegex(PhotoSessionError, "identity|replaced"):
                session.undo()

        self.assertEqual(first_reverse.destination.read_bytes(), b"replacement")
        self.assertFalse(first_reverse.source.exists())
        self.assertTrue(session.can_undo)
        self.assertEqual(session.keep_count, 1)

    def test_posix_rollback_does_not_unlink_replaced_action_destination(self):
        raw = self.write("IMG.cr3", b"raw")
        self.write("IMG.jpg", b"jpg")
        session = self.make_session()
        session.load_queue()
        real_move = session._move_path_exclusive
        real_copy = session._copy_path_exclusive
        move_calls = 0
        replaced = False

        def fail_second_move(*args, **kwargs):
            nonlocal move_calls
            move_calls += 1
            if move_calls == 2:
                raise OSError("primary move failure")
            return real_move(*args)

        def replace_during_rollback(*args, **kwargs):
            nonlocal replaced
            destination = args[1]
            copied = real_copy(*args)
            if destination.parent == self.source and not replaced:
                replaced = True
                moved_raw = self.keep / raw.name
                moved_raw.unlink()
                moved_raw.write_bytes(b"replacement")
            return copied

        with (
            patch.object(session, "_move_path_exclusive", side_effect=fail_second_move),
            patch.object(
                session,
                "_copy_path_exclusive",
                side_effect=replace_during_rollback,
            ),
        ):
            with self.assertRaises(PhotoSessionError) as raised:
                session.decide("keep")

        self.assertIn("primary move failure", str(raised.exception))
        self.assertIn("replaced", str(raised.exception))
        self.assertEqual((self.keep / raw.name).read_bytes(), b"replacement")
        self.assertFalse(raw.exists())
        self.assertEqual(session.remaining_count, 1)

    def test_fallback_rollback_does_not_unlink_replaced_action_destination(self):
        raw = self.write("IMG.cr3", b"raw")
        self.write("IMG.jpg", b"jpg")
        session = self.force_fallback(self.make_session())
        session.load_queue()
        real_move = session._move_path_exclusive
        real_copy = session._copy_path_exclusive
        move_calls = 0
        replaced = False

        def fail_second_move(*args, **kwargs):
            nonlocal move_calls
            move_calls += 1
            if move_calls == 2:
                raise OSError("primary move failure")
            return real_move(*args, **kwargs)

        def replace_during_rollback(source, destination, *args, **kwargs):
            nonlocal replaced
            copied = real_copy(source, destination, *args, **kwargs)
            if destination.parent == self.source and not replaced:
                replaced = True
                source.unlink()
                source.write_bytes(b"replacement")
            return copied

        with (
            patch.object(
                session,
                "_move_path_exclusive",
                side_effect=fail_second_move,
            ),
            patch.object(
                session,
                "_copy_path_exclusive",
                side_effect=replace_during_rollback,
            ),
        ):
            with self.assertRaises(PhotoSessionError) as raised:
                session.decide("keep")

        self.assertIn("primary move failure", str(raised.exception))
        self.assertIn("replaced", str(raised.exception))
        self.assertEqual((self.keep / raw.name).read_bytes(), b"replacement")
        self.assertFalse(raw.exists())
        self.assertEqual(session.remaining_count, 1)

    def test_failed_group_copy_rolls_back_completed_members(self):
        self.write("IMG.cr3", b"raw")
        self.write("IMG.jpg", b"jpg")
        session = self.make_session(action_mode="copy")
        session.load_queue()
        real_copy = session._copy_path_exclusive
        calls = 0

        def fail_second(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("disk full")
            return real_copy(*args)

        with patch.object(session, "_copy_path_exclusive", side_effect=fail_second):
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
        real_move = session._move_path_exclusive
        calls = 0

        def fail_second(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("device error")
            return real_move(*args)

        with patch.object(session, "_move_path_exclusive", side_effect=fail_second):
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
        real_copy = session._copy_path_exclusive
        calls = 0

        def fail_second(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("primary failure")
            return real_copy(*args)

        real_remove = session._remove_owned_path

        def fail_final_destination_cleanup(path, *args):
            if not Path(path).name.startswith(".keep-or-nah-"):
                raise OSError("rollback failure")
            return real_remove(path, *args)

        with (
            patch.object(session, "_copy_path_exclusive", side_effect=fail_second),
            patch.object(
                session,
                "_remove_owned_path",
                side_effect=fail_final_destination_cleanup,
            ),
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
        real_move = session._move_path_exclusive
        calls = 0

        def fail_second_reverse(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("transient undo failure")
            return real_move(*args)

        with patch.object(session, "_move_path_exclusive", side_effect=fail_second_reverse):
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
        real_move = session._move_path_exclusive
        calls = 0

        def fail_reverse_and_rollback(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("undo failure")
            if calls == 3:
                raise OSError("undo rollback failure")
            return real_move(*args)

        with patch.object(
            session,
            "_move_path_exclusive",
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
        real_remove = session._remove_owned_path
        calls = 0

        def fail_second_unlink(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("copy undo failure")
            return real_remove(*args, **kwargs)

        with (
            patch.object(session, "_remove_owned_path", side_effect=fail_second_unlink),
            patch.object(
                session,
                "_copy_path_exclusive",
                side_effect=OSError("copy rollback failure"),
            ),
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
