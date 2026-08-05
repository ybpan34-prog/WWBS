from __future__ import annotations

import ctypes
import os
import time
from ctypes import wintypes
from pathlib import Path

from PIL import ImageGrab


user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

SW_RESTORE = 9
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_VIRTUALDESK = 0x4000
INPUT_MOUSE = 0
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202


def _enable_dpi_awareness() -> None:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass


_enable_dpi_awareness()


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class INPUT_UNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("union", INPUT_UNION)]


class ClientWindowController:
    def __init__(self, title_keyword: str = "鸣潮", base_size: tuple[int, int] | None = None):
        self.title_keyword = title_keyword.strip() or "鸣潮"
        self.base_size = base_size
        self.hwnd = 0
        self.scale = 1.0
        self.last_capture_size: tuple[int, int] | None = None
        self.last_screen_bbox: tuple[int, int, int, int] | None = None

    def connect(self) -> str:
        self.hwnd = self._find_window()
        title = self._window_title(self.hwnd)
        width, height = self.client_size()
        size_text = f"{width}x{height}"
        if self.base_size:
            base_width, base_height = self.base_size
            width_scale = width / base_width
            height_scale = height / base_height
            if abs(width_scale - height_scale) > 0.03:
                base = f"{base_width}x{base_height}"
                raise RuntimeError(f"已找到窗口：{title}，但当前 {size_text} 不是 {base} 的等比例缩放。")
            self.scale = (width_scale + height_scale) / 2
            base = f"{base_width}x{base_height}"
            return f"已找到窗口：{title}，当前 {size_text}，按 {base} 的 {self.scale:.3f} 倍识别"
        self.scale = 1.0
        return f"已找到窗口：{title}，分辨率 {size_text}"

    def template_scales(self) -> list[float]:
        return [self.scale, self.scale * 0.97, self.scale * 1.03, self.scale * 0.94, self.scale * 1.06]

    def screencap(self, target: Path, bring_to_front: bool = False) -> None:
        self._ensure_window()
        if bring_to_front:
            user32.ShowWindow(self.hwnd, SW_RESTORE)
            user32.SetForegroundWindow(self.hwnd)
            time.sleep(0.18)
        bbox = self._client_bbox()
        self.last_screen_bbox = bbox
        image = ImageGrab.grab(bbox=bbox, all_screens=True)
        self.last_capture_size = image.size
        image.save(target)

    def tap(self, x: int, y: int) -> dict[str, tuple[int, int] | bool]:
        self._ensure_window()
        client_x, client_y = self.screenshot_to_client(x, y)
        screen_x, screen_y = self._screenshot_point_to_desktop(x, y)
        screen_x, screen_y = self._clamp_to_virtual_screen(screen_x, screen_y)
        before = self.cursor_position()
        self._focus_window()
        moved, input_x, input_y, move_method = self._set_cursor_with_dpi_fallback(screen_x, screen_y)
        time.sleep(0.08)
        after_move = self.cursor_position()
        self._send_mouse_button(MOUSEEVENTF_LEFTDOWN)
        time.sleep(0.08)
        self._send_mouse_button(MOUSEEVENTF_LEFTUP)
        time.sleep(0.03)
        user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        time.sleep(0.05)
        user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
        self._post_client_click(x, y)
        after_click = self.cursor_position()
        return {
            "target": (screen_x, screen_y),
            "input": (input_x, input_y),
            "method": move_method,
            "client": (client_x, client_y),
            "capture": self.last_capture_size or (-1, -1),
            "bbox": self.last_screen_bbox or (-1, -1, -1, -1),
            "before": before,
            "after_move": after_move,
            "after_click": after_click,
            "set_cursor_ok": moved,
        }

    def screenshot_to_client(self, x: int, y: int) -> tuple[int, int]:
        if not self.last_capture_size:
            return x, y
        capture_width, capture_height = self.last_capture_size
        client_width, client_height = self.client_size()
        if capture_width <= 0 or capture_height <= 0:
            return x, y
        mapped_x = int(round(x * client_width / capture_width))
        mapped_y = int(round(y * client_height / capture_height))
        return mapped_x, mapped_y

    def screenshot_to_screen(self, x: int, y: int) -> tuple[int, int]:
        if not self.last_capture_size or not self.last_screen_bbox:
            return self._client_to_screen(x, y)
        capture_width, capture_height = self.last_capture_size
        left, top, right, bottom = self.last_screen_bbox
        screen_width = right - left
        screen_height = bottom - top
        if capture_width <= 0 or capture_height <= 0:
            return self._client_to_screen(x, y)
        return (
            int(round(left + x * screen_width / capture_width)),
            int(round(top + y * screen_height / capture_height)),
        )

    def _screenshot_point_to_desktop(self, x: int, y: int) -> tuple[int, int]:
        if self.last_screen_bbox and self.last_capture_size:
            left, top, right, bottom = self.last_screen_bbox
            capture_width, capture_height = self.last_capture_size
            if capture_width > 0 and capture_height > 0:
                return (
                    int(round(left + x * (right - left) / capture_width)),
                    int(round(top + y * (bottom - top) / capture_height)),
                )
        if self.base_size:
            client_width, client_height = self.client_size()
            base_width, base_height = self.base_size
            return self._client_to_screen(
                int(round(x * client_width / base_width)),
                int(round(y * client_height / base_height)),
            )
        return self._client_to_screen(x, y)

    def swipe(self, x: int, y: int, x2: int, y2: int, duration_ms: int) -> None:
        self._ensure_window()
        sx, sy = self._client_to_screen(x, y)
        ex, ey = self._client_to_screen(x2, y2)
        user32.ShowWindow(self.hwnd, SW_RESTORE)
        user32.SetForegroundWindow(self.hwnd)
        user32.SetCursorPos(sx, sy)
        user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        steps = max(4, int(duration_ms / 30))
        for index in range(1, steps + 1):
            t = index / steps
            user32.SetCursorPos(int(sx + (ex - sx) * t), int(sy + (ey - sy) * t))
            time.sleep(duration_ms / steps / 1000)
        user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)

    def text(self, value: str) -> None:
        raise RuntimeError("PC 客户端模式暂不支持自动输入文字。")

    def client_size(self) -> tuple[int, int]:
        self._ensure_window()
        rect = RECT()
        if not user32.GetClientRect(self.hwnd, ctypes.byref(rect)):
            raise RuntimeError("无法读取窗口分辨率。")
        return rect.right - rect.left, rect.bottom - rect.top

    def _ensure_window(self) -> None:
        if self.hwnd and user32.IsWindow(self.hwnd):
            return
        self.hwnd = self._find_window()

    def _find_window(self) -> int:
        exact_matches: list[int] = []
        partial_matches: list[int] = []
        current_pid = os.getpid()

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def enum_proc(hwnd, _lparam):
            if user32.IsWindowVisible(hwnd):
                pid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                if pid.value == current_pid:
                    return True
                title = self._window_title(hwnd)
                if not title:
                    return True
                if title == self.title_keyword:
                    exact_matches.append(hwnd)
                elif self.title_keyword.lower() in title.lower():
                    partial_matches.append(hwnd)
            return True

        user32.EnumWindows(enum_proc, 0)
        matches = exact_matches or partial_matches
        if not matches:
            raise RuntimeError(f"没有找到标题包含“{self.title_keyword}”的窗口。请先打开 PC 客户端。")
        return matches[0]

    @staticmethod
    def _window_title(hwnd: int) -> str:
        length = user32.GetWindowTextLengthW(hwnd)
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        return buffer.value

    def _client_bbox(self) -> tuple[int, int, int, int]:
        width, height = self.client_size()
        left_top = self._client_to_screen(0, 0)
        return (left_top[0], left_top[1], left_top[0] + width, left_top[1] + height)

    def _client_to_screen(self, x: int, y: int) -> tuple[int, int]:
        point = POINT(int(x), int(y))
        if not user32.ClientToScreen(self.hwnd, ctypes.byref(point)):
            raise RuntimeError("窗口坐标转换失败。")
        return point.x, point.y

    def _click_to_screen(self, x: int, y: int) -> tuple[int, int]:
        if self.last_capture_size and self.last_screen_bbox:
            return self.screenshot_to_screen(x, y)
        return self._client_to_screen(x, y)

    @staticmethod
    def _clamp_to_virtual_screen(x: int, y: int) -> tuple[int, int]:
        left = user32.GetSystemMetrics(76)
        top = user32.GetSystemMetrics(77)
        width = user32.GetSystemMetrics(78)
        height = user32.GetSystemMetrics(79)
        if width <= 0 or height <= 0:
            return x, y
        return (
            max(left, min(x, left + width - 1)),
            max(top, min(y, top + height - 1)),
        )

    def _set_cursor_with_dpi_fallback(self, x: int, y: int) -> tuple[bool, int, int, str]:
        candidates = [(x, y)]
        scale = self._dpi_scale()
        if scale and abs(scale - 1.0) > 0.01:
            candidates.append((int(round(x / scale)), int(round(y / scale))))
        if self.last_screen_bbox:
            left, top, _right, _bottom = self.last_screen_bbox
            if scale and abs(scale - 1.0) > 0.01:
                candidates.append((int(round(left / scale + (x - left) / scale)), int(round(top / scale + (y - top) / scale))))

        seen: set[tuple[int, int]] = set()
        for candidate_x, candidate_y in candidates:
            point = (candidate_x, candidate_y)
            if point in seen:
                continue
            seen.add(point)
            if self._send_absolute_move(candidate_x, candidate_y):
                return True, candidate_x, candidate_y, "SendInputAbsolute"
            try:
                if user32.SetPhysicalCursorPos(candidate_x, candidate_y):
                    return True, candidate_x, candidate_y, "SetPhysicalCursorPos"
            except Exception:
                pass
            if user32.SetCursorPos(candidate_x, candidate_y):
                return True, candidate_x, candidate_y, "SetCursorPos"
        return False, x, y, "failed"

    def _send_absolute_move(self, x: int, y: int) -> bool:
        left = user32.GetSystemMetrics(76)
        top = user32.GetSystemMetrics(77)
        width = user32.GetSystemMetrics(78)
        height = user32.GetSystemMetrics(79)
        if width <= 1 or height <= 1:
            return False
        absolute_x = int(round((x - left) * 65535 / (width - 1)))
        absolute_y = int(round((y - top) * 65535 / (height - 1)))
        move = INPUT(
            type=INPUT_MOUSE,
            union=INPUT_UNION(
                mi=MOUSEINPUT(
                    absolute_x,
                    absolute_y,
                    0,
                    MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK,
                    0,
                    0,
                )
            ),
        )
        sent = user32.SendInput(1, ctypes.byref(move), ctypes.sizeof(move))
        time.sleep(0.05)
        current = self.cursor_position()
        return sent == 1 and abs(current[0] - x) <= 2 and abs(current[1] - y) <= 2

    def _dpi_scale(self) -> float:
        try:
            dpi = user32.GetDpiForWindow(self.hwnd)
            if dpi:
                return dpi / 96.0
        except Exception:
            pass
        return 1.0

    @staticmethod
    def cursor_position() -> tuple[int, int]:
        point = POINT()
        if not user32.GetCursorPos(ctypes.byref(point)):
            return (-1, -1)
        return point.x, point.y

    def _focus_window(self) -> None:
        user32.ShowWindow(self.hwnd, SW_RESTORE)
        foreground = user32.GetForegroundWindow()
        current_thread = kernel32.GetCurrentThreadId()
        target_thread = user32.GetWindowThreadProcessId(self.hwnd, None)
        foreground_thread = user32.GetWindowThreadProcessId(foreground, None) if foreground else 0
        if foreground_thread:
            user32.AttachThreadInput(current_thread, foreground_thread, True)
        if target_thread:
            user32.AttachThreadInput(current_thread, target_thread, True)
        try:
            user32.BringWindowToTop(self.hwnd)
            user32.SetActiveWindow(self.hwnd)
            user32.SetForegroundWindow(self.hwnd)
            time.sleep(0.25)
        finally:
            if target_thread:
                user32.AttachThreadInput(current_thread, target_thread, False)
            if foreground_thread:
                user32.AttachThreadInput(current_thread, foreground_thread, False)

    @staticmethod
    def _send_mouse_button(flag: int) -> None:
        event = INPUT(type=INPUT_MOUSE, union=INPUT_UNION(mi=MOUSEINPUT(0, 0, 0, flag, 0, 0)))
        sent = user32.SendInput(1, ctypes.byref(event), ctypes.sizeof(event))
        if sent != 1:
            raise RuntimeError("鼠标点击发送失败。")

    def _post_client_click(self, x: int, y: int) -> None:
        lparam = (int(y) << 16) | (int(x) & 0xFFFF)
        user32.PostMessageW(self.hwnd, WM_LBUTTONDOWN, 1, lparam)
        user32.PostMessageW(self.hwnd, WM_LBUTTONUP, 0, lparam)
