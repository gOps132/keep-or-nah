from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock

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


if __name__ == "__main__":
    unittest.main()
