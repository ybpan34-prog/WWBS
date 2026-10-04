import tkinter as tk
import unittest
from unittest.mock import Mock

import app
from ui_controls import RoundedButton, ThinScrollbar


class ReleaseUiTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.configure(bg=app.COLORS['panel'])
        self.root.geometry('420x240+20+20')
        self.ui = app.App.__new__(app.App)
        self.ui.root = self.root

    def tearDown(self):
        self.root.destroy()

    def test_button_ignores_orphan_release_and_disabled_click(self):
        command = Mock()
        button = self.ui._ui_button(self.root, text='发送', command=command)
        button.pack()
        self.root.update()
        button.event_generate('<ButtonRelease-1>', x=20, y=20)
        command.assert_not_called()
        button.event_generate('<ButtonPress-1>', x=20, y=20)
        button.event_generate('<ButtonRelease-1>', x=20, y=20)
        command.assert_called_once()
        button.configure(state='disabled')
        button.event_generate('<ButtonPress-1>', x=20, y=20)
        button.event_generate('<ButtonRelease-1>', x=20, y=20)
        button.invoke()
        command.assert_called_once()

    def test_dynamic_model_choices_and_wheel_use_new_values(self):
        value = tk.StringVar(value='old')
        callback = Mock()
        picker = self.ui._rounded_picker(self.root, value, [], callback, editable=True)
        picker.pack(fill=tk.X)
        self.root.update()
        picker.set_choices(['model-a', 'model-b'])
        value.set('model-a')
        picker.event_generate('<MouseWheel>', delta=-120)
        self.root.update()
        self.assertEqual(value.get(), 'model-b')
        callback.assert_called_once()
        picker.set_choices([])
        picker.event_generate('<MouseWheel>', delta=-120)
        self.assertEqual(value.get(), 'model-b')

    def test_picker_row_reserves_button_width_at_large_font(self):
        self.root.tk.call('tk', 'scaling', 2.0)
        row = tk.Frame(self.root, bg=app.COLORS['panel'])
        row.pack(fill=tk.X)
        picker = self.ui._rounded_picker(row, tk.StringVar(value='测试'), ['测试'], lambda: None)
        picker.pack(side=tk.LEFT, fill=tk.X, expand=True)
        button = self.ui._ui_button(row, text='获取服务模型', command=lambda: None)
        button.pack(side=tk.LEFT)
        self.ui._reserve_row_controls(row, picker)
        self.root.update()
        self.assertGreaterEqual(button.winfo_width(), button.winfo_reqwidth())
        self.assertLessEqual(button.winfo_x()+button.winfo_width(), row.winfo_width())

    def test_rounded_entry_retains_native_focus_edit_and_readonly(self):
        value = tk.StringVar(value='20')
        entry = self.ui._rounded_entry(self.root, textvariable=value)
        entry.pack(fill=tk.X)
        self.root.update()
        entry.focus_force()
        entry.selection_range(0, tk.END)
        entry.delete(0, tk.END)
        entry.insert(0, '18.5')
        self.assertEqual(value.get(), '18.5')
        self.assertIs(self.root.focus_get(), entry)
        entry.configure(state='readonly')
        entry.delete(0, tk.END)
        self.assertEqual(value.get(), '18.5')

    def test_scrollbar_moves_view_and_button_rows_wrap(self):
        move = Mock()
        scrollbar = ThinScrollbar(self.root, colors=app.COLORS, command=move)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        scrollbar.set(0, .3)
        row = tk.Frame(self.root, bg=app.COLORS['panel'])
        row.pack(fill=tk.X)
        for text in ('使用原版简约主题', '使用卡提希娅主题', '使用爱弥斯主题'):
            RoundedButton(row, colors=app.COLORS, text=text).pack(side=tk.LEFT)
        self.ui._wrap_button_row(row)
        self.root.update()
        rows = {int(child.grid_info()['row']) for child in row.winfo_children()}
        self.assertGreater(len(rows), 1)
        scrollbar.event_generate('<Button-1>', x=3, y=160)
        self.assertEqual(move.call_args.args[0], 'moveto')
        self.assertGreater(move.call_args.args[1], 0)


if __name__ == '__main__':
    unittest.main()
