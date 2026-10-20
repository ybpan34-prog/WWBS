from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import Mock, patch

from PIL import Image

from tasks.runner import TaskRunner
from tasks.terminal_navigation import terminal_target


ROOT = Path(__file__).parents[1]
FIXTURES = ROOT/'tests/fixtures'
TEMPLATES = ROOT/'templates/daily'


class TerminalNavigationTests(unittest.TestCase):
    def test_reported_terminal_entries_are_found_at_window_sizes(self):
        with tempfile.TemporaryDirectory() as directory, Image.open(FIXTURES/'daily-terminal-menu.png') as image:
            path = Path(directory)/'frame.png'
            for width in (424, 1280, 1600, 1920, 2560):
                image.resize((width, round(width*9/16)), Image.Resampling.LANCZOS).save(path)
                for label, expected in (('索拉指南', (210/424, 165/239)),
                                        ('先约电台', (317/424, 45/239))):
                    with self.subTest(width=width, label=label):
                        target = terminal_target(path, TEMPLATES, label)
                        self.assertIsNotNone(target)
                        self.assertLess(abs(target[0]/width-expected[0]), .004)
                        self.assertLess(abs(target[1]/(width*9/16)-expected[1]), .006)

    def test_guide_or_radio_pages_and_isolated_icon_are_not_terminal(self):
        for name in ('daily-activity-zero.png', 'daily-radio-tasks.png', 'daily-material-header.png'):
            self.assertIsNone(terminal_target(FIXTURES/name, TEMPLATES, '索拉指南'))
        with tempfile.TemporaryDirectory() as directory, Image.open(FIXTURES/'daily-terminal-menu.png') as image:
            image.paste((9, 18, 23), (295, 25, 345, 85))
            path = Path(directory)/'one-icon.png'
            image.save(path)
            self.assertIsNone(terminal_target(path, TEMPLATES, '索拉指南'))

    def runner(self):
        runner = TaskRunner(Mock(), Mock(), dry_run=False)
        runner.matcher.templates_dir = TEMPLATES
        runner._fast_scales = lambda: [1600/1920]
        return runner

    def test_terminal_close_icon_does_not_count_as_guide_arrival(self):
        self.assertFalse(self.runner()._terminal_destination_ready(FIXTURES/'daily-terminal-menu.png', '索拉指南'))
        self.assertTrue(self.runner()._terminal_destination_ready(FIXTURES/'daily-activity-zero.png', '索拉指南'))
        self.assertTrue(self.runner()._terminal_destination_ready(FIXTURES/'daily-radio-tasks.png', '先约电台'))

    def run_navigation(self, directory, *, ignored_clicks=0, never_ready=False, stop_after_capture=False):
        runner = self.runner()
        now, clicks = [0.], []
        runner._sleep_interruptible = lambda duration: now.__setitem__(0, now[0]+duration)
        def capture(path):
            if stop_after_capture:
                runner.stop_event.set()
            if now[0] < 1.:
                Image.new('RGB', (1600, 900), 'black').save(path)
            elif clicks and len(clicks) > ignored_clicks and now[0]-clicks[-1][0] >= .8 and not never_ready:
                shutil.copy2(FIXTURES/'daily-activity-zero.png', path)
            else:
                with Image.open(FIXTURES/'daily-terminal-menu.png') as image:
                    image.resize((1600, 900), Image.Resampling.LANCZOS).save(path)
        runner._capture_for_matching = capture
        runner.controller.tap.side_effect = lambda x, y: clicks.append((now[0], x, y))
        with patch('tasks.other.APP_DIR', Path(directory)), patch('tasks.other.time.monotonic', side_effect=lambda: now[0]):
            if never_ready or stop_after_capture:
                with self.assertRaisesRegex(RuntimeError, '未确认从终端|已停止'):
                    runner._enter_terminal_destination('索拉指南')
            else:
                runner._enter_terminal_destination('索拉指南')
        return runner, now[0], clicks

    def test_delayed_terminal_waits_then_confirms_arrival_before_next_step(self):
        with tempfile.TemporaryDirectory() as directory:
            _runner, finished, clicks = self.run_navigation(directory)
        self.assertEqual(len(clicks), 1)
        self.assertGreaterEqual(clicks[0][0], 1.4-.001)
        self.assertGreaterEqual(finished-clicks[0][0], 1.5)
        self.assertLess(abs(clicks[0][1]-792), 3)

    def test_ignored_click_relocates_with_spacing_then_confirms(self):
        with tempfile.TemporaryDirectory() as directory:
            _runner, _finished, clicks = self.run_navigation(directory, ignored_clicks=1)
        self.assertEqual(len(clicks), 2)
        self.assertGreaterEqual(clicks[1][0]-clicks[0][0], 1.8-.001)

    def test_failed_entry_is_bounded_and_never_clicks_activity_or_chest(self):
        with tempfile.TemporaryDirectory() as directory:
            runner, _finished, clicks = self.run_navigation(directory, never_ready=True)
        self.assertEqual(len(clicks), 3)
        runner.controller.press_key.assert_not_called()
        self.assertTrue(all(abs(x-792) < 3 for _, x, _ in clicks))

    def test_stop_during_capture_prevents_input(self):
        with tempfile.TemporaryDirectory() as directory:
            _runner, _finished, clicks = self.run_navigation(directory, stop_after_capture=True)
        self.assertEqual(clicks, [])


if __name__ == '__main__':
    unittest.main()
