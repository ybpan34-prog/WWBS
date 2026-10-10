import json
import gc
import tkinter as tk
import unittest
from unittest.mock import Mock, patch, MagicMock

import app


def release(tag, **fields):
    return dict(tag_name=tag, assets=[{'name': 'wwbs-exe.zip', 'state': 'uploaded'}], **fields)


class UpdateDiscoveryTests(unittest.TestCase):
    def test_newer_beta_is_included_even_when_not_first_in_list(self):
        candidates = [release('v1.5.3'), release('v1.5.4-beta1', prerelease=True),
                      release('v1.5.4-beta2', prerelease=True)]
        self.assertEqual(app.App._select_update_release(candidates)[0], 'v1.5.4-beta2')

    def test_formal_version_beats_beta_with_same_version_number(self):
        self.assertEqual(app.App._select_update_release(
            [release('v1.5.4-beta99'), release('v1.5.4')])[0], 'v1.5.4')

    def test_drafts_missing_assets_and_incomplete_uploads_are_skipped(self):
        unfinished = release('v1.6.0-beta2')
        unfinished['assets'][0]['state'] = 'new'
        empty = release('v1.6.0-beta1')
        empty['assets'] = []
        self.assertEqual(app.App._select_update_release([
            release('v2.0.0', draft=True), unfinished, empty, release('v1.5.4-beta2')
        ])[0], 'v1.5.4-beta2')
        with self.assertRaises(RuntimeError):
            app.App._select_update_release([empty, unfinished])

    def test_check_fetches_release_list_and_passes_beta_to_ui(self):
        ui = app.App.__new__(app.App)
        ui.root, ui.status = Mock(), Mock()
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(
            [release('v1.5.3'), release('v1.5.4-beta3', prerelease=True)]).encode()
        ui._show_available_update = Mock()
        def dispatch(*, target, daemon):
            worker = Mock()
            worker.start.side_effect = target
            return worker
        with patch('app.urllib.request.urlopen', return_value=response) as opened, \
                patch('app.threading.Thread', side_effect=dispatch) as thread:
            ui._check_for_updates()
        thread.assert_called_once()
        ui.update_worker.start.assert_called_once()
        self.assertIn('/releases?per_page=100', opened.call_args.args[0].full_url)
        ui.root.after.call_args.args[1]()
        self.assertEqual(ui._show_available_update.call_args.args[0], 'v1.5.4-beta3')


class UpdateDialogTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.geometry('900x680+120+40')
        self.root.update()
        self.ui = app.App.__new__(app.App)
        self.ui.root, self.ui.status, self.ui.worker = self.root, Mock(), None
        self.notes = '\n'.join(f'第{i}条更新说明：滚动查看全部内容。' for i in range(400))

    def tearDown(self):
        self.root.destroy()
        gc.collect()

    def show(self, work_area=(0, 0, 800, 560)):
        with patch.object(self.ui, '_update_work_area', return_value=work_area):
            self.ui._show_available_update('v9.0.0-beta1',
                                           {'body': self.notes, 'prerelease': True}, {})
        self.root.update()
        return self.ui._update_offer_window

    def assert_footer_visible(self, window):
        footer = window._update_footer
        for button in footer.winfo_children():
            self.assertGreater(button.winfo_width(), 30)
            self.assertGreaterEqual(button.winfo_rootx(), window.winfo_rootx())
            self.assertLessEqual(button.winfo_rootx()+button.winfo_width(),
                                 window.winfo_rootx()+window.winfo_width())
            self.assertLessEqual(button.winfo_rooty()+button.winfo_height(),
                                 window.winfo_rooty()+window.winfo_height())

    def test_long_notes_scroll_and_footer_stays_visible_on_small_screen(self):
        window = self.show()
        self.assertLessEqual(window.winfo_rooty()+window.winfo_height(), 560)
        self.assertLessEqual(window.winfo_width(), 768)
        self.assertEqual(window.resizable(), (1, 1))
        self.assertIsNone(self.root.grab_current())
        self.assert_footer_visible(window)
        text = window._update_notes_text
        self.assertEqual(text.get('1.0', 'end-1c'), self.notes)
        self.assertLess(text.yview()[1], 1)
        text.event_generate('<MouseWheel>', delta=-120)
        self.root.update()
        self.assertGreater(text.yview()[0], 0)
        text.yview_moveto(1)
        self.root.update()
        self.assertAlmostEqual(text.yview()[1], 1)
        self.assert_footer_visible(window)

    def test_resize_changes_notes_area_and_preserves_buttons_at_large_font(self):
        self.root.tk.call('tk', 'scaling', 2.0)
        window = self.show((0, 0, 640, 480))
        text = window._update_notes_text
        before = text.winfo_height()
        window.geometry('480x300')
        self.root.update()
        self.assertLess(text.winfo_height(), before)
        self.assertGreater(text.winfo_height(), 20)
        self.assert_footer_visible(window)
        window.geometry('600x400')
        self.root.update()
        self.assertGreater(text.winfo_height(), before-20)
        self.assert_footer_visible(window)

    def test_close_button_escape_and_titlebar_all_close_without_installing(self):
        self.ui._begin_update_install = Mock()
        for method in ('button', 'escape', 'titlebar'):
            with self.subTest(method=method):
                window = self.show()
                if method == 'button':
                    next(w for w in window._update_footer.winfo_children()
                         if w.cget('text') == '关闭').invoke()
                elif method == 'escape':
                    window._update_notes_text.focus_force()
                    self.root.update()
                    window._update_notes_text.event_generate('<Escape>')
                else:
                    window.tk.call(window.protocol('WM_DELETE_WINDOW'))
                self.root.update()
                self.assertFalse(window.winfo_exists())
                self.assertIsNone(self.ui._update_offer_window)
        self.ui._begin_update_install.assert_not_called()

    def test_repeated_offer_replaces_old_window(self):
        old = self.show()
        new = self.show()
        self.assertFalse(old.winfo_exists())
        self.assertTrue(new.winfo_exists())

    def test_download_only_starts_after_explicit_install_click(self):
        window = self.show()
        with patch.object(app.sys, 'frozen', True, create=True), patch('app.threading.Thread') as thread:
            thread.assert_not_called()
            next(w for w in window._update_footer.winfo_children()
                 if w.cget('text') == '下载并安装').invoke()
            thread.return_value.start.assert_called_once()
            self.assertEqual(thread.call_args.kwargs['args'][0], 'v9.0.0-beta1')
            self.assertTrue(self.ui._update_installing)
            self.assertFalse(window.winfo_exists())


if __name__ == '__main__':
    unittest.main()
