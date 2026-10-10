import unittest
import threading
from pathlib import Path
from unittest.mock import Mock, patch

import app


class NativeController:
    def active_character_slot(self, _path):
        return 1


class UltimateTransitionTests(unittest.TestCase):
    def runner(self, native=False):
        runner = app.TaskRunner(NativeController() if native else Mock(), Mock(), dry_run=False)
        runner._inspect_4c_boss_header = Mock(return_value=False)
        runner._4c_reward_hint_present = Mock(return_value=False)
        runner._find_4c_absorb_prompt = Mock(return_value=(None, ''))
        runner._overworld_hud_ready = Mock(return_value=True)
        runner._sleep_interruptible = Mock()
        runner._capture_for_matching = Mock()
        return runner

    def test_missing_header_during_ultimate_is_unknown_not_defeated(self):
        runner = self.runner()
        runner._combat_animation_until = 15
        with patch.object(app.time, 'monotonic', return_value=12):
            self.assertEqual(runner._inspect_4c_battle_state(Path('screen.png'), 1, 0), (None, False))

    def test_hidden_hud_outside_fixed_grace_is_still_not_defeated(self):
        runner = self.runner(native=True)
        runner._overworld_hud_ready.return_value = False
        self.assertEqual(runner._inspect_4c_battle_state(Path('screen.png'), 1, 0), (None, False))
        runner._overworld_hud_ready.return_value = True
        self.assertEqual(runner._inspect_4c_battle_state(Path('screen.png'), 1, 0), (False, False))

    def test_reward_hint_wins_over_animation_protection(self):
        runner = self.runner(native=True)
        runner._combat_animation_until = float('inf')
        runner._4c_reward_hint_present.return_value = True
        self.assertEqual(runner._inspect_4c_battle_state(Path('screen.png'), 1, 0), (False, '领取奖励'))
        runner._overworld_hud_ready.assert_not_called()

    def test_slow_inspection_does_not_turn_an_old_animation_frame_into_completion(self):
        runner = self.runner()
        now = [10.]
        runner._combat_animation_until = 15
        runner._inspect_4c_boss_header.side_effect = lambda *_a, **_kw: (now.__setitem__(0, 20.), False)[1]
        with patch.object(app.time, 'monotonic', side_effect=lambda: now[0]):
            self.assertEqual(runner._inspect_4c_battle_state(Path('screen.png'), 1, 0), (None, False))

    def test_ultimate_opens_protection_before_input_and_keeps_original_binding(self):
        runner = self.runner()
        runner.controller.press_binding.side_effect = lambda *_: self.assertEqual(runner._combat_animation_until, 105)
        with patch.object(app.time, 'monotonic', return_value=100):
            runner._cast_timed_ultimate('R', threading.Event(), threading.Lock(), resume_attacks=False, settle_delay=0)
        runner.controller.press_binding.assert_called_once_with('R', 120)

    def test_daily_missing_task_is_not_finished_during_ultimate(self):
        runner = self.runner()
        runner._combat_animation_until = float('inf')
        runner._daily_battle_task_present = Mock(return_value=False)
        self.assertFalse(runner._confirm_daily_battle_finished(Path('screen.png')))
        runner._daily_battle_task_present.assert_not_called()


if __name__ == '__main__':
    unittest.main()
