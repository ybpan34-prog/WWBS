import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from PIL import Image
from tasks.runner import TaskRunner


class RecoverableTransitionsTests(unittest.TestCase):
    def test_capture_recovers_after_transient_failure(self):
        controller = Mock()
        controller.screencap.side_effect = [OSError('busy'), None]
        runner = TaskRunner(controller, Mock(), dry_run=False)
        runner._sleep_interruptible = Mock()
        runner._capture_for_matching(Path('screen.png'))
        self.assertEqual(controller.screencap.call_count, 2)
        controller.press_key.assert_not_called()

    def test_capture_failure_is_bounded_and_never_claimed_successful(self):
        controller = Mock()
        controller.screencap.side_effect = OSError('gone')
        runner = TaskRunner(controller, Mock(), dry_run=False)
        runner._sleep_interruptible = Mock()
        with self.assertRaisesRegex(RuntimeError, '连续截图失败'):
            runner._capture_for_matching(Path('screen.png'))
        self.assertEqual(controller.screencap.call_count, 3)

    def test_death_animation_waits_but_absorb_prompt_interrupts_grace(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            Image.new('RGB', (1600, 900)).save(root/'_runtime_screenshot.png')
            controller = Mock()
            runner = TaskRunner(controller, Mock(), dry_run=False)
            runner._capture_for_matching = Mock()
            runner._find_4c_absorb_prompt = Mock(side_effect=[(None, '')]*3+[(Mock(score=.99), 'absorb')])
            now = [0.]
            runner._sleep_interruptible = lambda seconds: now.__setitem__(0, now[0]+seconds)
            with patch('tasks.combat_4c.APP_DIR', root), patch('tasks.combat_4c.time.monotonic', side_effect=lambda: now[0]):
                runner._collect_4c_reward(1)
            controller.move_mouse_relative.assert_not_called()
            controller.press_keys.assert_not_called()
            controller.press_key.assert_called_once_with('F', 100)

    def test_spiral_starts_after_animation_grace_and_is_cancelable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            Image.new('RGB', (1600, 900)).save(root/'_runtime_screenshot.png')
            controller = Mock()
            runner = TaskRunner(controller, Mock(), dry_run=False)
            runner._capture_for_matching = Mock()
            runner._find_4c_absorb_prompt = Mock(return_value=(None, ''))
            now, moved = [0.], []
            runner._sleep_interruptible = lambda seconds: now.__setitem__(0, now[0]+seconds)
            def turn(*args):
                moved.append(now[0])
                runner.stop_event.set()
            controller.move_mouse_relative.side_effect = turn
            with patch('tasks.combat_4c.APP_DIR', root), patch('tasks.combat_4c.time.monotonic', side_effect=lambda: now[0]):
                runner._collect_4c_reward(1)
            self.assertEqual(len(moved), 1)
            self.assertGreaterEqual(moved[0], 2.5)
            controller.press_keys.assert_not_called()
