from itertools import islice
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from PIL import Image

from tasks.echo_spiral import echo_spiral_steps
from tasks.runner import TaskRunner


class EchoSpiralTests(unittest.TestCase):
    def test_path_turns_and_expands_across_laps_without_long_blind_walks(self):
        x = y = heading = yaw_total = 0.
        laps, points = [], []
        for turn, duration in islice(echo_spiral_steps(), 250):
            self.assertLess(turn, 0)
            self.assertLessEqual(duration, 220)
            heading += turn/84*math.pi/12  # Nominal camera yaw; radius is not a fixed game distance.
            yaw_total -= turn
            x += duration*math.cos(heading)
            y += duration*math.sin(heading)
            points.append((x, y))
            if yaw_total >= (len(laps)+1)*84*24:
                laps.append(points)
                points = []
                if len(laps) == 3:
                    break
        self.assertEqual(len(laps), 3)
        extents = [max(x for x, _ in lap)-min(x for x, _ in lap) for lap in laps]
        self.assertGreater(extents[1], extents[0]*1.25)
        self.assertGreater(extents[2], extents[1]*1.15)

    def runner(self, directory):
        path = Path(directory)/'_runtime_screenshot.png'
        Image.new('RGB', (1920, 1080), (30, 40, 50)).save(path)
        runner = TaskRunner(Mock(), Mock(), dry_run=False)
        runner._capture_for_matching = Mock()
        runner._find_4c_absorb_prompt = Mock(return_value=(None, ''))
        return runner

    def test_stop_during_turn_never_starts_another_forward_segment(self):
        with tempfile.TemporaryDirectory() as directory:
            runner = self.runner(directory)
            runner.controller.move_mouse_relative.side_effect = lambda *_: runner.stop_event.set()
            with patch('tasks.combat_4c.APP_DIR', Path(directory)):
                runner._collect_4c_reward(1)
            runner.controller.press_keys.assert_not_called()
            runner.controller.press_key.assert_not_called()

    def test_timed_out_spiral_releases_keys_and_does_not_absorb_or_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            runner = self.runner(directory)
            now = [0.]
            runner.REWARD_SEARCH_TIMEOUT = .1
            runner._sleep_interruptible = lambda duration: now.__setitem__(0, now[0]+duration)
            with patch('tasks.combat_4c.APP_DIR', Path(directory)), \
                    patch('tasks.combat_4c.time.monotonic', side_effect=lambda: now[0]), \
                    self.assertRaisesRegex(RuntimeError, '螺旋向外搜索'):
                runner._collect_4c_reward(1)
            runner.controller.release_keys.assert_called()
            runner.controller.press_key.assert_not_called()


if __name__ == '__main__':
    unittest.main()
