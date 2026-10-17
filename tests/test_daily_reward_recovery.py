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

    def test_reported_150_crop_and_full_screens_with_yellow_decoration_are_accepted(self):
        path=FIXTURES/'daily-activity-150.png'
        self.assertTrue(self.runner()._daily_activity_score_full(path))
        with tempfile.TemporaryDirectory() as directory, Image.open(path) as counter, \
                Image.open(FIXTURES/'daily-activity-zero.png') as source:
            for width in (1280,1600,1920,2560):
                with self.subTest(width=width):
                    screen=source.resize((width,round(width*9/16)),Image.Resampling.BILINEAR)
                    screen.paste((90,113,125),(round(width*.15),round(screen.height*.77),
                                             round(width*.29),round(screen.height*.94)))
                    scale=width/1920
                    patch_image=counter.resize((round(counter.width*scale),round(counter.height*scale)),
                                               Image.Resampling.BILINEAR)
                    screen.paste(patch_image,(round(width*.185),round(screen.height*.78)))
                    target=Path(directory)/'150.png'
                    screen.save(target)
                    self.assertTrue(self.runner(width)._daily_activity_score_full(target))

    def test_two_digit_50_is_not_full(self):
        with tempfile.TemporaryDirectory() as directory, Image.open(FIXTURES/'daily-activity-150.png') as source:
            image=source.copy()
            image.paste((90,113,125),(0,0,60,85))
            path=Path(directory)/'50.png'
            image.save(path)
            self.assertFalse(self.runner()._daily_activity_score_full(path))

    def test_full_digits_survive_background_changes_resize_and_reposition(self):
        from tasks.daily_activity import _yellow_digits
        with tempfile.TemporaryDirectory() as directory, \
                Image.open(FIXTURES/'daily-activity-zero.png') as source, \
                Image.open(app.TEMPLATES_DIR/'daily'/'activity_full.png') as counter:
            digits = _yellow_digits(counter)
            for color in ((32, 51, 60), (110, 149, 166), (178, 190, 197)):
                foreground = np.full((counter.height, counter.width, 3), color, dtype=np.uint8)
                foreground[digits] = np.asarray(counter.convert('RGB'))[digits]
                for width in (1280, 1600, 1920, 2560):
                    with self.subTest(color=color, width=width):
                        screen = source.resize((width, round(width*9/16)), Image.Resampling.BILINEAR)
                        screen.paste(color, (round(width*.15), round(screen.height*.77),
                                             round(width*.29), round(screen.height*.94)))
                        scale = width/1920
                        patch_image = Image.fromarray(foreground).resize(
                            (round(counter.width*scale), round(counter.height*scale)),
                            Image.Resampling.BILINEAR)
                        screen.paste(patch_image, (round(width*.195), round(screen.height*.805)))
                        path = Path(directory)/'full-varying-background.png'
                        screen.save(path)
                        self.assertTrue(self.runner(width)._daily_activity_score_full(path))

    def test_two_zeroes_and_three_zeroes_do_not_count_as_one_hundred(self):
        from tasks.daily_activity import _yellow_digits
        with tempfile.TemporaryDirectory() as directory, \
                Image.open(FIXTURES/'daily-activity-zero.png') as source, \
                Image.open(app.TEMPLATES_DIR/'daily'/'activity_full.png') as counter:
            pixels = np.asarray(counter.convert('RGB'))
            zero = pixels[30:70, 54:82].copy()
            zero_mask = _yellow_digits(Image.fromarray(zero))
            zero[~zero_mask] = (90, 113, 125)
            for number in ('00', '000'):
                screen = source.copy()
                screen.paste((90, 113, 125), (240, 693, 465, 846))
                for index in range(len(number)):
                    screen.paste(Image.fromarray(zero), (300+index*34, 750))
                path = Path(directory)/'wrong-digits.png'
                screen.save(path)
                self.assertFalse(self.runner()._daily_activity_score_full(path))

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
        with patch('tasks.other.APP_DIR', FIXTURES), \
                patch.object(app.Image, 'open', return_value=Image.new('RGB', (1600, 900))):
            runner._collect_daily_activity_rewards()
        runner.controller.tap.assert_called_once_with(1408, 221)
        self.assertTrue(any(call.args[:2] == (.945, .868) for call in runner._tap_ratio.call_args_list))
        runner._daily_activity_score_full.assert_not_called()

    def test_unconfirmed_claims_stop_before_the_chest(self):
        runner = self.runner()
        runner._yellow_claim_rows = Mock(return_value=[221])
        runner._daily_activity_score_full = Mock(return_value=True)
        with patch.object(app.Image, 'open', return_value=Image.new('RGB', (1600, 900))):
            with self.assertRaisesRegex(RuntimeError, '不会提前点击100宝箱'):
                runner._collect_daily_activity_rewards()
        runner._daily_activity_score_full.assert_not_called()

    def test_counter_above_100_or_unreadable_does_not_block_the_chest(self):
        runner = self.runner()
        runner._yellow_claim_rows = Mock(return_value=[])
        runner._daily_activity_score_full = Mock(side_effect=AssertionError('Score must not gate collection'))
        runner._collect_daily_activity_rewards()
        self.assertEqual(sum(call.args[:2] == (.945, .868) for call in runner._tap_ratio.call_args_list), 1)
        runner._daily_activity_score_full.assert_not_called()

    def test_already_open_activity_page_claims_without_reopening_or_score_gate(self):
        runner=self.runner()
        runner._yellow_claim_rows=Mock(return_value=[])
        runner._daily_activity_score_full=Mock(side_effect=AssertionError('No score gate'))
        runner._collect_daily_activity_rewards(already_open=True)
        runner._open_terminal_destination.assert_not_called()
        self.assertEqual([call.args[:2] for call in runner._tap_ratio.call_args_list],
                         [(.945,.868),(.957,.058)])

    def test_150_confirmed_twice_skips_combat_but_still_claims_all_rewards(self):
        runner=self.runner()
        runner.daily_zone_name=app.DAILY_ZONE_NAMES[0]
        runner._daily_activity_confirmed_full=True
        runner._open_daily_tacet_field=Mock(return_value=False)
        runner._collect_daily_activity_rewards=Mock()
        runner._collect_daily_battlepass_rewards=Mock()
        runner._continue_daily_into_weekly_travel=Mock()
        runner._run_daily_battle=Mock()
        runner._run_daily_routine(app.Step(action='daily_routine'))
        runner._run_daily_battle.assert_not_called()
        runner._collect_daily_activity_rewards.assert_called_once_with(already_open=True)
        runner._collect_daily_battlepass_rewards.assert_called_once()
        runner._continue_daily_into_weekly_travel.assert_called_once()

    def test_pending_page_requires_two_consistent_full_counter_frames(self):
        runner=self.runner()
        runner._sola_guide_page_ready=Mock(return_value=True)
        runner._daily_activity_page_present=Mock(return_value=True)
        runner._daily_activity_score_full=Mock(side_effect=[True,False,True,True])
        self.assertFalse(runner._daily_activity_still_pending())
        self.assertTrue(runner._daily_activity_confirmed_full)
        self.assertEqual(runner._daily_activity_score_full.call_count,4)
        runner._open_terminal_destination=Mock()
        runner._daily_activity_still_pending=Mock(return_value=False)
        runner._click_daily_template=Mock()
        self.assertFalse(runner._open_daily_tacet_field('zone.png'))
        runner._click_daily_template.assert_not_called()

    def test_tasks_are_claimed_before_chest_and_page_exit(self):
        runner = self.runner()
        runner._yellow_claim_rows = Mock(side_effect=[[221], [331], [], []])
        actions = []
        runner.controller.tap.side_effect = lambda x, y: actions.append(('task', x, y))
        runner._tap_ratio.side_effect = lambda x, y, pause: actions.append(('page', x, y))
        with patch.object(app.Image, 'open', return_value=Image.new('RGB', (1600, 900))):
            runner._collect_daily_activity_rewards()
        self.assertEqual(actions, [('page', .039, .174), ('task', 1408, 221),
                                   ('task', 1408, 331), ('page', .945, .868), ('page', .957, .058)])

    def test_stop_after_task_claims_does_not_click_chest_or_leave_page(self):
        runner = self.runner()
        def rows(_screenshot):
            runner.stop_event.set()
            return []
        runner._yellow_claim_rows = Mock(side_effect=rows)
        runner._collect_daily_activity_rewards()
        runner.controller.tap.assert_not_called()
        self.assertFalse(any(call.args[:2] in ((.945, .868), (.957, .058))
                             for call in runner._tap_ratio.call_args_list))

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
