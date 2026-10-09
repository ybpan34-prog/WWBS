import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from PIL import Image

import app
from combat_rotation import RotationClock
from combat_vision import active_character_slot
from image_matcher import TemplateMatcher


FIXTURES = Path(__file__).parent / 'fixtures'


class RoleVisionTests(unittest.TestCase):
    def test_active_portrait_badges_at_multiple_sizes(self):
        matcher = TemplateMatcher(app.TEMPLATES_DIR / 'roles')
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'screen.png'
            for slot in (1, 2, 3):
                with Image.open(FIXTURES / f'role-active-{slot}.png') as source:
                    for scale in (.75, 1., 1.25):
                        source.resize((round(1920*scale), round(1080*scale)), Image.Resampling.BILINEAR).save(target)
                        with self.subTest(slot=slot, scale=scale):
                            self.assertEqual(active_character_slot(target, matcher), slot)

    def test_hidden_hud_is_not_treated_as_a_confirmed_character(self):
        matcher = TemplateMatcher(app.TEMPLATES_DIR / 'roles')
        self.assertIsNone(active_character_slot(FIXTURES / 'tower-result.png', matcher))

    def test_warm_role_check_decodes_the_screenshot_only_once(self):
        matcher = TemplateMatcher(app.TEMPLATES_DIR / 'roles')
        path = FIXTURES / 'role-active-1.png'
        active_character_slot(path, matcher)
        with patch('combat_vision.Image.open', wraps=Image.open) as opened:
            self.assertEqual(active_character_slot(path, matcher), 1)
        opened.assert_called_once_with(path)


class ConfirmedController:
    def __init__(self):
        self.active = 3
        self.events = []
        self.two_attempts = 0
        self.ignore_two = 3

    def active_character_slot(self, _path):
        return self.active

    def press_key(self, key, duration):
        self.events.append((key, self.active))
        if key in ('1', '2', '3'):
            if key == '2':
                self.two_attempts += 1
                if self.two_attempts <= self.ignore_two:
                    return
            self.active = int(key)

    def press_binding(self, key, duration):
        self.events.append((key, self.active))

    def press_keys(self, keys, duration):
        self.events.append((keys, self.active))

    def left_click(self):
        self.events.append(('click', self.active))

    def hold_left_button(self, duration):
        self.events.append(('heavy', self.active))

    def release_keys(self, *_args):
        pass


class ConfirmedSwitchTests(unittest.TestCase):
    def setUp(self):
        self.now = 0.
        self.controller = ConfirmedController()
        self.runner = app.TaskRunner(self.controller, Mock(), dry_run=False)
        self.runner._rotation_slot = 3
        self.runner._capture_for_matching = lambda _: self.advance(.02)
        self.runner._sleep_interruptible = self.advance

    def advance(self, duration):
        self.now += duration

    def execute(self, action, clock):
        return self.runner._run_rotation_action(action, clock, 'E', 'R', threading.Event(), threading.Lock())

    def test_reported_321_axis_retries_two_and_gives_it_full_fifteen_seconds(self):
        preset = json.loads((FIXTURES / 'reported-321-axis.json').read_text(encoding='utf-8'))
        clock = RotationClock(preset['modules'], 0, slot_times=preset['slot_times'],
                              slot_order=preset['slot_order'], background_idle=True)
        with patch.object(app.time, 'monotonic', side_effect=lambda: self.now):
            self.execute(clock.next_action(self.now), clock)
            self.now = clock.visit_deadline
            action = clock.next_action(self.now)
            self.assertEqual(action['module']['slot'], 2)
            self.execute(action, clock)
            self.assertEqual(self.controller.active, 2)
            self.assertEqual(self.controller.two_attempts, 4)
            self.assertAlmostEqual(clock.visit_deadline-self.now, 15)
            self.assertNotIn(('1', 3), self.controller.events)
            self.execute(clock.next_action(self.now), clock)
            self.assertIn(('SPACE', 2), self.controller.events)
            while self.now < clock.visit_deadline:
                self.execute(clock.next_action(self.now), clock)
                self.advance(.05)
            next_role = clock.next_action(self.now)
            self.assertEqual(next_role['module']['slot'], 1)
            self.execute(next_role, clock)
        self.assertEqual(self.controller.active, 1)

    def test_failed_switch_stops_instead_of_skipping_to_one(self):
        self.controller.ignore_two = 999
        with patch.object(app.time, 'monotonic', side_effect=lambda: self.now):
            with self.assertRaisesRegex(RuntimeError, '不会跳过此角色'):
                self.runner._select_rotation_slot(2, verify=True)
        self.assertEqual(self.runner._rotation_slot, 3)
        self.assertTrue(all(key == '2' for key, _ in self.controller.events))

    def test_stop_during_confirmation_does_not_press_another_key(self):
        self.runner._capture_for_matching = lambda _: self.runner.stop_event.set()
        with patch.object(app.time, 'monotonic', side_effect=lambda: self.now):
            self.assertFalse(self.runner._select_rotation_slot(2, verify=True))
        self.assertEqual(self.controller.events, [])

    def test_success_during_confirmation_prevents_switch_inputs(self):
        self.runner._rotation_end_check = Mock(return_value=True)
        with patch.object(app.time, 'monotonic', side_effect=lambda: self.now):
            self.assertFalse(self.runner._select_rotation_slot(2, verify=True))
        self.assertTrue(self.runner._rotation_battle_finished)
        self.assertEqual(self.controller.events, [])

    def test_single_transient_hud_result_is_not_enough_to_confirm(self):
        observed = iter((2, 3, 2, 2))
        self.controller.active_character_slot = lambda _: next(observed)
        self.controller.ignore_two = 0
        with patch.object(app.time, 'monotonic', side_effect=lambda: self.now):
            self.assertTrue(self.runner._select_rotation_slot(2, verify=True))
        self.assertEqual(self.controller.two_attempts, 1)

    def test_successful_switch_uses_short_waits_and_one_settlement_scan(self):
        self.controller.ignore_two = 0
        self.runner._rotation_end_check = Mock(return_value=False)
        with patch.object(app.time, 'monotonic', side_effect=lambda: self.now):
            self.assertTrue(self.runner._select_rotation_slot(2, verify=True))
        # Three fresh captures, an 80 ms settle and a 25 ms stability check.
        self.assertAlmostEqual(self.now, .165)
        self.assertEqual(self.controller.two_attempts, 1)
        self.assertEqual(self.runner._rotation_end_check.call_count, 2)

    def test_second_frame_hidden_hud_still_checks_for_settlement(self):
        self.controller.active_character_slot = Mock(side_effect=[2, None])
        self.runner._rotation_end_check = Mock(side_effect=[False, True])
        with patch.object(app.time, 'monotonic', side_effect=lambda: self.now):
            self.assertFalse(self.runner._select_rotation_slot(2, verify=True))
        self.assertTrue(self.runner._rotation_battle_finished)
        self.assertEqual(self.controller.events, [])


if __name__ == '__main__':
    unittest.main()
