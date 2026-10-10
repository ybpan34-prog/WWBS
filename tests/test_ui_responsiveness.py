import queue
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import app


class UiResponsivenessTests(unittest.TestCase):
    def test_reselecting_current_page_does_not_redraw_or_relayout(self):
        ui = app.App.__new__(app.App)
        ui._visible_top_tab = 1
        ui._close_rounded_picker = Mock()
        ui._tab_panels = [Mock(), Mock()]
        ui._nav_buttons = [Mock(), Mock()]
        ui._draw_nav_button = Mock()
        ui._select_top_tab(1)
        ui._draw_nav_button.assert_not_called()
        ui._tab_panels[1].tkraise.assert_not_called()

    def test_switch_keeps_existing_page_and_only_updates_changed_navigation(self):
        ui = app.App.__new__(app.App)
        ui._visible_top_tab = 0
        ui._close_rounded_picker = Mock()
        ui._tab_panels = [Mock() for _ in range(6)]
        ui._nav_buttons = [Mock() for _ in range(6)]
        ui._draw_nav_button = Mock()
        original = ui._tab_panels[1]
        ui._select_top_tab(1)
        self.assertIs(ui._tab_panels[1], original)
        original.tkraise.assert_called_once()
        self.assertEqual([call.args[0] for call in ui._draw_nav_button.call_args_list], [0, 1])

    def test_hidden_preview_remembers_latest_image_without_decoding(self):
        ui = app.App.__new__(app.App)
        ui.preview_canvas = Mock()
        ui._selected_top_tab = 1
        path = Path(__file__).parent/'fixtures'/'daily-activity-zero.png'
        with patch.object(app.Image, 'open') as opened:
            ui._show_preview(path, '最新截图')
        opened.assert_not_called()
        self.assertEqual(ui.preview_source, path)
        self.assertTrue(ui._preview_deferred)

    def test_log_burst_is_bounded_and_inserted_as_one_batch(self):
        ui = app.App.__new__(app.App)
        ui.log_queue = queue.Queue()
        for i in range(75):
            ui.log_queue.put(f'line-{i}')
        ui.root, ui.detail, ui.log_text, ui.status = Mock(), Mock(), Mock(), Mock()
        ui._drain_logs()
        self.assertEqual(ui.log_queue.qsize(), 15)
        ui.detail.insert.assert_called_once()
        ui.status.set.assert_called_once_with('line-59')
        self.assertEqual(ui.root.after.call_args.args[0], 16)
        ui._drain_logs()
        self.assertTrue(ui.log_queue.empty())
        self.assertEqual(ui.status.set.call_args.args[0], 'line-74')


if __name__ == '__main__':
    unittest.main()
