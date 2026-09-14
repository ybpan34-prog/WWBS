import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np
from PIL import Image

import app
from app import DAILY_ZONE_NAMES, DAILY_ZONE_TEMPLATES, TaskRunner
from desktop_pet import DesktopPet


class DailyRoutineTests(unittest.TestCase):
    def test_daily_template_scale_search_stops_after_first_good_match(self):
        runner = TaskRunner(Mock(), lambda _message: None, dry_run=False)
        candidate = Mock(score=0.91)
        runner.matcher = Mock()
        runner.matcher.find_fast.return_value = candidate

        result = runner._find_daily_template(
            "anything.png",
            threshold=0.70,
            scales=[1.0, 0.97, 1.03],
            screenshot=Path("unused.png"),
        )

        self.assertIs(result, candidate)
        runner.matcher.find_fast.assert_called_once()

    def test_pet_menu_exposes_daily_weekly_and_new_4c_cycle_commands(self):
        labels = dict(DesktopPet.COMMAND_LABELS)
        self.assertEqual(labels["周常拿满奖励"], "run_rewards")
        self.assertEqual(labels["周常拿满星声"], "run_astrite")
        self.assertEqual(labels["一键日常（2轮双倍）"], "run_daily")
        self.assertEqual(labels["4C刷取（10次）"], "run_4c_10")
        self.assertEqual(labels["4C刷取（30次）"], "run_4c_30")
        self.assertNotIn("4C刷取（5次）", labels)
        self.assertNotIn("启动（拿满奖励）", labels)
        self.assertNotIn("拿满星声（13轮）", labels)

    def test_pet_windows_use_program_icon_and_stay_out_of_taskbar(self):
        window = Mock()

        DesktopPet._configure_auxiliary_window(window, app.APP_ICON)

        window.iconbitmap.assert_called_once_with(str(app.APP_ICON))
        window.wm_attributes.assert_called_once_with("-toolwindow", True)

    def test_terminal_destination_always_opens_with_escape_first(self):
        controller = Mock()
        controller.screenshot_to_client = lambda x, y: (x, y)
        runner = TaskRunner(controller, lambda _message: None, dry_run=False)
        events = []
        controller.press_key.side_effect = lambda key, duration: events.append(("key", key, duration))
        runner._sleep_interruptible = lambda seconds: events.append(("sleep", seconds))
        runner._tap_ratio = lambda x, y, pause=0.0: events.append(("tap", x, y, pause))
        runner._wait_for_overworld_hud = lambda **_kwargs: events.append(("world",))

        runner._open_terminal_destination("索拉指南", 0.515, 0.671)

        self.assertEqual(events[0], ("world",))
        self.assertEqual(events[1], ("key", "ESC", 70))
        self.assertEqual(events[-1], ("tap", 0.515, 0.671, 0.45))

    def test_overworld_hud_requires_all_three_anchor_regions(self):
        image = np.zeros((1080, 1920, 3), dtype=np.uint8)
        image[30:190, 1350:1890] = 235
        image[180:690, 1660:1890] = 235
        image[870:1060, 1400:1890] = 235
        with tempfile.TemporaryDirectory() as temp_dir:
            ready_path = Path(temp_dir) / "ready.png"
            loading_path = Path(temp_dir) / "loading.png"
            Image.fromarray(image).save(ready_path)
            Image.fromarray(np.zeros_like(image)).save(loading_path)
            self.assertTrue(TaskRunner._overworld_hud_ready(ready_path))
            self.assertFalse(TaskRunner._overworld_hud_ready(loading_path))

    def test_zone_picker_uses_exact_unique_templates(self):
        self.assertEqual(len(DAILY_ZONE_NAMES), len(set(DAILY_ZONE_NAMES)))
        self.assertEqual(len(DAILY_ZONE_TEMPLATES.values()), len(set(DAILY_ZONE_TEMPLATES.values())))
        self.assertNotEqual(
            DAILY_ZONE_TEMPLATES["荒石高地无音区 I"],
            DAILY_ZONE_TEMPLATES["荒石高地无音区 II"],
        )
        for template_name in DAILY_ZONE_TEMPLATES.values():
            self.assertTrue((Path(__file__).parents[1] / "templates" / "daily" / template_name).exists())

    def test_zone_search_uses_mouse_wheel_to_find_lower_rows(self):
        controller = Mock()
        controller.screenshot_to_client = lambda x, y: (x, y)
        runner = TaskRunner(controller, lambda _message: None, dry_run=False)
        runner.daily_zone_name = "荒石高地无音区 I"
        runner._open_terminal_destination = Mock()
        runner._tap_ratio = Mock()
        runner._capture_size = Mock(return_value=(Path("screen.png"), 1920, 1080))
        runner._daily_row_button_ready = Mock(return_value=True)
        attempts = iter((None, None, Mock(score=0.9, center=(900, 500))))
        runner._find_daily_template = Mock(side_effect=lambda *_args, **_kwargs: next(attempts))
        controller.wheel_at = Mock()

        runner._open_daily_tacet_field("zone.png")

        self.assertEqual(controller.wheel_at.call_count, 2)
        self.assertTrue(all(call.args[2] < 0 for call in controller.wheel_at.call_args_list))

    def test_slot_one_is_selected_only_after_battle_hud_is_ready(self):
        controller = Mock()
        runner = TaskRunner(controller, lambda _message: None, dry_run=False)
        runner._capture_for_matching = Mock()
        runner._sleep_interruptible = Mock()
        runner._daily_battle_task_present = Mock(side_effect=(False, True))

        runner._select_daily_slot_one_after_loading(Path("screen.png"))

        self.assertEqual(runner._capture_for_matching.call_count, 2)
        controller.press_key.assert_called_once_with("1", 65)

    def test_yellow_claim_rows_ignore_black_go_buttons(self):
        image = np.full((1080, 1920, 3), 235, dtype=np.uint8)
        image[250:305, 1570:1810] = (255, 240, 120)  # yellow 领取
        image[420:475, 1570:1810] = (25, 25, 25)  # black 前往
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "activity.png"
            Image.fromarray(image).save(path)
            rows = TaskRunner._yellow_claim_rows(path)
        self.assertEqual(len(rows), 1)
        self.assertGreater(rows[0], 250)
        self.assertLess(rows[0], 305)

    def test_activity_milestones_click_only_the_100_chest(self):
        runner = TaskRunner(Mock(), lambda _message: None, dry_run=False)
        taps = []
        runner._open_terminal_destination = Mock()
        runner._capture_for_matching = Mock()
        runner._yellow_claim_rows = Mock(return_value=[])
        runner._find_daily_template = Mock(return_value=object())
        runner._tap_ratio = lambda x, y, pause=0.0: taps.append((x, y))
        runner._dismiss_reward_overlay_safely = Mock()

        runner._collect_daily_activity_rewards()

        milestone_taps = [(x, y) for x, y in taps if abs(y - 0.868) < 0.001]
        self.assertEqual(milestone_taps, [(0.945, 0.868)])

    def test_battlepass_opens_directly_from_terminal_without_escape(self):
        controller = Mock()
        runner = TaskRunner(controller, lambda _message: None, dry_run=False)
        taps = []
        runner._open_terminal_destination = Mock()
        runner._tap_ratio = lambda x, y, pause=0.0: taps.append((x, y))
        runner._click_optional_daily_template = Mock(return_value=False)

        runner._collect_daily_battlepass_rewards()

        runner._open_terminal_destination.assert_not_called()
        controller.press_key.assert_not_called()
        self.assertEqual(taps[0], (0.744, 0.257))

    def test_completed_weekly_travel_skips_dream_park(self):
        runner = TaskRunner(Mock(), lambda _message: None, dry_run=False)
        runner._tap_ratio = Mock()
        runner._capture_for_matching = Mock()
        runner._wait_for_daily_template = Mock()
        runner._weekly_travel_completed = Mock(return_value=True)
        runner._run_default_weekly_from_daily = Mock()

        runner._continue_daily_into_weekly_travel()

        runner._run_default_weekly_from_daily.assert_not_called()
        self.assertEqual(runner._tap_ratio.call_args_list[0].args[:2], (0.515, 0.671))
        self.assertEqual(runner._tap_ratio.call_args_list[-1].args[:2], (0.957, 0.058))

    def test_unfinished_weekly_travel_selects_first_skill_when_empty(self):
        runner = TaskRunner(Mock(), lambda _message: None, dry_run=False)
        runner._tap_ratio = Mock()
        runner._capture_for_matching = Mock()
        runner._weekly_travel_completed = Mock(return_value=False)
        runner._weekly_skill_equipped = Mock(return_value=False)
        runner._wait_for_daily_template = Mock()
        runner._wait_for_weekly_skill_dialog = Mock()
        runner._run_default_weekly_from_daily = Mock()

        runner._continue_daily_into_weekly_travel()

        tapped = [call.args[:2] for call in runner._tap_ratio.call_args_list]
        self.assertIn((0.333, 0.170), tapped)
        self.assertIn((0.247, 0.505), tapped)
        self.assertIn((0.496, 0.768), tapped)
        self.assertIn((0.371, 0.505), tapped)
        self.assertIn((0.826, 0.858), tapped)
        runner._run_default_weekly_from_daily.assert_called_once_with()

    def test_plus_sign_weekly_slot_is_always_empty(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            screenshot = Path(temp_dir) / "empty-weekly-slot.png"
            image = np.zeros((1080, 1920, 3), dtype=np.uint8)
            image[:] = (130, 101, 70)
            center_x, center_y = round(1920 * 0.476), round(1080 * 0.79)
            cream = (252, 235, 181)
            image[center_y - 4:center_y + 5, center_x - 22:center_x + 23] = cream
            image[center_y - 22:center_y + 23, center_x - 4:center_x + 5] = cream
            image[round(1080 * 0.855):round(1080 * 0.90), round(1920 * 0.425):round(1920 * 0.555)] = (220, 135, 55)
            Image.fromarray(image).save(screenshot)

            self.assertTrue(TaskRunner._weekly_skill_slot_empty(screenshot))
            self.assertFalse(TaskRunner._weekly_skill_equipped(screenshot))

    def test_any_non_plus_weekly_skill_is_equipped(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            screenshot = Path(temp_dir) / "alternate-weekly-skill.png"
            image = np.zeros((1080, 1920, 3), dtype=np.uint8)
            image[:] = (122, 164, 196)
            Image.fromarray(image).save(screenshot)

            self.assertFalse(TaskRunner._weekly_skill_slot_empty(screenshot))
            self.assertTrue(TaskRunner._weekly_skill_equipped(screenshot))

    def test_standalone_weekly_run_checks_skill_before_clicking_start(self):
        runner = TaskRunner(Mock(), lambda _message: None, dry_run=False)
        runner._wait_for_daily_template = Mock()
        runner._ensure_weekly_skill_selected = Mock()
        runner._run_step = Mock()
        task = app.WeeklyTask(
            name=app.DEFAULT_GROUP_NAME,
            enabled=True,
            weekday="any",
            description="",
            template_group="default",
            steps=[app.Step(action="wait")],
        )

        runner.run_task(task)

        runner._wait_for_daily_template.assert_called_once_with("menu1.png", timeout=8.0, threshold=0.78)
        runner._ensure_weekly_skill_selected.assert_called_once_with()

    def test_daily_skips_tacet_field_when_activity_page_was_auto_skipped(self):
        runner = TaskRunner(Mock(), lambda _message: None, dry_run=False)
        runner._open_terminal_destination = Mock()
        runner._daily_activity_still_pending = Mock(return_value=False)
        runner._tap_ratio = Mock()

        self.assertFalse(runner._open_daily_tacet_field("zone_hukou_shanmai.png"))
        runner._tap_ratio.assert_not_called()

    def test_daily_completed_notice_is_sent_to_the_customer(self):
        notice = Mock()
        runner = TaskRunner(Mock(), lambda _message: None, dry_run=False, notice=notice)
        runner.daily_zone_name = "虎口山脉无音区"
        runner.controller.normalize_input_binding.side_effect = lambda value: value
        runner._open_daily_tacet_field = Mock(return_value=False)
        runner._continue_daily_from_open_guide_page = Mock()

        runner._run_daily_routine(app.Step(action="daily_routine"))

        notice.assert_called_once_with("今日日常已经完成，不再挑战无音区。")
        runner._continue_daily_from_open_guide_page.assert_called_once_with()

    def test_completed_daily_still_runs_unfinished_weekly_travel(self):
        runner = TaskRunner(Mock(), lambda _message: None, dry_run=False)
        runner._capture_for_matching = Mock()
        runner._weekly_travel_page_present = Mock(return_value=True)
        runner._start_weekly_travel_from_selected_page = Mock()

        runner._continue_daily_from_open_guide_page()

        runner._start_weekly_travel_from_selected_page.assert_called_once_with()

    def test_completed_daily_and_weekly_closes_the_advanced_guide_page(self):
        runner = TaskRunner(Mock(), lambda _message: None, dry_run=False)
        runner._capture_for_matching = Mock()
        runner._weekly_travel_page_present = Mock(return_value=False)
        runner._start_weekly_travel_from_selected_page = Mock()
        runner._tap_ratio = Mock()

        runner._continue_daily_from_open_guide_page()

        runner._start_weekly_travel_from_selected_page.assert_not_called()
        self.assertEqual(runner._tap_ratio.call_args.args[:2], (0.957, 0.058))

    def test_equipped_weekly_skill_is_kept(self):
        runner = TaskRunner(Mock(), lambda _message: None, dry_run=False)
        runner._tap_ratio = Mock()
        runner._capture_for_matching = Mock()
        runner._weekly_travel_completed = Mock(return_value=False)
        runner._weekly_skill_equipped = Mock(return_value=True)
        runner._wait_for_daily_template = Mock()
        runner._wait_for_weekly_skill_dialog = Mock()
        runner._run_default_weekly_from_daily = Mock()

        runner._continue_daily_into_weekly_travel()

        tapped = [call.args[:2] for call in runner._tap_ratio.call_args_list]
        self.assertNotIn((0.496, 0.768), tapped)
        runner._wait_for_weekly_skill_dialog.assert_not_called()
        runner._run_default_weekly_from_daily.assert_called_once_with()

    def test_exit_confirmation_detector_requires_white_panel_and_two_dark_buttons(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            dialog_path = Path(temp_dir) / "dialog.png"
            world_path = Path(temp_dir) / "world.png"
            dialog = np.zeros((1080, 1920, 3), dtype=np.uint8)
            dialog[313:767, 422:1498] = 238
            dialog[637:734, 461:826] = 25
            dialog[637:734, 1075:1459] = 25
            Image.fromarray(dialog).save(dialog_path)
            Image.fromarray(np.zeros_like(dialog)).save(world_path)

            self.assertTrue(TaskRunner._daily_exit_confirmation_present(dialog_path))
            self.assertFalse(TaskRunner._daily_exit_confirmation_present(world_path))

    def test_exit_confirmation_clicks_only_the_right_confirm_button(self):
        controller = Mock()
        runner = TaskRunner(controller, lambda _message: None, dry_run=False)
        runner._capture_for_matching = Mock()
        runner._daily_exit_confirmation_present = Mock(return_value=True)
        runner._sleep_interruptible = Mock()

        with tempfile.TemporaryDirectory() as temp_dir:
            screenshot = Path(temp_dir) / "_runtime_screenshot.png"
            Image.new("RGB", (1920, 1080)).save(screenshot)
            with unittest.mock.patch.object(app, "APP_DIR", Path(temp_dir)):
                self.assertTrue(runner._confirm_daily_exit_if_present())

        controller.tap.assert_called_once_with(round(1920 * 0.657), round(1080 * 0.628))

    def test_reward_orb_requires_dense_white_core(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            orb_path = Path(temp_dir) / "orb.png"
            portal_path = Path(temp_dir) / "portal.png"
            orb = np.zeros((1080, 1920, 3), dtype=np.uint8)
            orb[310:390, 930:1010] = (250, 250, 250)
            Image.fromarray(orb).save(orb_path)
            portal = np.zeros((1080, 1920, 3), dtype=np.uint8)
            portal[250:500, 700:950] = (35, 90, 180)
            Image.fromarray(portal).save(portal_path)
            x, y, density = TaskRunner._daily_reward_orb_location(orb_path)
            px, py, portal_density = TaskRunner._daily_reward_orb_location(portal_path)
        self.assertIsNotNone(x)
        self.assertIsNotNone(y)
        self.assertGreater(density, 0.1)
        self.assertIsNone(px)
        self.assertIsNone(py)
        self.assertEqual(portal_density, 0.0)

    def test_reward_orb_below_point_six_five_confidence_is_not_actionable(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "weak-orb.png"
            image = np.zeros((1080, 1920, 3), dtype=np.uint8)
            image[250:263, 900:913] = (245, 245, 250)
            Image.fromarray(image).save(path)
            x, y, confidence = TaskRunner._daily_reward_orb_location(path)
        self.assertGreater(confidence, 0.1)
        self.assertLessEqual(confidence, 0.65)
        self.assertIsNone(x)
        self.assertIsNone(y)

    def test_reward_search_turns_when_forward_movement_does_not_improve_confidence(self):
        self.assertTrue(TaskRunner._daily_reward_movement_stalled(0.24, 0.24))
        self.assertTrue(TaskRunner._daily_reward_movement_stalled(0.24, 0.18))
        self.assertFalse(TaskRunner._daily_reward_movement_stalled(0.24, 0.25))
        self.assertFalse(TaskRunner._daily_reward_movement_stalled(None, 0.25))

    def test_reward_search_returns_to_combat_when_task_text_reappears(self):
        controller = Mock()
        runner = TaskRunner(controller, lambda _message: None, dry_run=False)
        runner._capture_for_matching = Mock()
        runner._find_daily_reward_prompt = Mock(return_value=None)
        runner._daily_reward_orb_location = Mock(return_value=(None, None, 0.0))
        runner._daily_battle_task_present = Mock(return_value=True)

        self.assertFalse(runner._collect_daily_reward(1))
        controller.release_keys.assert_called_once()
        controller.move_mouse_relative.assert_not_called()
        controller.press_keys.assert_not_called()

    def test_reward_search_scans_current_height_then_raises_and_restores_pitch(self):
        adjustments = [TaskRunner._daily_reward_vertical_adjustment(index) for index in range(1, 19)]

        self.assertEqual(adjustments[4], -180)
        self.assertEqual(adjustments[10], -180)
        self.assertEqual(adjustments[16], 360)
        self.assertEqual(sum(adjustments), 0)
        self.assertEqual(adjustments[0], 0)

    def test_daily_healing_is_disabled_by_default(self):
        runner = TaskRunner(Mock(), lambda _message: None, dry_run=False)

        self.assertFalse(runner.daily_heal_enabled)

    def test_daily_healing_can_be_enabled_explicitly(self):
        runner = TaskRunner(
            Mock(),
            lambda _message: None,
            dry_run=False,
            daily_heal_enabled=True,
        )

        self.assertTrue(runner.daily_heal_enabled)

    def test_daily_battle_end_confirmation_stops_on_consecutive_missing_frames(self):
        runner = TaskRunner(Mock(), lambda _message: None, dry_run=False)
        runner._sleep_interruptible = Mock()
        runner._capture_for_matching = Mock()
        runner._daily_battle_task_present = Mock(return_value=False)

        self.assertTrue(runner._confirm_daily_battle_finished(Path("screen.png")))
        self.assertEqual(
            runner._daily_battle_task_present.call_count,
            runner.DAILY_TASK_MISSING_CONFIRMATIONS - 1,
        )

    def test_daily_battle_end_confirmation_cancels_when_marker_returns(self):
        runner = TaskRunner(Mock(), lambda _message: None, dry_run=False)
        runner._sleep_interruptible = Mock()
        runner._capture_for_matching = Mock()
        runner._daily_battle_task_present = Mock(return_value=True)

        self.assertFalse(runner._confirm_daily_battle_finished(Path("screen.png")))
        runner._daily_battle_task_present.assert_called_once_with(Path("screen.png"))

    def test_pending_battle_end_prevents_due_heal_rotation(self):
        controller = Mock()
        runner = TaskRunner(
            controller,
            lambda _message: None,
            dry_run=False,
            daily_heal_enabled=True,
        )
        runner.HEAL_ROTATION_INTERVAL = 0.5
        runner._select_daily_slot_one_after_loading = Mock()
        runner._capture_for_matching = Mock()
        runner._daily_reward_stage_present = Mock(return_value=False)
        runner._daily_battle_task_present = Mock(side_effect=(True, False))
        runner._confirm_daily_battle_finished = Mock(return_value=True)
        runner._perform_4c_heal_rotation = Mock()
        runner._sleep_interruptible = Mock()
        clock = iter(value / 10 for value in range(2, 30, 2))

        with patch.object(app.time, "monotonic", side_effect=lambda: next(clock)):
            runner._run_daily_battle(app.Step(action="daily_routine"), "E", "R", 1)

        runner._confirm_daily_battle_finished.assert_called_once()
        runner._perform_4c_heal_rotation.assert_not_called()

    def test_reward_stage_detection_accepts_prompt_or_strong_orb(self):
        runner = TaskRunner(Mock(), lambda _message: None, dry_run=False)
        runner._find_daily_reward_prompt = Mock(return_value=object())
        runner._daily_reward_orb_location = Mock(return_value=(None, None, 0.0))

        self.assertTrue(runner._daily_reward_stage_present(Path("screen.png")))
        runner._daily_reward_orb_location.assert_not_called()

        runner._find_daily_reward_prompt.return_value = None
        runner._daily_reward_orb_location.return_value = (900, 360, 0.82)
        self.assertTrue(runner._daily_reward_stage_present(Path("screen.png")))

    def test_reward_search_prefers_visible_orb_over_lingering_task_text(self):
        controller = Mock()
        runner = TaskRunner(controller, lambda _message: None, dry_run=False)
        runner._capture_for_matching = Mock()
        runner._find_daily_reward_prompt = Mock(return_value=None)
        runner._daily_reward_orb_location = Mock(return_value=(900, 360, 0.82))
        runner._daily_battle_task_present = Mock(return_value=True)
        runner._sleep_interruptible = Mock(side_effect=lambda _seconds: runner.stop_event.set())

        with tempfile.TemporaryDirectory() as temp_dir:
            screenshot = Path(temp_dir) / "_runtime_screenshot.png"
            Image.new("RGB", (1920, 1080)).save(screenshot)
            with patch.object(app, "APP_DIR", Path(temp_dir)):
                with self.assertRaises(RuntimeError):
                    runner._collect_daily_reward(1)

        runner._daily_battle_task_present.assert_not_called()
        controller.press_keys.assert_called_once_with(("W",), 500)

    def test_refill_never_selects_star_currency_card(self):
        runner = TaskRunner(Mock(), lambda _message: None, dry_run=False)
        taps = []
        runner._capture_for_matching = Mock()
        runner._daily_monomer_empty = Mock(return_value=False)
        runner._tap_ratio = lambda x, y, pause=0.0: taps.append((x, y))
        runner._wait_daily_refill_result = lambda: "still_short"
        self.assertFalse(runner._safe_refill_daily_stamina())
        selected_cards = [x for x, y in taps if abs(y - 0.455) < 0.001]
        self.assertEqual(selected_cards, [0.403, 0.505])
        self.assertNotIn(0.587, selected_cards)

    def test_refill_detects_small_red_zero_on_green_card(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            screenshot = Path(temp_dir) / "refill.png"
            image = np.full((1080, 1920, 3), 235, dtype=np.uint8)
            image[548:558, 829:837] = (180, 35, 45)
            Image.fromarray(image).save(screenshot)

            self.assertTrue(TaskRunner._daily_monomer_empty(screenshot))

    def test_refill_chooser_geometry_is_a_template_independent_fallback(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            chooser_path = Path(temp_dir) / "chooser.png"
            blank_path = Path(temp_dir) / "blank.png"
            chooser = np.zeros((1080, 1920, 3), dtype=np.uint8)
            chooser[173:864, 326:1594] = 238
            chooser[367:637, 672:1229] = 110
            chooser[734:853, 384:1536] = 25
            Image.fromarray(chooser).save(chooser_path)
            Image.fromarray(np.zeros_like(chooser)).save(blank_path)

            self.assertTrue(TaskRunner._daily_refill_chooser_present(chooser_path))
            self.assertFalse(TaskRunner._daily_refill_chooser_present(blank_path))

    def test_refill_falls_back_to_solvent_when_monomer_is_not_enough(self):
        runner = TaskRunner(Mock(), lambda _message: None, dry_run=False)
        taps = []
        states = iter(("still_short", "success"))
        runner._capture_for_matching = Mock()
        runner._daily_monomer_empty = Mock(return_value=False)
        runner._tap_ratio = lambda x, y, pause=0.0: taps.append((x, y))
        runner._wait_daily_refill_result = lambda: next(states)

        self.assertTrue(runner._safe_refill_daily_stamina())
        selected_cards = [x for x, y in taps if abs(y - 0.455) < 0.001]
        self.assertEqual(selected_cards, [0.403, 0.505])
        self.assertNotIn(0.587, selected_cards)

    def test_refill_skips_monomer_when_green_card_shows_red_zero(self):
        runner = TaskRunner(Mock(), lambda _message: None, dry_run=False)
        taps = []
        runner._capture_for_matching = Mock()
        runner._daily_monomer_empty = Mock(return_value=True)
        runner._tap_ratio = lambda x, y, pause=0.0: taps.append((x, y))
        runner._wait_daily_refill_result = Mock(return_value="success")

        self.assertTrue(runner._safe_refill_daily_stamina())
        selected_cards = [x for x, y in taps if abs(y - 0.455) < 0.001]
        self.assertEqual(selected_cards, [0.505])
        self.assertNotIn(0.403, selected_cards)
        self.assertNotIn(0.587, selected_cards)


if __name__ == "__main__":
    unittest.main()
