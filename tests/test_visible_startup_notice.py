"""A slow first paint must never show a modal while the main window is transparent."""
from contextlib import ExitStack
from pathlib import Path
import tempfile
import time
import tkinter as tk
import unittest
from unittest.mock import Mock, patch

import app
from ui_controls import show_ready_main_window


class VisibleStartupNoticeTests(unittest.TestCase):
    def test_slow_first_paint_still_shows_main_window_before_the_announcement(self):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as patches:
            patches.enter_context(patch.object(app, 'UPDATE_NOTICE_CONFIG', Path(directory)/'notice.json'))
            for method in ('_load_config', '_drain_logs', '_start_stop_hotkey',
                           '_start_desktop_pet', '_scan_local_models', '_report_settings_import'):
                patches.enter_context(patch.object(app.App, method))
            patches.enter_context(patch.object(app.sys, 'argv', ['app.py']))
            signal = patches.enter_context(patch.object(app, 'signal_update_ready'))
            root = tk.Tk()
            root.withdraw()
            timeout = None
            try:
                ui = app.App(root)
                observed = []
                def announcement(*_args, **options):
                    observed.append((root.winfo_ismapped(), root.attributes('-alpha'),
                                     root._main_frame_ready, options['parent'] is root))
                    root.quit()
                patches.enter_context(patch.object(app.messagebox, 'showinfo', side_effect=announcement))
                time.sleep(.35)  # The old constructor timer is now overdue.
                show_ready_main_window(root, ui._on_main_window_ready)
                self.assertEqual(observed, [])
                timeout = root.after(1500, root.quit)
                root.mainloop()
                self.assertEqual(observed, [(1, 1., True, True)])
                signal.assert_called_once()
                ui._on_main_window_ready()
                signal.assert_called_once()
            finally:
                if timeout:
                    root.after_cancel(timeout)
                root.destroy()

    def test_admin_restart_still_skips_automatic_notice_after_ready(self):
        ui = app.App.__new__(app.App)
        ui.root = Mock()
        with patch.object(app.sys, 'argv', ['app.py', '--admin-restarted']), \
                patch.object(app, 'is_running_as_admin', return_value=True), \
                patch.object(app, 'signal_update_ready'):
            ui._on_main_window_ready()
        callbacks = [call.args[1] for call in ui.root.after.call_args_list]
        self.assertNotIn(ui._show_startup_notice_once, callbacks)
