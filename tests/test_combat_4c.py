import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, call

from PIL import Image, ImageDraw

import app
from windows_client import ClientWindowController


class Combat4CTests(unittest.TestCase):
    def test_updated_rotation_and_reward_search_timing(self):
        self.assertEqual(app.TaskRunner.HEAL_ROTATION_INTERVAL, 9.0)
        self.assertEqual(app.TaskRunner.MAIN_Q_INTERVAL, 20.0)
        self.assertEqual(app.TaskRunner.ULTIMATE_READY_CHECK_INTERVAL, 5.0)
        self.assertEqual(app.TaskRunner.REWARD_SEARCH_TURN_PIXELS, 190 * 5)
        self.assertLess(app.TaskRunner.REWARD_INITIAL_CHECK_DELAY, 0.2)
        self.assertGreaterEqual(app.TaskRunner.REWARD_SEARCH_TIMEOUT, 90.0)
        self.assertEqual(app.TaskRunner.EMPTY_HEALTH_CONFIRMATIONS, 3)
        self.assertEqual(app.TaskRunner.BOSS_HEADER_CHECK_INTERVAL, 0.5)
        self.assertEqual(app.TaskRunner.DAILY_BATTLE_END_CHECK_INTERVAL, 0.2)

    def test_dark_absorb_prompt_template_is_detectable(self):
        template = Path(app.TEMPLATES_DIR) / "4c" / "absorb_prompt_dark.png"
        self.assertTrue(template.exists())
        with tempfile.TemporaryDirectory() as directory:
            screenshot = Path(directory) / "screen.png"
            canvas = Image.new("RGB", (1920, 1080), (15, 24, 32))
            with Image.open(template) as prompt:
                canvas.paste(prompt.convert("RGB"), (1200, 515))
            canvas.save(screenshot)
            runner = app.TaskRunner(Mock(), lambda _message: None, dry_run=False)
            runner.matcher.templates_dir = template.parent

            match, name = runner._find_4c_absorb_prompt(screenshot, 1.0)

            self.assertIsNotNone(match)
            self.assertEqual(name, "absorb_prompt_dark.png")
            self.assertGreater(match.score, 0.95)

    def test_absorb_prompt_is_detectable_at_a_nearby_scale(self):
        template = Path(app.TEMPLATES_DIR) / "4c" / "absorb_prompt_dark.png"
        with tempfile.TemporaryDirectory() as directory:
            screenshot = Path(directory) / "scaled-screen.png"
            canvas = Image.new("RGB", (1920, 1080), (15, 24, 32))
            with Image.open(template) as prompt:
                scaled = prompt.convert("RGB").resize(
                    (round(prompt.width * 0.88), round(prompt.height * 0.88)),
                    Image.Resampling.LANCZOS,
                )
                canvas.paste(scaled, (1180, 520))
            canvas.save(screenshot)
            runner = app.TaskRunner(Mock(), lambda _message: None, dry_run=False)
            runner.matcher.templates_dir = template.parent

            match, _name = runner._find_4c_absorb_prompt(screenshot, 1.0)

            self.assertIsNotNone(match)
            self.assertGreater(match.score, 0.90)

    def test_reward_prompt_outer_shape_is_not_accepted_as_absorb(self):
        template = Path(app.TEMPLATES_DIR) / "4c" / "absorb_prompt_dark.png"
        with tempfile.TemporaryDirectory() as directory:
            screenshot = Path(directory) / "reward-only.png"
            canvas = Image.new("RGB", (1920, 1080), (15, 24, 32))
            with Image.open(template) as source:
                reward = source.convert("RGB")
                draw = ImageDraw.Draw(reward)
                draw.rectangle((130, 19, 198, 69), fill=(30, 34, 36))
                draw.rectangle((137, 29, 145, 59), fill=(240, 240, 240))
                draw.rectangle((153, 29, 161, 59), fill=(240, 240, 240))
                draw.rectangle((169, 29, 177, 59), fill=(240, 240, 240))
                canvas.paste(reward, (1180, 515))
            canvas.save(screenshot)
            runner = app.TaskRunner(Mock(), lambda _message: None, dry_run=False)
            runner.matcher.templates_dir = template.parent

            match, name = runner._find_4c_absorb_prompt(screenshot, 1.0)

            self.assertIsNone(match)
            self.assertEqual(name, "")

    def test_absorb_text_wins_when_reward_and_absorb_are_both_visible(self):
        template = Path(app.TEMPLATES_DIR) / "4c" / "absorb_prompt_dark.png"
        with tempfile.TemporaryDirectory() as directory:
            screenshot = Path(directory) / "both.png"
            canvas = Image.new("RGB", (1920, 1080), (15, 24, 32))
            with Image.open(template) as source:
                absorb = source.convert("RGB")
                reward = absorb.copy()
                draw = ImageDraw.Draw(reward)
                draw.rectangle((130, 19, 198, 69), fill=(30, 34, 36))
                draw.rectangle((137, 29, 145, 59), fill=(240, 240, 240))
                draw.rectangle((153, 29, 161, 59), fill=(240, 240, 240))
                draw.rectangle((169, 29, 177, 59), fill=(240, 240, 240))
                canvas.paste(reward, (850, 515))
                canvas.paste(absorb, (1280, 515))
            canvas.save(screenshot)
            runner = app.TaskRunner(Mock(), lambda _message: None, dry_run=False)
            runner.matcher.templates_dir = template.parent

            match, name = runner._find_4c_absorb_prompt(screenshot, 1.0)

            self.assertIsNotNone(match)
            self.assertEqual(name, "absorb_prompt_dark.png")
            self.assertGreater(match.x, 1250)

    def test_combat_binding_presets_use_friendly_mouse_button_names(self):
        self.assertEqual(app.App._combat_binding_display("XBUTTON1"), "鼠标侧键1")
        self.assertEqual(app.App._combat_binding_display("XBUTTON2"), "鼠标侧键2")
        self.assertEqual(app.App._combat_binding_display("E"), "E")

    def test_main_attack_uses_same_steady_interval_as_healer(self):
        controller = Mock()
        runner = app.TaskRunner(controller, lambda _message: None, dry_run=False)
        runner._sleep_interruptible = Mock()

        runner._perform_4c_main_attack()

        self.assertEqual(controller.left_click.call_count, 1)
        self.assertEqual(runner._sleep_interruptible.call_count, 1)
        self.assertEqual(
            app.TaskRunner.MAIN_ATTACK_CLICK_INTERVAL,
            app.TaskRunner.HEAL_ATTACK_CLICK_INTERVAL,
        )
        runner._sleep_interruptible.assert_called_with(app.TaskRunner.MAIN_ATTACK_CLICK_INTERVAL)

    def test_each_battle_starts_with_middle_click_target_lock(self):
        controller = Mock()
        runner = app.TaskRunner(controller, lambda _message: None, dry_run=False)
        runner._sleep_interruptible = Mock()
        runner._capture_for_matching = Mock()
        runner._boss_health_ratio = Mock(return_value=0.0)
        runner._boss_name_ratio = Mock(return_value=0.02)
        runner._boss_bar_track_score = Mock(return_value=0.20)
        controller.left_click.side_effect = lambda: runner.stop_event.set()

        runner._run_4c_battle(Mock(timeout=30.0), "E", "R", 1)

        controller.press_key.assert_any_call("1", 65)
        controller.middle_click.assert_called_once_with()
        controller.left_click.assert_called_once_with()

    def test_continuous_attack_runs_on_its_own_rhythm(self):
        controller = Mock()
        runner = app.TaskRunner(controller, lambda _message: None, dry_run=False)
        runner.MAIN_ATTACK_CLICK_INTERVAL = 0.001
        enabled = app.threading.Event()
        finished = app.threading.Event()
        click_lock = app.threading.Lock()
        enabled.set()

        def finish_after_four_clicks():
            if controller.left_click.call_count >= 4:
                finished.set()

        controller.left_click.side_effect = finish_after_four_clicks
        runner._run_4c_continuous_attack(enabled, finished, click_lock)

        self.assertEqual(controller.left_click.call_count, 4)

    def test_heal_rotation_spaces_attacks_and_waits_before_return(self):
        controller = Mock()
        runner = app.TaskRunner(controller, lambda _message: None, dry_run=False)
        runner._sleep_interruptible = Mock()

        runner._perform_4c_heal_rotation("E")

        self.assertEqual(controller.left_click.call_count, 6)
        waits = [call.args[0] for call in runner._sleep_interruptible.call_args_list]
        self.assertEqual(waits[0], app.TaskRunner.HEAL_SWITCH_SETTLE_DELAY)
        self.assertEqual(waits.count(app.TaskRunner.HEAL_ATTACK_CLICK_INTERVAL), 4)
        self.assertGreater(app.TaskRunner.HEAL_ATTACK_CLICK_INTERVAL, 0.10)
        self.assertIn(app.TaskRunner.HEAL_RETURN_DELAY, waits)
        controller.press_key.assert_any_call("3", 65)
        controller.press_key.assert_any_call("Q", 65)
        controller.press_key.assert_any_call("1", 65)
        self.assertEqual(controller.press_key.call_args_list.count(call("SPACE", 50)), 2)

    def test_heal_rotation_stops_sending_keys_after_stop_request(self):
        controller = Mock()
        runner = app.TaskRunner(controller, lambda _message: None, dry_run=False)

        def stop_during_slot_switch(_seconds):
            runner.stop_event.set()

        runner._sleep_interruptible = Mock(side_effect=stop_during_slot_switch)

        self.assertFalse(runner._perform_4c_heal_rotation("E"))
        controller.press_key.assert_called_once_with("3", 65)
        controller.press_binding.assert_not_called()
        controller.left_click.assert_not_called()

    def test_ultimate_binding_defaults_to_r_and_supports_mouse_buttons(self):
        runner = app.TaskRunner(Mock(), lambda _message: None, dry_run=False)
        self.assertEqual(runner.combat_ultimate_key, "R")
        self.assertEqual(ClientWindowController.normalize_input_binding("R"), "R")
        self.assertEqual(ClientWindowController.normalize_input_binding("鼠标侧键1"), "XBUTTON1")

    def test_boss_header_detection_requires_name_and_bar_track_to_disappear(self):
        with tempfile.TemporaryDirectory() as directory:
            present_path = Path(directory) / "present.png"
            gone_path = Path(directory) / "gone.png"
            present = Image.new("RGB", (1920, 1080), (12, 18, 24))
            draw = ImageDraw.Draw(present)
            draw.rectangle((790, 15, 1130, 37), fill=(235, 230, 220))
            draw.rectangle((680, 55, 1240, 67), fill=(120, 120, 120))
            present.save(present_path)
            Image.new("RGB", (1920, 1080), (12, 18, 24)).save(gone_path)

            self.assertGreater(app.TaskRunner._boss_name_ratio(present_path), 0.015)
            self.assertGreater(app.TaskRunner._boss_bar_track_score(present_path), 0.18)
            self.assertLess(app.TaskRunner._boss_name_ratio(gone_path), 0.015)
            self.assertLess(app.TaskRunner._boss_bar_track_score(gone_path), 0.18)

    def test_health_bar_ratio_detects_colored_bar_and_empty_bar(self):
        with tempfile.TemporaryDirectory() as directory:
            filled_path = Path(directory) / "filled.png"
            empty_path = Path(directory) / "empty.png"
            filled = Image.new("RGB", (1920, 1080), (30, 35, 42))
            draw = ImageDraw.Draw(filled)
            draw.rectangle((680, 55, 1240, 67), fill=(225, 88, 35))
            filled.save(filled_path)
            Image.new("RGB", (1920, 1080), (30, 35, 42)).save(empty_path)

            self.assertGreater(app.TaskRunner._boss_health_ratio(filled_path), 0.20)
            self.assertLess(app.TaskRunner._boss_health_ratio(empty_path), 0.015)

    def test_skill_binding_supports_keyboard_and_mouse_side_buttons(self):
        self.assertEqual(ClientWindowController.normalize_input_binding("e"), "E")
        self.assertEqual(ClientWindowController.normalize_input_binding("Q"), "Q")
        self.assertEqual(ClientWindowController.normalize_input_binding("鼠标侧键1"), "XBUTTON1")
        self.assertEqual(ClientWindowController.normalize_input_binding("鼠标侧键2"), "XBUTTON2")
        self.assertEqual(ClientWindowController.normalize_input_binding("空格键"), "SPACE")
        self.assertEqual(ClientWindowController.normalize_input_binding("Esc"), "ESC")

    def test_gold_target_location_finds_large_gold_reward(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "gold.png"
            image = Image.new("RGB", (1920, 1080), (35, 45, 55))
            draw = ImageDraw.Draw(image)
            draw.rectangle((930, 260, 1030, 350), fill=(245, 190, 70))
            image.save(target)

            ratio, x, y = app.TaskRunner._gold_target_location(target)
            self.assertGreater(ratio, 0.005)
            self.assertIsNotNone(x)
            self.assertIsNotNone(y)
            self.assertGreater(x, 900)

    def test_gold_target_location_rejects_large_vertical_billboard(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "billboard.png"
            image = Image.new("RGB", (1920, 1080), (18, 24, 30))
            draw = ImageDraw.Draw(image)
            draw.rectangle((1250, 160, 1420, 520), fill=(210, 137, 45))
            draw.polygon(((1250, 160), (1420, 160), (1370, 520), (1280, 520)), fill=(235, 169, 65))
            image.save(target)

            ratio, x, y = app.TaskRunner._gold_target_location(target)

            self.assertEqual(ratio, 0.0)
            self.assertIsNone(x)
            self.assertIsNone(y)

    def test_gold_target_location_rejects_ring_below_wide_billboard(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "billboard-ring.png"
            image = Image.new("RGB", (1920, 1080), (18, 24, 30))
            draw = ImageDraw.Draw(image)
            draw.rectangle((930, 220, 1390, 480), fill=(220, 153, 45))
            draw.ellipse((1030, 610, 1110, 690), fill=(210, 155, 58))
            draw.ellipse((1048, 628, 1092, 672), fill=(18, 24, 30))
            image.save(target)

            ratio, x, y = app.TaskRunner._gold_target_location(target)

            self.assertEqual(ratio, 0.0)
            self.assertIsNone(x)
            self.assertIsNone(y)

    def test_gold_target_location_rejects_pale_floor_reflection(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "pale-reflection.png"
            image = Image.new("RGB", (1920, 1080), (35, 45, 55))
            draw = ImageDraw.Draw(image)
            draw.polygon(((600, 350), (1500, 380), (1400, 470), (650, 440)), fill=(245, 230, 185))
            image.save(target)

            ratio, x, y = app.TaskRunner._gold_target_location(target)

            self.assertEqual(ratio, 0.0)
            self.assertIsNone(x)
            self.assertIsNone(y)

    def test_gold_target_location_accepts_small_compact_deep_gold_echo(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "small-deep-gold.png"
            image = Image.new("RGB", (1920, 1080), (20, 28, 34))
            draw = ImageDraw.Draw(image)
            draw.ellipse((955, 245, 1015, 300), fill=(188, 137, 62))
            draw.ellipse((970, 235, 1000, 275), fill=(215, 158, 72))
            image.save(target)

            ratio, x, y = app.TaskRunner._gold_target_location(target)

            self.assertGreater(ratio, 0.0005)
            self.assertIsNotNone(x)
            self.assertIsNotNone(y)
            self.assertLess(abs(x - 985), 35)

    def test_gold_target_location_accepts_wide_perspective_echo(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "wide-perspective-echo.png"
            image = Image.new("RGB", (1920, 1080), (20, 28, 34))
            draw = ImageDraw.Draw(image)
            draw.ellipse((555, 402, 685, 454), fill=(198, 142, 58))
            image.save(target)

            ratio, x, y = app.TaskRunner._gold_target_location(target)

            self.assertGreater(ratio, 0.0005)
            self.assertIsNotNone(x)
            self.assertIsNotNone(y)
            self.assertLess(abs(x - 620), 45)

    def test_gold_target_location_accepts_small_lower_screen_echo(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "small-lower-echo.png"
            image = Image.new("RGB", (1920, 1080), (18, 24, 30))
            draw = ImageDraw.Draw(image)
            draw.ellipse((710, 665, 775, 730), fill=(198, 145, 62))
            image.save(target)

            ratio, x, y = app.TaskRunner._gold_target_location(target)

            self.assertGreater(ratio, 0.0005)
            self.assertIsNotNone(x)
            self.assertIsNotNone(y)
            self.assertLess(abs(x - 742), 35)

    def test_gold_target_location_ignores_high_sign_and_player_combat_ring(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "sign-and-ring.png"
            image = Image.new("RGB", (1920, 1080), (18, 24, 30))
            draw = ImageDraw.Draw(image)
            draw.rectangle((300, 80, 420, 175), fill=(205, 112, 38))
            draw.ellipse((1025, 670, 1115, 760), fill=(205, 157, 62))
            draw.ellipse((1045, 690, 1095, 740), fill=(18, 24, 30))
            image.save(target)

            ratio, x, y = app.TaskRunner._gold_target_location(target)

            self.assertEqual(ratio, 0.0)
            self.assertIsNone(x)
            self.assertIsNone(y)

    def test_visible_left_echo_is_approached_by_strafing_instead_of_wrapping_camera(self):
        controller = Mock()
        runner = app.TaskRunner(controller, lambda _message: None, dry_run=False)

        result = runner._approach_4c_gold_target(-440, 1920)

        controller.press_keys.assert_called_once_with(("W", "A"), 400)
        controller.move_mouse_relative.assert_not_called()
        self.assertIn("左侧", result)

    def test_visible_right_echo_turns_only_to_the_right_and_moves_forward(self):
        controller = Mock()
        runner = app.TaskRunner(controller, lambda _message: None, dry_run=False)

        result = runner._approach_4c_gold_target(360, 1920)

        turn = controller.move_mouse_relative.call_args.args[0]
        self.assertGreater(turn, 0)
        controller.press_keys.assert_called_once_with(("W",), 360)
        self.assertIn("右侧", result)

    def test_health_bar_detection_accounts_for_window_titlebar(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "windowed.png"
            image = Image.new("RGB", (1920, 1132), (30, 35, 42))
            draw = ImageDraw.Draw(image)
            draw.rectangle((680, 100, 1240, 112), fill=(225, 88, 35))
            image.save(target)
            self.assertGreater(app.TaskRunner._boss_health_ratio(target), 0.20)

    def test_invalid_multi_key_binding_is_rejected(self):
        with self.assertRaises(ValueError):
            ClientWindowController.normalize_input_binding("CTRL+E")


if __name__ == "__main__":
    unittest.main()
