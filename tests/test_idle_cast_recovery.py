import threading
import time
import unittest
from unittest.mock import Mock

import app
from combat_rotation import IdleAttackWorker, RotationClock, new_module


class IdleCastRecoveryTests(unittest.TestCase):
    def test_skill_followup_delay_keeps_idle_available_until_next_cast(self):
        skill, echo, idle = new_module('skill'), new_module('echo'), new_module('idle_attack')
        clock = RotationClock([skill, echo, idle], 0, slot_times={'1': 5}, background_idle=True)
        clock.next_action(0)
        self.assertEqual(clock.next_action(.01)['kind'], 'skill')
        clock.defer_cast_followup(.01, .2)
        self.assertEqual(clock.next_action(.02)['kind'], 'idle_attack')
        self.assertEqual(clock.next_action(.15)['kind'], 'idle_attack')
        self.assertEqual(clock.next_action(.22)['kind'], 'echo')

    def runner_and_clock(self, kind, wait=False):
        cast, idle = new_module(kind), new_module('idle_attack')
        modules = [cast, new_module('wait'), idle] if wait else [cast, idle]
        runner = app.TaskRunner(Mock(), Mock(), dry_run=False)
        runner._select_rotation_slot = Mock(return_value=True)
        runner._sleep_interruptible = Mock()
        runner._rotation_idle_worker = Mock()
        clock = RotationClock(modules, time.monotonic(), slot_times={'1': 25}, background_idle=True)
        clock.next_action(time.monotonic())
        return runner, clock, idle

    def test_casts_resume_idle_without_accumulating_two_seconds_of_settle(self):
        for kind in ('skill', 'ultimate', 'echo'):
            with self.subTest(kind=kind):
                runner, clock, idle = self.runner_and_clock(kind)
                action = clock.next_action(time.monotonic())
                runner._run_rotation_action(action, clock, 'E', 'R', threading.Event(), threading.Lock())
                runner._rotation_idle_worker.arm.assert_called_once_with(idle, clock.visit_deadline)
                self.assertFalse(any(call.args[0] > 0 for call in runner._sleep_interruptible.call_args_list))

    def test_explicit_wait_does_not_resume_idle_after_a_cast(self):
        for kind in ('skill', 'ultimate', 'echo'):
            runner, clock, _idle = self.runner_and_clock(kind, wait=True)
            runner._run_rotation_action(clock.next_action(time.monotonic()), clock,
                                        'E', 'R', threading.Event(), threading.Lock())
            runner._rotation_idle_worker.arm.assert_not_called()

    def test_disabled_idle_keeps_original_cast_settle(self):
        runner, clock, _idle = self.runner_and_clock('echo')
        runner._rotation_idle_worker = None
        runner._run_rotation_action(clock.next_action(time.monotonic()), clock,
                                    'E', 'R', threading.Event(), threading.Lock())
        runner._sleep_interruptible.assert_called_once_with(1.)

    def test_next_module_query_keeps_clicking_while_slow_and_actual_cast_pauses(self):
        runner, clock, idle = self.runner_and_clock('skill')
        clicks = []
        controller = Mock()
        controller.left_click.side_effect = lambda: clicks.append(time.monotonic())
        lock = threading.Lock()
        worker = IdleAttackWorker(controller, runner.stop_event, lock, attack_interval=.02)
        runner.controller = controller
        runner._rotation_idle_worker = worker
        try:
            runner._run_rotation_action(clock.next_action(time.monotonic()), clock,
                                        'E', 'R', threading.Event(), lock)
            first = time.monotonic()
            # Stand in for a slow scheduler query while the independent worker runs.
            time.sleep(.25)
            self.assertGreaterEqual(len([t for t in clicks if t > first]), 5)
            checked = []
            def cast(_key, _duration):
                before = len(clicks)
                time.sleep(.06)
                checked.append(len(clicks) == before)
            controller.press_binding.side_effect = cast
            runner._run_rotation_action({'kind': 'skill', 'module': clock.modules[0]}, clock,
                                        'E', 'R', threading.Event(), lock)
            self.assertEqual(checked, [True])
            self.assertEqual(worker.identity, (idle['id'], 1))
        finally:
            worker.close()


if __name__ == '__main__':
    unittest.main()
