import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from PIL import Image, ImageDraw
import app
from weekly_rewards import WeeklyRewardsVision, WeeklyLimitReached


class WeeklyRewardsTests(unittest.TestCase):
    def setUp(self):
        self.vision = WeeklyRewardsVision(app.TEMPLATES_DIR / "weekly")

    def fixture(self, claimed=(), glowing=()):
        image = Image.new("RGB", (1920, 1080), "#4b5967")
        image.paste(Image.open(app.TEMPLATES_DIR / "weekly/weekly_tab.png"), (585, 125))
        for index in claimed:
            x = self.vision.CHEST_X[index]
            image.paste(Image.open(app.TEMPLATES_DIR / "weekly/claimed.png"), (x - 21, 945))
        for index in glowing:
            x = self.vision.CHEST_X[index]
            image.paste(Image.open(app.TEMPLATES_DIR / "weekly/claimable.png"), (x - 28, 944))
            ImageDraw.Draw(image).polygon([(x + 33, 912), (x + 43, 922), (x + 33, 932), (x + 23, 922)], fill="#df536c")
        return image

    def test_selects_dynamic_rightmost_5000_or_6000_at_scales(self):
        for scale in (0.75, 1.0, 4 / 3):
            for index in (4, 5):
                with self.subTest(scale=scale, tier=index), tempfile.TemporaryDirectory() as tmp:
                    image = self.fixture(glowing=range(index + 1))
                    image = image.resize((round(1920 * scale), round(1080 * scale)))
                    path = Path(tmp) / "screen.png"
                    image.save(path)
                    self.assertEqual(self.vision.rightmost_claimable(path), (round(self.vision.CHEST_X[index] * scale), round(960 * scale)))

    def test_claimed_chests_never_clicked(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "screen.png"
            self.fixture(claimed=range(6)).save(path)
            self.assertTrue(self.vision.all_claimed(path))
            self.assertIsNone(self.vision.rightmost_claimable(path))

    def test_requires_weekly_page_and_red_hint(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "screen.png"
            image = self.fixture(glowing=[5])
            ImageDraw.Draw(image).rectangle((570, 115, 710, 166), fill="black")
            image.save(path)
            self.assertIsNone(self.vision.rightmost_claimable(path))
            image = self.fixture(glowing=[5])
            ImageDraw.Draw(image).rectangle((1798, 909, 1825, 938), fill="black")
            image.save(path)
            self.assertIsNone(self.vision.rightmost_claimable(path))

    def test_cap_navigation_and_verified_claim(self):
        runner = app.TaskRunner(Mock(), Mock(), dry_run=False)
        runner._tap_ratio = Mock()
        runner._capture_for_matching = Mock()
        runner._sleep_interruptible = Mock()
        runner._dismiss_reward_overlay_safely = Mock()
        vision = Mock()
        vision.cap_page.side_effect = ["result", "home"]
        vision.weekly_page.return_value = True
        vision.all_claimed.side_effect = [False, True]
        vision.rightmost_claimable.return_value = (1778, 960)
        vision.claimed_at.return_value = True
        with patch.object(app, "WeeklyRewardsVision", return_value=vision):
            with self.assertRaises(WeeklyLimitReached):
                runner._check_weekly_cap(Path("unused"))
        self.assertEqual([call.args[:2] for call in runner._tap_ratio.call_args_list], [(0.664, 0.848), (0.940, 0.0565)])
        runner.controller.tap.assert_called_once_with(1778, 960)
        self.assertFalse(runner.weekly_rewards_pending)

    def test_unknown_chest_state_requires_review_and_blocks_shutdown(self):
        runner = app.TaskRunner(Mock(), Mock(), dry_run=False)
        runner._tap_ratio = Mock()
        runner._capture_for_matching = Mock()
        vision = Mock()
        vision.cap_page.return_value = "home"
        vision.weekly_page.return_value = True
        vision.all_claimed.return_value = False
        vision.rightmost_claimable.return_value = None
        with patch.object(app, "WeeklyRewardsVision", return_value=vision), self.assertRaises(WeeklyLimitReached):
            runner._check_weekly_cap(Path("unused"))
        runner.controller.tap.assert_not_called()
        self.assertTrue(runner.weekly_rewards_pending)

    def test_cap_sentinel_is_not_retried_as_missing_template(self):
        runner = app.TaskRunner(Mock(), Mock(), dry_run=False)
        runner._find_image = Mock(side_effect=WeeklyLimitReached)
        with self.assertRaises(WeeklyLimitReached):
            runner._wait_for_cycle_template(app.Step(action="tap_image", template="menu.png"))
        runner._find_image.assert_called_once()
        self.assertFalse(runner.stop_event.is_set())


if __name__ == "__main__":
    unittest.main()
