"""Fresh two-frame probes, adjacent-step recovery and bounded cycle progress."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import app
from weekly_rewards import WeeklyLimitReached


class CycleRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.runner = app.TaskRunner(Mock(), Mock(), dry_run=False, notice=Mock())
        self.runner._sleep_interruptible = Mock()
        self.runner._sleep_click_interval = Mock()
        self.current = app.Step(action='tap_image', template='current.png', timeout=1)
        self.previous = app.Step(action='tap_image', template='previous.png', timeout=1)
        self.following = app.Step(action='tap_image', template='next.png', timeout=1)

    def missing(self):
        return RuntimeError('not matched')

    def names(self):
        return [call.args[0].template for call in self.runner._find_image.call_args_list]

    def test_second_current_probe_succeeds_without_any_neighbor_click(self):
        self.runner._find_image = Mock(side_effect=[self.missing(), (10, 20, .93)])
        result = self.runner._wait_for_cycle_template(self.current, self.previous, self.following)
        self.assertEqual(result, (self.current, 10, 20, .93))
        self.assertEqual(self.names(), ['current.png']*2)
        self.runner.controller.tap.assert_not_called()

    def test_previous_is_clicked_only_after_fresh_successful_match(self):
        self.runner.last_clicked_image_step = self.previous
        self.runner._find_image = Mock(side_effect=[self.missing(), self.missing(),
            self.missing(), (73, 84, .95), (120, 140, .96)])
        result = self.runner._wait_for_cycle_template(self.current, self.previous, self.following)
        self.assertEqual(result, (self.current, 120, 140, .96))
        self.assertEqual(self.names(), ['current.png']*2 + ['previous.png']*2 + ['current.png'])
        self.runner.controller.tap.assert_called_once_with(73, 84)

    def test_next_match_recovers_user_advance_without_clicking_missing_steps(self):
        self.runner._find_image = Mock(side_effect=[self.missing() for _ in range(5)] + [(300, 400, .97)])
        result = self.runner._wait_for_cycle_template(self.current, self.previous, self.following)
        self.assertEqual(result, (self.following, 300, 400, .97))
        self.assertEqual(self.names(), ['current.png']*2 + ['previous.png']*2 + ['next.png']*2)
        self.runner.controller.tap.assert_not_called()

    def test_final_current_recheck_can_recover_without_stopping(self):
        self.runner._find_image = Mock(side_effect=[self.missing() for _ in range(7)] + [(14, 25, .96)])
        result = self.runner._wait_for_cycle_template(self.current, self.previous, self.following)
        self.assertEqual(result, (self.current, 14, 25, .96))
        self.assertEqual(self.names(), ['current.png']*2 + ['previous.png']*2 + ['next.png']*2 + ['current.png']*2)
        self.assertFalse(self.runner.stop_event.is_set())

    def test_all_eight_probes_fail_stop_and_report_without_any_click(self):
        self.runner._find_image = Mock(side_effect=self.missing())
        with self.assertRaisesRegex(RuntimeError, 'current.png.*previous.png.*next.png'):
            self.runner._wait_for_cycle_template(self.current, self.previous, self.following)
        self.assertEqual(self.names(), ['current.png']*2 + ['previous.png']*2 + ['next.png']*2 + ['current.png']*2)
        self.assertTrue(all(call.kwargs == {'single_attempt': True}
                            for call in self.runner._find_image.call_args_list))
        self.assertTrue(self.runner.stop_event.is_set())
        self.runner.controller.tap.assert_not_called()
        self.runner.notice.assert_called_once()

    def test_previous_hit_does_not_restart_an_unbounded_recovery_loop(self):
        self.runner._find_image = Mock(side_effect=[self.missing(), self.missing(), (11, 22, .95)]
                                       + [self.missing() for _ in range(6)])
        with self.assertRaises(RuntimeError):
            self.runner._wait_for_cycle_template(self.current, self.previous, self.following)
        self.assertEqual(self.names(), ['current.png']*2 + ['previous.png'] + ['current.png']*2
                         + ['next.png']*2 + ['current.png']*2)
        self.runner.controller.tap.assert_called_once_with(11, 22)

    def test_missing_boundary_neighbors_are_skipped_without_wrapping_final_round(self):
        self.runner._find_image = Mock(side_effect=self.missing())
        with self.assertRaisesRegex(RuntimeError, '无上一张.*无下一张'):
            self.runner._wait_for_cycle_template(self.current)
        self.assertEqual(self.names(), ['current.png']*4)
        self.runner.controller.tap.assert_not_called()

    def test_stop_after_match_never_sends_a_click_or_more_probes(self):
        def match(*_args, **_kwargs):
            self.runner.stop_event.set()
            return 11, 22, .95
        self.runner._find_image = Mock(side_effect=match)
        with self.assertRaisesRegex(RuntimeError, '已停止'):
            self.runner._wait_for_cycle_template(self.current, self.previous, self.following)
        self.runner._find_image.assert_called_once()
        self.runner.controller.tap.assert_not_called()
        self.runner.notice.assert_not_called()

    def test_weekly_cap_at_each_recovery_stage_exits_immediately(self):
        for misses in (0, 2, 4, 6):
            with self.subTest(misses=misses):
                self.runner._find_image = Mock(side_effect=[self.missing() for _ in range(misses)]
                                               + [WeeklyLimitReached()])
                with self.assertRaises(WeeklyLimitReached):
                    self.runner._wait_for_cycle_template(self.current, self.previous, self.following)
                self.assertEqual(self.runner._find_image.call_count, misses+1)
                self.runner.controller.tap.assert_not_called()
                self.assertFalse(self.runner.stop_event.is_set())

    def cycle(self, names, responses, *, rounds=None):
        with tempfile.TemporaryDirectory() as tmp:
            self.runner.template_root = Path(tmp)
            for name in names:
                (Path(tmp)/name).touch()
            self.runner.max_cycles = rounds
            self.runner._find_image = Mock(side_effect=responses)
            self.runner._verify_final_cycle_click = Mock()
            self.runner._run_image_cycle(app.Step(action='tap_image_cycle', templates=names,
                                                  loop=rounds is not None, seconds=.15))

    def test_cycle_advances_cursor_after_next_match_and_clicks_it_once(self):
        self.runner.last_clicked_image_step = self.previous
        self.cycle(['a.png', 'b.png', 'c.png'], [self.missing() for _ in range(4)]
                   + [(31, 41, .95), (51, 61, .96)])
        self.assertEqual(self.names(), ['a.png']*2 + ['previous.png']*2 + ['b.png', 'c.png'])
        self.assertEqual([call.args for call in self.runner.controller.tap.call_args_list], [(31, 41), (51, 61)])
        self.assertEqual(self.runner.last_clicked_image_step.template, 'c.png')

    def test_wrap_recovery_counts_completed_round_and_does_not_launch_extra_round(self):
        self.cycle(['a.png', 'b.png'], [(10, 20, .95)] + [self.missing() for _ in range(4)]
                   + [(30, 40, .96), (50, 60, .97)], rounds=2)
        self.assertEqual(self.names(), ['a.png'] + ['b.png']*2 + ['a.png']*3 + ['b.png'])
        self.assertEqual([call.args for call in self.runner.controller.tap.call_args_list],
                         [(10, 20), (30, 40), (50, 60)])
        self.runner._verify_final_cycle_click.assert_called_once()
        self.assertTrue(self.runner.stop_event.is_set())

    def test_dry_run_recognizes_previous_but_never_clicks_it(self):
        self.runner.dry_run = True
        self.runner._find_image = Mock(side_effect=[self.missing(), self.missing(),
                                                  (20, 30, .95), (40, 50, .96)])
        self.runner._wait_for_cycle_template(self.current, self.previous, self.following)
        self.runner.controller.tap.assert_not_called()

    def test_single_attempt_uses_one_fresh_capture_and_no_hidden_retry_sleep(self):
        self.runner._capture_for_matching = Mock()
        self.runner.matcher.find = Mock(side_effect=self.missing())
        with patch.object(app.time, 'sleep') as sleep:
            with self.assertRaisesRegex(RuntimeError, 'not matched'):
                self.runner._find_image(self.current, single_attempt=True)
        self.runner._capture_for_matching.assert_called_once()
        self.runner.matcher.find.assert_called_once()
        sleep.assert_not_called()

    def test_weekly_delay_reduced_for_existing_configs_without_changing_other_tasks(self):
        del self.runner._sleep_click_interval
        with patch.object(app.random, 'uniform', return_value=.08) as jitter:
            self.runner._weekly_monitoring = True
            self.runner._sleep_click_interval(.15)
            low, high = jitter.call_args.args
            self.assertAlmostEqual(low, .06)
            self.assertAlmostEqual(high, .10)
            self.runner._weekly_monitoring = False
            self.runner._sleep_click_interval(.15)
            self.assertEqual(jitter.call_args.args, (0, .35))


if __name__ == '__main__':
    unittest.main()
