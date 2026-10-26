from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from tasks.models import Step
from tasks.weekly_runtime_150 import WeeklyRuntime
from tasks.weekly_matcher_150 import MatchResult


ROOT = Path(__file__).resolve().parents[1]


class WeeklyExitRecoveryTests(unittest.TestCase):
    def runner(self):
        runner = WeeklyRuntime(Mock(), Mock(), dry_run=False)
        self.now = 0.
        runner._sleep_interruptible = lambda seconds: setattr(self, 'now', self.now+seconds)
        self.current = Step(action='tap_image', template='menu97.png', timeout=1)
        self.previous = Step(action='tap_image', template='menu96.png', timeout=1)
        return runner

    def wait(self, runner):
        with patch('tasks.weekly_runtime_150.time.monotonic', side_effect=lambda: self.now):
            return runner._wait_for_cycle_template(self.current, self.previous)

    def test_irregular_exit_buttons_use_center_without_random_corner_offsets(self):
        runner = self.runner()
        match = MatchResult(1480,28,48,48,.824)
        for name in ('menu96.png','menu97.png'):
            runner._expected_template = name
            for _ in range(30):
                self.assertEqual(runner._random_click_point(match,20,20), match.center)
        fixture = ROOT/'tests/fixtures/weekly-exit-board-reported.png'
        found = runner.matcher.find(fixture, 'menu96.png', .82)
        self.assertTrue(1480 < found.center[0] < 1530)
        self.assertTrue(25 < found.center[1] < 80)
        self.assertIsNone(runner._shop_close(fixture))

    def test_animation_longer_than_old_five_misses_is_waited_without_blind_click(self):
        runner = self.runner()
        def find(step):
            self.now += .6
            if step.template == 'menu97.png' and self.now >= 9:
                return (1400,700,.99)
            raise RuntimeError('transition has no clickable control')
        runner._find_image = Mock(side_effect=find)
        self.assertEqual(self.wait(runner),(1400,700,.99))
        self.assertGreater(self.now, 8)
        runner.controller.tap.assert_not_called()

    def test_ignored_initial_click_relocates_and_retries_only_confirmed_center(self):
        runner = self.runner()
        def find(step):
            self.now += .5
            if step.template == 'menu96.png':
                return (1504,52,.99)
            if runner.controller.tap.call_count:
                return (1400,700,.99)
            raise RuntimeError('initial click ignored')
        runner._find_image = Mock(side_effect=find)
        self.assertEqual(self.wait(runner),(1400,700,.99))
        runner.controller.tap.assert_called_once_with(1504,52)

    def test_immediate_next_page_does_not_add_a_fixed_wait_or_recick(self):
        runner = self.runner()
        runner._find_image = Mock(return_value=(1400,700,.99))
        self.assertEqual(self.wait(runner),(1400,700,.99))
        self.assertEqual(self.now,0)
        runner.controller.tap.assert_not_called()

    def test_persistent_page_has_bounded_retry_and_never_claims_success(self):
        runner = self.runner()
        def find(step):
            self.now += .5
            if step.template == 'menu96.png':
                return (1504,52,.99)
            raise RuntimeError('not responding')
        runner._find_image = Mock(side_effect=find)
        with self.assertRaisesRegex(RuntimeError,'仍未出现menu97'):
            self.wait(runner)
        self.assertEqual(runner.controller.tap.call_count,3)
        self.assertTrue(all(call.args == (1504,52) for call in runner.controller.tap.call_args_list))

    def test_stop_during_confirmation_does_not_send_a_retry(self):
        runner = self.runner()
        def find(_step):
            runner.stop_event.set()
            raise RuntimeError('cancelled')
        runner._find_image = Mock(side_effect=find)
        with self.assertRaisesRegex(RuntimeError,'停止'):
            self.wait(runner)
        runner.controller.tap.assert_not_called()

    def test_other_weekly_steps_keep_original_retry_sequence(self):
        runner = self.runner()
        step = Step(action='tap_image', template='menu5.png')
        with patch('tasks.weekly_150.TaskRunner._wait_for_cycle_template', return_value=(1,2,.99)) as original:
            self.assertEqual(runner._wait_for_cycle_template(step,self.previous),(1,2,.99))
        original.assert_called_once_with(step,self.previous)
