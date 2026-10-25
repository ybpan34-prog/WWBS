from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import Mock, patch

from PIL import Image
from tasks.runner import TaskRunner
from tasks.tacet_navigation import selected_tacet_label, tacet_card_list_present


FIXTURES = Path(__file__).parent/'fixtures'


class TacetRecheckTests(unittest.TestCase):
    def test_reported_selected_page_at_multiple_sizes_and_activity_page_rejected(self):
        with tempfile.TemporaryDirectory() as directory, Image.open(FIXTURES/'daily-tacet-selected-reported.png') as source:
            for width in (1280, 1600, 1920, 2560):
                with self.subTest(width=width):
                    path = Path(directory)/'screen.png'
                    source.resize((width, round(width*9/16)), Image.Resampling.BILINEAR).save(path)
                    self.assertIsNotNone(selected_tacet_label(path))
                    self.assertTrue(tacet_card_list_present(path))
        self.assertIsNone(selected_tacet_label(FIXTURES/'daily-guide-activity-wrong-category.png'))

    def test_already_selected_is_confirmed_twice_without_another_click(self):
        runner = TaskRunner(Mock(), Mock(), dry_run=False)
        path = FIXTURES/'daily-tacet-selected-reported.png'
        runner._capture_size = Mock(return_value=(path, 1600, 900))
        runner._sleep_interruptible = Mock()
        with patch('tasks.other.APP_DIR', FIXTURES), patch('tasks.other.tacet_card_list_present', return_value=True):
            # The actual path argument supplied by capture is fixed below.
            runner._guide_tacet_section_selected = lambda *_args: selected_tacet_label(path) is not None
            runner._select_daily_tacet_section()
        self.assertEqual(runner._capture_size.call_count, 2)
        runner.controller.tap.assert_not_called()

    def test_temporary_blank_frames_are_rechecked_before_any_error(self):
        with tempfile.TemporaryDirectory() as directory, patch('tasks.other.APP_DIR', Path(directory)):
            path = Path(directory)/'_runtime_screenshot.png'
            runner = TaskRunner(Mock(), Mock(), dry_run=False)
            count = [0]
            def capture(_path):
                count[0] += 1
                if count[0] < 3:
                    Image.new('RGB', (1600, 900)).save(path)
                else:
                    shutil.copy2(FIXTURES/'daily-tacet-selected-reported.png', path)
                return path, 1600, 900
            runner._capture_size = capture
            runner._find_daily_template = Mock(return_value=None)
            runner._sleep_interruptible = Mock()
            runner._select_daily_tacet_section()
            self.assertEqual(count[0], 4)
            runner.controller.tap.assert_not_called()
