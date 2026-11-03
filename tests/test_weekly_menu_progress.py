from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import Mock, patch

from tasks.models import Step
from tasks.weekly_runtime_150 import WeeklyRuntime, WeeklyAdvanced, weekly_neighbor_names
from tasks.weekly_matcher_150 import MatchResult


FIXTURE = Path(__file__).parent/'fixtures/weekly-after-menu2-reported.png'


class WeeklyProgressTests(unittest.TestCase):
    def runner(self):
        runner = WeeklyRuntime(Mock(), Mock(), dry_run=False)
        runner._sleep_interruptible = Mock()
        runner._sleep_click_interval = Mock()
        runner._cap_result = Mock(return_value=False)
        runner._shop_close = Mock(return_value=None)
        runner.controller.screencap.side_effect = lambda path, **_: shutil.copy2(FIXTURE, path)
        return runner

    def test_reported_board_confirms_menu2_completed_and_menu3_present(self):
        runner = self.runner()
        with tempfile.TemporaryDirectory() as directory, patch('tasks.weekly_runtime_150.APP_DIR', Path(directory)):
            found = runner._probe_neighbors('menu2.png')
        self.assertIn('menu3.png', found)
        self.assertNotIn('menu1.png', found)
        self.assertNotIn('menu2.png', found)
        runner.controller.tap.assert_not_called()

    def test_menu2_click_records_success_after_two_fresh_board_frames(self):
        runner = self.runner()
        with tempfile.TemporaryDirectory() as directory, patch('tasks.weekly_runtime_150.APP_DIR', Path(directory)):
            runner._click_cycle_template(Step(action='tap_image', template='menu2.png'), 960, 710)
        self.assertIn('menu2.png', runner._completed_templates)
        self.assertEqual(runner.controller.screencap.call_count, 2)
        runner.controller.tap.assert_called_once_with(960, 710)

    def test_missing_menu2_advances_to_menu3_instead_of_clicking_menu1_again(self):
        runner = self.runner()
        runner._find_image = Mock(side_effect=RuntimeError('menu2 is gone'))
        with tempfile.TemporaryDirectory() as directory, patch('tasks.weekly_runtime_150.APP_DIR', Path(directory)):
            with self.assertRaises(WeeklyAdvanced) as raised:
                runner._wait_for_cycle_template(Step(action='tap_image', template='menu2.png'),
                                                Step(action='tap_image', template='menu1.png'))
        self.assertEqual(raised.exception.template, 'menu3.png')
        runner.controller.tap.assert_not_called()

    def test_cycle_changes_cursor_and_clicks_menu3_once_without_a_fake_menu2_click(self):
        runner = self.runner()
        def wait(step, _previous):
            if step.template == 'menu2.png':
                runner._completed_templates.add('menu2.png')
                raise WeeklyAdvanced('menu3.png')
            return (1680, 930, .95)
        runner._wait_for_cycle_template = Mock(side_effect=wait)
        runner._run_image_cycle(Step(action='tap_image_cycle', templates=['menu2.png', 'menu3.png'], loop=False))
        self.assertEqual([call.args[0].template for call in runner._wait_for_cycle_template.call_args_list],
                         ['menu2.png', 'menu3.png'])
        runner.controller.tap.assert_called_once_with(1680, 930)

    def test_ambiguous_previous_and_next_patterns_do_not_skip_steps(self):
        runner = self.runner()
        runner._find_image = Mock(side_effect=RuntimeError('not ready'))
        runner._probe_neighbors = Mock(return_value={'menu3.png': MatchResult(1, 2, 30, 20, .95),
                                                    'menu5.png': MatchResult(1, 2, 30, 20, .95)})
        with self.assertRaisesRegex(RuntimeError, '前后各2个'):
            runner._wait_for_cycle_template(Step(action='tap_image', template='menu4.png'),
                                            Step(action='tap_image', template='menu3.png'))
        runner.controller.tap.assert_not_called()

    def test_diagnosis_neighborhood_includes_both_sides(self):
        self.assertEqual(weekly_neighbor_names('menu4.png'),
                         ['menu2.png', 'menu3.png', 'menu4.png', 'menu5.png', 'menu6.png', 'menu99.png'])

    def test_retry_remembers_failed_menu2_and_resumes_from_confirmed_menu3(self):
        from tasks.weekly_150 import original_task, TaskRunner as OriginalRunner
        runner = self.runner()
        runner._resume_template = 'menu2.png'
        runner._probe_neighbors = Mock(return_value={'menu3.png': MatchResult(1600, 900, 100, 50, .95)})
        runner._run_image_cycle = Mock()
        with patch.object(OriginalRunner, 'run_task') as start:
            runner.run_task(original_task())
        start.assert_not_called()
        runner._run_image_cycle.assert_called_once()
        self.assertEqual(runner._resume_cycle_template, 'menu3.png')

    def test_state_verification_keeps_the_selected_round_count(self):
        runner = self.runner()
        runner.max_cycles = 2
        runner._wait_for_cycle_template = Mock(return_value=(960, 710, .95))
        runner._probe_neighbors = Mock(return_value={})
        runner._verify_final_cycle_click = Mock()
        runner._run_image_cycle(Step(action='tap_image_cycle', templates=['menu2.png', 'menu3.png'], loop=True))
        self.assertEqual(runner.controller.tap.call_count, 4)
        runner._verify_final_cycle_click.assert_called_once()
        self.assertTrue(runner.stop_event.is_set())
