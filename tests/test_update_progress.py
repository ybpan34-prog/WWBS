from contextlib import ExitStack
from pathlib import Path
import queue
import tempfile
import threading
import time
import tkinter as tk
import unittest
from unittest.mock import patch

import app


class UpdateProgressTests(unittest.TestCase):
    def setUp(self):
        self.root=tk.Tk()
        self.root.geometry('800x600+50+50')
        self.root.update()
        self.ui=app.App.__new__(app.App)
        self.ui.root=self.root
        self.ui.status=tk.StringVar(value='')
        self.ui._update_cancelled=threading.Event()
        self.ui._update_handoff_lock=threading.Lock()
        self.ui._update_launching=False
        self.ui._update_events=queue.Queue()
        self.ui._update_installing=True
        self.ui._show_update_progress('v1.5.5-beta1')
        self.root.update()
    def tearDown(self):
        self.ui._close_update_progress()
        self.root.destroy()
    def poll(self,*events):
        self.root.after_cancel(self.ui._update_progress_job)
        for event in events:
            self.ui._update_events.put(event)
        self.ui._poll_update_progress()
        self.root.update()
    def test_download_shows_percent_and_bytes_then_real_phase_without_fake_install_percent(self):
        self.poll(('download',1048576,2097152))
        self.assertEqual(float(self.ui._update_progress_bar['value']),50)
        self.assertIn('50.0%',self.ui._update_detail.get())
        self.assertIn('1.0 / 2.0 MB',self.ui._update_detail.get())
        self.poll(('phase','校验安装包'))
        self.assertEqual(str(self.ui._update_progress_bar['mode']),'indeterminate')
        self.assertEqual(self.ui._update_phase.get(),'校验安装包')
        window=self.ui._update_progress_window
        self.assertLess(abs(window.winfo_rootx()+window.winfo_width()/2-(self.root.winfo_rootx()+400)),25)
    def test_unknown_total_and_cancel_keep_original_running(self):
        self.poll(('download',1048576,0))
        self.assertIn('1.0 MB',self.ui._update_detail.get())
        self.ui._cancel_update_download()
        self.assertTrue(self.ui._update_cancelled.is_set())
        with patch.object(app.messagebox,'showerror') as error:
            self.poll(('cancelled',))
            error.assert_not_called()
        self.assertFalse(self.ui._update_installing)
        self.assertIsNone(self.ui._update_progress_window)
    def test_error_closes_progress_and_reports_the_failing_phase(self):
        with patch.object(app.messagebox,'showerror') as error:
            self.poll(('error','下载安装包失败'))
            self.assertIn('下载安装包失败',error.call_args.args[1])
        self.assertFalse(self.ui._update_installing)

    def test_real_speed_and_estimate_are_visible_and_clear_at_verification(self):
        self.poll(('speed', 262144, 8))
        self.assertIn('256.0 KB/s', self.ui._update_speed.get())
        self.assertIn('8 秒', self.ui._update_speed.get())
        self.poll(('phase', '校验安装包'))
        self.assertEqual(self.ui._update_speed.get(), '')

    def test_fresh_selection_starts_download_without_duplicate_metadata_request(self):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as patches:
            root = Path(directory)
            patches.enter_context(patch.object(app, 'create_update_work', return_value=root))
            refreshed = patches.enter_context(patch.object(app, 'refresh_release_asset'))
            downloaded = patches.enter_context(patch.object(app, 'download_asset', return_value={}))
            patches.enter_context(patch.object(app, 'prepare_update', return_value=root/'extract'))
            patches.enter_context(patch.object(app, 'snapshot_settings'))
            patches.enter_context(patch.object(app, 'install_script', return_value='# test'))
            patches.enter_context(patch.object(app.subprocess, 'Popen'))
            self.ui._download_and_install_update('v9', {'_wwbs_verified_at':time.monotonic()})
            refreshed.assert_not_called()
            self.assertEqual(downloaded.call_count, 1)
            self.assertEqual(downloaded.call_args.kwargs['cache_dir'].name, '.wwbs-update-cache')
    def test_update_worker_uses_queue_without_calling_tk_from_background(self):
        with tempfile.TemporaryDirectory() as directory,ExitStack() as patches:
            root=Path(directory)
            patches.enter_context(patch.object(app,'create_update_work',return_value=root))
            patches.enter_context(patch.object(app,'refresh_release_asset',return_value={}))
            def download(_asset,_path,**options): options['progress'](50,100)
            patches.enter_context(patch.object(app,'download_asset',side_effect=download))
            patches.enter_context(patch.object(app,'prepare_update',return_value=root/'extract'))
            patches.enter_context(patch.object(app,'snapshot_settings'))
            patches.enter_context(patch.object(app,'install_script',return_value='# test'))
            opened=patches.enter_context(patch.object(app.subprocess,'Popen'))
            with patch.object(self.root,'after') as after:
                self.ui._download_and_install_update('v9',{})
                after.assert_not_called()
            opened.assert_called_once()
            events=[]
            while not self.ui._update_events.empty():
                events.append(self.ui._update_events.get_nowait())
            self.assertIn(('download',50,100),events)
            self.assertIn(('phase','校验安装包'),events)
            self.assertEqual(events[-1],('handoff',))


if __name__=='__main__':
    unittest.main()
