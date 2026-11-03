from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from PIL import Image

from tasks.weekly_stage import stage_goal_confirm
from tasks.weekly_runtime_150 import WeeklyRuntime


FIXTURE = Path(__file__).parent/'fixtures/weekly-stage-goal-reported.png'


class StageGoalTests(unittest.TestCase):
    def test_reported_dialog_and_scaled_resolutions_find_only_confirm(self):
        with tempfile.TemporaryDirectory() as folder, Image.open(FIXTURE) as image:
            for width in (1280, 1600, 1920, 2560):
                path = Path(folder)/'screen.png'
                image.resize((width, round(width*9/16))).save(path)
                point = stage_goal_confirm(path)
                self.assertIsNotNone(point, width)
                self.assertAlmostEqual(point[0]/width, .5, delta=.005)
                self.assertAlmostEqual(point[1]/(width*9/16), 713/1080, delta=.006)

    def test_unrelated_confirm_and_title_without_button_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder, Image.open(FIXTURE) as image:
            path = Path(folder)/'screen.png'
            for box in ((750, 300, 1150, 430), (750, 620, 1170, 780)):
                changed = image.copy()
                changed.paste('black', box)
                changed.save(path)
                self.assertIsNone(stage_goal_confirm(path))

    def test_every_third_cycle_popup_is_closed_and_run_continues(self):
        runner = WeeklyRuntime(Mock(), Mock(), dry_run=False)
        runner._sleep_interruptible = Mock()
        runner._cap_result = Mock(return_value=False)
        runner._shop_close = Mock(return_value=None)
        runner._expected_template = 'menu96.png'
        state = [False]
        with Image.open(FIXTURE) as image, tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'screen.png'
            blank = Image.new('RGB', image.size, 'black')
            def capture(target, **_kwargs):
                (image if state[0] else blank).save(target)
            def click(x, y):
                self.assertAlmostEqual(x, 960, delta=5)
                self.assertAlmostEqual(y, 713, delta=5)
                state[0] = False
            runner.controller.screencap.side_effect = capture
            runner.controller.tap.side_effect = click
            for cycle in range(1, 10):
                state[0] = cycle % 3 == 0
                runner._capture_for_matching(path)
                self.assertFalse(state[0])
                self.assertFalse(runner.stop_event.is_set())
            self.assertEqual(runner.controller.tap.call_count, 3)

    def test_ignored_confirmation_stops_without_clicking_background(self):
        runner = WeeklyRuntime(Mock(), Mock(), dry_run=False)
        now = [0.]
        runner._sleep_interruptible = lambda seconds: now.__setitem__(0, now[0]+seconds)
        with patch('tasks.weekly_stage.stage_goal_confirm', return_value=(960, 713)), patch(
                'tasks.weekly_runtime_150.time.monotonic', side_effect=lambda: now[0]):
            with self.assertRaisesRegex(RuntimeError, '未复核关闭'):
                runner._dismiss_stage_goal(FIXTURE)
        self.assertTrue(runner.stop_event.is_set())
        self.assertEqual(runner.controller.tap.call_count, 3)
        self.assertTrue(all(call.args == (960, 713) for call in runner.controller.tap.call_args_list))

    def test_manual_stop_before_confirmation_sends_no_input(self):
        runner = WeeklyRuntime(Mock(), Mock(), dry_run=False)
        runner._sleep_interruptible = lambda _seconds: runner.stop_event.set()
        with self.assertRaisesRegex(RuntimeError, '停止'):
            runner._dismiss_stage_goal(FIXTURE)
        runner.controller.tap.assert_not_called()
