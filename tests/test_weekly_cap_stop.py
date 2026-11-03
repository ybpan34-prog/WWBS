from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from PIL import Image, ImageDraw

from tasks.runner import TaskRunner
from tasks.weekly_150 import from_host, original_task
from tasks.weekly_restart import restart_match
from tasks.weekly_runtime_150 import WeeklyRuntime, WeeklyCapReached
from tasks.models import Step


ROOT=Path(__file__).resolve().parents[1]
RESULT=ROOT/'tests/fixtures/weekly-cap-result-reported.png'


class WeeklyCapStopTests(unittest.TestCase):
    def runner(self):
        runner=WeeklyRuntime(Mock(),Mock(),dry_run=False,notice=Mock())
        runner._sleep_interruptible=Mock()
        return runner

    def test_reported_failed_result_cap_recognized_at_client_resolutions(self):
        runner=self.runner()
        with tempfile.TemporaryDirectory() as folder, Image.open(RESULT) as image:
            for width in (1280,1600,1920):
                path=Path(folder)/f'{width}.png'
                image.resize((width,round(width*9/16)),Image.Resampling.LANCZOS).save(path)
                self.assertTrue(runner._cap_result(path),width)

    def test_title_independent_but_both_cap_text_and_return_home_are_required(self):
        runner=self.runner()
        with tempfile.TemporaryDirectory() as folder, Image.open(RESULT) as source:
            path=Path(folder)/'screen.png'
            for box,expected in (((850,170,1120,250),True),((1140,475,1370,570),False),((950,710,1180,830),False)):
                image=source.copy()
                ImageDraw.Draw(image).rectangle(box,fill=(0,0,0))
                image.save(path)
                self.assertEqual(runner._cap_result(path),expected,box)
        for name in ('weekly-shop-reported.png','weekly-exit-board-reported.png'):
            self.assertFalse(runner._cap_result(ROOT/'tests/fixtures'/name))

    def test_two_fresh_result_frames_stop_before_restart_match_or_click(self):
        runner=self.runner()
        runner._cap_result=Mock(return_value=True)
        runner.matcher.find=Mock()
        with tempfile.TemporaryDirectory() as folder,patch('tasks.weekly_150.APP_DIR',Path(folder)):
            runner.controller.screencap.side_effect=lambda path,**_: Image.open(RESULT).save(path)
            with self.assertRaises(WeeklyCapReached):
                runner._wait_for_cycle_template(Step(action='tap_image',template='menu99.png',timeout=.1))
        self.assertEqual(runner.controller.screencap.call_count,2)
        runner.matcher.find.assert_not_called()
        runner.controller.tap.assert_not_called()

    def test_transient_single_frame_is_not_treated_as_confirmed_cap(self):
        runner=self.runner()
        runner._cap_result=Mock(side_effect=[True,False])
        runner._shop_close=Mock(return_value=None)
        runner._capture_for_matching(RESULT)
        self.assertEqual(runner.controller.screencap.call_count,2)
        self.assertFalse(runner.stop_event.is_set())
        runner.controller.tap.assert_not_called()

    def test_test_mode_keeps_restart_available_at_the_weekly_cap(self):
        host = TaskRunner(Mock(), Mock(), dry_run=False, max_cycles=13, weekly_test_mode=True)
        runner = from_host(host)
        self.assertTrue(runner.weekly_test_mode)
        self.assertTrue(runner._cap_result(RESULT))
        self.assertGreaterEqual(restart_match(RESULT).score, .93)
        runner._cap_result = Mock(return_value=True)
        runner._capture_for_matching(RESULT)
        runner._cap_result.assert_not_called()
        self.assertFalse(host.stop_event.is_set())

    def test_test_mode_passes_the_round_limit_and_honors_manual_stop(self):
        runner = WeeklyRuntime(Mock(), Mock(), dry_run=False, max_cycles=1, weekly_test_mode=True)
        runner._wait_for_cycle_template = Mock(return_value=(10, 20, .98))
        runner._verify_final_cycle_click = Mock()
        runner._sleep_click_interval = Mock()
        clicks = []

        def click(step, *_point):
            clicks.append(step.template)
            if len(clicks) == 3:
                runner.stop_event.set()

        runner._click_cycle_template = click
        runner._run_image_cycle(Step(action='tap_image_cycle', templates=['menu99.png'], loop=True))
        self.assertEqual(clicks, ['menu99.png']*3)
        runner._verify_final_cycle_click.assert_not_called()

    def test_test_mode_can_start_from_an_already_capped_result(self):
        runner = WeeklyRuntime(Mock(), Mock(), dry_run=False, weekly_test_mode=True)
        with tempfile.TemporaryDirectory() as folder, patch('tasks.weekly_runtime_150.APP_DIR', Path(folder)):
            def capture(path, **_kwargs):
                with Image.open(RESULT) as image:
                    image.save(path)

            runner.controller.screencap.side_effect = capture
            runner._restart_and_confirm = Mock(return_value='menu3.png')
            runner._run_image_cycle = Mock()
            runner.run_task(original_task())
        runner._restart_and_confirm.assert_called_once_with()
        runner._run_image_cycle.assert_called_once()
        self.assertEqual(runner._resume_cycle_template, 'menu3.png')

    def test_standalone_and_daily_entry_finish_normally_and_keep_result(self):
        for method,original in (('run_task','run_task'),('_run_default_weekly_from_daily','_run_default_weekly_from_daily'),
                                ('_start_weekly_travel_from_selected_page','_start_weekly_travel_from_selected_page')):
            runner=self.runner()
            with patch('tasks.weekly_150.TaskRunner.'+original,side_effect=WeeklyCapReached):
                if method=='run_task':
                    runner.run_task(original_task())
                else:
                    getattr(runner,method)()
            self.assertTrue(runner.stop_event.is_set())
            runner.notice.assert_called_once()
            runner.controller.tap.assert_not_called()

    def test_stop_during_second_confirmation_does_not_report_cap_or_click(self):
        runner=self.runner()
        runner._cap_result=Mock(return_value=True)
        runner._sleep_interruptible=lambda _:runner.stop_event.set()
        runner._capture_for_matching(RESULT)
        self.assertEqual(runner.controller.screencap.call_count,1)
        runner.notice.assert_not_called()
        runner.controller.tap.assert_not_called()
