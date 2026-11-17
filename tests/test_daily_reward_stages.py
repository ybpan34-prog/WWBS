import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, call, patch

from PIL import Image

from app import TaskRunner
from tasks.daily_verified import VerifiedDailyNavigation


class DailyRewardStagesTest(unittest.TestCase):
    def setUp(self):
        directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch("tasks.other.APP_DIR", directory))
        Image.new("RGB", (1920, 1080)).save(directory / "_runtime_screenshot.png")
        self.runner = TaskRunner(Mock(), Mock())
        self.navigation = VerifiedDailyNavigation(self.runner)
        self.events = Mock()
        for name, event in (
            ("_capture_for_matching", "capture"),
            ("_daily_reward_dialog_present", "dialog"),
            ("_daily_reward_marker", "arrow"),
            ("_daily_reward_orb_location", "orb"),
            ("_find_daily_reward_prompt", "prompt"),
            ("_claim_daily_double_reward", "claim"),
        ):
            setattr(self.runner, name, getattr(self.events, event))
        self.runner._sleep_interruptible = Mock()
        self.runner._wait_daily_reward_dialog = Mock(return_value="claim")
        self.events.attach_mock(self.runner.controller, "controller")
        self.events.capture.return_value = True
        self.events.dialog.return_value = False

    def test_existing_dialog_is_claimed_before_navigation(self):
        self.events.dialog.return_value = True
        self.assertTrue(self.navigation._collect_daily_reward(1))
        self.events.dialog.assert_called_once()
        self.events.claim.assert_called_once_with(1)
        self.events.arrow.assert_not_called()
        self.events.orb.assert_not_called()

    def test_arrows_then_orb_then_turn_back_after_confidence_drops(self):
        self.events.arrow.side_effect = [
            (600, 300, .9, "left"), (960, 300, .9, None), (960, 300, .9, None),
        ]
        self.events.orb.side_effect = [(960, 300, .8), (None, None, .55), (960, 300, .85)]
        self.events.prompt.side_effect = [None, (900, 500)]
        self.assertTrue(self.navigation._collect_daily_reward(2))
        self.assertEqual([event[0] for event in self.events.mock_calls if event[0] != "capture"], [
            "dialog", "arrow", "controller.move_mouse_relative", "arrow", "arrow",
            "orb", "prompt", "controller.press_keys", "orb", "controller.move_mouse_relative",
            "orb", "prompt", "controller.press_key", "claim",
        ])
        self.runner.controller.press_keys.assert_called_once_with(("W",), 750)
        self.runner.controller.press_key.assert_called_once_with("F", 100)
        self.assertEqual(self.runner.controller.move_mouse_relative.call_args, call(450, 0))
        self.events.claim.assert_called_once_with(2)
