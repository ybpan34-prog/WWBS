from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from PIL import Image

import app
from windows_client import ClientWindowController


class ResolutionAndPreviewTests(unittest.TestCase):
    def test_recommended_resolution_has_no_warning(self):
        self.assertEqual(ClientWindowController.resolution_warning(1920, 1080), '')

    def test_scaled_resolutions_warn_but_still_connect(self):
        for size in ((1280, 720), (1600, 900), (2560, 1440)):
            controller = ClientWindowController.__new__(ClientWindowController)
            controller.base_size = (1920, 1080)
            controller._find_window = Mock(return_value=1)
            controller._window_title = Mock(return_value='鸣潮')
            controller.client_size = Mock(return_value=size)
            controller.connect()
            self.assertIn('仍可正常使用', controller.resolution_notice)
            self.assertIn(f'{size[0]}×{size[1]}', controller.resolution_notice)

    def test_nonproportional_resolution_is_rejected(self):
        controller = ClientWindowController.__new__(ClientWindowController)
        controller.base_size = (1920, 1080)
        controller._find_window = Mock(return_value=1)
        controller._window_title = Mock(return_value='鸣潮')
        controller.client_size = Mock(return_value=(1280, 1024))
        with self.assertRaisesRegex(RuntimeError, '不是.*等比例'):
            controller.connect()
        self.assertIn('比例不一致', controller.resolution_notice)

    def test_error_preview_is_a_preserved_copy_of_last_capture(self):
        ui = app.App.__new__(app.App)
        ui.root = Mock()
        ui.root.after.side_effect = lambda _delay, action: action()
        ui._show_preview = Mock()
        ui._log = Mock()
        with tempfile.TemporaryDirectory() as directory, patch.object(app, 'APP_DIR', Path(directory)):
            path = Path(directory)/'last.png'
            Image.new('RGB', (160, 90), 'blue').save(path)
            controller = Mock(last_capture_path=path)
            ui._preserve_failure_preview(controller)
            Image.new('RGB', (160, 90), 'red').save(path)
            saved = Path(directory)/'_failure_preview.png'
            with Image.open(saved) as image:
                self.assertEqual(image.getpixel((0, 0)), (0, 0, 255))
            ui._show_preview.assert_called_once_with(saved, '报错时的游戏画面')
