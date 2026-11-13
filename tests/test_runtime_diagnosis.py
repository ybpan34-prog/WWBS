from __future__ import annotations

import queue
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app import App
import app as app_module


class RuntimeDiagnosisTests(unittest.TestCase):
    def test_elevated_launch_marks_restart_without_duplicate_flags(self):
        with patch.object(app_module.sys, "argv", ["app.py", "--admin-restarted"]):
            _, arguments = App._elevated_launch_command()
        self.assertEqual(arguments.count("--admin-restarted"), 1)

    def test_elevated_launch_adds_restart_flag(self):
        with patch.object(app_module.sys, "argv", ["app.py"]):
            _, arguments = App._elevated_launch_command()
        self.assertIn("--admin-restarted", arguments)

    def test_diagnosis_can_bind_to_recent_4c_task_instead_of_chorus(self) -> None:
        chorus = SimpleNamespace(steps=[SimpleNamespace(action="move_to_visual_target")])
        combat = SimpleNamespace(steps=[SimpleNamespace(action="combat_4c")])

        self.assertIs(App._task_with_action([combat, chorus], "combat_4c"), combat)
        self.assertIs(App._task_with_action([combat, chorus], "move_to_visual_target"), chorus)

    @staticmethod
    def _app(tasks, due=True):
        app = App.__new__(App)
        app.tasks = tasks
        app._is_due = Mock(return_value=due)
        app._log = Mock()
        app._diagnose_runtime = Mock()
        app._start_worker = Mock()
        app._event_line = Mock(return_value="已找到具体原因")
        app._pet_feedback = Mock()
        return app

    def test_no_enabled_task_starts_diagnosis_directly(self) -> None:
        app = self._app([SimpleNamespace(enabled=False)])
        app._run_enabled()
        app._diagnose_runtime.assert_called_once_with()
        app._start_worker.assert_not_called()

    def test_no_due_task_starts_diagnosis_directly(self) -> None:
        app = self._app([SimpleNamespace(enabled=True)], due=False)
        app._run_enabled()
        app._diagnose_runtime.assert_called_once_with()
        app._start_worker.assert_not_called()

    def test_eligible_task_starts_worker(self) -> None:
        task = SimpleNamespace(enabled=True)
        app = self._app([task], due=True)
        app._run_enabled()
        app._start_worker.assert_called_once_with([task])
        app._diagnose_runtime.assert_not_called()

    def test_task_failure_reports_known_reason_then_runs_silent_diagnosis(self) -> None:
        app = self._app([])
        app._show_task_error_feedback("未找到模板")
        app._diagnose_runtime.assert_called_once_with(announce=False)
        app._event_line.assert_called_once()
        self.assertEqual(app._event_line.call_args.args[0], "diagnose_error")
        app._pet_feedback.assert_called_once()

    def test_reported_weekly_failure_points_to_screenshot_without_assuming_display_settings(self):
        detail = App._friendly_runtime_error('周常模板流程无法继续：本次 menu4.png')
        self.assertIn('诊断截图', detail)
        self.assertNotIn('HDR', detail)
        self.assertNotIn('滤镜', detail)

    def test_log_reader_notifies_pet_about_mouse_move_failure(self) -> None:
        app = App.__new__(App)
        app.log_queue = queue.Queue()
        app.log_queue.put("[17:21:53] 鼠标没有移动成功：请尝试右键桌面快捷方式，以管理员身份运行。")
        app.detail = Mock()
        app.status = Mock()
        app.root = Mock()
        app._notify_mouse_move_failure = Mock()
        app._drain_logs()
        app._notify_mouse_move_failure.assert_called_once_with()

    def test_mouse_move_warning_has_cooldown(self) -> None:
        app = App.__new__(App)
        app._last_mouse_admin_warning_at = 0.0
        app._event_line = Mock(return_value="请以管理员身份运行")
        app._pet_feedback = Mock()
        with patch.object(app_module.time, "monotonic", side_effect=(100.0, 105.0, 113.0)):
            app._notify_mouse_move_failure()
            app._notify_mouse_move_failure()
            app._notify_mouse_move_failure()
        self.assertEqual(app._pet_feedback.call_count, 2)

    @staticmethod
    def _preflight_app() -> App:
        app = App.__new__(App)
        app._preflight_running = False
        app.target_mode = Mock()
        app.target_mode.get.return_value = "client"
        app.tasks = [SimpleNamespace(enabled=True)]
        app._is_due = Mock(return_value=True)
        app._pet_feedback = Mock()
        app._event_line = Mock(return_value="正在检查")
        app.window_title = Mock()
        app.window_title.get.return_value = "鸣潮"
        app._parse_resolution = Mock(return_value=(1920, 1080))
        app.template_group = Mock()
        app.template_group.get.return_value = "default"
        app._template_group_dir = Mock(return_value=Path("templates"))
        app._run_enabled = Mock()
        app._show_task_error_feedback = Mock()
        app._handle_task_failure = Mock()
        app._log = Mock()
        app.root = Mock()
        app.root.after.side_effect = lambda _delay, callback: callback()
        return app

    def test_fast_preflight_starts_task_after_success(self) -> None:
        app = self._preflight_app()
        controller = Mock()
        controller.scale = 1.0
        immediate_thread = lambda target, daemon: SimpleNamespace(start=target)
        with (
            patch.object(app_module, "ClientWindowController", return_value=controller),
            patch.object(app_module, "TemplateMatcher"),
            patch.object(app_module.threading, "Thread", side_effect=immediate_thread),
        ):
            app._preflight_enabled_run()
        app._run_enabled.assert_called_once_with()
        app._show_task_error_feedback.assert_not_called()
        self.assertFalse(app._preflight_running)

    def test_weekly_preflight_defers_page_position_to_runtime_observer(self):
        app = self._preflight_app()
        app.tasks = [SimpleNamespace(enabled=True, template_group='default', name=app_module.DEFAULT_GROUP_NAME, steps=[])]
        with patch.object(app_module, 'ClientWindowController', side_effect=AssertionError('must not require menu1')):
            app._preflight_enabled_run()
        app._run_enabled.assert_called_once_with()
        self.assertFalse(app._preflight_running)

    def test_fast_preflight_reports_failure_before_worker(self) -> None:
        app = self._preflight_app()
        controller = Mock()
        controller.connect.side_effect = RuntimeError("没有找到游戏窗口")
        immediate_thread = lambda target, daemon: SimpleNamespace(start=target)
        with (
            patch.object(app_module, "ClientWindowController", return_value=controller),
            patch.object(app_module.threading, "Thread", side_effect=immediate_thread),
        ):
            app._preflight_enabled_run()
        app._handle_task_failure.assert_called_once_with("没有找到游戏窗口")
        app._show_task_error_feedback.assert_not_called()
        app._run_enabled.assert_not_called()
        self.assertFalse(app._preflight_running)

    def test_non_admin_task_failure_restarts_with_elevation(self) -> None:
        app = App.__new__(App)
        app._admin_restart_requested = False
        app._elevated_launch_command = Mock(return_value=("C:\\wwbs.exe", '--mode "daily"'))
        app._log = Mock()
        app.stop_event = Mock()
        app.root = Mock()
        app._close_app = Mock()
        app._show_task_error_feedback = Mock()
        shell32 = Mock()
        shell32.ShellExecuteW.return_value = 42

        with (
            patch.object(app_module, "is_running_as_admin", return_value=False),
            patch.object(app_module.ctypes, "windll", SimpleNamespace(shell32=shell32)),
        ):
            app._handle_task_failure("键盘操作发送失败")

        shell32.ShellExecuteW.assert_called_once_with(
            None,
            "runas",
            "C:\\wwbs.exe",
            '--mode "daily"',
            str(app_module.APP_DIR),
            1,
        )
        app.stop_event.set.assert_called_once_with()
        app.root.after.assert_called_once_with(120, app._close_app)
        app._show_task_error_feedback.assert_not_called()

    def test_admin_task_failure_keeps_normal_error_feedback(self) -> None:
        app = App.__new__(App)
        app._admin_restart_requested = False
        app._show_task_error_feedback = Mock()

        with patch.object(app_module, "is_running_as_admin", return_value=True):
            app._handle_task_failure("普通错误")

        app._show_task_error_feedback.assert_called_once_with("普通错误")

    def test_real_run_requests_admin_before_starting(self) -> None:
        app = App.__new__(App)
        app.dry_run = Mock()
        app.dry_run.get.return_value = False
        app._request_admin_restart = Mock(return_value=True)

        with patch.object(app_module, "is_running_as_admin", return_value=False):
            self.assertFalse(app._ensure_admin_for_real_run())

        app._request_admin_restart.assert_called_once_with(
            "真实任务开始前检测到程序未使用管理员权限，正在请求管理员权限并自动重启。"
        )

    def test_preview_does_not_request_admin(self) -> None:
        app = App.__new__(App)
        app.dry_run = Mock()
        app.dry_run.get.return_value = True
        app._request_admin_restart = Mock()

        with patch.object(app_module, "is_running_as_admin", return_value=False):
            self.assertTrue(app._ensure_admin_for_real_run())

        app._request_admin_restart.assert_not_called()

    @staticmethod
    def _shutdown_app(enabled=True, dry_run=False, manually_stopped=False) -> App:
        app = App.__new__(App)
        app.auto_shutdown_enabled = Mock()
        app.auto_shutdown_enabled.get.return_value = enabled
        app.dry_run = Mock()
        app.dry_run.get.return_value = dry_run
        app._manual_stop_requested = manually_stopped
        app._pet_feedback = Mock()
        app._event_line = Mock(return_value="任务完成")
        app._log = Mock()
        return app

    def test_successful_real_task_schedules_shutdown(self) -> None:
        app = self._shutdown_app()
        with patch.object(app_module.subprocess, "Popen") as popen:
            app._handle_successful_task_completion()
        command = popen.call_args.args[0]
        self.assertEqual(command[:4], ["shutdown.exe", "/s", "/t", "30"])
        app._log.assert_any_call("任务正常完成，已请求 Windows 在30秒后自动关机。")

    def test_preview_and_manual_stop_never_schedule_shutdown(self) -> None:
        for dry_run, manually_stopped in ((True, False), (False, True)):
            with self.subTest(dry_run=dry_run, manually_stopped=manually_stopped):
                app = self._shutdown_app(dry_run=dry_run, manually_stopped=manually_stopped)
                with patch.object(app_module.subprocess, "Popen") as popen:
                    app._handle_successful_task_completion()
                popen.assert_not_called()

    def test_native_windows_icon_is_sent_to_taskbar_window(self) -> None:
        window = Mock()
        window.winfo_id.return_value = 111
        user32 = Mock()
        user32.GetParent.return_value = 222
        user32.LoadImageW.side_effect = (333, 444)

        with (
            patch.object(app_module.os, "name", "nt"),
            patch.object(app_module.ctypes, "windll", SimpleNamespace(user32=user32)),
        ):
            result = app_module.apply_windows_taskbar_icon(window, app_module.APP_ICON)

        self.assertTrue(result)
        self.assertEqual(user32.SendMessageW.call_count, 2)
        user32.SendMessageW.assert_any_call(222, 0x0080, 0, 333)
        user32.SendMessageW.assert_any_call(222, 0x0080, 1, 444)


if __name__ == "__main__":
    unittest.main()
