from pathlib import Path
import tempfile
import unittest
from threading import Event
from unittest.mock import Mock, patch

from PIL import Image, ImageOps

from tasks.combat_4c_entrance import EntranceFrame
from tasks.guide_challenges import FORGERY_ZONES, ForgeryChallenge, SCREENSHOT, _skip_target, forgery_category
from tasks.models import Step
from tasks.runner import TaskRunner


def frame(*words):
    return EntranceFrame(Image.new('RGB', (1920, 1080)), [
        {'words': [{'text': label, 'x': x, 'y': y, 'width': 70, 'height': 22}]}
        for label, x, y in words
    ])


class StoryTests(unittest.TestCase):
    def test_only_clicks_top_left_skip_or_confirmed_story_popup(self):
        self.assertEqual(_skip_target(frame(('跳过', 75, 66)), False), ('skip', (110, 77)))
        self.assertEqual(_skip_target(frame(('跳过', 1000, 650)), False), (None, None))
        popup = frame(('是否跳过', 810, 460), ('确认', 1200, 680))
        self.assertEqual(_skip_target(popup, True), ('confirm', (1235, 691)))
        self.assertEqual(_skip_target(frame(('确认', 1200, 680)), True), (None, None))

    def test_icon_only_skip_is_found_below_letterbox_and_ignores_right_side(self):
        template_path = Path(__file__).parents[1]/'templates/daily/story_skip_icon.png'
        with Image.open(template_path) as source:
            icon = source.convert('RGB')
        scene = Image.new('RGB', (1920, 1080))
        scene.paste(icon, (1733, 160))
        self.assertEqual(_skip_target(EntranceFrame(scene, []), False), (None, None))
        scene.paste(icon, (54, 160))
        for width in (1280, 1920, 2560):
            with self.subTest(width=width):
                scaled = scene.resize((width, width*9//16), Image.Resampling.BILINEAR)
                action, point = _skip_target(EntranceFrame(scaled, []), False)
                self.assertEqual(action, 'skip')
                self.assertAlmostEqual(point[0], 78*width/1920, delta=2)
                self.assertAlmostEqual(point[1], 184*width/1920, delta=2)


class ForgeryTests(unittest.TestCase):
    def test_five_selectable_domains_open_their_own_rows(self):
        screenshot = Path(__file__).parent/'fixtures/forgery-five-zones.png'
        runner = TaskRunner(Mock(), Mock(), dry_run=False)
        for target, expected_y in zip(FORGERY_ZONES, (266, 419, 572, 725, 878)):
            with self.subTest(target=target):
                ocr = Mock()
                challenge = ForgeryChallenge(runner, ocr, target)
                runner.controller.tap.reset_mock()
                self.assertTrue(challenge.select_row(screenshot))
                runner.controller.tap.assert_called_once_with(1741, expected_y)
                ocr.recognize.assert_not_called()

    def test_approaches_start_orb_and_interacts_before_accepting_combat(self):
        runner = Mock(stop_event=Event())
        challenge = ForgeryChallenge(runner, Mock(), '目标领域')
        challenge.read = Mock(return_value=frame())
        challenge.loaded = Mock(return_value=True)
        runner._daily_reward_orb_location.return_value = (1280, 350, .9)
        # Enemy bars by themselves cannot bypass an unactivated orb.
        challenge.battle = lambda _path: True
        challenge.challenge_prompt = lambda _path: (
            runner._step_toward_challenge_orb.called and not runner.controller.press_key.called)
        time_now = [0.]
        runner._sleep_interruptible.side_effect = lambda seconds: time_now.__setitem__(0, time_now[0]+seconds)
        with patch('tasks.daily_checks.time.monotonic', side_effect=lambda: time_now[0]):
            self.assertTrue(challenge.start_combat(approach=True))
        runner._step_toward_challenge_orb.assert_called_once_with(SCREENSHOT, 1280)
        runner.controller.press_key.assert_called_once_with('F', 100)

    def test_reported_sidebar_opens_even_when_ocr_cannot_read_the_category(self):
        fixture = Path(__file__).parent/'fixtures/forgery-guide-sidebar-reported.png'
        with Image.open(fixture) as source:
            inactive = source.convert('RGB')
        active = inactive.copy()
        card = (94, 188, 334, 236)
        active.paste(ImageOps.invert(active.crop(card)), card[:2])
        with tempfile.TemporaryDirectory() as folder:
            screen = Path(folder)/'screen.png'
            runner = TaskRunner(Mock(), Mock(), dry_run=False)
            runner._capture_for_matching = Mock(side_effect=lambda path: (
                active if runner.controller.tap.called else inactive).save(path))
            runner._sleep_interruptible = Mock()
            runner._click_daily_template = Mock()
            ocr = Mock()
            with patch('tasks.guide_challenges.SCREENSHOT', screen):
                challenge = ForgeryChallenge(runner, ocr, '目标领域')
                challenge.battle = Mock(return_value=True)
                self.assertTrue(challenge.enter())
                self.assertEqual(forgery_category(screen), ((119, 212), True))
            runner.controller.tap.assert_called_once_with(119, 212)
            runner._click_daily_template.assert_not_called()
            ocr.recognize.assert_not_called()

    def test_opening_a_row_uses_its_own_button_and_not_adjacent_row(self):
        runner = Mock(stop_event=Event())
        challenge = ForgeryChallenge(runner, Mock(), '目标领域')
        challenge.read = Mock(return_value=frame(
            ('目标领域', 710, 420), ('前往', 1650, 300), ('直接挑战', 1650, 483)))
        self.assertTrue(challenge.select_row(SCREENSHOT))
        runner.controller.tap.assert_called_once_with(1685, 494)

    def test_repeat_runs_existing_battle_engine_with_forgery_preset(self):
        runner = Mock(max_cycles=2, stop_event=Event())
        challenge = ForgeryChallenge(runner, Mock(), '目标领域')
        challenge.enter = Mock(return_value=True)
        challenge.start_combat = Mock(return_value=True)
        step = Step(action='forgery_challenge')
        challenge.run(step)
        challenge.enter.assert_called_once()
        runner._click_daily_settlement_action.assert_called_once_with('restart')
        self.assertEqual(runner._run_tower_battle.call_count, 2)
        for run in runner._run_tower_battle.call_args_list:
            self.assertEqual(run.args, (step, SCREENSHOT))
            self.assertEqual(run.kwargs['mode'], 'forgery')


class EchoOverworldTests(unittest.TestCase):
    def test_overworld_waits_for_respawn_and_keeps_existing_4c_engine(self):
        runner = TaskRunner(Mock(), Mock(), dry_run=False, max_cycles=2)
        runner._run_4c_battle = Mock()
        runner._collect_4c_reward = Mock()
        runner._wait_4c_overworld_boss = Mock()
        runner._restart_4c_challenge = Mock()
        runner._run_4c_combat(Step(action='combat_4c', text='overworld'))
        self.assertEqual(runner._run_4c_battle.call_count, 2)
        runner._wait_4c_overworld_boss.assert_called_once()
        runner._restart_4c_challenge.assert_not_called()
        for collect in runner._collect_4c_reward.call_args_list:
            self.assertEqual(collect.kwargs, {})
