"""Construct the real settings widgets, without opening a visible app or jobs."""
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import Mock, patch
import tkinter as tk
import app
from chat_history import ChatHistory


class BetaUiTests(unittest.TestCase):
    def test_drag_card_follows_pointer_and_restores_zone_picker(self):
        root = tk.Tk()
        try:
            root.geometry("480x440+80+80")
            instance = app.App.__new__(app.App)
            instance.root = root
            instance._start_action_cards = {}
            instance._start_action_order = ["daily", "weekly_rewards"]
            instance.daily_zone = tk.StringVar(value=app.DAILY_ZONE_NAMES[0])
            instance._save_daily_zone = Mock()
            instance._save_start_action_order = Mock()
            run_task = Mock()
            instance.start_left_canvas = tk.Canvas(root, height=400)
            instance.start_left_canvas.pack(fill=tk.BOTH, expand=True)
            parent = tk.Frame(instance.start_left_canvas)
            instance.start_left_canvas.create_window(0, 0, window=parent, anchor="nw", width=440)
            picker = instance._make_start_action_card(
                parent, "daily", "每日任务", "拖动测试", run_task, "daily", with_zone=True)
            instance._make_start_action_card(
                parent, "weekly_rewards", "周常奖励", "第二项", run_task, "weekly")
            instance._repack_start_action_cards()
            root.update()
            card = instance._start_action_cards["daily"]
            self.assertEqual(card.cget("cursor"), "hand2")
            initial_x, initial_y = card.winfo_rootx(), card.winfo_rooty()
            second = instance._start_action_cards["weekly_rewards"]
            drop_y = second.winfo_rooty() + second.winfo_height() // 2 + 20
            card.event_generate("<ButtonPress-1>", x=20, y=31)
            card.event_generate("<B1-Motion>", x=40, y=drop_y - initial_y,
                                rootx=initial_x + 40, rooty=drop_y)
            root.update()
            ghost = card._drag_ghost
            self.assertEqual(ghost.winfo_rootx(), initial_x + 20)
            self.assertEqual(ghost.winfo_rooty(), drop_y - 31)
            self.assertIsNone(root.grab_current())
            self.assertEqual(instance._start_action_order, ["weekly_rewards", "daily"])
            self.assertFalse(picker.winfo_ismapped())
            card.event_generate("<B1-Motion>", x=60, y=220,
                                rootx=initial_x + 60, rooty=initial_y + 220)
            root.update()
            self.assertEqual(ghost.winfo_rootx(), initial_x + 40)
            self.assertEqual(ghost.winfo_rooty(), initial_y + 189)
            card.event_generate("<ButtonRelease-1>", x=20, y=31)
            root.update()
            self.assertIsNone(card._drag_ghost)
            self.assertFalse(ghost.winfo_exists())
            self.assertTrue(picker.winfo_ismapped())
            instance._save_start_action_order.assert_called_once()
            run_task.assert_not_called()
        finally:
            root.destroy()

    def test_picker_opens_above_bottom_edge_without_blocking_other_controls(self):
        root = tk.Tk()
        try:
            instance = app.App.__new__(app.App)
            instance.root = root
            value = tk.StringVar(value="E")
            root.geometry(f"340x90+0+{max(0, root.winfo_screenheight() - 100)}")
            picker = instance._rounded_picker(root, value, ("E", "Q", "R"),
                                              lambda: None, editable=True)
            picker.pack(fill=tk.X)
            root.update()
            picker.event_generate("<Button-1>", x=20, y=15)
            root.update()
            popup = picker._popup_window
            self.assertIsNotNone(popup)
            self.assertLess(popup.winfo_rooty(), picker.winfo_rooty())
            self.assertIsNone(root.grab_current())
            root.event_generate("<Button-1>", x=10, y=70)
            root.update()
            self.assertIsNone(picker._popup_window)
            picker.event_generate("<Button-1>", x=20, y=15)
            root.update()
            surface = picker._popup_window.winfo_children()[0]
            target = next(item for item in surface.find_all()
                          if surface.type(item) == "text" and surface.itemcget(item, "text") == "Q")
            target_x, target_y = surface.coords(target)
            surface.event_generate("<Button-1>", x=round(target_x), y=round(target_y))
            root.update()
            self.assertEqual(value.get(), "Q")
            self.assertIsNone(picker._popup_window)
        finally:
            root.destroy()

    def test_settings_and_history_widgets_build(self):
        root = tk.Tk()
        root.withdraw()
        try:
            with tempfile.TemporaryDirectory() as tmp, ExitStack() as stack:
                stack.enter_context(patch.object(root, "after", return_value="test-job"))
                stack.enter_context(patch.object(root, "after_idle", return_value="test-idle"))
                for method in ("_load_config", "_refresh_templates", "_drain_logs", "_start_stop_hotkey"):
                    stack.enter_context(patch.object(app.App, method))
                stack.enter_context(patch.object(app, "ChatHistory", return_value=ChatHistory(Path(tmp) / "history.json")))
                instance = app.App(root)
                labels = []
                def visit(widget):
                    if "text" in widget.keys():
                        labels.append(str(widget.cget("text")))
                    if isinstance(widget, tk.Canvas):
                        labels.extend(widget.itemcget(item, "text") for item in widget.find_all() if widget.type(item) == "text")
                    for child in widget.winfo_children():
                        visit(child)
                visit(root)
                for removed in ("ADB 路径", "设备 ID", "任务配置", "保存一张当前截图", "查看程序目录"):
                    self.assertNotIn(removed, labels)
                self.assertIn("4C刷取（自定义次数）", labels)
                self.assertTrue(any("关闭后恢复主动发言" in text for text in labels))
                def texts_under(widget):
                    result = []
                    def collect(node):
                        if "text" in node.keys():
                            result.append(str(node.cget("text")))
                        if isinstance(node, tk.Canvas):
                            result.extend(node.itemcget(item, "text") for item in node.find_all() if node.type(item) == "text")
                        for child in node.winfo_children():
                            collect(child)
                    collect(widget)
                    return result
                start_texts = texts_under(instance.start_tab)
                settings_texts = texts_under(instance.settings_tab)
                self.assertIsInstance(instance.start_left_canvas, tk.Canvas)
                self.assertIn("实时截图", start_texts)
                self.assertEqual(instance.start_left_scrollbar.winfo_reqwidth(), 7)
                with patch.object(instance.start_left_canvas, "yview_scroll") as scroll:
                    self.assertEqual(instance._scroll_start_left(Mock(delta=-120)), "break")
                    scroll.assert_called_once_with(3, "units")
                instance._start_scroll_range = (0.0, 0.5)
                with patch.object(instance.start_left_canvas, "yview_moveto") as move, \
                     patch.object(instance.start_left_scrollbar, "winfo_height", return_value=100):
                    instance._drag_start_scrollbar(Mock(y=75))
                    self.assertGreater(move.call_args.args[0], 0.0)
                instance._select_top_tab(1)
                self.assertEqual(instance._selected_top_tab, 1)
                instance._select_top_tab(0)
                def card_with_title(widget, title):
                    if isinstance(widget, tk.Canvas) and any(
                        widget.type(item) == "text" and widget.itemcget(item, "text") == title
                        for item in widget.find_all()
                    ):
                        return widget
                    for child in widget.winfo_children():
                        found = card_with_title(child, title)
                        if found is not None:
                            return found
                    return None
                weekly_card = card_with_title(instance.start_tab, "周常拿满奖励")
                self.assertIsNotNone(weekly_card)
                self.assertEqual(len(instance._start_action_cards), 6)
                self.assertEqual(instance._start_action_order[0], "weekly_rewards")
                daily_card = instance._start_action_cards["daily"]
                self.assertTrue(any(getattr(child, "_is_rounded_picker", False)
                                    for child in daily_card.winfo_children()))
                self.assertEqual(
                    instance._normalize_start_action_order(["daily", "daily", "unknown"]),
                    ["daily", "weekly_rewards", "weekly_astrite", "combat_4c_10", "combat_4c_custom", "tower"],
                )
                second = instance._start_action_cards["weekly_astrite"]
                third = instance._start_action_cards["daily"]
                with patch.object(instance, "_repack_start_action_cards"), \
                     patch.object(second, "winfo_rooty", return_value=70), \
                     patch.object(second, "winfo_height", return_value=70), \
                     patch.object(third, "winfo_rooty", return_value=140), \
                     patch.object(third, "winfo_height", return_value=70):
                    instance._move_start_action_card("weekly_rewards", 150)
                self.assertEqual(instance._start_action_order[:3],
                                 ["weekly_astrite", "weekly_rewards", "daily"])
                with patch.object(app, "UI_CONFIG", Path(tmp) / "ui-settings.json"):
                    instance._save_start_action_order()
                    self.assertEqual(instance._load_start_action_order(), instance._start_action_order)
                with patch.object(instance, "_start_enabled_real") as run_weekly, \
                     patch.object(weekly_card, "winfo_width", return_value=360), \
                     patch.object(weekly_card, "winfo_height", return_value=70):
                    instance._activate_start_action_card(
                        weekly_card, Mock(x=100, y=25),
                        lambda: instance._start_enabled_real(15), "weekly", False,
                    )
                    run_weekly.assert_called_once_with(15)
                    with patch.object(instance, "_show_run_notice") as notice:
                        instance._activate_start_action_card(
                            weekly_card, Mock(x=300, y=25),
                            lambda: instance._start_enabled_real(15), "weekly", False,
                        )
                        notice.assert_called_once_with("weekly")
                    run_weekly.assert_called_once_with(15)
                self.assertNotIn("日常启用三号位回血", start_texts)
                for moved in ("4C 技能键位", "4C 大招键位", "任务正常完成后自动关机"):
                    self.assertIn(moved, start_texts)
                    self.assertNotIn(moved, settings_texts)
                self.assertNotIn("保存键位", labels)
                instance.agent_provider.set("DeepSeek API")
                instance._change_agent_provider()
                self.assertEqual(instance.cartethyia_agent_endpoint.get(), "https://api.deepseek.com")
                instance.chat_history.append(instance.pet_id, "你", "测试消息")
                shell = tk.Frame(root)
                instance._build_pet_chat_history(shell)
                def walk(node):
                    for child in node.winfo_children():
                        yield child
                        yield from walk(child)
                texts = [child for child in walk(shell) if isinstance(child, tk.Text)]
                self.assertIn("测试消息", texts[0].get("1.0", "end"))
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main()
