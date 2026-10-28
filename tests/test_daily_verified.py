import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from PIL import Image

from tasks.daily_verified import VerifiedDailyNavigation
from tasks.daily_team import team_start_target
from tasks.runner import TaskRunner


class DailyVerifiedTests(unittest.TestCase):
    def test_confirmed_restart_skips_redundant_stamina_prompt_even_if_hud_fades(self):
        nav, runner = self.navigation()
        nav._checks.transition = Mock(return_value=True)
        runner._capture_for_matching = Mock(side_effect=AssertionError('must not rescan optional prompt after confirmed battle'))
        runner._normal = Mock(return_value=False)
        self.assertTrue(nav._click_daily_template('restart_challenge.png', '重新挑战'))
        self.assertTrue(runner._daily_restart_confirmed)
        self.assertFalse(nav._click_optional_daily_template('insufficient_continue.png', '体力不足继续提示的确认', timeout=5))
        self.assertFalse(runner._daily_restart_confirmed)
        runner.controller.tap.assert_not_called()

    def test_cancelled_restart_cannot_acknowledge_the_stamina_prompt(self):
        nav, runner = self.navigation()
        nav._checks.transition = Mock(return_value=False)
        self.assertFalse(nav._click_daily_template('restart_challenge.png', '重新挑战'))
        self.assertFalse(runner._daily_restart_confirmed)

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
        runner._open_menu = Mock(return_value=False)
        runner._enter = Mock()
        self.assertFalse(nav._open_terminal_destination('索拉指南'))
        runner._enter.assert_not_called()

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
