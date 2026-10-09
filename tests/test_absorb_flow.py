import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from PIL import Image

import app


class AbsorbFlowTests(unittest.TestCase):
    def screen(self, directory):
        screen = Path(directory) / "screen.png"
        Image.new("RGB", (1920, 1080), (25, 30, 35)).save(screen)
        return screen

    def test_absorb_on_initial_frame_ends_only_battle_then_runs_remaining_rounds(self):
        runner = app.TaskRunner(Mock(), Mock(), dry_run=False, max_cycles=2)
        runner._sleep_interruptible = Mock()
        runner._inspect_4c_battle_state = Mock(return_value=(True, "吸收"))
        runner._run_rotation_action = Mock()
        runner._collect_4c_reward = Mock()
        runner._restart_4c_challenge = Mock()
        runner._run_4c_combat(Mock(timeout=30))
        self.assertEqual(runner._collect_4c_reward.call_count, 2)
        runner._restart_4c_challenge.assert_called_once_with(2)
        runner._run_rotation_action.assert_not_called()
        self.assertFalse(runner.stop_event.is_set())

    def test_fresh_absorb_text_is_a_battle_end_signal(self):
        with tempfile.TemporaryDirectory() as directory:
            screen = self.screen(directory)
            with Image.open(screen) as source, Image.open(app.TEMPLATES_DIR / "4c" / "absorb_prompt_dark.png") as prompt:
                source.paste(prompt.convert("RGB"), (1200, 515))
                source.save(screen)
            runner = app.TaskRunner(Mock(), Mock())
            runner.matcher.templates_dir = app.TEMPLATES_DIR / "4c"
            runner._capture_for_matching = Mock()
            runner._boss_name_ratio = Mock(return_value=.03)
            runner._boss_bar_track_score = Mock(return_value=.3)
            self.assertEqual(runner._inspect_4c_battle_state(screen, 1, 0), (True, "吸收"))

    def test_sidebar_hint_works_from_actual_4c_template_group(self):
        with tempfile.TemporaryDirectory() as directory:
            screen = self.screen(directory)
            with Image.open(screen) as source, Image.open(Path(__file__).parent / "fixtures" / "4c-reward-sidebar.png") as sidebar:
                source.paste(sidebar, (0, 0))
                source.save(screen)
            runner = app.TaskRunner(Mock(), Mock())
            runner.matcher.templates_dir = app.TEMPLATES_DIR / "4c"
            self.assertTrue(runner._4c_reward_hint_present(screen))

    def test_prompt_is_absorbed_before_any_movement(self):
        with tempfile.TemporaryDirectory() as directory:
            screen = self.screen(directory)
            runner = app.TaskRunner(Mock(), Mock(), dry_run=False)
            runner._capture_for_matching = Mock()
            runner._find_4c_absorb_prompt = Mock(return_value=(Mock(score=.95), "absorb"))
            runner._sleep_interruptible = Mock()
            with patch.object(app, "APP_DIR", screen.parent):
                screen.rename(screen.parent / "_runtime_screenshot.png")
                runner._collect_4c_reward(1)
            runner.controller.press_key.assert_called_once_with("F", 100)
            runner.controller.press_keys.assert_not_called()
            runner.controller.move_mouse_relative.assert_not_called()
            runner.controller.wheel_at.assert_not_called()

    def test_missing_prompt_moves_forward_in_short_segments_and_checks_each_time(self):
        with tempfile.TemporaryDirectory() as directory:
            screen = self.screen(directory)
            runner = app.TaskRunner(Mock(), Mock(), dry_run=False)
            events = []
            runner._capture_for_matching = lambda _: events.append("capture")
            runner._find_4c_absorb_prompt = Mock(side_effect=[(None, ""), (None, ""), (Mock(score=.95), "absorb")])
            runner._sleep_interruptible = Mock()
            runner.controller.press_keys.side_effect = lambda keys, ms: events.append((keys, ms))
            runner.controller.press_key.side_effect = lambda key, ms: events.append(key)
            with patch.object(app, "APP_DIR", screen.parent):
                screen.rename(screen.parent / "_runtime_screenshot.png")
                runner._collect_4c_reward(1)
            self.assertEqual(events, ["capture", (("W",), 400), "capture", (("W",), 400), "capture", "F"])
            runner.controller.move_mouse_relative.assert_not_called()
            runner.controller.wheel_at.assert_not_called()

    def test_stop_during_probe_prevents_forward_movement(self):
        with tempfile.TemporaryDirectory() as directory:
            screen = self.screen(directory)
            runner = app.TaskRunner(Mock(), Mock(), dry_run=False)
            runner._capture_for_matching = Mock()
            runner._find_4c_absorb_prompt = Mock(side_effect=lambda *_: (runner.stop_event.set(), (None, ""))[1])
            with patch.object(app, "APP_DIR", screen.parent):
                screen.rename(screen.parent / "_runtime_screenshot.png")
                runner._collect_4c_reward(1)
            runner.controller.press_keys.assert_not_called()
            runner.controller.press_key.assert_not_called()


if __name__ == "__main__":
    unittest.main()
