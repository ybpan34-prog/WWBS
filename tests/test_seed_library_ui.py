import threading
import time
import tkinter as tk
import unittest
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import app
from combat_rotation import default_store
from combat_seed import export_seed
from ui_controls import RoundedButton


def walk(widget):
    yield widget
    for child in widget.winfo_children():
        yield from walk(child)


class SeedLibraryUiTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.geometry('900x700')
        self.ui = app.App.__new__(app.App)
        self.ui.root = self.root

    def tearDown(self):
        self.root.destroy()

    def wait_job(self, dialog):
        deadline = time.monotonic()+3
        self.root.update()
        while getattr(dialog, '_seed_job_running', False) and time.monotonic() < deadline:
            self.root.update()
            time.sleep(.01)
        self.assertFalse(getattr(dialog, '_seed_job_running', False))

    def test_open_loads_recent_records_as_separate_cards_without_search(self):
        workers = []
        def search(query):
            workers.append(threading.get_ident())
            self.assertEqual(query, '')
            return ([{'id': 'a'*24, 'name': '最新上传', 'modules': 18},
                     {'id': 'b'*24, 'name': '之前上传', 'modules': 15}], False)
        with patch.object(app, 'search_seeds', side_effect=search) as request:
            dialog = self.ui._rotation_online_seed_library()
            self.wait_job(dialog)
        request.assert_called_once_with('')
        self.assertNotEqual(workers[0], threading.get_ident())
        self.assertFalse(any(isinstance(w, tk.Text) for w in walk(dialog)))
        labels = [w.cget('text') for w in walk(dialog) if isinstance(w, tk.Label)]
        self.assertLess(labels.index('最新上传'), labels.index('之前上传'))
        buttons = [w for w in walk(dialog) if isinstance(w, RoundedButton) and w.cget('text') == '下载并导入']
        self.assertEqual(len(buttons), 2)
        self.assertNotEqual(buttons[0].master, buttons[1].master)

    def test_each_card_downloads_its_own_seed_and_adds_without_changing_modes(self):
        self.ui.rotation_store = default_store()
        modes = dict(self.ui.rotation_store['modes'])
        self.ui.rotation_choice = tk.StringVar()
        self.ui._rotation_save = Mock(return_value=True)
        self.ui._rotation_refresh_picker = Mock()
        self.ui._rotation_rebuild_cards = Mock()
        seed_preset = default_store()['presets'][0]
        seed_preset['name'] = '第二条种子'
        seed = export_seed(seed_preset)
        items = [{'id': 'a'*24, 'name': '第一条种子', 'modules': 15},
                 {'id': 'b'*24, 'name': '第二条种子', 'modules': 18, 'created': '2026-10-19T01:02:03Z'}]
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(app, 'COMBAT_PRESETS_CONFIG', Path(directory)/'axis.json'), \
                patch.object(app, 'search_seeds', return_value=(items, False)), \
                patch.object(app, 'download_seed', return_value=seed) as download:
            dialog = self.ui._rotation_online_seed_library()
            self.wait_job(dialog)
            buttons = [w for w in walk(dialog) if isinstance(w, RoundedButton) and w.cget('text') == '下载并导入']
            buttons[1].invoke()
            self.wait_job(dialog)
        download.assert_called_once_with('b'*24)
        self.assertEqual(len(self.ui.rotation_store['presets']), 2)
        self.assertEqual(self.ui.rotation_store['presets'][-1]['name'], '第二条种子')
        self.assertEqual(self.ui.rotation_store['modes'], modes)

    def test_long_card_list_can_scroll_and_short_refresh_does_not_leave_blank_space(self):
        items = [{'id': f'{i:024x}', 'name': f'种子{i}', 'modules': 18} for i in range(50)]
        with patch.object(app, 'search_seeds', return_value=(items, False)):
            dialog = self.ui._rotation_online_seed_library()
            self.wait_job(dialog)
        host = next(w for w in walk(dialog) if hasattr(w, '_seed_canvas'))
        canvas = host._seed_canvas
        self.assertLess(canvas.yview()[1], 1)
        canvas.yview_moveto(1)
        self.assertGreater(canvas.yview()[0], 0)
        with patch.object(app, 'search_seeds', return_value=(items[:1], False)):
            search = next(w for w in walk(dialog) if isinstance(w, RoundedButton) and w.cget('text') == '搜索')
            search.invoke()
            self.wait_job(dialog)
        self.assertEqual(canvas.yview(), (0., 1.))

    def test_network_error_is_visible_and_does_not_leave_a_blank_silent_dialog(self):
        with patch.object(app, 'search_seeds', side_effect=RuntimeError('连接失败，请检查网络')):
            dialog = self.ui._rotation_online_seed_library()
            self.wait_job(dialog)
        values = [self.root.getvar(w.cget('textvariable')) for w in walk(dialog)
                  if isinstance(w, tk.Label) and w.cget('textvariable')]
        self.assertIn('连接失败，请检查网络', values)

    def test_closing_during_request_does_not_deliver_results_to_destroyed_widgets(self):
        dialog = tk.Toplevel(self.root)
        status = tk.StringVar()
        finish = Mock()
        release = threading.Event()
        self.ui._seed_library_job(dialog, status, lambda: release.wait(2), finish)
        dialog.destroy()
        release.set()
        deadline = time.monotonic()+.15
        while time.monotonic() < deadline:
            self.root.update()
            time.sleep(.01)
        finish.assert_not_called()
