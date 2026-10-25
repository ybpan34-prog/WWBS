from pathlib import Path
import tempfile
import tkinter as tk
import unittest
from unittest.mock import Mock, patch

import app
from local_settings import Installation, prepare_import, settings_files
from ui_controls import RoundedButton


class SourceModalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)
        self.target, self.old = base/'current', base/'old'
        self.target.mkdir()
        self.old.mkdir()
        (self.old/'combat-settings.json').write_text('{"skill_key":"Q","ultimate_key":"T"}')
        self.source = Installation(self.old, '1.5.5', settings_files(self.old))
        self.root = tk.Tk()
        self.root.geometry('1100x850+40+40')
        self.errors = []
        self.root.report_callback_exception = lambda *args: self.errors.append(args)
        self.ui = app.App.__new__(app.App)
        self.ui.root, self.ui.worker = self.root, None
        self.ui.status = tk.StringVar(self.root)
        self.ui.local_settings_status = tk.StringVar(self.root)
        self.ui._settings_scan_sources = [self.source]
        self.settings = patch.object(app, 'USER_SETTINGS_DIR', self.target)
        self.settings.start()
        self.ui._offer_local_settings(prepare_import(self.source, self.target), False)
        self.root.update()
        self.parent = self.ui._settings_import_window

    def tearDown(self):
        self.root.destroy()
        self.settings.stop()
        self.temp.cleanup()

    def click(self, window, text):
        def walk(widget):
            yield widget
            for child in widget.winfo_children():
                yield from walk(child)
        button = next(w for w in walk(window) if isinstance(w, RoundedButton) and w.cget('text') == text)
        button.event_generate('<ButtonPress-1>', x=20, y=15)
        button.event_generate('<ButtonRelease-1>', x=20, y=15)
        self.root.update()
        self.assertEqual(self.errors, [])

    def test_close_transfers_grab_back_and_parent_buttons_still_work(self):
        self.assertEqual(self.root.grab_current(), self.parent)
        self.click(self.parent, '选择其他来源')
        child = self.ui._settings_source_window
        self.assertEqual(self.root.grab_current(), child)
        self.assertFalse(self.parent.winfo_ismapped())
        self.click(child, '关闭')
        self.assertFalse(child.winfo_exists())
        self.assertEqual(self.root.grab_current(), self.parent)
        self.assertTrue(self.parent.winfo_ismapped())
        self.click(self.parent, '取消')
        self.assertIsNone(self.root.grab_current())

    def test_using_source_closes_both_old_windows_and_starts_a_fresh_scan(self):
        self.ui._detect_local_settings = Mock()
        self.click(self.parent, '选择其他来源')
        child = self.ui._settings_source_window
        self.click(child, '使用所选来源')
        self.assertFalse(child.winfo_exists())
        self.assertFalse(self.parent.winfo_exists())
        self.assertIsNone(self.root.grab_current())
        self.ui._detect_local_settings.assert_called_once_with(search_roots=[self.old])
