from pathlib import Path
import tempfile
import unittest

from PIL import Image

from tasks.daily_reward_marker import reward_marker_location


FIXTURE = Path(__file__).parent/'fixtures/daily-reward-marker-reported.png'


class DailyMarkerTests(unittest.TestCase):
    def test_marker_below_bright_scenery_is_found_at_scaled_resolutions(self):
        with Image.open(FIXTURE) as image, tempfile.TemporaryDirectory() as directory:
            for width in (1280, 1600, 1920, 2560):
                path = Path(directory)/'scene.png'
                image.resize((width, round(image.height*width/image.width))).save(path)
                x, y, score = reward_marker_location(path)
                self.assertIsNotNone(x, width)
                self.assertAlmostEqual(x/width, 1250/1600, delta=.005)
                self.assertAlmostEqual(y/width, 504/1600, delta=.005)
                self.assertGreaterEqual(score, .82)

    def test_same_scene_with_marker_removed_does_not_follow_white_flare(self):
        with Image.open(FIXTURE) as image, tempfile.TemporaryDirectory() as directory:
            image.paste((60, 60, 65), (1210, 475, 1290, 550))
            path = Path(directory)/'scene.png'
            image.save(path)
            self.assertEqual(reward_marker_location(path), (None, None, 0.))

    def test_large_white_core_alone_is_not_a_reward_target(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Image.new('RGB', (1920, 1080), 'black')
            image.paste('white', (850, 250, 1100, 450))
            path = Path(directory)/'scene.png'
            image.save(path)
            self.assertEqual(reward_marker_location(path), (None, None, 0.))
