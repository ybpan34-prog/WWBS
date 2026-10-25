import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from PIL import Image

from tasks.daily_verified import VerifiedDailyNavigation
from tasks.runner import TaskRunner


class DailyVerifiedTests(unittest.TestCase):
    def navigation(self):
        runner = TaskRunner(Mock(), Mock(), dry_run=False)
        nav = VerifiedDailyNavigation(runner)
        return nav, runner

    def test_cancelled_menu_never_attempts_next_destination(self):
        nav, runner = self.navigation()
        runner._open_menu = Mock(return_value=False)
        runner._enter = Mock()
        self.assertFalse(nav._open_terminal_destination('索拉指南'))
        runner._enter.assert_not_called()

    def test_already_world_exit_does_not_wait_for_or_click_settlement(self):
        nav, runner = self.navigation()
        runner._world = Mock(return_value=True)
        runner._capture_for_matching = Mock()
        runner._sleep_interruptible = Mock()
        nav._click_daily_template('exit_instance.png', 'exit')
        self.assertEqual(runner._capture_for_matching.call_count, 2)
        runner.controller.tap.assert_not_called()

    def test_start_button_detector_rejects_world_and_tacet_list(self):
        nav, runner = self.navigation()
        runner._world = Mock(return_value=True)
        self.assertIsNone(nav._start_target('not-opened.png'))
        self.assertIsNone(nav._ocr)

    def test_stable_battle_does_not_wait_five_seconds_for_absent_optional_dialog(self):
        nav, runner = self.navigation()
        runner._capture_for_matching = Mock()
        runner._sleep_interruptible = Mock()
        runner._match = Mock(return_value=None)
        runner._normal = Mock(return_value=True)
        self.assertFalse(nav._click_optional_daily_template('insufficient_continue.png', 'continue', timeout=5))
        self.assertEqual(runner._capture_for_matching.call_count, 2)
        runner.controller.tap.assert_not_called()

    def test_unknown_page_cannot_be_treated_as_no_optional_rewards(self):
        nav, runner = self.navigation()
        runner._capture_for_matching = Mock()
        runner._match = Mock(return_value=None)
        runner._normal = Mock(return_value=False)
        now = [0.]
        runner._sleep_interruptible = lambda seconds: now.__setitem__(0, now[0]+seconds)
        with patch('tasks.daily_verified.time.monotonic', side_effect=lambda: now[0]):
            with self.assertRaisesRegex(RuntimeError, '等待并复核'):
                nav._click_optional_daily_template('one_click_claim.png', 'radio', timeout=3)
        runner.controller.tap.assert_not_called()

    def test_tap_does_not_reach_controller_after_cancel(self):
        nav, runner = self.navigation()
        runner.stop_event.set()
        self.assertFalse(nav._tap((800, 400)))
        runner.controller.tap.assert_not_called()

    def test_disabled_grey_claim_is_not_retried(self):
        nav, runner = self.navigation()
        runner._find_daily_template = Mock(return_value=Mock(x=10, y=10, width=100, height=30))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'screen.png'
            Image.new('RGB', (200, 100), (130, 130, 130)).save(path)
            self.assertIsNone(nav._match(path, 'one_click_claim.png'))
