from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import Mock, patch

from PIL import Image

from tasks.models import Step
from tasks.weekly_restart import restart_match, skip_match
from tasks.weekly_runtime_150 import WeeklyRuntime, WeeklyRoundRestarted, WeeklyCapReached, weekly_neighbor_names
from windows_client import BlankGameCapture


ROOT = Path(__file__).parents[1]
RESULT = ROOT/'tests/fixtures/weekly-restart-result-reported.png'
BOARD = ROOT/'tests/fixtures/weekly-after-menu2-reported.png'


class RestartAckTests(unittest.TestCase):
    def runner(self):
        runner = WeeklyRuntime(Mock(), Mock(), dry_run=False)
        self.now = 0.
        runner._sleep_interruptible = lambda seconds: setattr(self, 'now', self.now+max(seconds, .5))
        runner._sleep_click_interval = Mock()
        runner._cap_result = Mock(return_value=False)
        runner._shop_close = Mock(return_value=None)
        return runner

    def test_real_result_matches_bottom_restart_and_never_skip(self):
        with tempfile.TemporaryDirectory() as folder, Image.open(RESULT) as image:
            for width in (1280, 1600, 1920, 2560):
                path = Path(folder)/'result.png'
                image.resize((width, round(width*9/16))).save(path)
                match = restart_match(path)
                self.assertAlmostEqual(match.center[0]/width, 643/1920, delta=.005)
                self.assertAlmostEqual(match.center[1]/(width*9/16), 916/1080, delta=.005)
                with self.assertRaises(RuntimeError):
                    skip_match(path)

    def test_first_click_ignored_relocates_and_second_click_is_acknowledged(self):
        runner = self.runner()
        runner.controller.screencap.side_effect = lambda path, **_: shutil.copy2(
            BOARD if runner.controller.tap.call_count >= 2 else RESULT, path)
        with tempfile.TemporaryDirectory() as folder, patch('tasks.weekly_runtime_150.APP_DIR', Path(folder)), patch(
                'tasks.weekly_runtime_150.time.monotonic', side_effect=lambda: self.now):
            state = runner._restart_and_confirm()
        self.assertEqual(state, 'menu3.png')
        self.assertEqual(runner.controller.tap.call_count, 2)
        self.assertTrue(all(call.args == (643, 916) for call in runner.controller.tap.call_args_list))
        self.assertIn('menu99.png', runner._completed_templates)

    def test_still_on_result_does_not_acknowledge_background_changes(self):
        runner = self.runner()
        runner.controller.screencap.side_effect = lambda path, **_: shutil.copy2(RESULT, path)
        with tempfile.TemporaryDirectory() as folder, patch('tasks.weekly_runtime_150.APP_DIR', Path(folder)), patch(
                'tasks.weekly_runtime_150.time.monotonic', side_effect=lambda: self.now), patch(
                'tasks.weekly_restart.round_entry', return_value='menu4.png') as entry:
            with self.assertRaisesRegex(RuntimeError, '未计为完成'):
                runner._restart_and_confirm()
        entry.assert_not_called()
        self.assertEqual(runner.controller.tap.call_count, 3)
        self.assertNotIn('menu99.png', runner._completed_templates)

    def test_fade_then_skip_page_needs_two_recognized_frames(self):
        runner = self.runner()
        frames = []
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            blank, skip = folder/'blank.png', folder/'skip.png'
            Image.new('RGB', (1920, 1080), 'black').save(blank)
            image = Image.new('RGB', (1920, 1080), (40, 50, 60))
            with Image.open(ROOT/'templates/weekly150/menu4.png') as button:
                image.paste(button, (1200, 800))
            image.save(skip)
            def capture(path, **_kwargs):
                source = RESULT if not runner.controller.tap.call_count else blank if not frames else skip
                if runner.controller.tap.call_count:
                    frames.append(source)
                shutil.copy2(source, path)
            runner.controller.screencap.side_effect = capture
            with patch('tasks.weekly_runtime_150.APP_DIR', folder), patch(
                    'tasks.weekly_runtime_150.time.monotonic', side_effect=lambda: self.now):
                state = runner._restart_and_confirm()
        self.assertEqual(state, 'menu4.png')
        self.assertEqual(frames, [blank, skip, skip])
        self.assertEqual(runner.controller.tap.call_count, 1)

    def test_native_blank_capture_retries_and_breaks_the_entry_confirmation_streak(self):
        runner = self.runner()
        transition = iter([None, None, BOARD, None, BOARD, BOARD])
        frames = []

        def capture(path, **_kwargs):
            source = next(transition) if runner.controller.tap.call_count else RESULT
            if runner.controller.tap.call_count:
                frames.append(source)
            if source is None:
                raise BlankGameCapture('blank foreground')
            shutil.copy2(source, path)

        runner.controller.screencap.side_effect = capture
        with tempfile.TemporaryDirectory() as folder, patch('tasks.weekly_runtime_150.APP_DIR', Path(folder)), patch(
                'tasks.weekly_runtime_150.time.monotonic', side_effect=lambda: self.now):
            self.assertEqual(runner._restart_and_confirm(), 'menu3.png')
        self.assertEqual(frames, [None, None, BOARD, None, BOARD, BOARD])
        runner.controller.tap.assert_called_once()
        self.assertIn('menu99.png', runner._completed_templates)

    def test_persistent_post_click_blank_times_out_without_reclicking_the_stale_result(self):
        runner = self.runner()

        def capture(path, **_kwargs):
            if runner.controller.tap.call_count:
                raise BlankGameCapture('blank foreground')
            shutil.copy2(RESULT, path)

        runner.controller.screencap.side_effect = capture
        with tempfile.TemporaryDirectory() as folder, patch('tasks.weekly_runtime_150.APP_DIR', Path(folder)), patch(
                'tasks.weekly_runtime_150.time.monotonic', side_effect=lambda: self.now):
            with self.assertRaisesRegex(RuntimeError, '最新截图仍为空白'):
                runner._restart_and_confirm()
            self.assertEqual((Path(folder)/'_runtime_screenshot.png').read_bytes(), RESULT.read_bytes())
        runner.controller.tap.assert_called_once()
        self.assertGreaterEqual(self.now, 15)
        self.assertNotIn('menu99.png', runner._completed_templates)

    def test_initial_blank_and_post_click_focus_failure_are_reported_directly(self):
        with tempfile.TemporaryDirectory() as folder, patch('tasks.weekly_runtime_150.APP_DIR', Path(folder)):
            runner = self.runner()
            runner.controller.screencap.side_effect = BlankGameCapture('initial blank')
            with self.assertRaisesRegex(BlankGameCapture, 'initial blank'):
                runner._restart_and_confirm()
            runner.controller.tap.assert_not_called()

            def capture(path, **_kwargs):
                if runner.controller.tap.call_count:
                    raise RuntimeError('未获得焦点')
                shutil.copy2(RESULT, path)

            runner.controller.screencap.side_effect = capture
            with self.assertRaisesRegex(RuntimeError, '未获得焦点'):
                runner._restart_and_confirm()
            runner.controller.tap.assert_called_once()
            self.assertNotIn('menu99.png', runner._completed_templates)

    def test_menu4_cross_round_review_includes_and_recovers_menu99(self):
        self.assertIn('menu99.png', weekly_neighbor_names('menu4.png'))
        runner = self.runner()
        runner._find_image = Mock(side_effect=RuntimeError('skip not present'))
        runner._probe_neighbors = Mock(return_value={'menu99.png': Mock()})
        runner._restart_and_confirm = Mock(return_value='menu4.png')
        with self.assertRaises(WeeklyRoundRestarted) as restarted:
            runner._wait_for_cycle_template(Step(action='tap_image', template='menu4.png'))
        self.assertEqual(restarted.exception.template, 'menu4.png')
        runner._restart_and_confirm.assert_called_once()

    def test_second_round_uses_confirmed_entry_instead_of_requiring_earlier_dialogs(self):
        runner = self.runner()
        runner.max_cycles = 2
        runner._wait_for_cycle_template = Mock(return_value=(10, 20, .99))
        def click(step, *_args):
            if step.template == 'menu99.png':
                runner._completed_templates.add('menu99.png')
                runner._round_entry_template = 'menu4.png'
        runner._click_cycle_template = Mock(side_effect=click)
        runner._run_image_cycle(Step(action='tap_image_cycle',
            templates=['menu2.png', 'menu3.png', 'menu4.png', 'menu99.png'], loop=True))
        self.assertEqual([call.args[0].template for call in runner._wait_for_cycle_template.call_args_list],
                         ['menu2.png', 'menu3.png', 'menu4.png', 'menu99.png', 'menu4.png', 'menu99.png'])

    def test_failed_restart_never_logs_next_cycle(self):
        runner = self.runner()
        runner.max_cycles = 2
        runner._wait_for_cycle_template = Mock(return_value=(688, 672, .824))
        runner._restart_and_confirm = Mock(side_effect=RuntimeError('not acknowledged'))
        with self.assertRaisesRegex(RuntimeError, 'not acknowledged'):
            runner._run_image_cycle(Step(action='tap_image_cycle', templates=['menu99.png'], loop=True))
        self.assertFalse(any('第 2 轮' in call.args[0] for call in runner.log.call_args_list))

    def test_weekly_cap_stops_before_any_restart_input(self):
        runner = self.runner()
        runner._cap_result = Mock(return_value=True)
        runner.controller.screencap.side_effect = lambda path, **_: shutil.copy2(RESULT, path)
        with tempfile.TemporaryDirectory() as folder, patch('tasks.weekly_runtime_150.APP_DIR', Path(folder)):
            with self.assertRaises(WeeklyCapReached):
                runner._restart_and_confirm()
        runner.controller.tap.assert_not_called()

    def test_actual_second_round_card_selection_is_menu4(self):
        from tasks.weekly_restart import round_entry
        self.assertEqual(round_entry(ROOT/'tests/fixtures/weekly-exit-board-reported.png'), 'menu4.png')

    def test_native_restart_uses_bottom_button_not_reported_old_middle_coordinate(self):
        import windows_client as client
        from test_weekly_exit_precision import WeeklyExitTests
        controller = WeeklyExitTests().controller(cursor=(743, 1016))
        controller.screencap.side_effect = lambda path, **_: shutil.copy2(RESULT, path)
        with tempfile.TemporaryDirectory() as folder, patch.object(client.time, 'sleep'):
            controller.last_capture_path = Path(folder)/'previous.png'
            result = controller.tap_weekly_restart()
        self.assertEqual(result['target'], (743, 1016))
        self.assertEqual(controller.screencap.call_count, 2)
        self.assertEqual(controller._send_mouse_button.call_count, 2)
