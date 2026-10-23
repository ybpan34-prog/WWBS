from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import Mock, patch

from PIL import Image

from tasks.daily_settlement import DailySettlementVision
from tasks.runner import TaskRunner


ROOT = Path(__file__).parents[1]
FIXTURE = ROOT/'tests/fixtures/daily-settlement-reported.png'


class Controller:
    def __init__(self):
        self.press_key = Mock()
        self.left_click = Mock()
        self.middle_click = Mock()
        self.release_keys = Mock()
        self.tap = Mock()

    def active_character_slot(self, _path):
        return None


class DailySettlementTests(unittest.TestCase):
    def runner(self, directory):
        runner = TaskRunner(Controller(), Mock(), dry_run=False)
        runner._fast_scales = lambda: [1280/1920]
        runner._capture_for_matching = lambda path: shutil.copy2(FIXTURE, path)
        runner._sleep_interruptible = Mock()
        return runner

    def test_reported_settlement_matches_at_multiple_sizes_with_cropped_client_width(self):
        vision = DailySettlementVision(ROOT/'templates/daily')
        with tempfile.TemporaryDirectory() as directory, Image.open(FIXTURE) as image:
            path = Path(directory)/'frame.png'
            for width in (1280, 1600, 1920, 2560):
                image.resize((width, round(image.height*width/image.width)), Image.Resampling.LANCZOS).save(path)
                result = vision.read(path, [width/1920])
                with self.subTest(width=width):
                    self.assertIsNotNone(result)
                    self.assertLess(abs(result.exit.center[0]-400*width/1280), 5)
                    self.assertLess(abs(result.restart.center[0]-824*width/1280), 5)

    def test_success_title_alone_or_only_one_action_is_not_a_full_settlement(self):
        with tempfile.TemporaryDirectory() as directory, Image.open(FIXTURE) as source:
            for box in ((240, 640, 1000, 740), (675, 640, 1000, 740), (480, 130, 760, 245)):
                image = source.copy()
                image.paste((55, 55, 55), box)
                path = Path(directory)/'partial.png'
                image.save(path)
                self.assertIsNone(DailySettlementVision(ROOT/'templates/daily').read(path, [.833]))
        self.assertIsNone(DailySettlementVision(ROOT/'templates/daily').read(
            ROOT/'tests/fixtures/daily-activity-zero.png', [.833]))

    def test_settlement_during_native_role_confirmation_sends_no_switch_or_attack(self):
        with tempfile.TemporaryDirectory() as directory, patch('tasks.combat_4c.APP_DIR', Path(directory)):
            runner = self.runner(directory)
            runner._rotation_end_check = runner._daily_battle_end_present
            self.assertFalse(runner._select_rotation_slot(1, verify=True))
            self.assertTrue(runner._rotation_battle_finished)
            self.assertTrue(runner._combat_input_cancel.is_set())
            runner.controller.press_key.assert_not_called()
            runner.controller.left_click.assert_not_called()

    def test_loading_into_existing_settlement_does_not_lock_or_attack(self):
        with tempfile.TemporaryDirectory() as directory, patch('tasks.other.APP_DIR', Path(directory)):
            runner = self.runner(directory)
            runner._run_daily_battle(Mock(timeout=180), 'E', 'R', 1)
            runner.controller.middle_click.assert_not_called()
            runner.controller.press_key.assert_not_called()
            self.assertIsNone(runner._rotation_end_check)

    def test_reward_collection_on_settlement_does_not_move_press_f_or_reenter_combat(self):
        with tempfile.TemporaryDirectory() as directory, patch('tasks.other.APP_DIR', Path(directory)):
            runner = self.runner(directory)
            self.assertTrue(runner._collect_daily_reward(1))
            runner.controller.press_key.assert_not_called()
            runner.controller.left_click.assert_not_called()
            runner.controller.release_keys.assert_called_once()

    def test_background_ending_callback_stops_input_before_main_loop_polls(self):
        runner = self.runner(None)
        runner._select_daily_slot_after_loading = Mock()
        runner._capture_for_matching = Mock()
        runner._read_daily_settlement = Mock(return_value=None)
        runner._daily_reward_stage_present = Mock(return_value=False)
        runner._daily_battle_task_present = Mock(return_value=True)
        def monitor(_inspect, _initial, _stop, *, on_result):
            on_result((True, False))
            return Mock(error=None, poll=Mock(return_value=None))
        with patch('tasks.other.BattleMonitor', side_effect=monitor):
            runner._run_daily_battle(Mock(timeout=180), 'E', 'R', 1)
        self.assertTrue(runner._combat_input_cancel.is_set())
        runner.controller.press_key.assert_not_called()
        runner.controller.left_click.assert_not_called()

    def test_loading_timeout_and_old_settlement_after_restart_never_force_role(self):
        for pending in (False, True):
            with self.subTest(pending=pending):
                runner = self.runner(None)
                runner._daily_restart_pending = pending
                runner._capture_for_matching = Mock()
                runner._daily_battle_end_present = Mock(return_value=pending)
                runner._daily_combat_visible = Mock(return_value=False)
                now = [0.]
                runner._sleep_interruptible = lambda seconds: now.__setitem__(0, now[0]+seconds)
                with patch('tasks.other.time.monotonic', side_effect=lambda: now[0]), \
                        self.assertRaisesRegex(RuntimeError, '不会在未知页面强制切人'):
                    runner._select_daily_slot_after_loading(Path('unused.png'))
                runner.controller.press_key.assert_not_called()
                self.assertFalse(runner._rotation_battle_finished)

    def test_stable_action_click_is_relocated_and_waits_for_page_transition(self):
        with tempfile.TemporaryDirectory() as directory, patch('tasks.other.APP_DIR', Path(directory)):
            runner = self.runner(directory)
            now = [0.]
            runner._sleep_interruptible = lambda seconds: now.__setitem__(0, now[0]+seconds)
            def capture(path):
                if runner.controller.tap.called:
                    Image.new('RGB', (1280, 825), 'black').save(path)
                else:
                    shutil.copy2(FIXTURE, path)
            runner._capture_for_matching = capture
            with patch('tasks.other.time.monotonic', side_effect=lambda: now[0]):
                runner._click_daily_settlement_action('restart')
            runner.controller.tap.assert_called_once()
            self.assertLess(abs(runner.controller.tap.call_args.args[0]-824), 5)
            self.assertGreaterEqual(now[0], .55)
            self.assertTrue(runner._daily_restart_pending)

    def test_ignored_settlement_button_has_three_verified_attempts_then_stops(self):
        with tempfile.TemporaryDirectory() as directory, patch('tasks.other.APP_DIR', Path(directory)):
            runner = self.runner(directory)
            now = [0.]
            runner._sleep_interruptible = lambda seconds: now.__setitem__(0, now[0]+seconds)
            with patch('tasks.other.time.monotonic', side_effect=lambda: now[0]), \
                    self.assertRaisesRegex(RuntimeError, '旧结算页'):
                runner._click_daily_settlement_action('restart')
            self.assertEqual(runner.controller.tap.call_count, 3)
            runner.controller.press_key.assert_not_called()


if __name__ == '__main__':
    unittest.main()
