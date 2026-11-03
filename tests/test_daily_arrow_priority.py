from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from PIL import Image

from image_matcher import TemplateMatcher
from tasks.runner import TaskRunner
from tasks.daily_reward_marker import reward_marker_location, reward_marker_direction


ROOT = Path(__file__).parents[1]


class DailyArrowTests(unittest.TestCase):
    def test_reported_left_edge_marker_and_arrow_are_detected(self):
        with tempfile.TemporaryDirectory() as folder, Image.open(ROOT/'tests/fixtures/daily-marker-left-arrow-reported.png') as sample:
            image = Image.new('RGB', (1600, 900), (40, 45, 60))
            image.paste(sample, (0, 400))
            path = Path(folder)/'screen.png'
            image.save(path)
            x, y, score = reward_marker_location(path)
            self.assertAlmostEqual(x, 80, delta=3)
            self.assertGreater(score, .82)
            self.assertEqual(reward_marker_direction(path, x, y), 'left')

    def test_all_arrow_orientations_and_no_arrow(self):
        with tempfile.TemporaryDirectory() as folder, Image.open(ROOT/'templates/daily/reward_arrow_left.png') as arrow, Image.open(
                ROOT/'templates/daily/reward_marker_5.png') as marker:
            for name, angle, dx, dy in (('left', 0, -35, 0), ('right', 180, 35, 0),
                    ('up', 270, 0, -35), ('down', 90, 0, 35), (None, 0, 0, 0)):
                image = Image.new('RGB', (1600, 900), (40, 45, 60))
                image.paste(marker, (779, 429))
                rotated = arrow.rotate(angle, expand=True)
                if name:
                    image.paste(rotated, (round(800+dx-rotated.width/2), round(450+dy-rotated.height/2)))
                path = Path(folder)/'screen.png'
                image.save(path)
                self.assertEqual(reward_marker_direction(path, 800, 450), name)

    def test_reported_down_right_arrow_and_its_mirror_guide_horizontally(self):
        sample_path = ROOT/'tests/fixtures/daily-marker-down-right-reported.png'
        with tempfile.TemporaryDirectory() as folder, Image.open(sample_path) as sample:
            left = sample.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
            left.paste(sample.crop((27, 41, 73, 84)), (57, 41))
            for direction, crop in (('right', sample), ('left', left)):
                for width in (1600, 1920):
                    with self.subTest(direction=direction, width=width):
                        image = Image.new('RGB', (1600, 900), (40, 45, 60))
                        image.paste(crop, (740, 370))
                        path = Path(folder)/'screen.png'
                        image.resize((width, width*9//16)).save(path)
                        x, y, score = reward_marker_location(path)
                        self.assertGreaterEqual(score, .82)
                        self.assertEqual(reward_marker_direction(path, x, y), direction)

    def runner(self, folder):
        Image.new('RGB', (1920, 1080), (40, 45, 60)).save(Path(folder)/'_runtime_screenshot.png')
        runner = TaskRunner(Mock(), Mock(), dry_run=False, daily_orb_confidence=.8)
        runner._capture_for_matching = Mock()
        runner._read_daily_settlement = Mock(return_value=None)
        runner._daily_combat_visible = Mock(return_value=False)
        runner._daily_reward_dialog_present = Mock(return_value=False)
        runner._find_daily_reward_prompt = Mock(side_effect=[None, Mock()])
        runner._wait_daily_reward_dialog = Mock(return_value='claim')
        runner._claim_daily_double_reward = Mock()
        runner._sleep_interruptible = Mock()
        runner._daily_reward_marker_location = Mock(return_value=(100, 500, .9))
        runner._daily_reward_marker_direction = Mock(return_value='left')
        return runner

    def test_orb_above_user_threshold_is_used_after_two_arrow_free_frames(self):
        with tempfile.TemporaryDirectory() as folder, patch('tasks.other.APP_DIR', Path(folder)):
            runner = self.runner(folder)
            runner._daily_reward_orb_location = Mock(return_value=(960, 350, .9))
            runner._daily_reward_marker_direction.side_effect = [None, None]
            runner._find_daily_reward_prompt.side_effect = [None, None, Mock()]
            self.assertTrue(runner._collect_daily_reward(1))
            runner.controller.press_keys.assert_called_once_with(('W',), 500)
            runner.controller.move_mouse_relative.assert_not_called()
            self.assertEqual(runner._daily_reward_marker_direction.call_count, 2)
            runner._daily_reward_orb_location.assert_called_once()

    def test_arrow_blocks_orb_detection_even_if_orb_would_be_above_threshold(self):
        for direction, turn in (('left', (-180, 0)), ('right', (180, 0)), ('up', (0, -100)), ('down', (0, 100))):
            with tempfile.TemporaryDirectory() as folder, patch('tasks.other.APP_DIR', Path(folder)):
                runner = self.runner(folder)
                runner._daily_reward_orb_location = Mock(return_value=(1400, 350, .99))
                runner._daily_reward_marker_direction.return_value = direction
                self.assertTrue(runner._collect_daily_reward(1))
                runner.controller.move_mouse_relative.assert_called_once_with(*turn)
                runner._daily_reward_orb_location.assert_not_called()
                runner.controller.press_keys.assert_not_called()

    def test_arrow_return_resets_the_two_frame_confirmation(self):
        with tempfile.TemporaryDirectory() as folder, patch('tasks.other.APP_DIR', Path(folder)):
            runner = self.runner(folder)
            runner._find_daily_reward_prompt.side_effect = [None, None, None, Mock()]
            runner._daily_reward_marker_direction.side_effect = [None, 'right', None]
            runner._daily_reward_orb_location = Mock(return_value=(960, 350, .99))
            self.assertTrue(runner._collect_daily_reward(1))
            runner.controller.move_mouse_relative.assert_called_once_with(180, 0)
            runner._daily_reward_orb_location.assert_not_called()
            runner.controller.press_keys.assert_not_called()

    def test_missing_marker_search_continues_past_old_deadline_without_orb_lookup(self):
        with tempfile.TemporaryDirectory() as folder, patch('tasks.other.APP_DIR', Path(folder)):
            runner = self.runner(folder)
            runner._daily_reward_marker_location.return_value = (None, None, 0.)
            runner._daily_reward_orb_location = Mock(return_value=(960, 350, .99))
            with patch('tasks.other.time.monotonic', side_effect=[0., 110., 121.]):
                with self.assertRaisesRegex(RuntimeError, '奖励阶段未找到'):
                    runner._collect_daily_reward(1)
            runner.controller.move_mouse_relative.assert_called_once_with(300, 0)
            runner._daily_reward_orb_location.assert_not_called()
            runner.controller.press_keys.assert_not_called()

    def test_combat_evidence_prevents_both_orb_and_arrow_navigation(self):
        with tempfile.TemporaryDirectory() as folder, patch('tasks.other.APP_DIR', Path(folder)):
            runner = self.runner(folder)
            runner._daily_combat_visible.return_value = True
            runner._daily_reward_orb_location = Mock()
            self.assertFalse(runner._collect_daily_reward(1))
            runner.controller.move_mouse_relative.assert_not_called()
            runner.controller.press_keys.assert_not_called()

    def test_open_reward_dialog_claims_even_after_navigation_deadline(self):
        panel_path = ROOT/'tests/fixtures/daily-reward-dialog-panel.png'
        for width in (1280, 1600, 1920):
            with self.subTest(width=width), tempfile.TemporaryDirectory() as folder, \
                    patch('tasks.other.APP_DIR', Path(folder)), Image.open(panel_path) as panel:
                runner = self.runner(folder)
                del runner._daily_reward_dialog_present, runner._wait_daily_reward_dialog
                runner.matcher = TemplateMatcher(ROOT/'templates/daily')
                runner._daily_reward_orb_location = Mock()
                runner._daily_combat_visible.return_value = True
                screen = Image.new('RGB', (1920, 1080), (40, 45, 60))
                screen.paste(panel, (419, 315))
                screen.resize((width, width*9//16)).save(Path(folder)/'_runtime_screenshot.png')
                with patch('tasks.other.time.monotonic', side_effect=[0., 121., 121., 121.2]):
                    self.assertTrue(runner._collect_daily_reward(1))
                self.assertEqual(runner._capture_for_matching.call_count, 3)
                runner._find_daily_reward_prompt.assert_not_called()
                runner._daily_reward_orb_location.assert_not_called()
                runner.controller.press_key.assert_not_called()
                runner.controller.move_mouse_relative.assert_not_called()
                runner._claim_daily_double_reward.assert_called_once_with(1)
