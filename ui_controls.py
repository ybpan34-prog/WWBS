"""Shared rounded controls for WWBS pages and application dialogs."""
import tkinter as tk
from tkinter import font as tkfont


def paint_round(canvas, x0, y0, x1, y1, radius, color):
    radius = min(radius, max(0, (x1-x0)/2), max(0, (y1-y0)/2))
    options = {'fill': color, 'outline': ''}
    canvas.create_rectangle(x0+radius, y0, x1-radius, y1, **options)
    canvas.create_rectangle(x0, y0+radius, x1, y1-radius, **options)
    for x in (x0, x1-radius*2):
        for y in (y0, y1-radius*2):
            canvas.create_oval(x, y, x+radius*2, y+radius*2, **options)


class RoundedButton(tk.Canvas):
    def __init__(self, parent, *, colors, text='', command=None, width=130,
                 primary=False, state='normal', font_family='Microsoft YaHei UI', **options):
        self.colors, self.label, self.command = dict(colors), text, command
        self.primary, self.control_state, self.pressed = primary, state, False
        font = tkfont.Font(root=parent, family=font_family, size=10,
                           weight='bold' if primary else 'normal')
        self.text_font = font
        super().__init__(parent, width=max(width, font.measure(text)+32),
                         height=max(42, font.metrics('linespace')+18),
                         bg=parent.cget('bg'), bd=0, highlightthickness=0,
                         takefocus=True, cursor='hand2')
        self._keep_canvas_style = True
        self._is_rounded_button = True
        self.bind('<Configure>', lambda _: self.draw())
        self.bind('<Enter>', lambda _: self.draw('hover'))
        self.bind('<Leave>', lambda _: self.draw())
        self.bind('<ButtonPress-1>', self.press)
        self.bind('<ButtonRelease-1>', self.release)
        self.bind('<Return>', lambda _: self.invoke())
        self.bind('<space>', lambda _: self.invoke())
        self.bind('<FocusIn>', lambda _: self.draw())
        self.bind('<FocusOut>', lambda _: self.draw())
        self.draw()

    def configure(self, cnf=None, **options):
        options = dict(cnf or {}, **options)
        if 'state' in options:
            self.control_state = options.pop('state')
            self.pressed = False
        if 'text' in options:
            self.label = options.pop('text')
            options.setdefault('width', self.text_font.measure(self.label)+32)
        if 'command' in options:
            self.command = options.pop('command')
        result = super().configure(**options)
        self.draw()
        return result

    config = configure

    def cget(self, key):
        if key == 'state':
            return self.control_state
        if key == 'text':
            return self.label
        return super().cget(key)

    def draw(self, phase='default'):
        self.delete('all')
        width, height = max(1, self.winfo_width()), max(1, self.winfo_height())
        if width <= 1:
            width, height = int(super().cget('width')), int(super().cget('height'))
        c = self.colors
        disabled = self.control_state == 'disabled'
        fill = c['primary'] if self.primary else c['panel']
        if phase == 'hover' and not disabled:
            fill = c['primary_hover'] if self.primary else c['panel_alt']
        if phase == 'pressed' and not disabled:
            fill = c['primary_hover'] if self.primary else c['line_soft']
        edge = c['primary'] if self.primary or self.focus_get() is self else c['line']
        paint_round(self, 0, 0, width, height, 9, edge)
        paint_round(self, 1, 1, width-1, height-1, 8, fill)
        self.create_text(width/2, height/2, text=self.label, font=self.text_font,
                         fill=c['muted'] if disabled else '#ffffff' if self.primary else c['text'])

    def press(self, _event):
        self.pressed = self.control_state != 'disabled'
        if self.pressed:
            self.focus_set()
            self.draw('pressed')

    def release(self, event):
        invoke = self.pressed and 0 <= event.x < self.winfo_width() and 0 <= event.y < self.winfo_height()
        self.pressed = False
        self.draw('hover')
        if invoke:
            self.invoke()

    def invoke(self):
        if self.control_state != 'disabled' and self.command:
            return self.command()


class ThinScrollbar(tk.Canvas):
    def __init__(self, parent, *, colors, command=None, orient='vertical'):
        super().__init__(parent, width=7, bd=0, highlightthickness=0,
                         bg=parent.cget('bg'), cursor='hand2')
        self.colors, self.command, self.range = dict(colors), command, (0., 1.)
        self._keep_canvas_style = True
        self._is_thin_scrollbar = True
        self.bind('<Configure>', lambda _: self.draw())
        self.bind('<Button-1>', self.drag)
        self.bind('<B1-Motion>', self.drag)
        self.bind('<MouseWheel>', self.wheel)

    def configure(self, cnf=None, **options):
        options = dict(cnf or {}, **options)
        if 'command' in options:
            self.command = options.pop('command')
        return super().configure(**options)

    config = configure

    def set(self, first, last):
        self.range = float(first), float(last)
        self.draw()

    def draw(self):
        self.delete('all')
        first, last = self.range
        height = self.winfo_height()
        if height <= 1 or last-first >= .999:
            return
        self.create_line(3, 2, 3, height-2, fill=self.colors['line_soft'], width=2)
        self.create_line(3, max(2, first*height), 3, min(height-2, max(first*height+24, last*height)),
                         fill=self.colors['line'], width=5, capstyle='round')

    def drag(self, event):
        first, last = self.range
        visible = min(1., last-first)
        height = max(1, self.winfo_height())
        thumb = max(24, visible*height)
        travel = max(1, height-thumb)
        if self.command:
            self.command('moveto', max(0, min(travel, event.y-thumb/2))/travel*(1-visible))

    def wheel(self, event):
        if self.command:
            self.command('scroll', -3 if event.delta > 0 else 3, 'units')
        return 'break'
