from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from PIL import Image

from tasks.models import Step
from tasks.weekly_board import board_ready
from tasks.weekly_runtime_150 import WeeklyRuntime
from tasks.weekly_matcher_150 import MatchResult


FIXTURES = Path(__file__).parent/'fixtures'


class ShopProgressTests(unittest.TestCase):
    def runner(self):
        runner = WeeklyRuntime(Mock(), Mock(), dry_run=False)
        runner._sleep_interruptible = Mock()
        runner._sleep_click_interval = Mock()
        runner._cap_result = Mock(return_value=False)
        return runner

    def test_reported_board_is_ready_but_shop_and_stage_overlay_are_not(self):
        self.assertTrue(board_ready(FIXTURES/'weekly-after-shop-reported.png'))
        self.assertFalse(board_ready(FIXTURES/'weekly-shop-reported.png'))
        self.assertFalse(board_ready(FIXTURES/'weekly-stage-goal-reported.png'))

    def test_actual_shop_to_board_transition_continues_94_95_96_in_order(self):
        runner = self.runner()
        state, clicks = ['shop'], []
        with Image.open(FIXTURES/'weekly-shop-reported.png') as shop, Image.open(
                FIXTURES/'weekly-after-shop-reported.png') as board, tempfile.TemporaryDirectory() as directory:
            shop = shop.resize(board.size)
            def capture(path, **_kwargs):
                (shop if state[0] == 'shop' else board).save(path)
            def click(x, y):
                clicks.append((state[0], x, y))
                state[0] = 'board' if state[0] == 'shop' else 'exit'
            runner.controller.screencap.side_effect = capture
            runner.controller.tap.side_effect = click
            with patch('tasks.weekly_runtime_150.APP_DIR', Path(directory)), patch('tasks.weekly_150.APP_DIR', Path(directory)):
                runner._run_image_cycle(Step(action='tap_image_cycle', templates=['menu94.png', 'menu95.png', 'menu96.png'],
                                             loop=False, timeout=.01))
        self.assertEqual([click[0] for click in clicks], ['shop', 'board'])
        self.assertEqual(state[0], 'exit')
        self.assertIn('menu94.png', runner._completed_templates)
        self.assertIn('menu95.png', runner._completed_templates)
        self.assertGreater(clicks[-1][1], 1750)
        self.assertLess(clicks[-1][2], 150)
        self.assertFalse(runner.stop_event.is_set())

    def test_board_alone_does_not_authorize_skipping_shop_steps(self):
        runner = self.runner()
        runner._board_verified = True
        runner._resume_template = 'menu94.png'
        matches = {'menu92.png': Mock(), 'menu96.png': Mock()}
        self.assertIsNone(runner._resolved_checkpoint('menu94.png', matches))
        runner._shop_closed_for = 'menu94.png'
        self.assertIsNone(runner._resolved_checkpoint('menu94.png', matches))

    def test_still_visible_confirmation_never_advances_to_exit(self):
        runner = self.runner()
        runner._board_verified = True
        runner._shop_closed_for = 'menu94.png'
        runner._completed_templates.update(('menu94.png', 'menu95.png'))
        self.assertIsNone(runner._resolved_checkpoint('menu94.png', {'menu94.png': Mock(), 'menu96.png': Mock()}))

    def test_unverified_forward_template_cannot_skip_required_confirmation(self):
        runner = self.runner()
        runner._find_image = Mock(side_effect=RuntimeError('not confirmed'))
        runner._probe_neighbors = Mock(return_value={'menu96.png': MatchResult(1750, 20, 70, 70, .99)})
        with self.assertRaisesRegex(RuntimeError, '前后各2个'):
            runner._wait_for_cycle_template(Step(action='tap_image', template='menu94.png'))
        runner.controller.tap.assert_not_called()
