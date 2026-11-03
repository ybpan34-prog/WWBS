from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from tasks.models import Step
from tasks.weekly_matcher_150 import MatchResult
from tasks.weekly_runtime_150 import WeeklyRuntime, WeeklyAdvanced


class Menu2OnceTests(unittest.TestCase):
    def runner(self):
        runner = WeeklyRuntime(Mock(), Mock(), dry_run=False)
        runner._capture_for_matching = Mock()
        runner._fast_scales = Mock(return_value=[1.])
        runner._sleep_interruptible = Mock()
        runner._sleep_click_interval = Mock()
        return runner

    def test_missing_menu2_has_one_capture_and_one_match_attempt(self):
        runner = self.runner()
        runner.matcher.find = Mock(side_effect=RuntimeError('missing'))
        runner._probe_neighbors = Mock(return_value={})
        with self.assertRaises(RuntimeError):
            runner._wait_for_cycle_template(Step(action='tap_image', template='menu2.png', timeout=8))
        self.assertEqual(runner.matcher.find.call_count, 1)
        self.assertEqual(runner._capture_for_matching.call_count, 1)

    def test_second_call_cannot_search_menu2_again_in_same_round(self):
        runner = self.runner()
        runner.matcher.find = Mock(return_value=MatchResult(10, 20, 80, 40, .99))
        step = Step(action='tap_image', template='menu2.png')
        runner._find_image(step)
        with self.assertRaisesRegex(RuntimeError, '一次'):
            runner._find_image(step)
        self.assertEqual(runner.matcher.find.call_count, 1)

    def test_neighbor_reviews_never_match_menu2(self):
        runner = self.runner()
        runner.matcher.find = Mock(side_effect=RuntimeError('missing'))
        with tempfile.TemporaryDirectory() as folder, patch('tasks.weekly_runtime_150.APP_DIR', Path(folder)), patch(
                'tasks.weekly_board.board_ready', return_value=False):
            for name in ('menu2.png', 'menu3.png', 'menu4.png'):
                runner._probe_neighbors(name)
        self.assertFalse(any(call.args[1] == 'menu2.png' for call in runner.matcher.find.call_args_list))

    def test_absent_menu2_can_continue_from_verified_menu4(self):
        runner = self.runner()
        runner.matcher.find = Mock(side_effect=RuntimeError('missing'))
        runner._probe_neighbors = Mock(return_value={'menu4.png': Mock()})
        with self.assertRaises(WeeklyAdvanced) as advanced:
            runner._wait_for_cycle_template(Step(action='tap_image', template='menu2.png'))
        self.assertEqual(advanced.exception.template, 'menu4.png')
        self.assertEqual(runner.matcher.find.call_count, 1)

    def test_limit_resets_for_a_new_round(self):
        runner = self.runner()
        runner.matcher.find = Mock(return_value=MatchResult(10, 20, 80, 40, .99))
        runner._click_cycle_template = Mock()
        runner._verify_final_cycle_click = Mock()
        runner.max_cycles = 2
        runner._run_image_cycle(Step(action='tap_image_cycle', templates=['menu2.png'], loop=True))
        self.assertEqual(runner.matcher.find.call_count, 2)
