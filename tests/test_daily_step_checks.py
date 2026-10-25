from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from tasks.daily_checks import DailyStepChecks


class DailyStepCheckTests(unittest.TestCase):
    def setup_checks(self):
        runner = Mock()
        runner.stop_event.is_set.return_value = False
        now = [0.]
        runner._sleep_interruptible.side_effect = lambda seconds: now.__setitem__(0, now[0]+seconds)
        return DailyStepChecks(runner, Path('screen.png')), runner, now

    def test_already_at_destination_requires_two_frames_and_never_reclicks(self):
        checks, runner, now = self.setup_checks()
        action = Mock(return_value=True)
        with patch('tasks.daily_checks.time.monotonic', side_effect=lambda: now[0]):
            self.assertTrue(checks.transition('exit', Mock(return_value=True), action))
        self.assertEqual(runner._capture_for_matching.call_count, 2)
        action.assert_not_called()

    def test_ignored_action_is_relocated_and_retried_before_advancing(self):
        checks, runner, now = self.setup_checks()
        action = Mock(return_value=True)
        with patch('tasks.daily_checks.time.monotonic', side_effect=lambda: now[0]):
            self.assertTrue(checks.transition('guide', lambda _p: action.call_count >= 2, action))
        self.assertEqual(action.call_count, 2)
        self.assertGreater(runner._capture_for_matching.call_count, 3)

    def test_timeout_has_bounded_clicks_and_cancel_after_capture_never_clicks(self):
        checks, runner, now = self.setup_checks()
        action = Mock(return_value=True)
        with patch('tasks.daily_checks.time.monotonic', side_effect=lambda: now[0]), self.assertRaisesRegex(RuntimeError, '未继续后续'):
            checks.transition('unknown', lambda _p: False, action, timeout=8)
        self.assertEqual(action.call_count, 3)
        checks, runner, now = self.setup_checks()
        runner._capture_for_matching.side_effect = lambda _p: setattr(runner.stop_event.is_set, 'return_value', True)
        action = Mock()
        self.assertFalse(checks.transition('cancelled', lambda _p: False, action))
        action.assert_not_called()
