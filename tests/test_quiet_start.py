import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import app


class QuietStartTests(unittest.TestCase):
    def ui(self):
        ui = app.App.__new__(app.App)
        ui._log = Mock()
        ui._show_update_notice = Mock()
        ui.worker = None
        return ui

    def test_announcement_persists_once_per_version_and_manual_view_remains(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(app, 'UPDATE_NOTICE_CONFIG', Path(directory)/'notice.json'):
            first = self.ui()
            first._show_startup_notice_once()
            first._show_startup_notice_once()
            first._show_update_notice.assert_called_once()
            second = self.ui()
            second._show_startup_notice_once()
            second._show_update_notice.assert_not_called()
            second._show_update_notice()
            second._show_update_notice.assert_called_once()
            self.assertIn(app.APP_VERSION, json.loads(app.UPDATE_NOTICE_CONFIG.read_text())['seen_versions'])

    def test_running_task_or_preflight_never_opens_automatic_announcement(self):
        for active in ('worker', 'preflight'):
            with self.subTest(active=active), tempfile.TemporaryDirectory() as directory, patch.object(app, 'UPDATE_NOTICE_CONFIG', Path(directory)/'notice.json'):
                ui = self.ui()
                ui.worker = Mock(is_alive=Mock(return_value=active == 'worker'))
                ui._preflight_running = active == 'preflight'
                ui._show_startup_notice_once()
                ui._show_update_notice.assert_not_called()

    def test_shortcut_launchers_do_not_ask_for_start_confirmation(self):
        ui = self.ui()
        ui.target_mode = Mock(get=Mock(return_value='client'))
        ui.dry_run = Mock()
        ui._ensure_admin_for_real_run = Mock(return_value=True)
        ui._preflight_enabled_run = Mock()
        ui._start_worker = Mock()
        ui.tasks = [app.WeeklyTask(name='4C刷取', enabled=False, weekday='any',
                                 steps=[app.Step(action='combat_4c')])]
        ui.daily_zone = Mock(get=Mock(return_value='沉心域无音区'))
        ui._save_daily_zone = Mock()
        with patch.object(app.messagebox, 'askyesno', side_effect=AssertionError('extra confirmation')):
            ui._start_enabled_real(15)
            ui._start_named_task_real('4C刷取', 10)
            ui._start_daily_routine()
        self.assertEqual(ui._start_worker.call_count, 2)
        ui._preflight_enabled_run.assert_called_once()


if __name__ == '__main__':
    unittest.main()
