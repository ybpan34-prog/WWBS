import time
import tkinter as tk
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from PIL import ImageGrab

import ui_controls
from windows_client import _enable_dpi_awareness


def pump(root, seconds):
    deadline = time.monotonic()+seconds
    while time.monotonic() < deadline:
        root.update()
        time.sleep(.01)


class RestoreRedrawTests(unittest.TestCase):
    def test_child_mapping_cannot_schedule_main_window_restore(self):
        root = Mock()
        root._main_frame_ready = True
        handler = ui_controls.RestoreRedraw(root)
        event = SimpleNamespace(widget=Mock())
        handler._unmap(event)
        handler._map(event)
        root.after.assert_not_called()
        root.after_idle.assert_not_called()

    def test_native_minimize_restore_preserves_controls_and_repaints_pixels(self):
        _enable_dpi_awareness()
        root = tk.Tk()
        root.withdraw()
        root.geometry('480x360+30+30')
        entry = tk.Entry(root)
        entry.insert(0, '保留我的设置')
        entry.pack(fill='x')
        canvas = tk.Canvas(root, background='#eef6ff', highlightthickness=0, scrollregion=(0, 0, 480, 1200))
        canvas.pack(fill='both', expand=True)
        canvas.create_rectangle(100, 500, 200, 600, fill='#70c0e0')
        ready = Mock()
        try:
            ui_controls.show_ready_main_window(root, ready)
            pump(root, .2)
            canvas.yview_moveto(.35)
            root.update_idletasks()
            position = canvas.yview()
            with patch('ui_controls._redraw_native_window', wraps=ui_controls._redraw_native_window) as native:
                for _ in range(3):
                    root.iconify()
                    pump(root, .1)
                    self.assertEqual(root.state(), 'iconic')
                    root.deiconify()
                    pump(root, .25)
                    self.assertEqual(entry.get(), '保留我的设置')
                    self.assertEqual(canvas.yview(), position)
                    x, y = canvas.winfo_rootx()+10, canvas.winfo_rooty()+10
                    pixel = ImageGrab.grab((x, y, x+1, y+1)).getpixel((0, 0))
                    self.assertTrue(all(value > 200 for value in pixel), pixel)
            self.assertGreaterEqual(native.call_count, 6)
            self.assertGreaterEqual(root._restore_redraw.paint_count, 6)
            ready.assert_called_once()
        finally:
            root.destroy()
