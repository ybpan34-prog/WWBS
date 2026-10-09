import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from PIL import Image

import app


class RewardHintTests(unittest.TestCase):
    def test_user_sidebar_is_detected_at_supported_window_sizes(self):
        fixture = Path(__file__).parent / "fixtures" / "4c-reward-sidebar.png"
        with tempfile.TemporaryDirectory() as directory:
            screen = Path(directory) / "screen.png"
            with Image.open(fixture) as sidebar:
                base = Image.new("RGB", (1920, 1080), (35, 40, 48))
                base.paste(sidebar, (0, 0))
            runner = app.TaskRunner(Mock(), lambda _: None)
            for scale in (1.0, 0.8, 1.2):
                with self.subTest(scale=scale):
                    base.resize((round(1920 * scale), round(1080 * scale)),
                                Image.Resampling.BILINEAR).save(screen)
                    self.assertTrue(runner._4c_reward_hint_present(screen))

    def test_missing_hint_and_right_hand_reward_prompt_are_not_completion(self):
        fixture = Path(__file__).parent / "fixtures" / "4c-reward-sidebar.png"
        with tempfile.TemporaryDirectory() as directory:
            screen = Path(directory) / "screen.png"
            with Image.open(fixture) as sidebar:
                base = Image.new("RGB", (1920, 1080), (35, 40, 48))
                base.paste(sidebar, (0, 0))
                # Replace only the hint with neighboring real floor pixels.
                base.paste(sidebar.crop((180, 269, 331, 298)), (0, 269))
            runner = app.TaskRunner(Mock(), lambda _: None)
            base.save(screen)
            self.assertFalse(runner._4c_reward_hint_present(screen))
            with Image.open(app.TEMPLATES_DIR / "4c" / "claim_reward_hint.png") as prompt:
                base.paste(prompt, (1400, 450))
            base.save(screen)
            self.assertFalse(runner._4c_reward_hint_present(screen))

    def test_reward_hint_wins_even_if_header_remains_and_enters_absorption(self):
        controller, log = Mock(), Mock()
        runner = app.TaskRunner(controller, log, dry_run=False)
        runner.max_cycles = 1
        runner._sleep_interruptible = Mock()
        runner._inspect_4c_battle_state = Mock(return_value=(True, True))
        runner._run_rotation_action = Mock()
        runner._collect_4c_reward = Mock()
        runner._restart_4c_challenge = Mock()
        runner._run_4c_combat(Mock(timeout=30))
        runner._collect_4c_reward.assert_called_once_with(1)
        runner._run_rotation_action.assert_not_called()
        runner._restart_4c_challenge.assert_not_called()
        controller.left_click.assert_not_called()
        self.assertTrue(any("出现领取奖励提示" in str(c) for c in log.call_args_list))

    def test_boss_without_reward_hint_still_uses_missing_header_confirmations(self):
        runner = app.TaskRunner(Mock(), lambda _: None, dry_run=False)
        runner._sleep_interruptible = Mock()
        runner._run_rotation_action = Mock(return_value=True)
        runner._inspect_4c_battle_state = Mock(side_effect=[
            (True, False), (False, False), (False, False),
        ])
        monitor = Mock(error=None)
        monitor.poll.side_effect = [((True, False),), ((False, False),)]
        with patch.object(app, "BattleMonitor", return_value=monitor):
            runner._run_4c_battle(Mock(timeout=80), "E", "R", 1)
        self.assertEqual(runner._inspect_4c_battle_state.call_count, 3)

    def test_header_and_hint_share_one_captured_frame(self):
        runner = app.TaskRunner(Mock(), lambda _: None)
        runner._capture_for_matching = Mock()
        runner._boss_health_ratio = Mock(return_value=0.0)
        runner._boss_name_ratio = Mock(return_value=0.02)
        runner._boss_bar_track_score = Mock(return_value=0.2)
        runner._4c_reward_hint_present = Mock(return_value=True)
        screenshot = Path("fresh.png")
        self.assertEqual(runner._inspect_4c_battle_state(screenshot, 1, 0), (True, "领取奖励"))
        runner._capture_for_matching.assert_called_once_with(screenshot)
        runner._4c_reward_hint_present.assert_called_once_with(screenshot)


if __name__ == "__main__":
    unittest.main()
