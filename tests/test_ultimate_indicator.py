import unittest
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

from app import TaskRunner


FIXTURES = Path(__file__).parent / "fixtures" / "ultimate-indicator"


class UltimateIndicatorTests(unittest.TestCase):
    def _classify(self, name: str) -> bool:
        with Image.open(FIXTURES / name) as source:
            crop = np.asarray(source.convert("RGB"))
        return TaskRunner._ultimate_indicator_crop_ready(crop)

    def test_colored_complete_rings_are_ready_across_character_colors(self):
        for name in ("ready-1.png", "ready-2.png", "ready-3.png", "ready-8.png"):
            with self.subTest(name=name):
                self.assertTrue(self._classify(name))

    def test_cooldown_partial_and_dark_rings_are_not_ready(self):
        for name in ("not-ready-5.png", "not-ready-6.png", "not-ready-7.png"):
            with self.subTest(name=name):
                self.assertFalse(self._classify(name))

    def test_special_complete_gray_blue_ring_is_not_ready(self):
        self.assertFalse(self._classify("not-ready-4-special.png"))

    def test_check_interval_is_five_seconds(self):
        self.assertEqual(TaskRunner.ULTIMATE_READY_CHECK_INTERVAL, 5.0)

    def test_full_screenshot_uses_configured_lower_right_region(self):
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        with Image.open(FIXTURES / "ready-1.png") as source:
            icon = np.asarray(source.convert("RGB"))
        left, top, right, bottom = TaskRunner.ULTIMATE_INDICATOR_REGION
        region_left = round(frame.shape[1] * left)
        region_top = round(frame.shape[0] * top)
        region_width = round(frame.shape[1] * right) - region_left
        x = region_left + (region_width - icon.shape[1]) // 2
        y = region_top + 8
        frame[y:y + icon.shape[0], x:x + icon.shape[1]] = icon

        with tempfile.TemporaryDirectory() as temp_dir:
            screenshot = Path(temp_dir) / "screen.png"
            Image.fromarray(frame).save(screenshot)
            self.assertTrue(TaskRunner._ultimate_indicator_ready(screenshot))


if __name__ == "__main__":
    unittest.main()
