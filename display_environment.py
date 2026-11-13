"""Read the game's display colour mode; never change system display settings.

Layouts follow Microsoft's wingdi.h. INFO_2 distinguishes HDR from WCG;
the legacy Advanced Color flag alone must not be reported as definite HDR.
"""
import ctypes as c
import os
from dataclasses import dataclass


FILTER_GUIDANCE = '检测范围仅包括系统 HDR 状态。游戏内滤镜及第三方滤镜的开启状态未检测。'
HDR_GUIDANCE = '如遇识别失败，可在 Windows 设置 → 系统 → 显示 → HDR 中关闭该屏幕的“使用 HDR”后重试。'
U32 = c.c_uint32
I32 = c.c_int32


class Luid(c.Structure):
    _fields_ = [('low', U32), ('high', I32)]


class Header(c.Structure):
    _fields_ = [('type', U32), ('size', U32), ('adapter', Luid), ('id', U32)]


class Source(c.Structure):
    _fields_ = [('adapter', Luid), ('id', U32), ('mode', U32), ('status', U32)]


class Target(c.Structure):
    _fields_ = [('adapter', Luid), ('id', U32), ('mode', U32), ('technology', U32),
                ('rotation', U32), ('scaling', U32), ('numerator', U32),
                ('denominator', U32), ('ordering', U32), ('available', I32), ('status', U32)]


class DisplayPath(c.Structure):
    _fields_ = [('source', Source), ('target', Target), ('flags', U32)]


class Mode(c.Structure):
    _fields_ = [('type', U32), ('id', U32), ('adapter', Luid), ('payload', c.c_uint64 * 6)]


class SourceName(c.Structure):
    _fields_ = [('header', Header), ('name', c.c_wchar * 32)]


class ColorInfo(c.Structure):
    _fields_ = [('header', Header), ('flags', U32), ('encoding', U32), ('bits', U32)]


class ColorInfo2(c.Structure):
    _fields_ = ColorInfo._fields_ + [('active_mode', U32)]


class Rect(c.Structure):
    _fields_ = [('left', I32), ('top', I32), ('right', I32), ('bottom', I32)]


class MonitorInfo(c.Structure):
    _fields_ = [('size', U32), ('monitor', Rect), ('work', Rect), ('flags', U32),
                ('device', c.c_wchar * 32)]


@dataclass(frozen=True)
class DisplayState:
    device: str
    mode: str  # hdr / sdr / wcg / advanced / unknown
    detail: str = ''


def interpret_color(device, info, *, modern):
    if modern:
        mode = {0: 'sdr', 1: 'wcg', 2: 'hdr'}.get(info.active_mode, 'unknown')
    else:
        mode = 'advanced' if info.flags & 2 else 'sdr'
    return DisplayState(device, mode)


def display_findings(states):
    """Input is restricted to targets on the game's monitor (including clones)."""
    findings = []
    if not states:
        findings.append(('info', '未能读取游戏所在屏幕的系统 HDR 状态。'))
    for state in states:
        if state.mode == 'hdr':
            findings.append(('warning', f'已确认游戏所在屏幕 {state.device} 启用了系统 HDR。'+HDR_GUIDANCE))
        elif state.mode == 'advanced':
            findings.append(('info', f'{state.device} 已启用高级颜色，具体模式为 HDR 还是广色域尚无法确认。'))
        elif state.mode == 'unknown':
            findings.append(('info', f'无法确认 {state.device} 的系统 HDR 状态。{state.detail}'))
        else:
            mode = '广色域 WCG' if state.mode == 'wcg' else 'SDR'
            findings.append(('ok', f'游戏所在屏幕 {state.device} 当前为{mode}，未启用系统 HDR。'))
    findings.append(('info', FILTER_GUIDANCE))
    return findings


class WindowsDisplayReader:
    def __init__(self):
        self.api = c.WinDLL('user32', use_last_error=True)
        self.api.MonitorFromWindow.argtypes = [c.c_void_p, U32]
        self.api.MonitorFromWindow.restype = c.c_void_p
        self.api.GetMonitorInfoW.argtypes = [c.c_void_p, c.POINTER(MonitorInfo)]
        self.api.GetMonitorInfoW.restype = I32
        self.api.GetDisplayConfigBufferSizes.argtypes = [U32, c.POINTER(U32), c.POINTER(U32)]
        self.api.GetDisplayConfigBufferSizes.restype = I32
        self.api.QueryDisplayConfig.argtypes = [U32, c.POINTER(U32), c.POINTER(DisplayPath),
                                               c.POINTER(U32), c.POINTER(Mode), c.c_void_p]
        self.api.QueryDisplayConfig.restype = I32
        self.api.DisplayConfigGetDeviceInfo.argtypes = [c.POINTER(Header)]
        self.api.DisplayConfigGetDeviceInfo.restype = I32

    def game_device(self, hwnd):
        monitor = self.api.MonitorFromWindow(hwnd, 2)
        info = MonitorInfo(size=c.sizeof(MonitorInfo))
        if not monitor or not self.api.GetMonitorInfoW(monitor, c.byref(info)):
            raise OSError('无法定位游戏所在显示器')
        return info.device

    def paths(self):
        for _ in range(3):
            path_count, mode_count = U32(), U32()
            result = self.api.GetDisplayConfigBufferSizes(2, c.byref(path_count), c.byref(mode_count))
            if result == 122:
                continue
            if result:
                raise OSError(f'读取显示配置大小失败（{result}）')
            paths, modes = (DisplayPath * path_count.value)(), (Mode * mode_count.value)()
            result = self.api.QueryDisplayConfig(2, c.byref(path_count), paths, c.byref(mode_count), modes, None)
            if result == 122:
                continue
            if result:
                raise OSError(f'读取显示配置失败（{result}）')
            return list(paths[:path_count.value])
        raise OSError('显示器配置正在变化，请重试')

    def get_info(self, info, kind, endpoint):
        info.header = Header(kind, c.sizeof(info), endpoint.adapter, endpoint.id)
        return self.api.DisplayConfigGetDeviceInfo(c.byref(info.header))

    def source_name(self, path):
        name = SourceName()
        if self.get_info(name, 1, path.source):
            return None
        return name.name

    def color(self, path, device):
        modern = ColorInfo2()
        if not self.get_info(modern, 15, path.target):
            return interpret_color(device, modern, modern=True)
        legacy = ColorInfo()
        if not self.get_info(legacy, 9, path.target):
            return interpret_color(device, legacy, modern=False)
        return DisplayState(device, 'unknown', '系统显示接口不支持读取此状态。')


def read_game_display(hwnd, *, reader=None):
    try:
        if not isinstance(hwnd, int) or not hwnd:
            return ()
        if reader is None:
            if os.name != 'nt':
                return ()
            reader = WindowsDisplayReader()
        device = reader.game_device(hwnd)
        states = [reader.color(path, device) for path in reader.paths()
                  if (reader.source_name(path) or '').casefold() == device.casefold()]
        return tuple(states) or (DisplayState(device, 'unknown', '未找到对应的活动显示路径。'),)
    except (OSError, AttributeError, ValueError, TypeError) as exc:
        return (DisplayState('游戏显示器', 'unknown', str(exc)),)
