from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import Mock, patch

from PIL import Image

import windows_client as client
from tasks.weekly_exit import weekly_exit_match


FIXTURE = Path(__file__).parent/'fixtures/weekly-after-shop-reported.png'


class WeeklyExitTests(unittest.TestCase):
    def test_exit_is_found_in_small_corner_at_supported_scales(self):
        with Image.open(FIXTURE) as image, tempfile.TemporaryDirectory() as folder:
            for width in (1280, 1600, 1920, 2560):
                path = Path(folder)/'screen.png'
                image.resize((width, round(width*9/16))).save(path)
                result = weekly_exit_match(path)
                self.assertGreater(result.score, .95)
                self.assertAlmostEqual(result.center[0]/width, 1807/1920, delta=.003)

    def test_identical_exit_shape_in_currency_bar_is_not_a_candidate(self):
        with Image.open(FIXTURE) as image, tempfile.TemporaryDirectory() as folder:
            exit_icon = image.crop((1776, 25, 1838, 96))
            image.paste('black', (1770, 20, 1850, 105))
            image.paste(exit_icon, (1500, 25))
            path = Path(folder)/'screen.png'
            image.save(path)
            with self.assertRaises(RuntimeError):
                weekly_exit_match(path)

    def controller(self, cursor=(1907, 160)):
        controller = client.ClientWindowController.__new__(client.ClientWindowController)
        controller._input_stopped = Mock(return_value=False)
        controller._ensure_window = Mock()
        controller._focus_window = Mock()
        controller.screenshot_to_client = lambda x, y: (x, y)
        controller._screenshot_point_to_desktop = lambda x, y: (x+100, y+100)
        controller._clamp_to_virtual_screen = lambda x, y: (x, y)
        controller._set_cursor_with_dpi_fallback = Mock(return_value=(True, 1907, 160, 'test'))
        controller.cursor_position = Mock(return_value=cursor)
        controller._send_mouse_button = Mock()
        controller.last_capture_path = FIXTURE
        controller.last_capture_size = (1920, 1080)
        controller.last_screen_bbox = (100, 100, 2020, 1180)
        controller._client_bbox = Mock(return_value=controller.last_screen_bbox)
        def capture(path, **_kwargs):
            shutil.copy2(FIXTURE, path)
            controller.last_capture_path = path
        controller.screencap = Mock(side_effect=capture)
        return controller

    def invoke(self, controller):
        with tempfile.TemporaryDirectory() as folder, patch.object(client.time, 'sleep'):
            controller.last_capture_path = Path(folder)/'previous.png'
            return controller.tap_weekly_exit()

    def test_two_fresh_frames_and_verified_center_send_only_one_click(self):
        controller = self.controller()
        result = self.invoke(controller)
        self.assertEqual(result['target'], (1907, 160))
        self.assertEqual(controller.screencap.call_count, 2)
        self.assertEqual(controller._send_mouse_button.call_count, 2)

    def test_cursor_landing_on_currency_bar_never_sends_click(self):
        controller = self.controller(cursor=(1640, 160))
        with self.assertRaisesRegex(RuntimeError, '未落在目标中心'):
            self.invoke(controller)
        controller._send_mouse_button.assert_not_called()

    def test_window_moving_after_capture_never_sends_click(self):
        controller = self.controller()
        controller._client_bbox.return_value = (250, 100, 2170, 1180)
        with self.assertRaisesRegex(RuntimeError, '窗口已移动'):
            self.invoke(controller)
        controller._send_mouse_button.assert_not_called()

    def test_window_moving_between_two_frames_is_rejected(self):
        controller = self.controller()
        capture = controller.screencap.side_effect
        count = [0]
        def moved(path, **kwargs):
            capture(path, **kwargs)
            count[0] += 1
            if count[0] == 2:
                controller.last_screen_bbox = (250, 100, 2170, 1180)
        controller.screencap.side_effect = moved
        with self.assertRaisesRegex(RuntimeError, '窗口位置变化'):
            self.invoke(controller)
        controller._send_mouse_button.assert_not_called()

    def test_offscreen_exit_is_not_clamped_onto_another_control(self):
        controller = self.controller()
        controller._clamp_to_virtual_screen = lambda x, y: (1640, y)
        with self.assertRaisesRegex(RuntimeError, '超出屏幕范围'):
            self.invoke(controller)
        controller._send_mouse_button.assert_not_called()

    def test_runtime_discards_old_currency_coordinate_and_uses_native_exit_guard(self):
        from tasks.models import Step
        from tasks.weekly_runtime_150 import WeeklyRuntime
        controller = self.controller()
        runner = WeeklyRuntime(controller, Mock(), dry_run=False)
        with tempfile.TemporaryDirectory() as folder, patch.object(client.time, 'sleep'):
            controller.last_capture_path = Path(folder)/'previous.png'
            result = runner._click_cycle_template(Step(action='tap_image', template='menu96.png'), 1500, 60)
        self.assertEqual(result['target'], (1907, 160))
        self.assertEqual(controller.screencap.call_count, 2)
        self.assertEqual(controller._send_mouse_button.call_count, 2)
