"""Shared rounded controls for WWBS pages and application dialogs."""
import tkinter as tk
import ctypes
from ctypes import wintypes
import re
from tkinter import font as tkfont
from functools import lru_cache
from math import cos, sin, pi


def work_area(owner):
    try:
        class MonitorInfo(ctypes.Structure):
            _fields_ = [('size', wintypes.DWORD), ('monitor', wintypes.RECT),
                        ('work', wintypes.RECT), ('flags', wintypes.DWORD)]
        user32 = ctypes.windll.user32
        user32.MonitorFromWindow.restype = wintypes.HANDLE
        user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
        monitor = user32.MonitorFromWindow(owner.winfo_id(), 2)
        info = MonitorInfo()
        info.size = ctypes.sizeof(info)
        if user32.GetMonitorInfoW(ctypes.c_void_p(monitor), ctypes.byref(info)):
            return info.work.left, info.work.top, info.work.right, info.work.bottom
    except (AttributeError, OSError, TypeError):
        pass
    return (owner.winfo_vrootx(), owner.winfo_vrooty(),
            owner.winfo_vrootx()+owner.winfo_vrootwidth(),
            owner.winfo_vrooty()+owner.winfo_vrootheight()-40)


class CenteredToplevel(tk.Toplevel):
    """Center application dialogs before their first visible frame."""
    def __init__(self, master=None, **options):
        self._requested_size = None
        super().__init__(master, **options)
        self.withdraw()
        self.after_idle(self._center_first_frame)

    def geometry(self, value=None):
        if value and (match := re.match(r'(\d+)x(\d+)', value)):
            self._requested_size = tuple(map(int, match.groups()))
        return super().geometry(value)

    wm_geometry = geometry

    def _center_first_frame(self):
        try:
            if not self.winfo_exists():
                return
            if getattr(self, '_centered_by_app', False):
                return
            if self.overrideredirect():  # Drag cards follow the pointer.
                self.deiconify()
                return
            # Packer requests are queued after construction of this window.
            # Resolve them before measuring, while it is still withdrawn.
            self.update_idletasks()
            if not self.winfo_exists():
                return
            owner = self.master.winfo_toplevel()
            self.transient(owner)
            left, top, right, bottom = work_area(owner)
            decoration = max(32, owner.winfo_rooty()-owner.winfo_y())
            requested = self._requested_size or (self.winfo_reqwidth(), self.winfo_reqheight())
            width, height = max(requested[0], self.winfo_reqwidth()), max(requested[1], self.winfo_reqheight())
            maximum_width, maximum_height = max(1, right-left-32), max(1, bottom-top-decoration-32)
            minimum_width, minimum_height = self.minsize()
            self.minsize(min(minimum_width, maximum_width), min(minimum_height, maximum_height))
            width, height = min(width, maximum_width), min(height, maximum_height)
            x = max(left+16, min(owner.winfo_x()+(owner.winfo_width()-width)//2, right-width-16))
            y = max(top+16, min(owner.winfo_y()+(owner.winfo_height()-height)//2, bottom-height-decoration-16))
            super().geometry(f'{width}x{height}{x:+d}{y:+d}')
            self.deiconify()
        except tk.TclError:
            pass


class ParentDialogs:
    """Supply the main window as the owner of otherwise unparented native dialogs."""
    def __init__(self, module):
        self.module = module

    def __getattr__(self, name):
        value = getattr(self.module, name)
        if not callable(value) or not name.startswith(('ask', 'show')):
            return value
        def invoke(*args, **options):
            owner = tk._default_root
            if owner is not None and 'parent' not in options:
                options['parent'] = owner
            return value(*args, **options)
        return invoke


def _redraw_native_window(root):
    """Invalidate the complete native window, including all Tk child surfaces."""
    try:
        user32 = ctypes.windll.user32
        user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
        user32.GetAncestor.restype = wintypes.HWND
        hwnd = user32.GetAncestor(root.winfo_id(), 2) or root.winfo_id()
        user32.RedrawWindow.argtypes = [wintypes.HWND, ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT]
        user32.RedrawWindow.restype = wintypes.BOOL
        # INVALIDATE | ERASE | ALLCHILDREN | UPDATENOW | FRAME
        return bool(user32.RedrawWindow(hwnd, None, None, 0x585))
    except (AttributeError, OSError, TypeError, tk.TclError):
        return False


class RestoreRedraw:
    """Repaint after a real minimize/restore, without rebuilding UI or task state."""
    def __init__(self, root, on_restore=lambda: None):
        self.root = root
        self.on_restore = on_restore
        self.unmapped = False
        self.generation = 0
        self.paint_count = 0
        root.bind('<Unmap>', self._unmap, add='+')
        root.bind('<Map>', self._map, add='+')

    def _unmap(self, event):
        if event.widget is self.root:
            self.generation += 1
            self.unmapped = bool(getattr(self.root, '_main_frame_ready', False))

    def _map(self, event):
        if event.widget is not self.root or not self.unmapped:
            return
        self.unmapped = False
        generation = self.generation
        self.root.after_idle(lambda: self._paint(generation))
        self.root.after(140, lambda: self._paint(generation))

    def _paint(self, generation):
        try:
            if generation != self.generation or not self.root.winfo_exists() or not self.root.winfo_ismapped():
                return
            if self.root.state() in ('iconic', 'withdrawn'):
                return
            # Tk's retained Canvas content and PhotoImages stay intact. Ask Tk
            # and Win32 to expose every visible child instead of reloading tabs.
            pending = [self.root]
            while pending:
                widget = pending.pop()
                if widget.winfo_ismapped():
                    widget.event_generate('<Expose>', when='tail')
                    pending.extend(widget.winfo_children())
            self.root.update_idletasks()
            _redraw_native_window(self.root)
            try:
                self.on_restore()
            except (tk.TclError, OSError):
                pass  # A preview file may be getting replaced by the worker.
            self.paint_count += 1
        except tk.TclError:
            return


def show_ready_main_window(root, on_ready=lambda: None, on_restore=lambda: None):
    """Finish layout and paint while invisible, then expose the first complete frame."""
    root.update_idletasks()
    if not hasattr(root, '_restore_redraw'):
        root._restore_redraw = RestoreRedraw(root, on_restore)
    root.attributes('-alpha', 0.0)
    root.deiconify()
    # Mapping delivers native Map/Expose events as well as Tk idle redraws.
    # Idle-only flushing leaves child controls unpainted on Windows.
    root.update()
    root.update_idletasks()

    def reveal():
        root.attributes('-alpha', 1.0)
        root._main_frame_ready = True
        on_ready()
    root.after(40, reveal)


@lru_cache(maxsize=64)
def _round_arc(radius):
    return tuple((radius*cos(i*pi/16), radius*sin(i*pi/16)) for i in range(9))


def paint_round(canvas, x0, y0, x1, y1, radius, color):
    # Coordinates are half-open like a widget's width/height. Polygon fills
    # include their right/bottom boundary, so keep it inside the final pixel;
    # otherwise the inner fill covers the outer border on those two sides.
    x1, y1 = max(x0, x1-1), max(y0, y1-1)
    radius = min(radius, max(0, (x1-x0)/2), max(0, (y1-y0)/2))
    # One closed surface avoids seams where stroked rectangles and circles used
    # to overlap, especially along the one-pixel right/bottom border.
    # Sample real circular arcs with the original radius. Tk's smoothed polygon
    # shrinks the effective corner radius and makes these controls look square.
    points = []
    arc = _round_arc(radius)
    for cx, cy, sx, sy in ((x1-radius, y0+radius, 1, -1),
                          (x1-radius, y1-radius, 1, 1),
                          (x0+radius, y1-radius, -1, 1),
                          (x0+radius, y0+radius, -1, -1)):
        quadrant = reversed(arc) if sx*sy < 0 else arc
        for dx, dy in quadrant:
            points.extend((cx+sx*dx, cy+sy*dy))
    return canvas.create_polygon(*points, fill=color, outline='', tags='shape')


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
