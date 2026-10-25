from types import SimpleNamespace
import threading
import time
import unittest
from unittest.mock import Mock, patch

import app
import windows_client
from windows_client import ClientWindowController, MOUSEEVENTF_LEFTDOWN


class FastStopTests(unittest.TestCase):
    def application(self):
        ui = app.App.__new__(app.App)
        ui.stop_event = threading.Event()
        ui._hotkey_stop_only = threading.Event()
        ui._hotkey_triggered = threading.Event()
        ui._last_hotkey_stop_at = 0.
        ui._log = Mock()
        ui._pet_feedback = Mock()
        ui._event_line = Mock(return_value='stop')
        ui._start_worker = Mock()
        ui.worker = Mock()
        ui.worker.is_alive.return_value = True
        ui._active_controller = Mock()
        ui._active_runner = SimpleNamespace(_combat_input_cancel=threading.Event(),
            _rotation_idle_worker=SimpleNamespace(pause_event=threading.Event(), pause=Mock()))
        return ui

    def test_background_signal_stops_inputs_without_waiting_for_ui_or_idle_lock(self):
        ui = self.application()
        ui._publish_hotkey_press()
        self.assertTrue(ui.stop_event.is_set())
        self.assertTrue(ui._active_runner._combat_input_cancel.is_set())
        self.assertTrue(ui._active_runner._rotation_idle_worker.pause_event.is_set())
        ui._active_runner._rotation_idle_worker.pause.assert_not_called()
        ui._active_controller.emergency_stop.assert_called_once()
        # The worker exits before Tk sees the message; this must not rerun it.
        ui.worker.is_alive.return_value = False
        ui._stop_from_hotkey()
        ui._start_worker.assert_not_called()

    def test_idle_shortcut_repeats_last_task_parameters_and_is_debounced(self):
        ui = self.application()
        ui.worker.is_alive.return_value = False
        ui._last_started_tasks = [SimpleNamespace(name='daily', steps=[])]
        ui._last_job_options = {'max_cycles': 12, 'dry_run': False, 'daily_zone': 'old zone',
                                'boss_challenge': {'level': '90'}}
        ui.dry_run, ui.daily_zone = Mock(), Mock()
        ui._stop_from_hotkey()
        ui._stop_from_hotkey()
        self.assertEqual(ui.max_cycles, 12)
        ui.dry_run.set.assert_called_with(False)
        ui.daily_zone.set.assert_called_with('old zone')
        self.assertEqual(ui._boss_challenge_run, {'level': '90'})
        ui._start_worker.assert_called_once()
        self.assertIsNot(ui._start_worker.call_args.args[0][0], ui._last_started_tasks[0])

    def test_heavy_and_keyboard_holds_are_released_without_waiting_for_their_duration(self):
        for action in ('heavy', 'keyboard'):
            with self.subTest(action=action):
                controller = ClientWindowController()
                controller.hwnd = 1
                controller._ensure_window = Mock()
                stopped, entered = threading.Event(), threading.Event()
                controller.set_cancel_event(stopped)
                def send(_count, pointer, _size):
                    event = pointer._obj
                    if (event.type == windows_client.INPUT_MOUSE and event.union.mi.dwFlags == MOUSEEVENTF_LEFTDOWN
                            or event.type == windows_client.INPUT_KEYBOARD and event.union.ki.dwFlags == 0):
                        entered.set()
                    return 1
                with patch.object(windows_client.user32, 'GetForegroundWindow', return_value=1), \
                        patch.object(windows_client.user32, 'SendInput', side_effect=send) as inject:
                    method = (lambda: controller.hold_left_button(2000)) if action == 'heavy' else (lambda: controller.press_keys(('W',), 1000))
                    thread = threading.Thread(target=method)
                    thread.start()
                    self.assertTrue(entered.wait(1))
                    started = time.monotonic()
                    controller.emergency_stop()
                    thread.join(.35)
                    self.assertFalse(thread.is_alive())
                    self.assertLess(time.monotonic()-started, .5)
                    self.assertFalse(controller._held_mouse)
                    self.assertFalse(controller._held_keys)
                    count = inject.call_count
                    controller._send_keyboard_event(ord('E'), key_up=False)
                    controller._send_mouse_button(MOUSEEVENTF_LEFTDOWN)
                    self.assertEqual(inject.call_count, count)

    def test_ui_fallback_does_not_duplicate_background_listener_press(self):
        ui = self.application()
        ui._hotkey_listener_active = True
        ui.root = Mock()
        ui._hotkey_ready = threading.Event()
        ui._hotkey_was_down = False
        ui._stop_hotkey_is_down = Mock(return_value=True)
        ui._stop_from_hotkey = Mock()
        ui._poll_stop_hotkey()
        ui._stop_from_hotkey.assert_not_called()
        ui._hotkey_triggered.set()
        ui._poll_stop_hotkey()
        ui._stop_from_hotkey.assert_called_once()

    def test_drag_maps_capture_coordinates_and_moves_before_pressing_mouse(self):
        controller = ClientWindowController()
        controller._ensure_window = Mock()
        controller._focus_window = Mock()
        controller.screenshot_to_client = Mock(side_effect=lambda x, y: (x//2, y//2))
        controller._client_to_screen = Mock(side_effect=lambda x, y: (x+100, y+50))
        moved = []
        def inject(flag):
            if flag == MOUSEEVENTF_LEFTDOWN:
                self.assertEqual(moved[-1], (300, 250))
                controller.emergency_stop()
        controller._send_mouse_button = Mock(side_effect=inject)
        with patch.object(windows_client.user32, 'SetCursorPos', side_effect=lambda x, y: moved.append((x, y))):
            controller.swipe(400, 400, 600, 400, 900)
        self.assertEqual(moved, [(300, 250)])
        self.assertEqual(controller._send_mouse_button.call_count, 2)
