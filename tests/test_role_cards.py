import itertools
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import app
from combat_rotation import RotationClock, default_store, load_store, new_module, save_store, validate_store


class RoleOrderTests(unittest.TestCase):
    def test_all_six_orders_repeat_and_keep_slot_times(self):
        modules = [new_module("attack_count", n) for n in (1, 2, 3)]
        times = {"1": 2, "2": 3, "3": 4}
        for order in itertools.permutations((1, 2, 3)):
            with self.subTest(order=order):
                clock = RotationClock(modules, 0, slot_times=times, slot_order=list(order))
                for expected in (*order, order[0]):
                    now = 0 if clock.needs_select else clock.visit_deadline
                    action = clock.next_action(now)
                    self.assertEqual(action["module"]["slot"], expected)
                    self.assertEqual(clock.visit_deadline-now, times[str(expected)])

    def test_empty_slots_skip_and_departure_keeps_cooldown(self):
        skill = new_module("skill", 3)
        clock = RotationClock([new_module("wait", 1), skill], 0,
                              slot_times={"1": 1, "2": 1, "3": 1}, slot_order=[3, 2, 1])
        self.assertEqual(clock.slots, [3, 1])
        self.assertEqual(clock.next_action(0)["module"]["slot"], 3)
        clock.next_action(.1)
        clock.next_action(1)
        self.assertEqual(clock.next_action(2)["module"]["slot"], 3)
        self.assertIsNone(clock.next_action(2.1))
        self.assertEqual(clock.last_run[skill["id"]], .1)

    def test_saved_order_roundtrip_and_legacy_default_order(self):
        store = default_store()
        preset = store["presets"][0]
        del preset["slot_order"]
        self.assertEqual(validate_store(store)["presets"][0]["slot_order"], [1, 2, 3])
        preset["slot_order"] = [3, 1, 2]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "combat.json"
            save_store(path, store)
            saved = load_store(path)["presets"][0]
        self.assertEqual(saved["slot_order"], [3, 1, 2])
        self.assertEqual(saved["slot_times"], preset["slot_times"])
        self.assertEqual(saved["modules"], preset["modules"])
        for invalid in ([1, 1, 3], [True, 2, 3], [1, 2], [3, 2, "1"]):
            preset["slot_order"] = invalid
            with self.assertRaisesRegex(ValueError, "角色顺序"):
                validate_store(store)

    def test_both_battles_force_the_first_role_before_casting(self):
        for mode in ("combat_4c", "daily"):
            with self.subTest(mode=mode):
                controller = Mock()
                events = []
                controller.press_key.side_effect = lambda key, ms: events.append(key)
                runner = app.TaskRunner(controller, Mock(), dry_run=False,
                                       rotation_presets={mode: [new_module("skill", 1), new_module("skill", 3)]},
                                       rotation_orders={mode: [3, 2, 1]})
                runner._sleep_interruptible = Mock()
                runner._inspect_4c_battle_state = Mock(return_value=(True, False))
                runner._capture_for_matching = Mock()
                runner._daily_reward_stage_present = Mock(return_value=False)
                runner._daily_battle_task_present = Mock(return_value=True)
                controller.press_binding.side_effect = lambda *_: (events.append("cast"), runner.stop_event.set())
                if mode == "daily":
                    runner._run_daily_battle(Mock(timeout=180), "E", "R", 1)
                else:
                    runner._run_4c_battle(Mock(timeout=30), "E", "R", 1)
                self.assertEqual(events[:2], ["3", "cast"])


class RoleCardUiTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.geometry("1080x850+40+40")
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "combat.json"
        self.config_patch = patch.object(app, "COMBAT_PRESETS_CONFIG", self.path)
        self.config_patch.start()
        self.ui = app.App.__new__(app.App)
        self.ui.root = self.root
        self.ui.rotation_store = default_store()
        self.ui.rotation_choice = tk.StringVar()
        shell = tk.Frame(self.root)
        shell.pack(fill=tk.BOTH, expand=True)
        self.ui.rotation_tab, self.ui.rotation_scroll_canvas = self.ui._create_scrollable_tab(shell, stretch=True)
        self.ui._build_rotation_tab()
        self.root.update()

    def tearDown(self):
        self.root.destroy()
        self.config_patch.stop()
        self.tmp.cleanup()

    def test_whole_role_drag_follows_pointer_and_keeps_contents_and_times(self):
        before = validate_store(self.ui.rotation_store)
        heading = self.ui._rotation_columns[3]["header"]
        heading.event_generate("<Motion>", x=12, y=15)
        self.assertEqual(heading.cget("cursor"), "hand2")
        x, y = heading.winfo_rootx(), heading.winfo_rooty()
        shell = self.ui._rotation_columns[3]["shell"]
        ox, oy = x+12-shell.winfo_rootx(), y+15-shell.winfo_rooty()
        target = self.ui._rotation_columns[1]["shell"]
        drop_x = target.winfo_rootx()+target.winfo_width()//2
        heading.event_generate("<ButtonPress-1>", x=12, y=15)
        heading.event_generate("<B1-Motion>", x=15, y=15, rootx=drop_x, rooty=y+30)
        self.root.update()
        ghost = heading._drag_ghost
        self.assertEqual((ghost.winfo_rootx(), ghost.winfo_rooty()), (drop_x-ox, y+30-oy))
        self.assertIsNone(self.root.grab_current())
        self.root.event_generate("<ButtonRelease-1>")
        self.root.update()
        self.assertFalse(ghost.winfo_exists())
        saved = load_store(self.path)["presets"][0]
        self.assertEqual(saved["slot_order"], [3, 1, 2])
        self.assertEqual(saved["modules"], before["presets"][0]["modules"])
        self.assertEqual(saved["slot_times"], before["presets"][0]["slot_times"])
        positions = [self.ui._rotation_columns[n]["shell"].winfo_x() for n in (3, 1, 2)]
        self.assertEqual(positions, sorted(positions))

    def test_escape_and_clicking_title_do_not_reorder_or_leave_ghost(self):
        header = self.ui._rotation_columns[3]["header"]
        header.event_generate("<ButtonPress-1>", x=40, y=15)
        header.event_generate("<B1-Motion>", x=70, y=20)
        self.assertIsNone(header._drag_ghost)
        header.event_generate("<ButtonPress-1>", x=12, y=15)
        header.event_generate("<B1-Motion>", x=70, y=20)
        self.root.update()
        ghost = header._drag_ghost
        self.root.focus_force()
        self.root.event_generate("<Escape>")
        self.root.update()
        self.assertFalse(ghost.winfo_exists())
        self.assertEqual(self.ui._rotation_current_preset()["slot_order"], [1, 2, 3])

    def test_cross_deletes_only_target_and_orphan_release_is_ignored(self):
        before = self.ui._rotation_current_preset()["modules"]
        module_id = before[1]["id"]
        card = self.ui._rotation_cards[module_id]
        x = card.winfo_width()-46
        card.event_generate("<ButtonRelease-1>", x=x, y=31)
        self.assertIn(module_id, self.ui._rotation_cards)
        with patch.object(self.ui, "_rotation_edit") as edit:
            card.event_generate("<ButtonPress-1>", x=x, y=31)
            card.event_generate("<ButtonRelease-1>", x=x, y=31)
            self.root.update()
        edit.assert_not_called()
        saved = load_store(self.path)["presets"][0]["modules"]
        self.assertEqual(saved, [m for m in before if m["id"] != module_id])

    def test_short_list_never_scrolls_below_its_origin_and_long_list_scrolls(self):
        first = self.ui._rotation_columns[1]
        self.root.geometry("1500x1400")
        self.root.update()
        card = self.ui._rotation_cards[self.ui._rotation_current_preset()["modules"][0]["id"]]
        for delta in (-120, 120, -120, -120, 120):
            card.event_generate("<MouseWheel>", delta=delta)
            self.root.update()
            self.assertEqual(first["list"].winfo_rooty(), first["canvas"].winfo_rooty())
        self.root.geometry("1080x680")
        self.root.update()
        third = self.ui._rotation_columns[3]
        third["list"].event_generate("<MouseWheel>", delta=-120)
        self.root.update()
        self.assertGreater(third["canvas"].yview()[0], 0)
        third["canvas"].yview_moveto(1)
        self.root.update()
        self.assertLessEqual(third["list"].winfo_rooty(), third["canvas"].winfo_rooty())


if __name__ == "__main__":
    unittest.main()
