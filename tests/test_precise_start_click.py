import unittest
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

from PIL import Image

import windows_client as client


class PreciseClickTests(unittest.TestCase):
    def test_stale_guide_row_cannot_click_third_slot_after_page_changes(self):
        controller = self.controller((1475, 965))
        fixture = Path(__file__).parent/'fixtures/daily-team-start-full-reported.png'
        with tempfile.TemporaryDirectory() as directory:
            previous = Path(directory)/'previous.png'
            Image.new('RGB', (1600, 939), (180, 180, 180)).save(previous)
            controller.last_capture_path = previous
            def capture(path, **_kwargs):
                with Image.open(fixture) as image:
                    image.save(path)
                controller.last_capture_path = path
            controller.screencap = capture
            with self.assertRaisesRegex(RuntimeError, '拒绝旧页面坐标'):
                controller.tap_team_guarded(1432, 424)
        controller._send_mouse_button.assert_not_called()

    def test_fresh_team_button_is_allowed_and_geometry_change_is_rejected(self):
        controller = self.controller((1475, 965))
        fixture = Path(__file__).parent/'fixtures/daily-team-start-full-reported.png'
        with tempfile.TemporaryDirectory() as directory:
            previous = Path(directory)/'previous.png'
            with Image.open(fixture) as image:
                image.save(previous)
            controller.last_capture_path = previous
            def capture(path, **_kwargs):
                with Image.open(fixture) as image:
                    image.save(path)
                controller.last_capture_path = path
            controller.screencap = capture
            with patch.object(client.time, 'sleep'):
                controller.tap_team_guarded(1374, 865)
            self.assertEqual(controller._send_mouse_button.call_count, 2)
            controller._send_mouse_button.reset_mock()
            def moved(path, **kwargs):
                capture(path, **kwargs)
                controller.last_screen_bbox = (200, 100, 1800, 1039)
            controller.screencap = moved
            with self.assertRaisesRegex(RuntimeError, '窗口位置或尺寸已变化'):
                controller.tap_precise(1374, 865)
            controller._send_mouse_button.assert_not_called()

    def controller(self, cursor):
        controller = client.ClientWindowController.__new__(client.ClientWindowController)
        controller._input_stopped = Mock(return_value=False)
        controller._ensure_window = Mock()
        controller.screenshot_to_client = Mock(return_value=(1375, 865))
        controller._screenshot_point_to_desktop = Mock(return_value=(1475, 965))
        controller._clamp_to_virtual_screen = lambda x, y: (x, y)
        controller._focus_window = Mock()
        controller._set_cursor_with_dpi_fallback = Mock(return_value=(True, 1475, 965, 'test'))
        controller.cursor_position = Mock(return_value=cursor)
        controller._send_mouse_button = Mock()
        controller.last_capture_size = (1600, 939)
        controller.last_screen_bbox = (100, 100, 1700, 1039)
        return controller

    def test_dpi_or_movement_offset_never_clicks_third_portrait(self):
        controller = self.controller((1475, 750))
        with patch.object(client.time, 'sleep'), self.assertRaisesRegex(RuntimeError, '未落在目标中心'):
            controller.tap_precise(1375, 865)
        controller._send_mouse_button.assert_not_called()

    def test_verified_center_sends_one_click(self):
        controller = self.controller((1475, 965))
        with patch.object(client.time, 'sleep'):
            controller.tap_precise(1375, 865)
        self.assertEqual([c.args[0] for c in controller._send_mouse_button.call_args_list],
                         [client.MOUSEEVENTF_LEFTDOWN, client.MOUSEEVENTF_LEFTUP])
