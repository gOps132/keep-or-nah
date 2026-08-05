import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import warnings

from photo_groups import PhotoGroup
from photo_session import ActionRecord, FileOperation, PhotoSession
from app_settings import resolve_settings_path
from session_persistence import SessionLifecycle, SessionPersistence, resolve_session_path
from session_startup import choose_source_directory, initialize_gui_session, show_session_warning


class PhotoSessionSnapshotTests(unittest.TestCase):
    @staticmethod
    def _version_two_snapshot(session):
        return {
            "snapshot_version": 2,
            "source_dir": str(session.source_dir),
            "keep_dir": str(session.keep_dir) if session.keep_dir is not None else None,
            "nah_dir": str(session.nah_dir) if session.nah_dir is not None else None,
            "action_mode": session.action_mode,
            "queue": [
                {
                    "stem": group.stem,
                    "members": [str(member) for member in group.members],
                    "representative": str(group.representative),
                }
                for group in session.queue
            ],
            "active_index": session.active_index,
            "active_stem": (
                session.active_group.stem if session.active_group is not None else None
            ),
            "total_loaded": session.total_loaded,
            "keep_count": session.keep_count,
            "nah_count": session.nah_count,
            "available_extensions": list(session.available_extensions),
            "enabled_extensions": sorted(session.enabled_extensions),
            "history": [
                {
                    "decision": record.decision,
                    "action_mode": record.action_mode,
                    "group": {
                        "stem": record.group.stem,
                        "members": [str(member) for member in record.group.members],
                        "representative": str(record.group.representative),
                    },
                    "files": [
                        {
                            "source": str(operation.source),
                            "destination": str(operation.destination),
                            "destination_identity": list(
                                operation.destination_identity
                            ),
                        }
                        for operation in record.files
                    ],
                    "index": record.index,
                }
                for record in session.history
            ],
        }

    def test_grouped_snapshot_round_trip_preserves_filter_groups_and_history(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            keep = root / "keep"
            nah = root / "nah"
            source.mkdir()
            (source / "A_done.cr3").write_bytes(b"raw")
            (source / "A_done.jpg").write_bytes(b"jpg")
            active = source / "Z_active.png"
            active.write_bytes(b"png")

            session = PhotoSession()
            session.set_source_dir(source)
            session.set_keep_dir(keep)
            session.set_nah_dir(nah)
            session.set_action_mode("copy")
            session.load_queue()
            result = session.decide("keep")
            session.apply_extension_filter({".png"})

            expected_snapshot = self._version_two_snapshot(session)
            snapshot = session.to_snapshot()
            self.assertEqual(snapshot, expected_snapshot)
            restored = PhotoSession.from_snapshot(snapshot)

            self.assertEqual(snapshot["snapshot_version"], 2)
            self.assertEqual(snapshot["active_stem"], "Z_active")
            self.assertEqual(len(snapshot["queue"][0]["members"]), 1)
            self.assertEqual(len(snapshot["history"][0]["files"]), 2)
            self.assertEqual(
                snapshot["history"][0]["files"][0]["destination_identity"],
                list(result.files[0].destination_identity),
            )
            self.assertEqual(getattr(restored, "snapshot_version", None), 2)
            self.assertEqual(restored.queue, session.queue)
            self.assertEqual(restored.active_group.stem, session.active_group.stem)
            self.assertEqual(restored.available_extensions, session.available_extensions)
            self.assertEqual(restored.enabled_extensions, session.enabled_extensions)
            self.assertEqual(restored.history, session.history)
            self.assertEqual(restored.to_snapshot(), snapshot)

    def test_version_two_unsafe_group_payload_invalidates_entire_session(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            source.mkdir()
            photo = source / "photo.jpg"
            photo.touch()
            session = PhotoSession()
            session.set_source_dir(source)
            session.load_queue()
            snapshot = self._version_two_snapshot(session)
            self.assertIsNotNone(PhotoSession.from_snapshot(snapshot))
            outside = root / "outside.jpg"
            outside.touch()

            unsafe_groups = (
                {**snapshot["queue"][0], "members": [str(outside)]},
                {**snapshot["queue"][0], "representative": str(outside)},
                {**snapshot["queue"][0], "stem": "wrong"},
                {**snapshot["queue"][0], "members": []},
            )
            for group in unsafe_groups:
                with self.subTest(group=group):
                    self.assertIsNone(
                        PhotoSession.from_snapshot({**snapshot, "queue": [group]})
                    )

    def test_version_two_rejects_group_member_symlink_escape(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            source.mkdir()
            photo = source / "photo.jpg"
            photo.touch()
            session = PhotoSession()
            session.set_source_dir(source)
            session.load_queue()
            snapshot = self._version_two_snapshot(session)
            self.assertIsNotNone(PhotoSession.from_snapshot(snapshot))
            outside = root / "outside.jpg"
            outside.touch()
            escaped = source / "escaped.jpg"
            try:
                escaped.symlink_to(outside)
            except OSError:
                self.skipTest("symlinks unavailable")
            snapshot["queue"][0]["members"] = [str(escaped)]
            snapshot["queue"][0]["representative"] = str(escaped)
            snapshot["queue"][0]["stem"] = "escaped"

            self.assertIsNone(PhotoSession.from_snapshot(snapshot))

    def test_version_two_drops_whole_compound_history_record_when_one_file_is_unsafe(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            keep = root / "keep"
            source.mkdir()
            (source / "done.cr3").touch()
            (source / "done.jpg").touch()
            (source / "remaining.jpg").touch()
            session = PhotoSession()
            session.set_source_dir(source)
            session.set_keep_dir(keep)
            session.set_action_mode("copy")
            session.load_queue()
            session.decide("keep")
            snapshot = self._version_two_snapshot(session)
            self.assertIsNotNone(PhotoSession.from_snapshot(snapshot))
            outside = root / "outside.cr3"
            outside.touch()
            snapshot["history"][0]["files"][0]["destination"] = str(outside)

            restored = PhotoSession.from_snapshot(snapshot)

            self.assertIsNotNone(restored)
            self.assertEqual(restored.history, [])

    def test_version_two_drops_history_when_destination_identity_no_longer_owns_file(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            keep = root / "keep"
            source.mkdir()
            (source / "done.jpg").touch()
            (source / "remaining.jpg").touch()
            session = PhotoSession()
            session.set_source_dir(source)
            session.set_keep_dir(keep)
            session.set_action_mode("copy")
            session.load_queue()
            result = session.decide("keep")
            snapshot = self._version_two_snapshot(session)
            self.assertIsNotNone(PhotoSession.from_snapshot(snapshot))
            result.destination.unlink()
            result.destination.write_bytes(b"replacement")

            restored = PhotoSession.from_snapshot(snapshot)

            self.assertIsNotNone(restored)
            self.assertFalse(restored.can_undo)

    def test_version_two_rejects_malformed_numeric_fields(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "source"
            source.mkdir()
            (source / "photo.jpg").touch()
            session = PhotoSession()
            session.set_source_dir(source)
            session.load_queue()
            snapshot = self._version_two_snapshot(session)
            self.assertIsNotNone(PhotoSession.from_snapshot(snapshot))

            invalid_fields = (
                ("active_index", True),
                ("active_index", -1),
                ("total_loaded", "1"),
                ("keep_count", 1.5),
                ("nah_count", float("inf")),
            )
            for field, value in invalid_fields:
                with self.subTest(field=field, value=value):
                    self.assertIsNone(
                        PhotoSession.from_snapshot({**snapshot, field: value})
                    )

    def test_version_two_rejects_unknown_version_and_malformed_extensions(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "source"
            source.mkdir()
            (source / "photo.jpg").touch()
            session = PhotoSession()
            session.set_source_dir(source)
            session.load_queue()
            snapshot = self._version_two_snapshot(session)
            self.assertIsNotNone(PhotoSession.from_snapshot(snapshot))

            self.assertIsNone(
                PhotoSession.from_snapshot({**snapshot, "snapshot_version": 99})
            )
            self.assertIsNone(
                PhotoSession.from_snapshot(
                    {**snapshot, "enabled_extensions": ["../jpg"]}
                )
            )

    def test_legacy_snapshot_rebuilds_groups_and_preserves_active_stem_and_filter(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "source"
            source.mkdir()
            raw = source / "IMG_1.cr3"
            jpg = source / "IMG_1.jpg"
            active = source / "IMG_2.jpg"
            png = source / "IGNORED.png"
            for path in (raw, jpg, active, png):
                path.touch()
            legacy = {
                "source_dir": str(source),
                "queue": [str(jpg), str(active)],
                "active_index": 1,
                "history": [],
            }

            restored = PhotoSession.from_snapshot(legacy)

            self.assertIsNotNone(restored)
            self.assertEqual(getattr(restored, "snapshot_version", None), 2)
            self.assertEqual(restored.enabled_extensions, {".jpg"})
            self.assertEqual(
                restored.queue,
                [
                    PhotoGroup("IMG_1", (raw, jpg), jpg),
                    PhotoGroup("IMG_2", (active,), active),
                ],
            )
            self.assertEqual(restored.active_group.stem, "IMG_2")

    def test_legacy_identity_history_migrates_to_one_file_compound_record(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            keep = root / "keep"
            source.mkdir()
            keep.mkdir()
            remaining = source / "remaining.jpg"
            remaining.touch()
            destination = keep / "done.jpg"
            destination.touch()
            identity = destination.stat().st_dev, destination.stat().st_ino
            legacy = {
                "source_dir": str(source),
                "keep_dir": str(keep),
                "queue": [str(remaining)],
                "history": [{
                    "decision": "keep",
                    "action_mode": "move",
                    "source": str(source / "done.jpg"),
                    "destination": str(destination),
                    "destination_identity": list(identity),
                    "index": 0,
                }],
            }

            restored = PhotoSession.from_snapshot(legacy)

            self.assertEqual(len(restored.history), 1)
            self.assertEqual(len(restored.history[0].files), 1)
            self.assertEqual(restored.history[0].files[0].destination_identity, identity)

    def test_restore_prunes_missing_and_unsupported_queue_and_normalizes_index(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "source"
            source.mkdir()
            valid = source / "valid.jpg"
            invalid = source / "notes.txt"
            valid.touch()
            invalid.touch()
            snapshot = {
                "source_dir": str(source), "keep_dir": None, "nah_dir": None,
                "action_mode": "move", "queue": [str(source / "missing.jpg"), str(invalid), str(valid)],
                "active_index": 99, "total_loaded": 3, "keep_count": 1, "nah_count": 1, "history": [],
            }

            restored = PhotoSession.from_snapshot(snapshot)

            self.assertEqual(restored.queue, [PhotoGroup("valid", (valid,), valid)])
            self.assertEqual(restored.active_index, 0)

    def test_restore_rejects_existing_queue_file_outside_source(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            source.mkdir()
            outside = root / "outside.jpg"
            outside.touch()
            snapshot = {
                "source_dir": str(source),
                "queue": [str(outside)],
                "active_index": 0,
                "history": [],
            }

            self.assertIsNone(PhotoSession.from_snapshot(snapshot))

    def test_restore_rejects_queue_symlink_escaping_source(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            source.mkdir()
            outside = root / "outside.jpg"
            outside.touch()
            escaped = source / "escaped.jpg"
            try:
                escaped.symlink_to(outside)
            except OSError:
                self.skipTest("symlinks unavailable")
            snapshot = {
                "source_dir": str(source),
                "queue": [str(escaped)],
                "active_index": 0,
                "history": [],
            }

            self.assertIsNone(PhotoSession.from_snapshot(snapshot))

    def test_restore_keeps_same_active_photo_when_earlier_items_are_pruned(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "source"
            source.mkdir()
            active = source / "active.jpg"
            later = source / "later.jpg"
            active.touch()
            later.touch()
            snapshot = {
                "source_dir": str(source),
                "queue": [str(source / "missing.jpg"), str(active), str(later)],
                "active_index": 1,
                "history": [],
            }

            restored = PhotoSession.from_snapshot(snapshot)

            self.assertEqual(restored.active_photo, active)

    def test_restore_uses_nearest_earlier_valid_photo_when_active_is_missing(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "source"
            source.mkdir()
            earlier = source / "earlier.jpg"
            later = source / "later.jpg"
            earlier.touch()
            later.touch()
            snapshot = {
                "source_dir": str(source),
                "queue": [str(earlier), str(source / "missing.jpg"), str(later)],
                "active_index": 1,
                "history": [],
            }

            restored = PhotoSession.from_snapshot(snapshot)

            self.assertEqual(restored.active_photo, earlier)

    def test_restore_rejects_missing_source_or_empty_queue(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "source"
            source.mkdir()
            base = {"source_dir": str(source), "queue": [], "history": []}
            self.assertIsNone(PhotoSession.from_snapshot(base))
            base["source_dir"] = str(source / "missing")
            base["queue"] = [str(source / "photo.jpg")]
            self.assertIsNone(PhotoSession.from_snapshot(base))

    def test_non_finite_numeric_snapshot_is_invalid_and_cleared(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            source.mkdir()
            photo = source / "photo.jpg"
            photo.touch()
            store = SessionPersistence(root / "session.json")
            store.path.write_text(
                json.dumps({
                    "source_dir": str(source),
                    "queue": [str(photo)],
                    "active_index": 1e309,
                    "history": [],
                }),
                encoding="utf-8",
            )

            restored = SessionLifecycle(store, error_handler=lambda _message: None).restore()

            self.assertIsNone(restored)
            self.assertFalse(store.path.exists())

    def test_restored_history_remains_undoable(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            keep = root / "keep"
            source.mkdir()
            first = source / "first.jpg"
            second = source / "second.jpg"
            first.touch()
            second.touch()
            session = PhotoSession()
            session.set_source_dir(source)
            session.set_keep_dir(keep)
            session.set_action_mode("copy")
            session.load_queue()
            result = session.decide("keep")

            snapshot = session.to_snapshot()
            self.assertIn("files", snapshot["history"][0])
            self.assertEqual(
                snapshot["history"][0]["files"][0]["destination_identity"],
                list(result.files[0].destination_identity),
            )

            restored = PhotoSession.from_snapshot(snapshot)
            restored.undo()

            self.assertEqual(restored.active_photo, first)
            self.assertFalse(result.destination.exists())
            self.assertEqual(restored.keep_count, 0)

    def test_legacy_history_without_identity_cannot_claim_unrelated_file(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            keep = root / "keep"
            source.mkdir()
            keep.mkdir()
            remaining = source / "remaining.jpg"
            remaining.touch()
            unrelated = keep / "processed.jpg"
            unrelated.write_bytes(b"unrelated")
            snapshot = {
                "source_dir": str(source),
                "keep_dir": str(keep),
                "queue": [str(remaining)],
                "history": [
                    {
                        "decision": "keep",
                        "action_mode": "copy",
                        "source": str(source / "processed.jpg"),
                        "destination": str(unrelated),
                        "index": 0,
                    }
                ],
            }

            restored = PhotoSession.from_snapshot(snapshot)

            self.assertFalse(restored.can_undo)
            self.assertEqual(unrelated.read_bytes(), b"unrelated")

    def test_history_identity_must_be_two_plain_ints_matching_destination(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            keep = root / "keep"
            source.mkdir()
            keep.mkdir()
            remaining = source / "remaining.jpg"
            remaining.touch()
            destination = keep / "processed.jpg"
            destination.touch()
            destination_stat = destination.stat()
            base_record = {
                "decision": "keep",
                "action_mode": "copy",
                "source": str(source / "processed.jpg"),
                "destination": str(destination),
                "index": 0,
            }
            invalid_identities = (
                [destination_stat.st_dev],
                [True, destination_stat.st_ino],
                ["device", destination_stat.st_ino],
                [destination_stat.st_dev, destination_stat.st_ino, 3],
                [destination_stat.st_dev, destination_stat.st_ino + 1],
            )

            for identity in invalid_identities:
                with self.subTest(identity=identity):
                    snapshot = {
                        "source_dir": str(source),
                        "keep_dir": str(keep),
                        "queue": [str(remaining)],
                        "history": [
                            {
                                **base_record,
                                "destination_identity": identity,
                            }
                        ],
                    }

                    restored = PhotoSession.from_snapshot(snapshot)

                    self.assertFalse(restored.can_undo)

    def test_restore_discards_history_with_destination_outside_decision_folder(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            keep = root / "keep"
            source.mkdir()
            keep.mkdir()
            remaining = source / "remaining.jpg"
            remaining.touch()
            arbitrary = root / "arbitrary.jpg"
            arbitrary.touch()
            snapshot = {
                "source_dir": str(source),
                "keep_dir": str(keep),
                "queue": [str(remaining)],
                "history": [{
                    "decision": "keep",
                    "action_mode": "copy",
                    "source": str(source / "processed.jpg"),
                    "destination": str(arbitrary),
                    "index": 0,
                }],
            }

            restored = PhotoSession.from_snapshot(snapshot)

            self.assertFalse(restored.can_undo)
            self.assertTrue(arbitrary.exists())

    def test_restore_discards_history_without_destination_root_or_with_outside_source(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            keep = root / "keep"
            source.mkdir()
            keep.mkdir()
            remaining = source / "remaining.jpg"
            remaining.touch()
            snapshot = {
                "source_dir": str(source),
                "queue": [str(remaining)],
                "history": [
                    {
                        "decision": "nah",
                        "action_mode": "copy",
                        "source": str(source / "processed.jpg"),
                        "destination": str(root / "nah" / "processed.jpg"),
                        "index": 0,
                    },
                    {
                        "decision": "keep",
                        "action_mode": "copy",
                        "source": str(root / "outside-source.jpg"),
                        "destination": str(keep / "processed.jpg"),
                        "index": 0,
                    },
                ],
                "keep_dir": str(keep),
                "nah_dir": None,
            }

            restored = PhotoSession.from_snapshot(snapshot)

            self.assertEqual(restored.history, [])


class SessionPersistenceTests(unittest.TestCase):
    def test_save_load_and_clear(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "session.json"
            store = SessionPersistence(path)
            payload = {"source_dir": "/tmp/source", "queue": ["/tmp/a.jpg"]}
            store.save(payload)
            self.assertEqual(store.load(), payload)
            self.assertFalse(path.with_suffix(".json.tmp").exists())
            store.clear()
            self.assertIsNone(store.load())

    def test_corrupt_json_is_safe(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "session.json"
            path.write_text("not json", encoding="utf-8")
            self.assertIsNone(SessionPersistence(path).load())

    def test_session_path_sits_beside_settings(self):
        self.assertEqual(resolve_session_path().name, "session.json")
        self.assertEqual(resolve_session_path().parent, resolve_settings_path().parent)

    def test_lifecycle_restores_valid_session_and_clears_finished_session(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            source.mkdir()
            photo = source / "photo.jpg"
            photo.touch()
            store = SessionPersistence(root / "session.json")
            original = PhotoSession()
            original.source_dir = source
            original.queue = [photo]
            original.total_loaded = 1
            store.save(original.to_snapshot())
            lifecycle = SessionLifecycle(store)

            restored = lifecycle.restore()
            self.assertEqual(restored.active_photo, photo)
            restored.queue.clear()
            lifecycle.persist(restored)
            self.assertIsNone(store.load())

    def test_lifecycle_clears_invalid_snapshot(self):
        with tempfile.TemporaryDirectory() as temp:
            store = SessionPersistence(Path(temp) / "session.json")
            store.save({"source_dir": "/missing", "queue": ["/missing/a.jpg"]})
            self.assertIsNone(SessionLifecycle(store).restore())
            self.assertFalse(store.path.exists())

    def test_lifecycle_clears_corrupt_json_snapshot(self):
        with tempfile.TemporaryDirectory() as temp:
            store = SessionPersistence(Path(temp) / "session.json")
            store.path.write_text("not json", encoding="utf-8")

            self.assertIsNone(SessionLifecycle(store).restore())
            self.assertFalse(store.path.exists())

    def test_lifecycle_clears_non_object_json_snapshot(self):
        with tempfile.TemporaryDirectory() as temp:
            store = SessionPersistence(Path(temp) / "session.json")
            store.path.write_text("[]", encoding="utf-8")

            self.assertIsNone(SessionLifecycle(store).restore())
            self.assertFalse(store.path.exists())

    def test_lifecycle_save_error_is_reported_once_and_never_raised(self):
        store = Mock()
        store.save.side_effect = OSError("disk full")
        errors = []
        lifecycle = SessionLifecycle(store, error_handler=errors.append)
        session = Mock(remaining_count=1)
        session.to_snapshot.return_value = {"queue": ["a.jpg"]}

        self.assertFalse(lifecycle.persist(session))
        self.assertFalse(lifecycle.persist(session))
        self.assertEqual(len(errors), 1)
        self.assertIn("disk full", errors[0])

    def test_lifecycle_clear_error_is_non_fatal(self):
        store = Mock()
        store.clear.side_effect = OSError("read only")
        errors = []
        lifecycle = SessionLifecycle(store, error_handler=errors.append)

        self.assertFalse(lifecycle.persist(Mock(remaining_count=0)))
        self.assertEqual(len(errors), 1)


class StartupCoordinatorTests(unittest.TestCase):
    def test_persistence_warning_is_non_modal_and_visible_in_window_title(self):
        app = Mock()
        with patch("session_startup.print") as output:
            show_session_warning(app, "disk full")
        app.title.assert_called_once_with("Keep or Nah — Session recovery unavailable")
        output.assert_called_once()

    def test_restored_session_initializes_pipeline_and_preview(self):
        class Calls:
            restored_startup_session = True
            session = type("Session", (), {"source_dir": Path("/photos"), "queue": [Path("a.jpg")]})()
            last_browsed_dir = None
            pipeline_queue = None
            previewed = False
            refreshed = False
            preview_pipeline = type("Pipeline", (), {"reset": lambda owner, queue: setattr(app, "pipeline_queue", queue)})()
            def refresh_ui(self): self.refreshed = True
            def refresh_preview(self): self.previewed = True
            def choose_source_folder(self): self.fail = True
        app = Calls()
        initialize_gui_session(app)
        self.assertEqual(app.pipeline_queue, app.session.queue)
        self.assertTrue(app.refreshed)
        self.assertTrue(app.previewed)

    def test_empty_startup_opens_source_picker(self):
        class Calls:
            restored_startup_session = False
            picked = False
            def choose_source_folder(self): self.picked = True
        app = Calls()
        initialize_gui_session(app)
        self.assertTrue(app.picked)

    def test_picker_cancel_leaves_empty_app_unchanged(self):
        app = Mock()
        selected = choose_source_directory(app, lambda **_kwargs: "")
        self.assertFalse(selected)
        app.replace_source_folder.assert_not_called()

    def test_picker_selection_replaces_source_and_autoloads(self):
        app = Mock()
        app.get_initial_directory.return_value = "/initial"
        selected = choose_source_directory(app, lambda **_kwargs: "/photos")
        self.assertTrue(selected)
        app.replace_source_folder.assert_called_once_with("/photos")
        app.load_queue.assert_called_once_with()


class FrontendIntegrationTests(unittest.TestCase):
    def test_both_frontends_delegate_source_picker_to_shared_coordinator(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from classic_gui import ClassicApp
            from gui_app import App

        for module_name, app_class in (("classic_gui", ClassicApp), ("gui_app", App)):
            fake = object()
            with self.subTest(frontend=app_class.__name__), patch(
                f"{module_name}.choose_source_directory"
            ) as coordinator:
                app_class.choose_source_folder(fake)
                coordinator.assert_called_once_with(fake)

    def test_both_frontends_persist_after_successful_load(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from classic_gui import ClassicApp
            from gui_app import App

        class Session:
            queue = [Path("photo.jpg")]
            def load_queue(self): return 1

        class Pipeline:
            def reset(self, queue): self.queue = queue

        for app_class in (ClassicApp, App):
            fake = Mock()
            fake.session = Session()
            fake.preview_pipeline = Pipeline()
            fake.preview_source_path = Path("old.jpg")
            fake.preview_source_image = object()
            with self.subTest(frontend=app_class.__name__):
                app_class.load_queue(fake)
                fake.persist_session.assert_called_once_with()

    def test_both_frontends_persist_mode_navigation_decision_and_undo(self):
        from classic_gui import ClassicApp
        from gui_app import App

        class Session:
            queue = [Path("photo.jpg")]
            can_undo = True
            def set_action_mode(self, mode): self.action_mode = mode
            def set_active_index(self, index): return self.queue[0]
            def move_active(self, offset): return self.queue[0]
            def decide(self, decision): self.decision = decision
            def undo(self): self.undone = True

        class Pipeline:
            def reset(self, queue): self.queue = queue

        for app_class in (ClassicApp, App):
            fake = Mock()
            fake.session = Session()
            fake.preview_pipeline = Pipeline()
            fake.action_mode_var.get.return_value = "copy"
            mutations = [
                lambda: app_class.select_photo_at_index(fake, 0),
                lambda: app_class.navigate_selection(fake, 1),
                lambda: app_class.sort_current_photo(fake, "keep"),
                lambda: app_class.undo_last_action(fake),
            ]
            mutations.insert(
                0,
                (lambda: app_class.handle_action_mode_change(fake))
                if app_class is ClassicApp
                else (lambda: app_class.handle_action_mode_change(fake, "copy")),
            )
            for mutation in mutations:
                fake.persist_session.reset_mock()
                mutation()
                with self.subTest(frontend=app_class.__name__, mutation=mutation):
                    fake.persist_session.assert_called_once_with()

    def test_both_frontends_refresh_after_decision_when_persistence_fails(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from classic_gui import ClassicApp
            from gui_app import App

        class Session:
            queue = []
            def decide(self, _decision): return None

        for app_class in (ClassicApp, App):
            fake = Mock()
            fake.session = Session()
            fake.persist_session.side_effect = lambda: False
            with self.subTest(frontend=app_class.__name__):
                app_class.sort_current_photo(fake, "keep")
                fake.persist_session.assert_called_once_with()
                fake.refresh_ui.assert_called_once_with()
                fake.refresh_preview.assert_called_once_with()

    def test_both_frontends_refresh_after_undo_when_persistence_fails(self):
        from classic_gui import ClassicApp
        from gui_app import App

        class Session:
            queue = [Path("photo.jpg")]
            can_undo = True
            def undo(self): return None

        for app_class in (ClassicApp, App):
            fake = Mock()
            fake.session = Session()
            fake.persist_session.return_value = False
            with self.subTest(frontend=app_class.__name__):
                app_class.undo_last_action(fake)
                fake.refresh_ui.assert_called_once_with()
                fake.refresh_preview.assert_called_once_with()

    def test_both_frontends_close_even_when_persistence_fails(self):
        from classic_gui import ClassicApp
        from gui_app import App

        for app_class in (ClassicApp, App):
            fake = Mock()
            fake.persist_session.return_value = False
            with self.subTest(frontend=app_class.__name__):
                app_class.handle_window_close(fake)
                fake.persist_session.assert_called_once_with()
                fake.destroy.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
