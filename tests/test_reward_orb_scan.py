from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import numpy as np
from PIL import Image

import app
from tasks.reward_orb_scan import ORB_SCAN_STEP, OrbDirectionSweep


class OrbDirectionTests(unittest.TestCase):
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
        runner._find_daily_reward_prompt=Mock(side_effect=prompts)
        runner._daily_battle_task_present=Mock(return_value=False)
        runner._sleep_interruptible=Mock()
        runner._claim_daily_double_reward=Mock()
        return runner

    def test_above_point_eight_goes_directly_without_starting_a_scan(self):
        with tempfile.TemporaryDirectory() as directory, patch('tasks.other.APP_DIR',Path(directory)):
            runner=self.runner(directory,[(960,300,.81),(960,300,.81)],[None,Mock()])
            with patch('tasks.other.OrbDirectionSweep') as sweep:
                self.assertTrue(runner._collect_daily_reward(1))
                sweep.assert_not_called()
            runner.controller.press_keys.assert_called_once_with(('W',),500)
            runner.controller.move_mouse_relative.assert_not_called()

    def test_point_eight_still_scans_and_forward_waits_for_lap_and_fresh_capture(self):
        with tempfile.TemporaryDirectory() as directory, patch('tasks.other.APP_DIR',Path(directory)):
            runner=self.runner(directory,[(960,300,.8)]*4,[None,None,None,Mock()])
            scan=Mock(complete=False,best=Mock(confidence=.8))
            scan.return_delta.return_value=-ORB_SCAN_STEP
            order=[]
            def observe(*_):
                order.append('observe')
                scan.complete=scan.observe.call_count==2
            scan.observe.side_effect=observe
            runner._capture_for_matching.side_effect=lambda _: order.append('capture')
            runner.controller.move_mouse_relative.side_effect=lambda *_: order.append('turn')
            runner.controller.press_keys.side_effect=lambda *_: order.append('forward')
            with patch('tasks.other.OrbDirectionSweep',return_value=scan):
                self.assertTrue(runner._collect_daily_reward(1))
            self.assertEqual(order,['capture','observe','turn','capture','observe','turn','capture','forward','capture'])
            runner.controller.press_keys.assert_called_once_with(('W',),500)

    def test_twelve_failed_turns_then_spiral_and_prompt_stops_movement(self):
        with tempfile.TemporaryDirectory() as directory, patch('tasks.other.APP_DIR', Path(directory)):
            runner = self.runner(directory, [(None, None, .3)]*14, [None]*13+[Mock()])
            self.assertTrue(runner._collect_daily_reward(1))
            turns = runner.controller.move_mouse_relative.call_args_list
            self.assertEqual([call.args for call in turns[:12]], [(300, 0)]*12)
            self.assertEqual(len(turns), 13)
            self.assertEqual(turns[-1].args, (-84, 0))
            runner.controller.press_keys.assert_called_once_with(('W',), 180)
            runner.controller.press_key.assert_called_once_with('F', 100)

    def test_selected_confidence_rejects_lower_orb_and_accepts_above_threshold(self):
        with tempfile.TemporaryDirectory() as directory, patch('tasks.other.APP_DIR', Path(directory)):
            runner = self.runner(directory, [(960, 300, .81), (960, 300, .91), (960, 300, .91)], [None, None, Mock()])
            runner.daily_orb_confidence = .9
            self.assertTrue(runner._collect_daily_reward(1))
            runner.controller.move_mouse_relative.assert_called_once_with(300, 0)
            runner.controller.press_keys.assert_called_once_with(('W',), 500)

    def test_combat_return_during_spiral_stops_without_claiming_or_moving_again(self):
        with tempfile.TemporaryDirectory() as directory, patch('tasks.other.APP_DIR', Path(directory)):
            runner = self.runner(directory, [(None, None, .3)]*14, [None]*13+[Mock()])
            runner._daily_combat_visible = Mock(side_effect=[False]*13+[True])
            self.assertFalse(runner._collect_daily_reward(1))
            self.assertEqual(runner.controller.move_mouse_relative.call_count, 13)
            runner.controller.press_keys.assert_called_once_with(('W',), 180)
            runner.controller.press_key.assert_not_called()
            runner._claim_daily_double_reward.assert_not_called()

    def test_boss_hud_alone_prevents_reward_search_even_without_objective(self):
        with tempfile.TemporaryDirectory() as directory, patch('tasks.other.APP_DIR', Path(directory)):
            runner = self.runner(directory, [(None, None, .3)], [None])
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
            with patch('tasks.other.OrbDirectionSweep') as sweep:
                self.assertTrue(runner._collect_daily_reward(1))
                sweep.assert_not_called()
            runner.controller.move_mouse_relative.assert_not_called()
            runner.controller.press_keys.assert_not_called()
            runner.controller.press_key.assert_called_once_with('F',100)


if __name__=='__main__':
    unittest.main()
