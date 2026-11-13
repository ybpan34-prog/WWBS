from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import numpy as np
from PIL import Image

import app
from tasks.reward_orb_scan import OrbDirectionSweep, RewardCamera


class OrbDirectionTests(unittest.TestCase):
    def test_camera_adjusts_step_to_distance_progress_and_reversal(self):
        camera = RewardCamera()
        far, _ = camera.follow('left', 394, 576, 1920, 1080)
        stalled, _ = camera.follow('left', 394, 576, 1920, 1080)
        near, _ = camera.follow('left', 850, 576, 1920, 1080)
        correction, dy = camera.follow('right', 1260, 576, 1920, 1080)
        self.assertLess(stalled, far)
        self.assertLess(far, near)
        self.assertLess(near, 0)
        self.assertEqual(dy, 0)
        self.assertGreater(correction, 0)
        self.assertLess(correction, abs(near))
        camera.follow('left', 394, 576, 1920, 1080)
        self.assertEqual([camera.sweep(i) for i in (0, 1, 11)], [-225, -300, -600])

    def test_scan_waits_for_full_lap_and_remembers_highest_direction(self):
        panorama = np.random.default_rng(34).random((72,864))
        offsets = (0,216,432,648,840,864)
        frames = [panorama[:,(np.arange(216)+offset)%864] for offset in offsets]
        scan=OrbDirectionSweep()
        with patch.object(scan,'_scene',side_effect=frames):
            for index,confidence in enumerate((.51,.73,.8,.72,.55,.56)):
                scan.observe(None,960,confidence)
                self.assertEqual(scan.complete,index==5)
                if index!=5:
                    scan.advance(260)
        self.assertEqual(scan.best.confidence,.8)
        self.assertEqual(scan.return_delta(),-780)

    def test_stationary_camera_and_textureless_scene_never_claim_a_full_lap(self):
        for frame in (np.zeros((72,216)),np.random.default_rng(4).random((72,216))):
            scan=OrbDirectionSweep()
            with patch.object(scan,'_scene',return_value=frame):
                for _ in range(20):
                    scan.observe(None,900,.7)
                    scan.advance(260)
            self.assertFalse(scan.complete)

    def runner(self,directory,locations,prompts):
        Image.new('RGB',(1920,1080),(20,30,40)).save(Path(directory)/'_runtime_screenshot.png')
        runner=app.TaskRunner(Mock(),Mock(),dry_run=False)
        runner._capture_for_matching=Mock()
        runner._daily_reward_orb_location=Mock(side_effect=locations)
        runner._daily_reward_marker_location=Mock(return_value=(None, None, 0.))
        runner._find_daily_reward_prompt=Mock(side_effect=prompts)
        runner._daily_battle_task_present=Mock(return_value=False)
        runner._sleep_interruptible=Mock()
        runner._claim_daily_double_reward=Mock()
        runner._wait_daily_reward_dialog=Mock(return_value='claim')
        return runner

    def show_arrow_free_marker(self, runner, x=960):
        runner._daily_reward_marker_location.return_value = (x, 300, .9)
        runner._daily_reward_marker_direction = Mock(return_value=None)

    def test_above_point_eight_goes_directly_without_starting_a_scan(self):
        with tempfile.TemporaryDirectory() as directory, patch('tasks.other.APP_DIR',Path(directory)):
            runner=self.runner(directory,[(960,300,.81)],[None,None,Mock()])
            self.show_arrow_free_marker(runner)
            self.assertTrue(runner._collect_daily_reward(1))
            runner.controller.press_keys.assert_called_once_with(('W',),1000)
            runner.controller.move_mouse_relative.assert_not_called()

    def test_arrow_free_marker_allows_orb_at_selected_threshold(self):
        with tempfile.TemporaryDirectory() as directory, patch('tasks.other.APP_DIR',Path(directory)):
            for confidence in (.45, .6, .8):
                runner=self.runner(directory,[(960,300,confidence)],[None,None,Mock()])
                self.show_arrow_free_marker(runner)
                runner.daily_orb_confidence = confidence
                self.assertTrue(runner._collect_daily_reward(1))
                runner.controller.press_keys.assert_called_once_with(('W',),1000)
                runner.controller.move_mouse_relative.assert_not_called()

    def test_missing_marker_only_rotates_even_after_twelve_searches(self):
        with tempfile.TemporaryDirectory() as directory, patch('tasks.other.APP_DIR', Path(directory)):
            runner = self.runner(directory, [(None, None, .3)]*14, [None]*13+[Mock()])
            self.assertTrue(runner._collect_daily_reward(1))
            turns = runner.controller.move_mouse_relative.call_args_list
            self.assertEqual([call.args for call in turns[:12]],
                             [(step, 0) for step in (225, 300, 375, 450, 525, 600, 600, 600, 600, 600, 600, 600)])
            self.assertEqual(len(turns), 13)
            self.assertEqual(turns[-1].args, (600, 0))
            runner.controller.press_keys.assert_not_called()
            runner.controller.press_key.assert_called_once_with('F', 100)

    def test_selected_confidence_rejects_lower_orb_and_accepts_above_threshold(self):
        with tempfile.TemporaryDirectory() as directory, patch('tasks.other.APP_DIR', Path(directory)):
            runner = self.runner(directory, [(1600, 300, .81), (960, 300, .91)], [None, None, None, Mock()])
            self.show_arrow_free_marker(runner, x=460)
            runner.daily_orb_confidence = .9
            self.assertTrue(runner._collect_daily_reward(1))
            runner.controller.move_mouse_relative.assert_not_called()
            runner.controller.press_keys.assert_called_once_with(('W',), 1000)

    def test_combat_return_during_camera_search_stops_without_claiming(self):
        with tempfile.TemporaryDirectory() as directory, patch('tasks.other.APP_DIR', Path(directory)):
            runner = self.runner(directory, [(None, None, .3)]*15, [None]*15)
            runner._daily_combat_visible = Mock(side_effect=[False]*13+[True]*2)
            self.assertFalse(runner._collect_daily_reward(1))
            self.assertEqual(runner.controller.move_mouse_relative.call_count, 13)
            runner.controller.press_keys.assert_not_called()
            runner.controller.press_key.assert_not_called()
            runner._claim_daily_double_reward.assert_not_called()

    def test_boss_hud_alone_prevents_reward_search_even_without_objective(self):
        with tempfile.TemporaryDirectory() as directory, patch('tasks.other.APP_DIR', Path(directory)):
            runner = self.runner(directory, [(None, None, .3)], [None, None])
            with patch('tasks.other.boss_bar_present', return_value=True):
                self.assertFalse(runner._collect_daily_reward(1))
            runner.controller.move_mouse_relative.assert_not_called()
            runner.controller.press_keys.assert_not_called()

    def test_confidence_save_keeps_zone_and_loads_for_task(self):
        from tasks.reward_orb_scan import orb_confidence
        import json
        for raw, expected in [('75%', .75), (.9, .9), ('bad', .45), (float('nan'), .45), (2, .45)]:
            self.assertEqual(orb_confidence(raw), expected)
        with tempfile.TemporaryDirectory() as directory, patch.object(app, 'DAILY_CONFIG', Path(directory)/'daily-settings.json'):
            ui = app.App.__new__(app.App)
            ui.daily_zone = Mock(get=Mock(return_value=app.DAILY_ZONE_NAMES[0]))
            ui.daily_orb_confidence = Mock(get=Mock(return_value='75%'))
            ui.status = Mock()
            ui._save_daily_zone()
            data = json.loads(app.DAILY_CONFIG.read_text(encoding='utf-8'))
            self.assertEqual(data['orb_confidence'], .75)
            self.assertEqual(data['zone'], app.DAILY_ZONE_NAMES[0])
            runner = app.TaskRunner(Mock(), Mock(), daily_orb_confidence=data['orb_confidence'])
            self.assertEqual(runner.daily_orb_confidence, .75)

    def test_reward_prompt_interrupts_scan_without_more_camera_or_movement(self):
        with tempfile.TemporaryDirectory() as directory, patch('tasks.other.APP_DIR',Path(directory)):
            runner=self.runner(directory,[(960,300,.7)],[Mock()])
            self.assertTrue(runner._collect_daily_reward(1))
            runner.controller.move_mouse_relative.assert_not_called()
            runner.controller.press_keys.assert_not_called()
            runner.controller.press_key.assert_called_once_with('F',100)


if __name__=='__main__':
    unittest.main()
