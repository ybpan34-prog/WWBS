from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import Mock, patch

from PIL import Image

from tasks.daily_radio import DailyRadioVision
from tasks.daily_verified import VerifiedDailyNavigation
from tasks.match3_solver import ranked_moves, Tile, evaluate, runs
from tasks.match3_vision import read_board
from tasks.match3_task import Match3Session
from tasks.models import Step, WeeklyTask, TaskNeedsReview
from tasks.runner import TaskRunner


ROOT = Path(__file__).parents[1]
FIXTURES = ROOT/'tests/fixtures'
RADIO = FIXTURES/'daily-radio-rewards-reported.png'
TARGETS = FIXTURES/'match3-targets-reported.png'


class ReportedRadioTests(unittest.TestCase):
    def runner(self):
        runner = TaskRunner(Mock(), Mock(), dry_run=False)
        runner.matcher.templates_dir = ROOT/'templates/daily'
        return runner

    def test_reward_page_selected_icon_and_close_across_resolutions(self):
        with tempfile.TemporaryDirectory() as directory, Image.open(RADIO) as image:
            path = Path(directory)/'screen.png'
            for width in (1280, 1600, 1920, 2560):
                image.resize((width, round(width*9/16)), Image.Resampling.BILINEAR).save(path)
                runner = self.runner()
                runner._fast_scales = lambda: [width/1920]
                self.assertTrue(runner._terminal_destination_ready(path, '先约电台'), width)
                self.assertTrue(runner._daily_battlepass_tab_selected(path, 1), width)
                self.assertFalse(runner._daily_battlepass_tab_selected(path, 2), width)
                close = DailyRadioVision(ROOT/'templates/daily').close(path)
                self.assertIsNotNone(close, width)
                self.assertLess(abs(close.center[0]/width-.942), .006)

    def test_no_claim_is_not_failure_and_already_selected_tab_is_not_reclicked(self):
        runner = self.runner()
        runner._capture_for_matching = lambda path: shutil.copy2(RADIO, path)
        runner._sleep_interruptible = Mock()
        runner._fast_scales = lambda: [1600/1920]
        with tempfile.TemporaryDirectory() as directory, patch('tasks.other.APP_DIR', Path(directory)):
            runner._wait_daily_battlepass_tab(1)
        nav = VerifiedDailyNavigation(runner)
        with tempfile.TemporaryDirectory() as directory:
            nav._checks.screenshot = Path(directory)/'screen.png'
            self.assertFalse(nav._click_optional_daily_template('one_click_claim.png', '大众频道一键领取', threshold=.66))
        runner.controller.tap.assert_not_called()
        runner.controller.press_key.assert_not_called()

    def test_closing_reported_radio_relocates_x_and_confirms_terminal(self):
        runner = self.runner()
        state, now = {'closed': False}, [0.]
        def capture(path):
            shutil.copy2(FIXTURES/'daily-terminal-menu.png' if state['closed'] else RADIO, path)
        runner._capture_for_matching = capture
        runner._sleep_interruptible = lambda sec: now.__setitem__(0, now[0]+sec)
        runner._fast_scales = lambda: [1600/1920]
        runner.controller.tap.side_effect = lambda x, y: state.__setitem__('closed', x > 1450 and y < 90)
        nav = VerifiedDailyNavigation(runner)
        with tempfile.TemporaryDirectory() as directory, patch('tasks.daily_checks.time.monotonic', side_effect=lambda: now[0]):
            nav._checks.screenshot = Path(directory)/'screen.png'
            self.assertTrue(nav._close_page())
        runner.controller.tap.assert_called_once()
        self.assertTrue(state['closed'])

    def test_radio_header_does_not_match_guide_or_incomplete_header(self):
        vision = DailyRadioVision(ROOT/'templates/daily')
        for name in ('daily-activity-zero.png', 'daily-tacet-selected-reported.png', 'daily-terminal-menu.png'):
            self.assertFalse(vision.page(FIXTURES/name), name)


class OrbInteractionTests(unittest.TestCase):
    def runner(self, directory):
        path = Path(directory)/'_runtime_screenshot.png'
        Image.new('RGB', (1920, 1080), (20, 30, 40)).save(path)
        runner = TaskRunner(Mock(), Mock(), dry_run=False)
        runner._capture_for_matching = Mock()
        runner._sleep_interruptible = Mock()
        runner._read_daily_settlement = Mock(return_value=None)
        runner._daily_combat_visible = Mock(return_value=False)
        runner._daily_reward_dialog_present = Mock(return_value=False)
        runner._claim_daily_double_reward = Mock()
        return runner

    def test_missed_f_relocates_and_approaches_before_second_interaction(self):
        with tempfile.TemporaryDirectory() as directory, patch('tasks.other.APP_DIR', Path(directory)):
            runner = self.runner(directory)
            runner._find_daily_reward_prompt = Mock(side_effect=[Mock(), None, Mock()])
            runner._daily_reward_orb_location = Mock(return_value=(960, 300, .95))
            runner._wait_daily_reward_dialog = Mock(side_effect=['', 'claim'])
            self.assertTrue(runner._collect_daily_reward(1))
        self.assertEqual(runner.controller.press_key.call_args_list[0].args, ('F', 100))
        self.assertEqual(runner.controller.press_key.call_count, 2)
        runner.controller.press_keys.assert_called_once_with(('W',), 500)
        runner._claim_daily_double_reward.assert_called_once_with(1)

    def test_two_failed_interactions_never_claim_or_report_success(self):
        with tempfile.TemporaryDirectory() as directory, patch('tasks.other.APP_DIR', Path(directory)):
            runner = self.runner(directory)
            runner._find_daily_reward_prompt = Mock(return_value=Mock())
            runner._daily_reward_orb_location = Mock(return_value=(960, 300, .95))
            runner._wait_daily_reward_dialog = Mock(return_value='')
            with self.assertRaisesRegex(RuntimeError, '未当作领取成功'):
                runner._collect_daily_reward(1)
        self.assertEqual(runner.controller.press_key.call_count, 2)
        runner._claim_daily_double_reward.assert_not_called()

    def test_dialog_requires_two_new_frames_and_transient_one_does_not_confirm(self):
        for frames, expected in (([False, True, False, True, True], 'claim'), ([False, True]+[False]*9, '')):
            with tempfile.TemporaryDirectory() as directory, patch('tasks.other.APP_DIR', Path(directory)):
                runner = self.runner(directory)
                now = [0.]
                runner._sleep_interruptible = lambda sec: now.__setitem__(0, now[0]+sec)
                runner._daily_reward_dialog_present = Mock(side_effect=frames+[False]*20)
                with patch('tasks.other.time.monotonic', side_effect=lambda: now[0]):
                    self.assertEqual(runner._wait_daily_reward_dialog(timeout=1.5), expected)
                self.assertGreaterEqual(runner._capture_for_matching.call_count, 5)
                runner._claim_daily_double_reward.assert_not_called()
                runner.controller.press_key.assert_not_called()

    def test_combat_return_and_stop_during_f_confirmation_never_claim(self):
        for combat in (True, False):
            with tempfile.TemporaryDirectory() as directory, patch('tasks.other.APP_DIR', Path(directory)):
                runner = self.runner(directory)
                runner._find_daily_reward_prompt = Mock(return_value=Mock())
                runner._daily_reward_orb_location = Mock(return_value=(960, 300, .95))
                def wait():
                    if not combat:
                        runner.stop_event.set()
                    return 'combat' if combat else ''
                runner._wait_daily_reward_dialog = wait
                self.assertFalse(runner._collect_daily_reward(1))
                runner._claim_daily_double_reward.assert_not_called()
                self.assertEqual(runner.controller.press_key.call_count, 1)


class TargetBoardTests(unittest.TestCase):
    def test_reported_target_board_reads_all_cells_and_never_swaps_target(self):
        with tempfile.TemporaryDirectory() as directory, Image.open(TARGETS) as image:
            for width in (1280, 1600, 1920, 2560):
                path = Path(directory)/'screen.png'
                image.resize((width, round(width*9/16)), Image.Resampling.BILINEAR).save(path)
                diagnostics = {}
                frame = read_board(path, diagnostics)
                self.assertIsNotNone(frame, diagnostics)
                targets = {(r, c) for r in range(7) for c in range(8) if frame.tiles[r][c].special == 'target'}
                self.assertEqual(targets, {(1, 1), (1, 6), (5, 1), (5, 6)})
                self.assertTrue(all(frame.tiles[r][c].health == 3 for r, c in targets))
                moves = ranked_moves(frame.tiles)
                self.assertTrue(moves)
                self.assertFalse(any(move.start in targets or move.end in targets for move in moves))
                self.assertFalse(runs(frame.tiles))

    def test_goal_tiles_do_not_form_three_of_a_kind_or_allow_direct_swaps(self):
        board = [[Tile((r+c)%5) for c in range(8)] for r in range(7)]
        board[0][:3] = [Tile(6, 'target', 3)]*3
        self.assertFalse(runs(board))
        self.assertIsNone(evaluate(board, (0, 2), (1, 2)))

    def test_unknown_board_explains_cell_and_is_not_logged_as_task_completion(self):
        runner = TaskRunner(Mock(), Mock(), dry_run=False)
        runner.template_root = ROOT/'templates/match3'
        task = WeeklyTask(name='无音消除', template_group='match3', steps=[Step(action='match3_puzzle')])
        with patch.object(Match3Session, 'stable_board', return_value=None):
            with self.assertRaises(TaskNeedsReview):
                runner.run_task(task)
        self.assertFalse(any('完成任务:' in str(call.args[0]) for call in runner.log.call_args_list))
        with tempfile.TemporaryDirectory() as directory, Image.open(TARGETS) as image:
            image.paste('black', (740, 130, 810, 200))
            path = Path(directory)/'unknown.png'
            image.save(path)
            details = {}
            partial = read_board(path, details)
            self.assertIsNotNone(partial)
            self.assertLess(partial.tiles[0][0].color, 0)
            self.assertIn((0, 0), details['unknown'])
