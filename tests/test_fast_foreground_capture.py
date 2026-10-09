import unittest
from unittest.mock import Mock, patch

from PIL import Image

import windows_client as client


class ForegroundCaptureTests(unittest.TestCase):
    def controller(self):
        controller = client.ClientWindowController.__new__(client.ClientWindowController)
        controller.hwnd = 123
        controller._client_bbox = Mock(return_value=(0, 0, 1920, 1080))
        controller._capture_has_content = Mock(return_value=True)
        return controller

    def test_already_focused_capture_skips_refocus_and_long_sleep(self):
        controller = self.controller()
        frame = Image.new('RGB', (1920, 1080))
        with patch.object(client, 'user32') as api, patch.object(client.time, 'sleep') as sleep, \
                patch.object(client.ImageGrab, 'grab', return_value=frame):
            api.GetForegroundWindow.return_value = 123
            api.IsIconic.return_value = False
            image, bounds = controller._capture_foreground_client()
            api.SetForegroundWindow.assert_not_called()
            sleep.assert_called_once_with(.03)
        self.assertEqual(image.size, (1920, 1080))
        self.assertEqual(bounds, (0, 0, 1920, 1080))

    def test_focus_failure_never_captures_another_window(self):
        controller = self.controller()
        controller._focus_window = Mock()
        with patch.object(client, 'user32') as api, patch.object(client.time, 'sleep'), \
                patch.object(client.ImageGrab, 'grab') as grab:
            api.GetForegroundWindow.return_value = 456
            with self.assertRaisesRegex(RuntimeError, '未获得焦点'):
                controller._capture_foreground_client()
            grab.assert_not_called()
        self.assertEqual(controller._focus_window.call_count, 2)

    def test_blank_first_frame_retries_with_settle_wait(self):
        controller = self.controller()
        controller._capture_has_content.side_effect = [False, True]
        with patch.object(client, 'user32') as api, patch.object(client.time, 'sleep') as sleep, \
                patch.object(client.ImageGrab, 'grab', return_value=Image.new('RGB', (1920, 1080))) as grab:
            api.GetForegroundWindow.return_value = 123
            api.IsIconic.return_value = False
            controller._capture_foreground_client()
        self.assertEqual(grab.call_count, 2)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [.03, .12])


if __name__ == '__main__':
    unittest.main()
