import tkinter as tk
import unittest

import app


class CenteredInputTests(unittest.TestCase):
    def test_new_axis_name_dialog_opens_in_owner_center(self):
        root = tk.Tk()
        try:
            root.geometry('1050x800+200+40')
            root.update()
            ui = app.App.__new__(app.App)
            ui.root = root
            measurements = []
            def inspect_and_close():
                dialog = next(w for w in root.winfo_children() if isinstance(w, tk.Toplevel))
                dialog.update_idletasks()
                measurements.append((abs(dialog.winfo_rootx()+dialog.winfo_width()/2-root.winfo_rootx()-root.winfo_width()/2),
                                     abs(dialog.winfo_rooty()+dialog.winfo_height()/2-root.winfo_rooty()-root.winfo_height()/2)))
                dialog.destroy()
            root.after(120, inspect_and_close)
            self.assertIsNone(ui._ask_text('新建战斗排轴', '输入新预设名称：'))
            self.assertEqual(len(measurements), 1)
            self.assertLess(measurements[0][0], 40)
            self.assertLess(measurements[0][1], 40)
        finally:
            root.destroy()


if __name__ == '__main__':
    unittest.main()
