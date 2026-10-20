from __future__ import annotations

import unittest
from collections import OrderedDict
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

from PIL import Image

from gui_app import App

FRONTENDS = (App,)


def _make_fake_frontend(frontend: type) -> SimpleNamespace:
    fake = SimpleNamespace(
        destroyed=False,
        preview_refresh_job=None,
        thumbnail_rebuild_job=None,
        rendered_preview_size=None,
        rendered_preview_scrollregion=None,
        scale_preview_display_to_current_canvas=Mock(),
        schedule_preview_refresh=Mock(),
        refresh_thumbnail_strip=Mock(),
        after_cancel=Mock(),
        after=Mock(return_value=7),
        preview_canvas=SimpleNamespace(),
    )

    def _bound_flush():
        frontend._flush_thumbnail_strip_rebuild(fake)

    fake._flush_thumbnail_strip_rebuild = _bound_flush
    return fake


def _make_sized_canvas(real_width: int, real_height: int) -> SimpleNamespace:
    return SimpleNamespace(
        winfo_width=Mock(return_value=real_width),
        winfo_height=Mock(return_value=real_height),
        scale=Mock(),
        configure=Mock(),
        create_image=Mock(),
        create_text=Mock(),
        delete=Mock(),
        canvasx=Mock(return_value=0.0),
        canvasy=Mock(return_value=0.0),
    )


class ThumbnailStripDebounceTests(unittest.TestCase):
    def test_configure_rebuilds_debounce_on_trailing_60ms_timer(self) -> None:
        for frontend in FRONTENDS:
            with self.subTest(frontend=frontend.__name__):
                fake = _make_fake_frontend(frontend)

                for _ in range(3):
                    frontend.schedule_thumbnail_strip_rebuild(fake)

                fake.after_cancel.assert_called_with(7)
                self.assertEqual(fake.after.call_count, 3)
                (delay, fired_callback) = fake.after.call_args_list[-1].args
                self.assertEqual(delay, 60)
                self.assertFalse(fake.refresh_thumbnail_strip.called)

                fired_callback()

                self.assertIsNone(fake.thumbnail_rebuild_job)
                fake.refresh_thumbnail_strip.assert_called_once_with(force_rebuild=True)

    def test_destroyed_frontend_skips_scheduling_entirely(self) -> None:
        for frontend in FRONTENDS:
            with self.subTest(frontend=frontend.__name__):
                fake = _make_fake_frontend(frontend)
                fake.destroyed = True

                frontend.schedule_thumbnail_strip_rebuild(fake)

                self.assertFalse(fake.after.called)
                self.assertFalse(fake.after_cancel.called)


class PreviewResizeScaleTests(unittest.TestCase):
    def test_preview_configure_scales_texture_then_schedules_debounced_refresh(self) -> None:
        for frontend in FRONTENDS:
            with self.subTest(frontend=frontend.__name__):
                fake = _make_fake_frontend(frontend)

                frontend.handle_preview_configure(fake)

                fake.scale_preview_display_to_current_canvas.assert_called_once_with()
                fake.schedule_preview_refresh.assert_called_once_with()

    def test_preview_configure_is_skipped_when_destroyed(self) -> None:
        for frontend in FRONTENDS:
            with self.subTest(frontend=frontend.__name__):
                fake = _make_fake_frontend(frontend)
                fake.destroyed = True

                frontend.handle_preview_configure(fake)

                fake.scale_preview_display_to_current_canvas.assert_not_called()
                fake.schedule_preview_refresh.assert_not_called()

    def test_canvas_scale_scales_items_and_scrollregion_with_viewport_ratio(self) -> None:
        for frontend in FRONTENDS:
            with self.subTest(frontend=frontend.__name__):
                fake = _make_fake_frontend(frontend)
                fake.rendered_preview_size = (200, 100)
                fake.rendered_preview_scrollregion = (0, 0, 300, 100)
                fake.preview_canvas = _make_sized_canvas(400, 100)

                frontend.scale_preview_display_to_current_canvas(fake)

                fake.preview_canvas.scale.assert_called_once_with("all", 0, 0, 2.0, 1.0)
                fake.preview_canvas.configure.assert_called_once_with(scrollregion=(0, 0, 600, 100))

    def test_canvas_scale_is_skipped_without_rendered_texture(self) -> None:
        for frontend in FRONTENDS:
            with self.subTest(frontend=frontend.__name__):
                fake = _make_fake_frontend(frontend)
                fake.rendered_preview_size = None
                fake.preview_canvas = _make_sized_canvas(400, 100)

                frontend.scale_preview_display_to_current_canvas(fake)

                fake.preview_canvas.scale.assert_not_called()
                fake.preview_canvas.configure.assert_not_called()
                self.assertIsNone(fake.rendered_preview_size)

    def test_canvas_scale_is_skipped_when_size_is_unchanged(self) -> None:
        for frontend in FRONTENDS:
            with self.subTest(frontend=frontend.__name__):
                fake = _make_fake_frontend(frontend)
                fake.rendered_preview_size = (400, 100)
                fake.rendered_preview_scrollregion = (0, 0, 300, 100)
                fake.preview_canvas = _make_sized_canvas(400, 100)

                frontend.scale_preview_display_to_current_canvas(fake)

                fake.preview_canvas.scale.assert_not_called()
                fake.preview_canvas.configure.assert_not_called()
                self.assertEqual(fake.rendered_preview_size, (400, 100))


class RenderedSizeTrackingTests(unittest.TestCase):
    def test_display_preview_image_records_rendered_size_and_scrollregion(self) -> None:
        for frontend in FRONTENDS:
            with self.subTest(frontend=frontend.__name__):
                fake = _make_fake_frontend(frontend)
                fake.preview_canvas = _make_sized_canvas(128, 64)
                fake.preview_photo = None
                fake.get_preview_texture = Mock(return_value=Mock())
                fake.restore_view_center = Mock()
                fake.loading_overlay_visible = False
                fake.render_loading_overlay = Mock()
                image = Image.new("RGBA", (50, 50), "blue")

                frontend.display_preview_image(fake, image)

                self.assertEqual(fake.rendered_preview_size, (128, 64))
                self.assertEqual(fake.rendered_preview_scrollregion, (0, 0, 128, 64))

    def test_clear_preview_resets_rendered_tracking(self) -> None:
        for frontend in FRONTENDS:
            with self.subTest(frontend=frontend.__name__):
                fake = _make_fake_frontend(frontend)
                fake.rendered_preview_size = (300, 300)
                fake.rendered_preview_scrollregion = (0, 0, 300, 300)
                fake.preview_canvas = _make_sized_canvas(320, 240)
                fake.loading_overlay_visible = False
                fake.render_loading_overlay = Mock()
                fake._apply_appearance_mode = Mock(side_effect=lambda values: values[0])

                frontend.clear_preview(fake, message="No Photo")

                self.assertEqual(fake.rendered_preview_size, (320, 240))
                self.assertEqual(fake.rendered_preview_scrollregion, (0, 0, 320, 240))


class ThumbnailFakeFactory:
    @staticmethod
    def make_async(app_type) -> SimpleNamespace:
        fake = SimpleNamespace(
            destroyed=False,
            thumbnail_pending_requests=set(),
            thumbnail_raws=OrderedDict(),
            thumbnail_cache=OrderedDict(),
            thumbnail_refs=[],
            thumbnail_cache_limit=192,
            request_strip_thumbnail=Mock(),
            _ensure_thumbnail_worker=Mock(),
            prune_strip_thumbnail_state=Mock(),
            after=Mock(return_value=job_holder["job"]),
            after_cancel=Mock(),
            thumbnail_poll_job=None,
            thumbnail_work_queue=_QueueStub([]),
            thumbnail_result_queue=_QueueStub([]),
            schedule_thumbnail_result_poll=Mock(),
            make_strip_photo_from_raw=App.make_strip_photo_from_raw,
            session=SimpleNamespace(preview_paths=(Path("a.jpg"),)),
        )
        return fake

    @staticmethod
    def make_raw(width: int, height: int):
        from collections import namedtuple

        Raw = namedtuple("Raw", "width height data")
        return Raw(width, height, bytes(width * height * 4))


job_holder = {"job": 5}


class AsyncThumbnailStripTests(unittest.TestCase):
    def test_missing_visible_paths_are_posted_to_native_worker(self) -> None:
        fake = ThumbnailFakeFactory.make_async(App)
        paths = (Path("a.jpg"), Path("b.jpg"), Path("c.jpg"))
        fake.thumbnail_cache[Path("b.jpg")] = None  # previous decode failure

        App.request_missing_strip_thumbnails(fake, paths, (0, 3))

        fake.request_strip_thumbnail.assert_has_calls(
            [call(paths[0]), call(paths[2])], any_order=False
        )
        self.assertNotIn(call(paths[1]), fake.request_strip_thumbnail.call_args_list)

    def test_request_is_deduplicated_and_skipped_when_destroyed(self) -> None:
        fake = ThumbnailFakeFactory.make_async(App)
        path = Path("a.jpg")

        App.request_strip_thumbnail(fake, path)
        App.request_strip_thumbnail(fake, path)

        fake._ensure_thumbnail_worker.assert_called_once_with()

        fake.destroyed = True
        unexpected = Path("late.jpg")
        App.request_strip_thumbnail(fake, unexpected)
        self.assertNotIn(unexpected, fake.thumbnail_pending_requests)

    def test_decode_uses_native_engine_and_never_pillow(self) -> None:
        ThumbnailFakeFactory.make_async(App)
        native_raw = ThumbnailFakeFactory.make_raw(72, 48)

        with patch("gui_app.thumbnail_rgba", return_value=native_raw) as native_decode:
            result = App.decode_strip_thumbnail(Path("x.jpg"))

        native_decode.assert_called_once_with("x.jpg", fake_thumbnail_size)
        self.assertIs(result, native_raw)

        with patch("gui_app.thumbnail_rgba", side_effect=OSError("disk gone")):
            self.assertIsNone(App.decode_strip_thumbnail(Path("x.jpg")))

    def test_main_thread_never_decodes_with_pillow_for_missing_slots(self) -> None:
        fake = ThumbnailFakeFactory.make_async(App)
        paths = (Path("a.jpg"),)

        with patch(
            "gui_app.Image",
            create=True,
            side_effect=AssertionError("main thread must not decode thumbnails with Pillow"),
        ):
            App.request_missing_strip_thumbnails(fake, paths, (0, 1))
            self.assertIsNone(App.get_thumbnail_photo(fake, paths[0]))

    def test_raw_results_build_photos_on_the_main_thread(self) -> None:
        fake = ThumbnailFakeFactory.make_async(App)
        raw = ThumbnailFakeFactory.make_raw(72, 48)
        fake.thumbnail_raws[Path("a.jpg")] = raw

        with (
            patch("gui_app.Image.frombytes") as frombytes,
            patch("gui_app.ImageTk.PhotoImage") as photo_image,
        ):
            photo = App.get_thumbnail_photo(fake, Path("a.jpg"))

        frombytes.assert_called_once_with("RGBA", (72, 48), raw.data)
        photo_image.assert_called_once_with(frombytes.return_value)
        self.assertIs(photo, photo_image.return_value)
        self.assertIs(fake.thumbnail_cache[Path("a.jpg")], photo)

    def test_apply_results_builds_photo_and_refreshes_strip(self) -> None:
        fake = ThumbnailFakeFactory.make_async(App)

        class FakeRaw:
            width = 72
            height = 48
            data = bytes(72 * 48 * 4)

        raw_instance = FakeRaw()
        fake.decode_strip_thumbnail = Mock()
        fake.thumbnail_result_queue = _QueueStub([(Path("a.jpg"), raw_instance)])
        fake.thumbnail_pending_requests = {Path("a.jpg")}
        fake.make_strip_photo_from_raw = Mock(return_value=object())
        fake.prune_strip_thumbnail_state = Mock()
        fake.refresh_thumbnail_strip = Mock()
        fake.schedule_thumbnail_result_poll = Mock()

        App.drain_thumbnail_results(fake)

        self.assertNotIn(Path("a.jpg"), fake.thumbnail_pending_requests)
        self.assertIs(fake.thumbnail_raws[Path("a.jpg")], raw_instance)
        fake.prune_strip_thumbnail_state.assert_called_once_with({Path("a.jpg")})
        fake.refresh_thumbnail_strip.assert_called_once_with()
        fake.schedule_thumbnail_result_poll.assert_not_called()


class _QueueStub:
    def __init__(self, items):
        import queue

        self._items = list(items)
        self._empty = queue.Empty

    def get_nowait(self):
        if not self._items:
            raise self._empty()
        return self._items.pop(0)

    def put(self, item):
        self._items.append(item)


fake_thumbnail_size = 72


if __name__ == "__main__":
    unittest.main()
