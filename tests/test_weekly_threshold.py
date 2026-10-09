import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np
from PIL import Image

import app
import image_matcher
from image_matcher import MatchResult, TemplateMatcher


class WeeklyThresholdTests(unittest.TestCase):
    def test_old_weekly_config_uses_half_threshold_and_first_probe_succeeds(self):
        runner = app.TaskRunner(Mock(spec=[]), Mock(), dry_run=False)
        runner._weekly_monitoring = True
        runner._capture_for_matching = Mock()
        runner._check_weekly_cap = Mock()
        runner._fast_scales = Mock(return_value=[1.0, .95, 1.05])
        runner._random_click_point = Mock(return_value=(100, 200))
        runner.matcher.find = Mock(return_value=MatchResult(80, 180, 40, 40, .6))
        runner._sleep_interruptible = Mock()
        old_step = app.Step(action="tap_image", template="menu3.png", threshold=.82)
        result = runner._probe_cycle_template(old_step, "本次")
        self.assertEqual(result, (100, 200, .6))
        runner.matcher.find.assert_called_once_with(
            app.APP_DIR / "_runtime_screenshot.png", "menu3.png", .5,
            [1.0, .95, 1.05], first_match=True,
        )
        runner._capture_for_matching.assert_called_once()
        runner._sleep_interruptible.assert_not_called()

    def test_unmatched_first_scale_continues_and_stops_at_next_success(self):
        rng = np.random.default_rng(42)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            Image.fromarray(rng.integers(0, 256, (100, 200, 3), dtype=np.uint8)).save(root / "screen.png")
            Image.fromarray(rng.integers(0, 256, (20, 40, 3), dtype=np.uint8)).save(root / "menu.png")
            candidates = [MatchResult(20, 30, 40, 20, score) for score in (.4, .6, .9)]
            with patch.object(image_matcher, "_match_single_scale_gray", side_effect=candidates) as match:
                result = TemplateMatcher(root).find(root / "screen.png", "menu.png", .5,
                                                    [1, .9, 1.1], first_match=True)
            self.assertEqual(result.score, .6)
            self.assertEqual(match.call_count, 2)

    def test_non_weekly_task_retains_configured_threshold(self):
        runner = app.TaskRunner(Mock(spec=[]), Mock())
        runner._capture_for_matching = Mock()
        runner._fast_scales = Mock(return_value=[1.0])
        runner._random_click_point = Mock(return_value=(30, 40))
        runner.matcher.find = Mock(return_value=MatchResult(20, 30, 20, 20, .9))
        runner._find_image(app.Step(action="tap_image", template="other.png", threshold=.79), single_attempt=True)
        runner.matcher.find.assert_called_once_with(
            app.APP_DIR / "_runtime_screenshot.png", "other.png", .79, [1.0],
        )


if __name__ == "__main__":
    unittest.main()
