import threading
import time
import unittest
from unittest.mock import Mock, patch

import app
from combat_rotation import BattleMonitor, IdleAttackWorker, RotationClock, new_module


class CancelableController:
    def __init__(self):
        self.entered = threading.Event()
        self.released = threading.Event()

    def left_click(self):
        pass

    def hold_left_button_cancelable(self, duration, cancel_event):
        self.entered.set()
        cancel_event.wait(duration/1000)
        self.released.set()

    def press_keys_cancelable(self, keys, duration, cancel_event):
        self.hold_left_button_cancelable(duration, cancel_event)


class ImmediateAbsorbTests(unittest.TestCase):
    def test_finished_idle_worker_cannot_be_rearmed_by_a_late_scheduler_query(self):
        controller = Mock()
        worker = IdleAttackWorker(controller, threading.Event(), threading.Lock())
        worker.close()
        worker.arm(new_module('idle_attack'), time.monotonic()+1)
        time.sleep(.03)
        controller.left_click.assert_not_called()
        self.assertTrue(worker.pause_event.is_set())

    def test_finite_heavy_and_approach_modules_can_also_be_interrupted(self):
        for kind, action_kind in (('heavy_count', 'hold_left'), ('approach', 'approach')):
            with self.subTest(kind=kind):
                controller = CancelableController()
                runner = app.TaskRunner(controller, Mock(), dry_run=False)
                runner._select_rotation_slot = Mock(return_value=True)
                module = new_module(kind)
                if kind == 'approach':
                    module['value'] = 3
                clock = RotationClock([module], time.monotonic(), slot_times={'1': 5})
                thread = threading.Thread(target=runner._run_rotation_action,
                    args=({'kind': action_kind, 'module': module}, clock, 'E', 'R', threading.Event(), threading.Lock()))
                try:
                    thread.start()
                    self.assertTrue(controller.entered.wait(1))
                    runner._rotation_battle_finished = True
                    runner._combat_input_cancel.set()
                    thread.join(.3)
                    self.assertFalse(thread.is_alive())
                    self.assertTrue(controller.released.is_set())
                finally:
                    runner._combat_input_cancel.set()
                    thread.join(1)

    def test_detection_callback_stops_a_heavy_without_waiting_for_poll(self):
        controller = CancelableController()
        stop = threading.Event()
        worker = IdleAttackWorker(controller, stop, threading.Lock(), attack_interval=.01, heavy_hold_ms=800)
        module = new_module('idle_attack')
        module['value'] = 1
        stopped = threading.Event()
        monitor = None
        try:
            worker.arm(module, time.monotonic()+3)
            self.assertTrue(controller.entered.wait(1))
            def detected(_result):
                worker.pause()
                stopped.set()
            monitor = BattleMonitor(lambda: (False, '吸收'), (True, False), stop, on_result=detected)
            monitor.poll()  # Consume the initial frame; never poll the detection.
            start = time.monotonic()
            monitor.request()
            self.assertTrue(stopped.wait(.3))
            self.assertLess(time.monotonic()-start, .3)
            self.assertTrue(controller.released.is_set())
            self.assertFalse(stop.is_set())  # Collection and later rounds continue.
        finally:
            if monitor is not None:
                monitor.close()
            worker.close()

    def test_4c_detected_absorb_goes_to_collection_without_more_attack_inputs(self):
        runner = app.TaskRunner(Mock(), Mock(), dry_run=False)
        runner.max_cycles = 1
        runner._inspect_4c_battle_state = Mock(return_value=(True, False))
        runner._collect_4c_reward = Mock()
        runner._sleep_interruptible = Mock()
        def monitor(_inspect, _initial, _stop, *, on_result):
            on_result((False, '吸收'))
            return Mock(error=None, poll=Mock(return_value=None))
        with patch.object(app, 'BattleMonitor', side_effect=monitor):
            runner._run_4c_combat(Mock(timeout=30))
        runner.controller.left_click.assert_not_called()
        runner.controller.press_binding.assert_not_called()
        runner.controller.press_key.assert_not_called()
        runner._collect_4c_reward.assert_called_once_with(1)
        self.assertFalse(runner.stop_event.is_set())


if __name__ == '__main__':
    unittest.main()
