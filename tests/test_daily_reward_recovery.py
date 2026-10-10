import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np
from PIL import Image

import app


FIXTURES = Path(__file__).parent/'fixtures'


class ReportedRewardVisionTests(unittest.TestCase):
    def runner(self, width=1600):
        runner = app.TaskRunner(Mock(), Mock(), dry_run=False)
        runner.matcher = app.TemplateMatcher(app.TEMPLATES_DIR/'daily')
        runner._fast_scales = lambda: [width/1920]
        return runner

    def test_reported_zero_is_not_one_hundred_and_five_claim_buttons_have_centres(self):
        path = FIXTURES/'daily-activity-zero.png'
        runner = self.runner()
        self.assertFalse(runner._daily_activity_score_full(path))
        self.assertEqual(runner._yellow_claim_rows(path), [221, 339, 456, 574, 691])
        self.assertTrue(runner._daily_activity_page_present(path))

    def test_zero_and_milestone_numbers_are_rejected_at_multiple_window_sizes(self):
        with tempfile.TemporaryDirectory() as directory, Image.open(FIXTURES/'daily-activity-zero.png') as source:
            path = Path(directory)/'screen.png'
            for width in (1280, 1600, 1920, 2560):
                source.resize((width, round(width*9/16)), Image.Resampling.BILINEAR).save(path)
                with self.subTest(width=width):
                    runner = self.runner(width)
                    self.assertFalse(runner._daily_activity_score_full(path))
                    self.assertEqual(len(runner._yellow_claim_rows(path)), 5)

    def test_true_one_hundred_counter_is_accepted_in_its_own_region(self):
        with tempfile.TemporaryDirectory() as directory, Image.open(FIXTURES/'daily-activity-zero.png') as source, \
                Image.open(app.TEMPLATES_DIR/'daily'/'activity_full.png') as counter:
            target = source.copy()
            target.paste((90, 113, 125), (260, 726, 415, 842))
            target.paste(counter.resize((round(counter.width*1600/1920),
                                        round(counter.height*1600/1920)), Image.Resampling.BILINEAR), (260, 740))
            path = Path(directory)/'full.png'
            target.save(path)
            self.assertTrue(self.runner()._daily_activity_score_full(path))

    def test_reported_radio_tasks_page_confirms_second_tab_but_not_first(self):
        runner = self.runner()
        self.assertTrue(runner._daily_battlepass_tab_selected(FIXTURES/'daily-radio-tasks.png', 2))
        self.assertFalse(runner._daily_battlepass_tab_selected(FIXTURES/'daily-radio-tasks.png', 1))
        self.assertFalse(runner._daily_battlepass_tab_selected(FIXTURES/'daily-activity-zero.png', 1))

    def test_first_radio_tab_requires_the_icon_to_be_highlighted(self):
        with tempfile.TemporaryDirectory() as directory, Image.open(FIXTURES/'daily-radio-tasks.png') as source:
            pixels = np.asarray(source).copy()
            icon = pixels[125:193, 32:96]
            gray = icon.mean(axis=2)
            light = gray > 135
            icon[light] = np.stack((np.minimum(gray[light]*1.12, 255),
                                   np.minimum(gray[light]*1.03, 255), gray[light]*.48), axis=-1).astype(np.uint8)
            path = Path(directory)/'first.png'
            Image.fromarray(pixels).save(path)
            self.assertTrue(self.runner()._daily_battlepass_tab_selected(path, 1))


class RewardRecoveryFlowTests(unittest.TestCase):
    def runner(self):
        runner = app.TaskRunner(Mock(), Mock(), dry_run=False)
        runner._capture_for_matching = Mock()
        runner._open_terminal_destination = Mock()
        runner._wait_daily_reward_page = Mock()
        runner._sleep_interruptible = Mock()
        runner._dismiss_reward_overlay_safely = Mock()
        runner._tap_ratio = Mock()
        return runner

    def test_transient_empty_frame_does_not_skip_the_claim_rows(self):
        runner = self.runner()
        runner._yellow_claim_rows = Mock(side_effect=[[], [221], [], []])
        runner._daily_activity_score_full = Mock(return_value=False)
        with patch.object(app, 'APP_DIR', FIXTURES), \
                patch.object(app.Image, 'open', return_value=Image.new('RGB', (1600, 900))):
            runner._collect_daily_activity_rewards()
        runner.controller.tap.assert_called_once_with(1408, 221)
        self.assertFalse(any(call.args[:2] == (.945, .868) for call in runner._tap_ratio.call_args_list))

    def test_unconfirmed_claims_stop_before_the_chest(self):
        runner = self.runner()
        runner._yellow_claim_rows = Mock(return_value=[221])
        runner._daily_activity_score_full = Mock(return_value=True)
        with patch.object(app.Image, 'open', return_value=Image.new('RGB', (1600, 900))):
            with self.assertRaisesRegex(RuntimeError, '不会提前点击100宝箱'):
                runner._collect_daily_activity_rewards()
        runner._daily_activity_score_full.assert_not_called()

    def test_full_counter_must_persist_in_a_second_frame(self):
        runner = self.runner()
        runner._yellow_claim_rows = Mock(return_value=[])
        runner._daily_activity_score_full = Mock(side_effect=[True, False])
        runner._collect_daily_activity_rewards()
        self.assertFalse(any(call.args[:2] == (.945, .868) for call in runner._tap_ratio.call_args_list))

    def test_radio_tab_switch_retries_and_waits_for_two_confirmations(self):
        runner = self.runner()
        now = [0.]
        runner._sleep_interruptible = lambda duration: now.__setitem__(0, now[0]+duration)
        runner._daily_battlepass_tab_selected = Mock(side_effect=[False]*7+[True, True])
        with patch.object(app.time, 'monotonic', side_effect=lambda: now[0]):
            runner._wait_daily_battlepass_tab(1)
        self.assertGreaterEqual(runner._tap_ratio.call_count, 2)
        self.assertTrue(all(call.args[:2] == (.039, .174) for call in runner._tap_ratio.call_args_list))

    def test_radio_does_not_claim_rewards_before_a_tab_is_confirmed(self):
        runner = self.runner()
        runner._wait_daily_battlepass_tab = Mock(side_effect=RuntimeError('未确认标签'))
        runner._click_optional_daily_template = Mock()
        with self.assertRaisesRegex(RuntimeError, '未确认标签'):
            runner._collect_daily_battlepass_rewards()
        runner._click_optional_daily_template.assert_not_called()

    def test_activity_title_without_loaded_task_rows_is_not_ready(self):
        runner = self.runner()
        now = [0.]
        runner._sleep_interruptible = lambda duration: now.__setitem__(0, now[0]+duration)
        runner._capture_size = Mock(return_value=(Path('screen.png'), 1600, 900))
        runner._find_daily_template = Mock(return_value=object())
        runner._daily_activity_page_present = Mock(side_effect=[False, True, True])
        with patch.object(app.time, 'monotonic', side_effect=lambda: now[0]):
            app.TaskRunner._wait_daily_reward_page(runner, 'activity_title.png', '活跃行迹')
        self.assertEqual(runner._capture_size.call_count, 3)


if __name__ == '__main__':
    unittest.main()
