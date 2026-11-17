import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from PIL import Image, ImageDraw

from tasks.daily_verified import VerifiedDailyNavigation
from tasks.daily_team import team_start_target
from tasks.runner import TaskRunner


class DailyVerifiedTests(unittest.TestCase):
    def test_confirmed_restart_skips_redundant_stamina_prompt_even_if_hud_fades(self):
        nav, runner = self.navigation()
        runner._click_daily_settlement_action = Mock()
        runner._capture_for_matching = Mock()
        runner._match = Mock(return_value=None)
        runner._restart_battle_visible = Mock(return_value=True)
        runner._read_daily_settlement = Mock(return_value=None)
        self.assertTrue(nav._click_daily_template('restart_challenge.png', '重新挑战'))
        self.assertTrue(runner._daily_restart_ready)
        self.assertTrue(runner._daily_restart_confirmed)
        self.assertFalse(nav._click_optional_daily_template('insufficient_continue.png', '体力不足继续提示的确认', timeout=5))
        self.assertFalse(runner._daily_restart_confirmed)
        self.assertFalse(runner._select_daily_slot_after_loading(nav._checks.screenshot))
        runner._capture_for_matching.assert_called_once()
        runner.controller.tap.assert_not_called()

    def test_cancelled_restart_cannot_acknowledge_the_stamina_prompt(self):
        nav, runner = self.navigation()
        runner._click_daily_settlement_action = Mock(side_effect=lambda *a, **kw: runner.stop_event.set())
        self.assertFalse(nav._click_daily_template('restart_challenge.png', '重新挑战'))
        self.assertFalse(runner._daily_restart_confirmed)

    def test_restart_accepts_stamina_continue_then_battle_on_next_capture(self):
        nav, runner = self.navigation()
        runner._click_daily_settlement_action = Mock()
        runner._capture_for_matching = Mock()
        runner._match = Mock(side_effect=[Mock(center=(1250, 650)), None])
        runner._read_daily_settlement = Mock(return_value=None)
        runner._restart_battle_visible = Mock(return_value=True)
        runner._sleep_interruptible = Mock()
        self.assertTrue(nav._click_daily_template('restart_challenge.png', '重新挑战'))
        self.assertEqual(runner._capture_for_matching.call_count, 2)
        runner.controller.tap.assert_called_once_with(1250, 650)
        self.assertTrue(runner._daily_restart_ready)

    def test_scrolls_and_recaptures_when_tacet_title_is_at_bottom(self):
        nav, runner = self.navigation()
        runner._open_terminal_destination = Mock(return_value=True)
        runner._panel = Mock(return_value=True)
        runner._weekly_travel_page_present = Mock(return_value=False)
        runner._match = Mock(return_value=True)
        runner._daily_activity_page_present = Mock(return_value=True)
        runner._daily_activity_score_full = Mock(return_value=False)
        runner._capture_for_matching = Mock()
        runner._click_daily_template = Mock()
        runner._select_daily_tacet_section = Mock()
        runner._capture_size = Mock(return_value=(nav._checks.screenshot, 1920, 1080))
        runner.daily_zone_name = '落日堤屿无音区'
        runner._locate_zone_row = Mock(side_effect=[(Mock(center=(910, 967)), None),
                                                   (Mock(center=(910, 810)), (1720, 840))])
        runner._enter_zone = Mock(return_value=True)
        runner._tap_ratio = Mock(return_value=True)
        runner._sleep_interruptible = Mock()
        runner.controller.screenshot_to_client.side_effect = lambda x, y: (x, y)
        with patch('tasks.daily_verified.Image.open') as image_open:
            image_open.return_value.__enter__.return_value = Image.new('RGB', (1920, 1080))
            self.assertTrue(nav._open_daily_tacet_field('zone_luori_diyu.png'))
        runner.controller.wheel_at.assert_called_once_with(1747, 648, -120)
        runner._enter_zone.assert_called_once_with('zone_luori_diyu.png')
        self.assertEqual(runner._capture_size.call_count, 2)

    def test_full_activity_skips_tacet_selection(self):
        nav, runner = self.navigation()
        runner._open_terminal_destination = Mock(return_value=True)
        runner._panel = Mock(return_value=True)
        runner._weekly_travel_page_present = Mock(return_value=False)
        runner._match = Mock(return_value=None)
        runner._daily_activity_score_full = Mock(return_value=True)
        runner._capture_for_matching = Mock()
        runner._sleep_interruptible = Mock()
        runner._click_daily_template = Mock()
        with tempfile.TemporaryDirectory() as tmp:
            nav._checks.screenshot = Path(tmp) / 'screen.png'
            fixture = Path(__file__).parent/'fixtures'/'daily-guide-activity-wrong-category.png'
            with Image.open(fixture) as source:
                source.resize((1920, 1080)).save(nav._checks.screenshot)
            self.assertFalse(nav._open_daily_tacet_field('zone_luori_diyu.png'))
        runner._click_daily_template.assert_not_called()
        runner.controller.tap.assert_not_called()

    def test_pending_weekly_opens_tab_then_starts_after_confirmation(self):
        nav, runner = self.navigation()
        runner._capture_for_matching = Mock()
        runner._sleep_interruptible = Mock()
        runner._panel = Mock(return_value=True)
        runner._start_weekly_travel_from_selected_page = Mock()
        runner._close_page = Mock()
        with patch('tasks.daily_verified.WeeklyRewardsVision') as vision:
            vision.return_value.guide_status.side_effect = [None, 'pending', 'pending', 'pending']
            vision.return_value.inactive_tab.return_value = Mock(center=(665, 140))
            nav._continue_daily_from_open_guide_page()
        runner.controller.tap.assert_called_once_with(665, 140)
        runner._start_weekly_travel_from_selected_page.assert_called_once()
        runner._close_page.assert_not_called()

    def test_radio_rewards_exits_through_terminal_and_starts_weekly(self):
        from shutil import copyfile

        nav, runner = self.navigation()
        fixtures = Path(__file__).parent / 'fixtures'
        runner.matcher.templates_dir = fixtures.parents[1] / 'templates/daily'
        stage = 'daily-radio-rewards-reported.png'
        now = [0.]
        runner._sleep_interruptible = lambda seconds: now.__setitem__(0, now[0] + seconds)

        def leave_radio(key, duration):
            nonlocal stage
            self.assertEqual((key, duration), ('ESC', 70))
            self.assertEqual(stage, 'daily-radio-rewards-reported.png')
            stage = 'daily-terminal-menu.png'

        def open_guide(*point):
            nonlocal stage
            self.assertEqual(stage, 'daily-terminal-menu.png')
            stage = 'daily-activity-claims-reported.jpg'

        runner.controller.press_key.side_effect = leave_radio
        runner.controller.tap.side_effect = open_guide
        runner._capture_for_matching = lambda path: copyfile(fixtures / stage, path)
        runner._start_weekly_travel_from_selected_page = Mock()
        with (
            tempfile.TemporaryDirectory() as directory,
            patch('tasks.daily_verified.time.monotonic', side_effect=lambda: now[0]),
            patch('tasks.daily_verified.WeeklyRewardsVision') as weekly,
        ):
            nav._checks.screenshot = Path(directory) / 'screen.png'
            weekly.return_value.guide_status.return_value = 'pending'
            nav._continue_daily_into_weekly_travel()
        runner.controller.press_key.assert_called_once()
        runner.controller.tap.assert_called_once()
        runner._start_weekly_travel_from_selected_page.assert_called_once()

    def test_completed_weekly_reports_completion_and_closes(self):
        nav, runner = self.navigation()
        runner._capture_for_matching = Mock()
        runner._sleep_interruptible = Mock()
        runner._panel = Mock(return_value=True)
        runner._start_weekly_travel_from_selected_page = Mock()
        runner._close_page = Mock()
        with patch('tasks.daily_verified.WeeklyRewardsVision') as vision:
            vision.return_value.guide_status.return_value = 'completed'
            nav._continue_daily_from_open_guide_page()
        runner.log.assert_any_call('任务完成：周常已完成')
        runner._close_page.assert_called_once()
        runner._start_weekly_travel_from_selected_page.assert_not_called()

    def test_start_click_waits_through_blank_loading_frames_without_reclicking(self):
        nav, runner = self.navigation()
        runner._sleep_interruptible = Mock()
        runner._capture_for_matching = Mock(side_effect=[None, False, False, None, None])
        runner._restart_battle_visible = Mock(side_effect=[False, True, True])
        runner._tap_start = Mock(return_value=True)
        self.assertTrue(nav._tap_ratio(.86, .92))
        runner._tap_start.assert_called_once()
        self.assertTrue(runner._daily_entry_ready)
        self.assertFalse(runner._select_daily_slot_after_loading(nav._checks.screenshot))
        self.assertEqual(runner._capture_for_matching.call_count, 5)

    def test_fifth_zone_finds_button_below_its_title(self):
        nav, runner = self.navigation()
        root = Path(__file__).parents[1]
        runner.matcher.templates_dir = root/'templates/daily'
        runner._fast_scales = lambda: [1600/1920]
        with tempfile.TemporaryDirectory() as folder, Image.open(
                root/'tests/fixtures/daily-tacet-selected-reported.png') as scene, Image.open(
                runner.matcher.templates_dir/'zone_luori_diyu.png') as title:
            path = Path(folder)/'list.png'
            scene.paste(title.resize((258, 54), Image.Resampling.LANCZOS), (728, 620))
            scene.save(path)
            found, button = nav._locate_zone_row(path, 'zone_luori_diyu.png', 1600, 900)
            self.assertIsNotNone(found)
            self.assertEqual(button, (1432, 679))
            self.assertGreater(button[1]-found.center[1], 22)

    def test_recorded_fifth_zone_is_found_without_matching_a_different_zone(self):
        nav, runner = self.navigation()
        root = Path(__file__).parents[1]
        runner.matcher.templates_dir = root/'templates/daily'
        runner._fast_scales = lambda: [1]
        for second, expected in ((7, (1747, 750)), (19, (1747, 512)), (92, None)):
            with self.subTest(second=second):
                path = root/f'tests/fixtures/daily-tacet-video-list-{second}.png'
                title, point = nav._locate_zone_row(path, 'zone_luori_diyu.png', 1920, 1080)
                self.assertEqual(point, expected)
                self.assertEqual(title is None, expected is None)
    def test_full_reported_frame_clicks_button_center_at_window_scales(self):
        nav, runner = self.navigation()
        fixture = Path(__file__).parent/'fixtures/daily-team-start-full-reported.png'
        with tempfile.TemporaryDirectory() as directory, Image.open(fixture) as source:
            path = Path(directory)/'team.png'
            for titlebar in (0, 38):
                original = source.crop((0, titlebar, source.width, source.height))
                for scale in (.6, 1, 1.5):
                    original.resize((round(original.width*scale), round(original.height*scale)), Image.Resampling.BILINEAR).save(path)
                    with self.subTest(titlebar=titlebar, scale=scale):
                        runner.controller.tap.reset_mock()
                        self.assertTrue(nav._tap_start(path))
                        x, y = runner.controller.tap.call_args.args
                        self.assertLess(abs(x/scale-1375), 12)
                        self.assertLess(abs(y/scale-(865-titlebar)), 8)

    def test_start_click_rejects_a_target_on_third_portrait(self):
        nav, runner = self.navigation()
        runner._start_target = Mock(return_value=(1375, 650))
        self.assertFalse(nav._tap_start(Path(__file__).parent/'fixtures/daily-team-start-full-reported.png'))
        runner.controller.tap.assert_not_called()

    def test_reported_team_page_is_confirmed_then_start_button_is_clicked(self):
        nav, runner = self.navigation()
        fixture = Path(__file__).parent/'fixtures/daily-team-start-reported.png'
        now = [0.]
        runner._sleep_interruptible = lambda seconds: now.__setitem__(0, now[0]+seconds)
        runner._capture_for_matching = Mock()
        runner._battle = lambda _: runner.controller.tap.called
        with tempfile.TemporaryDirectory() as directory:
            screen = Path(directory)/'screen.png'
            with Image.open(fixture) as source:
                source.save(screen)
            nav._checks.screenshot = screen
            with patch('tasks.daily_checks.time.monotonic', side_effect=lambda: now[0]):
                self.assertTrue(nav._checks.transition('进入队伍页', lambda p: nav._start_target(p) is not None))
                self.assertTrue(nav._tap_ratio(.86, .92))
        runner.controller.tap.assert_called_once_with(363, 219)

    def test_reported_team_page_is_not_world_and_start_ignores_character_art(self):
        fixture = Path(__file__).parent/'fixtures/daily-team-start-reported.png'
        nav, runner = self.navigation()
        with tempfile.TemporaryDirectory() as directory, Image.open(fixture) as original:
            path = Path(directory)/'team.png'
            for width in (424, 1280, 1600, 1920, 2560):
                for replace_party in (False, True):
                    image = original.resize((width, round(width*239/424)), Image.Resampling.BILINEAR)
                    if replace_party:
                        image.paste((30, 35, 45), (round(width*.14), round(image.height*.14),
                                                 round(width*.96), round(image.height*.84)))
                    image.save(path)
                    with self.subTest(width=width, replace_party=replace_party):
                        target = nav._start_target(path)
                        self.assertIsNotNone(target)
                        self.assertLess(abs(target[0]/width-.85), .025)
                        self.assertLess(abs(target[1]/image.height-.92), .025)
                        self.assertFalse(nav._world(path))

    def test_team_buttons_are_absent_on_world_menus_and_settlement(self):
        for name in ('tower-scene.png', 'tower-prompt.png', 'tower-result.png',
                     'daily-activity-zero.png', 'daily-radio-tasks.png',
                     'daily-terminal-menu.png', 'daily-settlement-reported.png'):
            with self.subTest(frame=name):
                self.assertIsNone(team_start_target(Path(__file__).parent/'fixtures'/name))

    def navigation(self):
        runner = TaskRunner(Mock(), Mock(), dry_run=False)
        nav = VerifiedDailyNavigation(runner)
        return nav, runner

    def test_cancelled_menu_never_attempts_next_destination(self):
        nav, runner = self.navigation()
        runner._capture_for_matching = Mock(side_effect=lambda path: runner.stop_event.set())
        runner._panel = Mock()
        self.assertFalse(nav._open_terminal_destination('索拉指南'))
        runner._panel.assert_not_called()
        runner.controller.tap.assert_not_called()

    def test_open_destination_continues_from_an_already_open_activity_page(self):
        nav, runner = self.navigation()
        runner.matcher.templates_dir = Path(__file__).parents[1]/'templates/daily'
        nav._checks.screenshot = Path(__file__).parent/'fixtures'/'daily-activity-claims-reported.jpg'
        runner._capture_for_matching = Mock()
        runner._sleep_interruptible = Mock()
        self.assertTrue(nav._open_terminal_destination('索拉指南'))
        self.assertTrue(nav._open_activity_page())
        runner.controller.press_key.assert_not_called()
        runner.controller.tap.assert_not_called()

    def test_activity_claims_reported_rows_then_visible_chest_and_closes(self):
        nav, runner = self.navigation()
        runner.matcher.templates_dir = Path(__file__).parents[1]/'templates/daily'
        fixture = Path(__file__).parent/'fixtures'/'daily-activity-claims-reported.jpg'
        runner._open_terminal_destination = Mock(return_value=True)
        runner._sleep_interruptible = Mock()
        runner._close_page = Mock(return_value=True)
        with tempfile.TemporaryDirectory() as folder, Image.open(fixture) as screen:
            nav._checks.screenshot = Path(folder)/'screen.png'
            runner._capture_for_matching = screen.save
            rows = runner._yellow_claim_rows(fixture)
            self.assertEqual(len(rows), 4)
            def claim(x, y):
                draw = ImageDraw.Draw(screen)
                if x > 1600:
                    draw.rectangle((1550, y-26, 1820, y+26), fill='#d0d7d9')
                else:
                    draw.rectangle((720, 900, 805, 990), fill='#587381')
            runner.controller.tap.side_effect = claim
            nav._collect_daily_activity_rewards()
        self.assertEqual([call.args for call in runner.controller.tap.call_args_list],
                         [(1690, y) for y in rows] + [(754, 958)])
        runner._close_page.assert_called_once()

    def test_already_world_exit_does_not_wait_for_or_click_settlement(self):
        nav, runner = self.navigation()
        runner._world = Mock(return_value=True)
        runner._capture_for_matching = Mock()
        runner._sleep_interruptible = Mock()
        nav._click_daily_template('exit_instance.png', 'exit')
        self.assertEqual(runner._capture_for_matching.call_count, 2)
        runner.controller.tap.assert_not_called()

    def test_start_button_detector_rejects_world_and_tacet_list(self):
        nav, runner = self.navigation()
        runner._world = Mock(return_value=True)
        self.assertIsNone(nav._start_target(Path(__file__).parent/'fixtures/tower-scene.png'))
        self.assertIsNone(nav._ocr)

    def test_stable_battle_does_not_wait_five_seconds_for_absent_optional_dialog(self):
        nav, runner = self.navigation()
        runner._capture_for_matching = Mock()
        runner._sleep_interruptible = Mock()
        runner._match = Mock(return_value=None)
        runner._normal = Mock(return_value=True)
        self.assertFalse(nav._click_optional_daily_template('insufficient_continue.png', 'continue', timeout=5))
        self.assertEqual(runner._capture_for_matching.call_count, 2)
        runner.controller.tap.assert_not_called()

    def test_unknown_page_cannot_be_treated_as_no_optional_rewards(self):
        nav, runner = self.navigation()
        runner._capture_for_matching = Mock()
        runner._match = Mock(return_value=None)
        runner._normal = Mock(return_value=False)
        now = [0.]
        runner._sleep_interruptible = lambda seconds: now.__setitem__(0, now[0]+seconds)
        with patch('tasks.daily_verified.time.monotonic', side_effect=lambda: now[0]):
            with self.assertRaisesRegex(RuntimeError, '等待并复核'):
                nav._click_optional_daily_template('one_click_claim.png', 'radio', timeout=3)
        runner.controller.tap.assert_not_called()

    def test_tap_does_not_reach_controller_after_cancel(self):
        nav, runner = self.navigation()
        runner.stop_event.set()
        self.assertFalse(nav._tap((800, 400)))
        runner.controller.tap.assert_not_called()

    def test_disabled_grey_claim_is_not_retried(self):
        nav, runner = self.navigation()
        runner._find_daily_template = Mock(return_value=Mock(x=10, y=10, width=100, height=30))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'screen.png'
            Image.new('RGB', (200, 100), (130, 130, 130)).save(path)
            self.assertIsNone(nav._match(path, 'one_click_claim.png'))
