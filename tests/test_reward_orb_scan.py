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
