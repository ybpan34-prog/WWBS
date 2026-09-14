import json
import ctypes
from ctypes import wintypes
import io
import os
import queue
import random
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import webbrowser
import zipfile
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tkinter import BOTH, END, LEFT, RIGHT, TOP, X, BooleanVar, Button, Canvas, Checkbutton, Entry, Frame, Label, Listbox, StringVar, Text, Tk, Toplevel, filedialog, messagebox, simpledialog, ttk

from PIL import Image, ImageDraw, ImageTk
import numpy as np

from image_matcher import TemplateMatcher
from windows_client import ClientWindowController
from desktop_pet import DesktopPet
from daniya_persona import event_line as daniya_event_line, idle_line as daniya_idle_line
from aemeath_persona import (
    event_line as aemeath_event_line,
    idle_dialogue as aemeath_idle_dialogue,
    record_departure as record_aemeath_departure,
    welcome_dialogue as aemeath_welcome_dialogue,
)
from jingran_persona import event_line as jingran_event_line, idle_line as jingran_idle_line


APP_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG = APP_DIR / "weekly_tasks.json"
TEMPLATES_DIR = APP_DIR / "templates"
DEFAULT_GROUP_KEY = "default"
DEFAULT_GROUP_NAME = "幻梦游园"
APP_ICON = APP_DIR / "wwbs.ico"
APP_VERSION = "1.4.7"
RUN_NOTICE_DIR = APP_DIR / "assets" / "run-notice"
RUN_NOTICES = {
    "daily": (
        "一键日常启动页面",
        RUN_NOTICE_DIR / "daily-start.jpg",
    ),
    "weekly": (
        "一键周常启动页面",
        RUN_NOTICE_DIR / "weekly-start.jpg",
    ),
    "combat_4c": (
        "4C刷取启动页面",
        RUN_NOTICE_DIR / "combat-4c-start.jpg",
    ),
}


def is_running_as_admin() -> bool:
    """Return whether the current Windows process is elevated."""
    if os.name != "nt":
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def apply_windows_taskbar_icon(window, icon_path: Path) -> bool:
    """Apply an .ico to the real top-level HWND used by the Windows taskbar."""
    if os.name != "nt" or not icon_path.exists():
        return False
    try:
        window.update_idletasks()
        child_hwnd = int(window.winfo_id())
        parent_hwnd = int(ctypes.windll.user32.GetParent(child_hwnd))
        hwnd = parent_hwnd or child_hwnd
        image_icon = 1
        load_from_file = 0x0010
        wm_seticon = 0x0080
        handles = []
        for size, slot in ((16, 0), (32, 1)):
            handle = ctypes.windll.user32.LoadImageW(
                None,
                str(icon_path),
                image_icon,
                size,
                size,
                load_from_file,
            )
            if handle:
                ctypes.windll.user32.SendMessageW(hwnd, wm_seticon, slot, handle)
                handles.append(handle)
        if handles:
            # Windows needs these handles to remain alive for the lifetime of the window.
            window._wwbs_native_icon_handles = handles
            return True
    except Exception:
        pass
    return False
THEME_CONFIG = APP_DIR / "theme-settings.json"
PET_CONFIG = APP_DIR / "pet-settings.json"
PET_DISPLAY_CONFIG = APP_DIR / "pet-display-settings.json"
COMBAT_CONFIG = APP_DIR / "combat-settings.json"
DAILY_CONFIG = APP_DIR / "daily-settings.json"
DANIYA_THEME_PACK = APP_DIR / "optional-themes" / "daniya-theme.wwbstheme"
AEMEATH_THEME_PACK = APP_DIR / "optional-themes" / "aemeath-theme.wwbstheme"
JINGRAN_THEME_PACK = APP_DIR / "optional-themes" / "jingran-theme.wwbstheme"
UPDATE_API_URL = "https://api.github.com/repos/ybpan34-prog/WWBS/releases/latest"
UPDATE_ASSET_NAME = "wwbs-exe.zip"
ABOUT_BILIBILI_URL = "https://www.bilibili.com/video/BV1aPuo6uE9r/"
ABOUT_GITHUB_URL = "https://github.com/ybpan34-prog/WWBS"
UPDATE_NOTICE = """v1.3.5 更新内容
1. 新增循环点击回退验证，下一张模板多次未出现时会检查上一张是否仍在画面。
2. 若上一张仍存在，程序会自动补点；最后一轮也会确认末模板消失后再停止。
3. 回退验证最多执行 2 次，累计 5 次仍未找到下一张时自动停止。
4. 保留原有循环次数、随机点击和随机间隔逻辑。

使用前请确认
1. 请以管理员身份运行。
2. 请将游戏窗口调整为 1920*1080p 或等比例缩放。
3. 请先完成周本的新手教程，并将速度调整至 MAX。"""
UPDATE_HISTORY = [
    (
        "v1.4.7",
        """v1.4.7 更新内容
- 4C刷取次数调整为10次和30次。
- 桌宠隐藏状态会自动保存并在下次启动时恢复，自动任务反馈不再强制显示桌宠。
- 日常战斗新增奖励光球/领取提示结束判定，修复目标文字残留时一直攻击的问题；三号位回血也不再阻塞收尾。
- 大招改为每5秒检查右下角状态，只在彩色完整亮环就绪时施放；灰蓝完整圈、暗圈、残缺圈和倒计时均不会触发。
""",
    ),
    (
        "v1.4.6",
        """v1.4.6 更新内容
- 新增景燃深色青金主题，使用专属头图与角色台词。
- 新增景燃Q版桌宠及完整基础动作；空闲动作随机轮播并支持16向视线。
- 景燃桌宠支持一键日常、周常拿满奖励、周常拿满星声、4C刷取与运行诊断。
- 原版简约主题保持默认，选择桌宠不再连带修改程序主题。
""",
    ),
    (
        "v1.4.5",
        """v1.4.5 更新内容
- 任务执行报错且检测到程序未使用管理员权限时，自动请求管理员权限并重启。
- 修复部分 Windows 环境中底部任务栏仍显示 Tk 羽毛图标的问题。
- 4C刷取按钮固定使用内置4C模板，不再需要手动切换模板组。
- 日常奖励光球最低置信度由0.25提高到0.65，减少误判。
- 周本祝福只以“＋ / 选择祝福”判断空槽；任意已装备祝福均可直接开始，不再要求第一个祝福。
""",
    ),
    (
        "v1.4.4",
        """v1.4.4 更新内容
- 活跃度已满时跳过无音区，但仍会继续检查并执行尚未完成的周度游历。
- 修复“＋ / 选择祝福”空槽被误判为已有技能的问题，单独周常与日常衔接周常均生效。
""",
    ),
    (
        "v1.4.3",
        """v1.4.3 更新内容
- 一键日常完成领奖后会检查周度游历，未完成时自动进入幻梦游园并执行15轮周常。
- 一键日常、一键周常和4C刷取按钮旁新增圆圈问号，可查看16:9启动页面示例。
- 修复桌宠及底部任务栏图标显示异常。
""",
    ),
    (
        "v1.4.2",
        """v1.4.2 更新内容
1. 修复第二轮挑战结束后点击“退出副本”，卡在“确认离开”二次提示的问题。
2. 程序会验证中央白色弹窗与左右两个黑色按钮同时存在，再点击右侧“确认”。
3. 未出现二次提示时不会盲点固定坐标，会继续按原流程等待返回大世界。
4. 修复补充体力界面加载稍慢时未识别绿色结晶单质为0、没有及时切换黄色结晶溶剂的问题。
5. 进入补充界面后会多帧确认资源数量；绿色为0或确认后仍停留在补充界面时立即改用黄色，仍绝不选择星声。""",
    ),
    (
        "v1.4.1",
        """v1.4.1 更新内容
1. 修复日常战斗结束后镜头过低、水平转向仍找不到奖励光球的问题。
2. 奖励搜索改为分层扫描：先保持当前高度寻找，连续未找到才逐级抬高，最后恢复初始高度，避免正常视角被抬得过高。
3. 设置页新增“日常战斗回血”，默认关闭；开启后定时切换三号位执行回血连段，并自动切回一号位继续战斗。
4. 日常回血会暂停一号位持续普攻，连段完成后再恢复，避免角色切换期间产生误操作。""",
    ),
    (
        "v1.4.0",
        """v1.4.0 更新内容
1. “一键日常”转为正式功能：滑动选择指定无音区，自动完成两轮挑战与双倍领取。
2. 体力不足时仅按顺序使用结晶单质、结晶溶剂；绿色资源为0或补充后仍不足时自动改用溶剂，绝不消耗星声。
3. 优化无音区列表滚动、进入战斗后一号位确认、战斗结束复核、奖励光球搜索与靠近逻辑。
4. 奖励光球最低置信度提高至0.65；靠近后置信度未提升会立即转向重新寻找。
5. 自动领取活跃度100宝箱及先约电台免费奖励，并完善大世界、终端与页面切换确认。
6. 优化日常流程的界面识别区域与轮询速度，识别成功后立即执行下一步，同时保留加载超时保护。
7. 改进4C声骸搜索与吸收验证，排除广告牌等相似目标，并在目标停滞时主动换向。
8. 修复角色开大时误判战斗结束，以及全局 Ctrl + Alt + S 停止快捷键失效的问题。
9. 桌宠可直接启动周常拿满奖励、周常拿满星声和一键日常。""",
    ),
    (
        "v1.3.9",
        """v1.3.9 更新内容
1. 新增“群声共振模拟域”实验任务与独立模板组。
2. 用户自行选择关卡后，程序从场景选择页点击“开始模拟”。
3. 进入场景后，在固定镜头下识别蓝色守岸人，并用 W/A/S/D 短按逐步靠近。
4. 出现“F / 守岸人”提示后立即释放方向键并按 F 交互。
5. 新增独立“4C刷取”：一号位以0.15秒固定节奏持续普攻，每10秒技能并额外每20秒按Q；每9秒切三号位执行回血连段。
6. 战斗中每2秒无打断检查首领名字和血条；疑似消失时暂停攻击并快速复核3次，确认击败后才进入吸收流程。
7. 提供5次和10次两个循环档位；4C技能键和大招键支持键盘单键、鼠标侧键1或鼠标侧键2。
8. 修复模板组只切换图片却没有切换任务的问题；幻梦游园与群声现在会同步启用和停用。
9. 加入失焦、连续识别失败、超时与全局停止保护；吸收阶段会核验“吸收”文字，不再把“领取奖励”误判为吸收。
10. 桌宠支持多档大小调整，选择后立即生效并自动保存。
11. 重制多尺寸高清程序图标，改善任务栏小图标的清晰度。""",
    ),
    (
        "v1.3.8",
        """v1.3.8 更新内容
1. PC 窗口标题默认改为“自动”，同时识别国服“鸣潮”和国际服 Steam 版“Wuthering Waves”。
2. 修复误选 199x34 等同名启动器或辅助小窗口的问题，优先选择真实 Unreal 游戏窗口。
3. 修复任务识别阶段把模板缩放固定为 1.0、导致实际上只有 1920x1080 可用的问题。
4. 模板匹配改用更耐缩放的灰度抗锯齿识别，保持原阈值，减少缩放后的漏识别与误点风险。
5. 已验证 1920x1080、1600x900、1536x864 和 1280x720 等 16:9 分辨率。""",
    ),
    (
        "v1.3.7",
        """v1.3.7 更新内容
1. 新增第二款桌宠“爱弥斯”及专属动画、气泡语言、主动闲聊与欢迎反馈。
2. 新增可选“爱弥斯主题”；主题与对应桌宠自动绑定，同时保留达妮娅主题和原版简约主题。
3. 达妮娅与爱弥斯会更自然地称呼用户为“漂泊者”，并保留各自独立人格。
4. 自动任务无法启动或运行失败时，桌宠会直接诊断管理员权限、窗口比例、模板与正确起始界面。
5. 优化失败反馈速度，并补充“鼠标未移动成功”等运行错误的即时可爱提醒。
6. 图像匹配改为内置 NumPy 实现，不再依赖 SciPy，避免诊断时报缺少模块。
7. 默认程序窗口调整为 1280×1280，并继续支持全局停止快捷键 Ctrl + Alt + S。""",
    ),
    (
        "v1.3.6",
        """v1.3.6 更新内容
1. 加入 Q 版桌宠“达妮娅”，支持状态动作、可爱气泡、主动闲聊和运行诊断。
2. 加入可选“达妮娅主题”，使用粉色界面与星海背景横幅。
3. 保留原版简约主题，可在“设置 → 程序主题”中随时切换。
4. 达妮娅主题以独立压缩包保存，程序直接读取，额外占用约 49 KB。
5. 新增全局停止快捷键 Ctrl + Alt + S，焦点在游戏窗口时也能请求停止任务。
6. 桌宠触发自动任务时不再显示重复的开始确认窗口。""",
    ),
    ("v1.3.5", UPDATE_NOTICE.split("\n使用前请确认", 1)[0]),
    (
        "v1.3.4",
        """v1.3.4 更新内容
1. 恢复更新公告记录中的 v1.3.1。
2. 更新公告历史改为按版本追加，旧公告不再被覆盖。
3. 新增“关于”功能，可查看版本号并跳转至作者的 B 站视频和 GitHub 仓库。
4. 保留随机点击、随机间隔和稳定游戏截图逻辑。""",
    ),
    (
        "v1.3.3",
        """v1.3.3 更新内容
1. 图像识别点击会在模板方框内部随机选择安全落点。
2. 保留每个模板原有的点击偏移，并避开方框边缘。
3. 每次点击后的间隔会在原固定值上下 0.2 秒内随机。
4. 保留 v1.3.2 的稳定游戏截图与坐标映射逻辑。""",
    ),
    (
        "v1.3.2",
        """v1.3.2 更新内容
1. PC 客户端优先使用不受其他窗口遮挡的窗口捕获。
2. DirectX 窗口不支持离屏捕获时，自动置前游戏并截取完整客户区。
3. 检测游戏窗口、制作模板和执行识别统一使用同一套稳定截图逻辑。
4. 保留原有截图坐标到游戏客户区、屏幕坐标的映射方式。""",
    ),
    (
        "v1.3.1",
        """v1.3.1 更新内容
1. 新增抽取概率计算，可以分别填写角色水位和武器水位。
2. 新增“现在是否拥有大保底”选项，角色概率可按当前保底状态计算。
3. 优化小概率显示，不再把极低概率显示成 0.00%。
4. 保留原有自动周历、模板识别和循环点击功能。""",
    ),
]
LOCAL_TZ = timezone(timedelta(hours=8))
PREVIEW_ASPECT = 16 / 9
PREVIEW_MAX_HEIGHT = 520
PREVIEW_MIN_HEIGHT = 320
START_CONTENT_SIDE_PADDING = 28
ACTION_PANEL_WIDTH = 360
THEME_BANNER_HEIGHT = 176
STOP_HOTKEY_ID = 0xB136
STOP_HOTKEY_LABEL = "Ctrl + Alt + S"
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_NOREPEAT = 0x4000
VK_S = 0x53
VK_CONTROL = 0x11
VK_ALT = 0x12
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
CLICK_EDGE_MARGIN_RATIO = 0.10
CLICK_JITTER_RATIO = 0.25
CLICK_DELAY_JITTER_SECONDS = 0.20
CYCLE_MAX_MISSES = 5
CYCLE_FALLBACK_MISS_COUNTS = (2, 4)
DAILY_REWARD_ORB_MIN_CONFIDENCE = 0.65
CYCLE_FINAL_MAX_RETRIES = 2
DIAGNOSTIC_START_TEMPLATE = "menu1.png"
FONT_FAMILY = "Microsoft YaHei UI"
MONO_FONT = "Consolas"
SIMPLE_COLORS = {
    "app_bg": "#f5f5f7",
    "panel": "#ffffff",
    "panel_alt": "#fbfbfd",
    "line": "#d2d2d7",
    "line_soft": "#e5e5ea",
    "text": "#1d1d1f",
    "muted": "#6e6e73",
    "primary": "#007aff",
    "primary_hover": "#0a84ff",
    "danger": "#ff3b30",
    "preview": "#111318",
}
DANIYA_COLORS = {
    "app_bg": "#fff4f8",
    "panel": "#fffafd",
    "panel_alt": "#fff0f6",
    "line": "#e9b9cf",
    "line_soft": "#f3d9e5",
    "text": "#402c39",
    "muted": "#806474",
    "primary": "#d65f98",
    "primary_hover": "#e976ab",
    "danger": "#c94f73",
    "preview": "#241d2d",
}
AEMEATH_COLORS = {
    "app_bg": "#fff7fb",
    "panel": "#fffdfd",
    "panel_alt": "#fff0f7",
    "line": "#e8b7ce",
    "line_soft": "#f3d9e6",
    "text": "#43303f",
    "muted": "#856778",
    "primary": "#d95d9d",
    "primary_hover": "#ee78b4",
    "danger": "#c84e78",
    "preview": "#252336",
}
JINGRAN_COLORS = {
    "app_bg": "#0a1117",
    "panel": "#101a22",
    "panel_alt": "#15232c",
    "line": "#31515c",
    "line_soft": "#243a43",
    "text": "#edf4f4",
    "muted": "#9ab0b5",
    "primary": "#42c8dc",
    "primary_hover": "#6edbe8",
    "danger": "#d17a58",
    "preview": "#050a0f",
}
THEME_DEFINITIONS = {
    "daniya": {
        "pack": DANIYA_THEME_PACK,
        "manifest_id": "daniya-pink",
        "name": "达妮娅主题",
        "colors": DANIYA_COLORS,
        "banner_title": "达妮娅",
        "banner_subtitle": "我不太擅长战斗啦……可以申请偷懒吗？",
        "banner_overlay": (24, 18, 42, 34),
        "banner_text": "#fff7fb",
        "banner_muted": "#f5c9dd",
        "focus_y": 0.38,
    },
    "aemeath": {
        "pack": AEMEATH_THEME_PACK,
        "manifest_id": "aemeath-pink-tech",
        "name": "爱弥斯主题",
        "colors": AEMEATH_COLORS,
        "banner_title": "爱弥斯",
        "banner_subtitle": "拯救什么这种事，本来就很酷，很美好啊。",
        "banner_overlay": (255, 244, 250, 28),
        "banner_text": "#4a3043",
        "banner_muted": "#8a5d77",
        "focus_y": 0.24,
    },
    "jingran": {
        "pack": JINGRAN_THEME_PACK,
        "manifest_id": "jingran-cyan-night",
        "name": "景燃主题",
        "colors": JINGRAN_COLORS,
        "banner_title": "景燃",
        "banner_subtitle": "行于阴阳未判之处，踏遍祸福未卜之途，借阴路而行，自也向死地而生。",
        "banner_overlay": (3, 9, 15, 72),
        "banner_text": "#f3f7f4",
        "banner_muted": "#b9eaf0",
        "focus_y": 0.48,
    },
}
PET_DEFINITIONS = {
    "daniya": {
        "name": "达妮娅",
        "frames": APP_DIR / "pet-assets" / "pink-lace-chibi" / "frames",
        "scale": 1.15,
        "event_line": daniya_event_line,
        "idle_line": daniya_idle_line,
        "bubble_palette": {},
    },
    "aemeath": {
        "name": "爱弥斯",
        "frames": APP_DIR / "pet-assets" / "aemeath-chibi" / "frames-sharp",
        "scale": 1.0,
        "event_line": aemeath_event_line,
        "idle_line": aemeath_idle_dialogue,
        "welcome_dialogue": aemeath_welcome_dialogue,
        "bubble_palette": {
            "shadow": "#cdb8dc",
            "body": "#fffafd",
            "outline": "#df8fbc",
            "badge": "#d75f9d",
            "badge_outline": "#bd4f89",
            "ornament": "#70ddeb",
            "ornament_outline": "#36bcca",
            "text": "#54384f",
        },
    },
    "jingran": {
        "name": "景燃",
        "frames": APP_DIR / "pet-assets" / "jingran-chibi" / "frames",
        "look_spritesheet": APP_DIR / "pet-assets" / "jingran-chibi" / "spritesheet.webp",
        "scale": 1.0,
        "event_line": jingran_event_line,
        "idle_line": jingran_idle_line,
        "bubble_palette": {
            "shadow": "#071015",
            "body": "#111d25",
            "outline": "#4ac8d8",
            "badge": "#b99455",
            "badge_outline": "#d2b273",
            "ornament": "#60d8e6",
            "ornament_outline": "#2b9eb0",
            "text": "#edf7f7",
        },
    },
}
COLORS = dict(SIMPLE_COLORS)

# “一键日常”无音区使用精确名称匹配。相似名称（尤其荒石高地 I / II）
# 必须各自对应独立模板，避免滑动列表时误点相邻条目。
DAILY_ZONE_TEMPLATES = {
    "方擎西峰无音区": "zone_fangqing_xifeng.png",
    "玄幽东岳无音区": "zone_xuanyou_dongyue.png",
    "落日堤屿无音区": "zone_luori_diyu.png",
    "冰原运输港无音区": "zone_bingyuan_yunshugang.png",
    "加拉尔冠阶无音区": "zone_jialaer_guanxie.png",
    "隐喙深腹无音区": "zone_yinhui_shenfu.png",
    "陷足流川无音区": "zone_xianzu_liuchuan.png",
    "哀恸谷无音区": "zone_aitong_gu.png",
    "贝奥海域无音区": "zone_beiao_haiyu.png",
    "黎乔利群岛无音区": "zone_liqiaoli_qundao.png",
    "榄生半岛无音区": "zone_lansheng_bandao.png",
    "悲叹墓岛无音区": "zone_beitan_mudao.png",
    "中曲台地无音区": "zone_zhongqu_taidi.png",
    "荒石高地无音区 I": "zone_huangshi_gaodi_1.png",
    "虎口山脉无音区": "zone_hukou_shanmai.png",
    "怨鸟泽无音区": "zone_yuanniao_ze.png",
    "归墟港市无音区": "zone_guixu_gangshi.png",
    "荒石高地无音区 II": "zone_huangshi_gaodi_2.png",
    "无光之森无音区": "zone_wuguang_zhisen.png",
}
DAILY_ZONE_NAMES = tuple(DAILY_ZONE_TEMPLATES)


@dataclass
class Step:
    action: str
    label: str = ""
    template: str = ""
    templates: list[str] = field(default_factory=list)
    template_offsets: dict[str, dict[str, int]] = field(default_factory=dict)
    loop: bool = False
    skip_missing: bool = True
    threshold: float = 0.82
    timeout: float = 8.0
    offset_x: int = 0
    offset_y: int = 0
    x: int | None = None
    y: int | None = None
    x2: int | None = None
    y2: int | None = None
    duration_ms: int = 300
    seconds: float = 0.8
    text: str = ""


@dataclass
class WeeklyTask:
    name: str
    enabled: bool = True
    weekday: str = "any"
    description: str = ""
    template_group: str = "default"
    steps: list[Step] = field(default_factory=list)


class ConfigStore:
    def __init__(self, path: Path):
        self.path = path

    def load(self) -> list[WeeklyTask]:
        if not self.path.exists():
            raise FileNotFoundError(f"配置文件不存在: {self.path}")
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        tasks = []
        for item in raw.get("tasks", []):
            steps = [Step(**step) for step in item.get("steps", [])]
            tasks.append(
                WeeklyTask(
                    name=item["name"],
                    enabled=item.get("enabled", True),
                    weekday=item.get("weekday", "any"),
                    description=item.get("description", ""),
                    template_group=item.get("template_group", "default"),
                    steps=steps,
                )
            )
        return tasks

    def save(self, tasks: list[WeeklyTask]) -> None:
        payload = {
            "version": 1,
            "reset_hint": "鸣潮国服常见周刷新为周一 04:00；如你的服务器不同，请按实际情况改任务 weekday。",
            "tasks": [
                {
                    "name": task.name,
                    "enabled": task.enabled,
                    "weekday": task.weekday,
                    "description": task.description,
                    "template_group": task.template_group,
                    "steps": [step.__dict__ for step in task.steps],
                }
                for task in tasks
            ],
        }
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


class AdbClient:
    def __init__(self, adb_path: str = "adb", device: str = ""):
        self.adb_path = adb_path.strip() or "adb"
        self.device = device.strip()

    def _base_cmd(self) -> list[str]:
        cmd = [self.adb_path]
        if self.device:
            cmd.extend(["-s", self.device])
        return cmd

    def run(self, args: list[str], timeout: int = 15) -> str:
        result = subprocess.run(
            self._base_cmd() + args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
        output = (result.stdout + result.stderr).strip()
        if result.returncode != 0:
            raise RuntimeError(output or f"ADB 命令失败: {' '.join(args)}")
        return output

    def devices(self) -> str:
        return self.run(["devices"])

    def tap(self, x: int, y: int) -> None:
        self.run(["shell", "input", "tap", str(x), str(y)])

    def swipe(self, x: int, y: int, x2: int, y2: int, duration_ms: int) -> None:
        self.run(["shell", "input", "swipe", str(x), str(y), str(x2), str(y2), str(duration_ms)])

    def text(self, value: str) -> None:
        escaped = value.replace(" ", "%s")
        self.run(["shell", "input", "text", escaped])

    def screencap(self, target: Path) -> None:
        data = subprocess.run(
            self._base_cmd() + ["exec-out", "screencap", "-p"],
            capture_output=True,
            timeout=20,
            check=False,
        )
        if data.returncode != 0:
            raise RuntimeError(data.stderr.decode("utf-8", errors="replace") or "截图失败")
        target.write_bytes(data.stdout)


class TaskRunner:
    ATTACK_CLICK_INTERVAL = 0.150
    MAIN_ATTACK_CLICK_INTERVAL = ATTACK_CLICK_INTERVAL
    MAIN_Q_INTERVAL = 20.0
    ULTIMATE_READY_CHECK_INTERVAL = 5.0
    ULTIMATE_INDICATOR_REGION = (0.755, 0.74, 0.875, 0.95)
    ULTIMATE_RING_MIN_SATURATION = 0.27
    ULTIMATE_RING_MIN_COLOR_COVERAGE = 0.30
    ULTIMATE_RING_MIN_BRIGHTNESS = 0.58
    HEAL_ROTATION_INTERVAL = 9.0
    HEAL_SWITCH_SETTLE_DELAY = 2.0
    HEAL_ATTACK_CLICK_INTERVAL = ATTACK_CLICK_INTERVAL
    HEAL_RETURN_DELAY = 1.0
    HEAL_Q_TO_RETURN_DELAY = 0.12
    REWARD_INITIAL_CHECK_DELAY = 0.15
    REWARD_SEARCH_TURN_PIXELS = 950
    REWARD_SEARCH_TIMEOUT = 90.0
    EMPTY_HEALTH_CONFIRMATIONS = 3
    EMPTY_HEALTH_CONFIRMATION_INTERVAL = 0.15
    BOSS_HEADER_CHECK_INTERVAL = 0.5
    DAILY_BATTLE_END_CHECK_INTERVAL = 0.2
    DAILY_TASK_MISSING_CONFIRMATIONS = 3
    DAILY_TASK_MISSING_CONFIRMATION_INTERVAL = 0.15
    ABSORB_PROMPT_TEMPLATES = ("absorb_prompt_dark.png", "absorb_prompt.png")
    ABSORB_TEXT_CROPS = {
        "absorb_prompt_dark.png": (130, 19, 198, 69),
        "absorb_prompt.png": (122, 10, 193, 59),
    }

    def __init__(
        self,
        controller,
        log,
        dry_run: bool = True,
        stop_event: threading.Event | None = None,
        max_cycles: int | None = None,
        combat_skill_key: str = "E",
        combat_ultimate_key: str = "R",
        daily_zone_name: str = "",
        daily_heal_enabled: bool = False,
        notice=None,
    ):
        self.controller = controller
        self.log = log
        self.dry_run = dry_run
        self.stop_event = stop_event or threading.Event()
        self.max_cycles = max_cycles
        self.combat_skill_key = combat_skill_key
        self.combat_ultimate_key = combat_ultimate_key
        self.daily_zone_name = daily_zone_name
        self.daily_heal_enabled = bool(daily_heal_enabled)
        self.notice = notice or (lambda _message: None)
        self.matcher = TemplateMatcher(TEMPLATES_DIR)
        self.template_root = TEMPLATES_DIR
        self.debug_matches = False
        self.last_clicked_image_step: Step | None = None

    def run_task(self, task: WeeklyTask) -> None:
        group_dir = TEMPLATES_DIR / task.template_group if task.template_group != "default" else TEMPLATES_DIR
        if not group_dir.exists():
            raise FileNotFoundError(f"模板组不存在: {task.template_group}")
        self.template_root = group_dir
        self.matcher.templates_dir = group_dir
        self.log(f"使用模板组: {task.template_group}")
        self.log(f"开始任务: {task.name}")
        if task.template_group == "default" and task.name == DEFAULT_GROUP_NAME and not self.dry_run:
            self._wait_for_daily_template("menu1.png", timeout=8.0, threshold=0.78)
            self._ensure_weekly_skill_selected()
        for index, step in enumerate(task.steps, start=1):
            if self.stop_event.is_set():
                self.log("收到停止信号，任务已中断。")
                return
            name = step.label or step.action
            self.log(f"  {index}. {name}")
            self._run_step(step)
        self.log(f"完成任务: {task.name}")

    def _run_step(self, step: Step) -> None:
        if step.action == "tap":
            if self.dry_run:
                self.log("    干运行：跳过坐标点击。")
                time.sleep(min(step.seconds, 0.5))
                return
            self._require_xy(step)
            self.controller.tap(step.x, step.y)
            self._sleep_click_interval(step.seconds)
        elif step.action == "tap_image":
            x, y, score = self._find_image(step)
            self.log(f"    找到模板 {step.template}: ({x}, {y}) 相似度 {score:.3f}")
            if self.dry_run:
                self.log("    干运行：已识别位置，但不点击。")
            else:
                self.log(f"    正在点击识别坐标: ({x}, {y})")
                result = self.controller.tap(x, y)
                if isinstance(result, dict):
                    self.log(
                        "    鼠标移动结果: "
                        f"目标{result.get('target')}，"
                        f"输入{result.get('input')}，"
                        f"方式{result.get('method')}，"
                        f"窗口{result.get('client')}，"
                        f"截图{result.get('capture')}，"
                        f"区域{result.get('bbox')}，"
                        f"移动前{result.get('before')}，"
                        f"移动后{result.get('after_move')}，"
                        f"SetCursorPos={result.get('set_cursor_ok')}"
                    )
                    if not result.get("set_cursor_ok"):
                        self.log("    鼠标没有移动成功：请尝试右键桌面快捷方式，以管理员身份运行。")
                elif result:
                    self.log(f"    已发送点击，屏幕坐标: {result}")
                self.last_clicked_image_step = step
            self._sleep_click_interval(step.seconds)
        elif step.action == "tap_image_cycle":
            self._run_image_cycle(step)
        elif step.action == "move_to_visual_target":
            self._run_visual_navigation(step)
        elif step.action == "combat_4c":
            self._run_4c_combat(step)
        elif step.action == "daily_routine":
            self._run_daily_routine(step)
        elif step.action == "swipe":
            if self.dry_run:
                self.log("    干运行：跳过滑动。")
                time.sleep(min(step.seconds, 0.5))
                return
            if None in (step.x, step.y, step.x2, step.y2):
                raise ValueError("swipe 步骤需要 x/y/x2/y2")
            self.controller.swipe(step.x, step.y, step.x2, step.y2, step.duration_ms)
            time.sleep(step.seconds)
        elif step.action == "wait":
            time.sleep(step.seconds)
        elif step.action == "text":
            if self.dry_run:
                self.log("    干运行：跳过文本输入。")
                time.sleep(min(step.seconds, 0.5))
                return
            self.controller.text(step.text)
            time.sleep(step.seconds)
        else:
            raise ValueError(f"未知步骤类型: {step.action}")

    def _run_4c_combat(self, step: Step) -> None:
        required = (
            "press_keys",
            "press_key",
            "press_binding",
            "left_click",
            "middle_click",
            "wheel_at",
            "move_mouse_relative",
            "release_keys",
        )
        if any(not hasattr(self.controller, name) for name in required):
            raise RuntimeError("4C刷取目前只支持 PC 客户端窗口。")
        skill_key = self.controller.normalize_input_binding(self.combat_skill_key)
        ultimate_key = self.controller.normalize_input_binding(self.combat_ultimate_key)
        cycle_count = max(1, int(self.max_cycles or 1))
        if self.dry_run:
            self.log(
                f"    干运行：计划执行 {cycle_count} 轮；每轮开打先按鼠标中键锁定敌人，"
                f"再由独立攻击节奏以0.15秒间隔不间断普攻并接近敌人，每10秒按 {skill_key}，"
                f"一号位每20秒按Q，每5秒检查右下角大招状态并在就绪时施放 {ultimate_key}；每9秒执行 "
                "3→等待2秒→技能→空格→左键×3→等待1秒→空格→左键×3→Q→1。"
            )
            return

        self.log(
            f"    4C刷取已开始：共 {cycle_count} 轮，当前技能键位 {skill_key}，"
            f"大招键位 {ultimate_key}。"
        )
        try:
            for cycle_index in range(1, cycle_count + 1):
                if self.stop_event.is_set():
                    self.log("    收到停止信号，4C刷取已停止。")
                    return
                self.log(f"    === 第 {cycle_index}/{cycle_count} 轮 ===")
                self._run_4c_battle(step, skill_key, ultimate_key, cycle_index)
                if self.stop_event.is_set():
                    return
                self._collect_4c_reward(cycle_index)
                if self.stop_event.is_set():
                    return
                if cycle_index >= cycle_count:
                    self.log(f"    已完成 {cycle_count} 轮战斗与吸收，停止4C刷取。")
                    return
                self._restart_4c_challenge(cycle_index + 1)
        finally:
            try:
                self.controller.release_keys(("W", "A", "S", "D", "SPACE", "1", "2", "3", "4"))
            except Exception as exc:
                self.log(f"    释放战斗按键时遇到问题: {exc}")

    def _run_4c_battle(self, step: Step, skill_key: str, ultimate_key: str, cycle_index: int) -> None:
        started = time.monotonic()
        deadline = started + max(30.0, step.timeout)
        last_skill = started
        last_main_q = started
        last_ultimate_check = started
        last_heal = started
        last_approach = 0.0
        last_header_check = 0.0
        boss_header_seen = False
        screenshot = APP_DIR / "_runtime_screenshot.png"
        self.controller.press_key("1", 65)
        self._sleep_interruptible(0.20)
        self.log(f"    第{cycle_index}轮：鼠标中键锁定敌人。")
        self.controller.middle_click()
        self._sleep_interruptible(0.18)
        attack_enabled = threading.Event()
        attack_finished = threading.Event()
        attack_lock = threading.Lock()
        attack_enabled.set()
        attack_worker = threading.Thread(
            target=self._run_4c_continuous_attack,
            args=(attack_enabled, attack_finished, attack_lock),
            name="wwbs-4c-continuous-attack",
            daemon=True,
        )
        attack_worker.start()
        try:
            while time.monotonic() < deadline:
                if self.stop_event.is_set():
                    return
                now = time.monotonic()
                if now - last_header_check >= self.BOSS_HEADER_CHECK_INTERVAL:
                    header_present = self._inspect_4c_boss_header(
                        screenshot,
                        cycle_index,
                        0,
                        log_result=False,
                    )
                    last_header_check = time.monotonic()
                    if header_present:
                        boss_header_seen = True
                    elif boss_header_seen:
                        attack_enabled.clear()
                        with attack_lock:
                            pass
                        missing_header_checks = 1
                        self.controller.release_keys()
                        self.log("    战斗监测发现首领名字与血条疑似消失，暂停攻击并快速复核。")
                        while missing_header_checks < self.EMPTY_HEALTH_CONFIRMATIONS:
                            self._sleep_interruptible(self.EMPTY_HEALTH_CONFIRMATION_INTERVAL)
                            if self._inspect_4c_boss_header(
                                screenshot,
                                cycle_index,
                                missing_header_checks,
                            ):
                                missing_header_checks = 0
                                break
                            missing_header_checks += 1
                        if missing_header_checks >= self.EMPTY_HEALTH_CONFIRMATIONS:
                            self.controller.release_keys()
                            self.log(
                                f"    第{cycle_index}轮：已确认首领名字与整条血条彻底消失，进入吸收流程。"
                            )
                            return
                    elif now - started >= 15.0:
                        raise RuntimeError("没有检测到屏幕顶部的首领名字和血条，已停止4C刷取。请先进入战斗。")
                    if not attack_enabled.is_set():
                        attack_enabled.set()
                if now - last_heal >= self.HEAL_ROTATION_INTERVAL:
                    attack_enabled.clear()
                    with attack_lock:
                        pass
                    self.log(
                        "    每9秒切换三号位：等待2秒→技能→跳跃→普攻三次→"
                        "等待1秒→再次跳跃→普攻三次→Q→切回一号位。"
                    )
                    self._perform_4c_heal_rotation(skill_key)
                    last_heal = time.monotonic()
                    attack_enabled.set()
                    continue
                if now - last_skill >= 10.0:
                    self.log(f"    一号位施放技能：{skill_key}。")
                    self.controller.press_binding(skill_key, 65)
                    last_skill = time.monotonic()
                if now - last_main_q >= self.MAIN_Q_INTERVAL:
                    self.log("    一号位额外施放 Q。")
                    self.controller.press_key("Q", 65)
                    last_main_q = time.monotonic()
                if now - last_ultimate_check >= self.ULTIMATE_READY_CHECK_INTERVAL:
                    self._capture_for_matching(screenshot)
                    if self._ultimate_indicator_ready(screenshot):
                        self.log(f"    检测到大招彩色完整亮环，施放大招：{ultimate_key}。")
                        self.controller.press_binding(ultimate_key, 65)
                    last_ultimate_check = time.monotonic()
                if now - last_approach >= 0.75:
                    self.controller.press_keys(("W",), 90)
                    last_approach = time.monotonic()
                self._sleep_interruptible(0.025)
            raise RuntimeError("单轮4C战斗达到安全时限，已自动停止。")
        finally:
            attack_enabled.clear()
            attack_finished.set()
            attack_worker.join(timeout=1.0)

    def _inspect_4c_boss_header(
        self,
        screenshot: Path,
        cycle_index: int,
        missing_checks: int,
        *,
        log_result: bool = True,
    ) -> bool:
        """Capture the boss header and report whether its name or full track remains."""
        self._capture_for_matching(screenshot)
        health_ratio = self._boss_health_ratio(screenshot)
        name_ratio = self._boss_name_ratio(screenshot)
        bar_track_score = self._boss_bar_track_score(screenshot)
        header_present = name_ratio >= 0.015 or bar_track_score >= 0.18
        confirmation = 0 if header_present else missing_checks + 1
        if log_result:
            self.log(
                f"    第{cycle_index}轮快速复核：血量色彩 {health_ratio:.3f}，名字 {name_ratio:.3f}，"
                f"血条轨道 {bar_track_score:.3f}"
                f"（完整消失确认 {confirmation}/{self.EMPTY_HEALTH_CONFIRMATIONS}）。"
            )
        return header_present

    def _run_4c_continuous_attack(
        self,
        attack_enabled: threading.Event,
        attack_finished: threading.Event,
        attack_lock: threading.Lock,
    ) -> None:
        """Attack on its own clock so screenshots and movement never form click bursts."""
        while not attack_finished.is_set() and not self.stop_event.is_set():
            if not attack_enabled.wait(timeout=0.05):
                continue
            if attack_finished.is_set() or self.stop_event.is_set():
                return
            try:
                with attack_lock:
                    if attack_enabled.is_set():
                        self.controller.left_click()
            except Exception as exc:
                self.log(f"    一号位持续普攻失败：{exc}")
                self.stop_event.set()
                return
            attack_finished.wait(self.MAIN_ATTACK_CLICK_INTERVAL)

    def _run_daily_routine(self, step: Step) -> None:
        """Run the two-round daily tacet-field flow with optional healing."""
        required = (
            "press_keys",
            "press_key",
            "press_binding",
            "left_click",
            "middle_click",
            "move_mouse_relative",
            "release_keys",
        )
        if any(not hasattr(self.controller, name) for name in required):
            raise RuntimeError("一键日常目前只支持 PC 客户端窗口。")
        template_name = DAILY_ZONE_TEMPLATES.get(self.daily_zone_name)
        if not template_name:
            raise RuntimeError("请先在开始页滑动选择要挑战的无音区。")
        if self.dry_run:
            self.log(
                f"    干运行：将精确寻找“{self.daily_zone_name}”，完成两轮战斗与双倍领取，"
                "随后领取活跃度与先约电台奖励；周度游历未完成时继续执行15轮幻梦游园。"
            )
            return

        skill_key = self.controller.normalize_input_binding(self.combat_skill_key)
        ultimate_key = self.controller.normalize_input_binding(self.combat_ultimate_key)
        self.log(f"    一键日常目标：{self.daily_zone_name}。")
        self.log(
            "    日常三号位回血已开启。"
            if self.daily_heal_enabled
            else "    日常三号位回血未开启，仅使用一号位战斗。"
        )
        try:
            if not self._open_daily_tacet_field(template_name):
                completed_message = "今日日常已经完成，不再挑战无音区。"
                self.log(f"    【提示】检测到索拉指南已自动跳过活跃度页面，{completed_message}")
                self.notice(completed_message)
                self._continue_daily_from_open_guide_page()
                self.log("    日常已完成后的周度游历检查结束。")
                return
            for cycle_index in (1, 2):
                if self.stop_event.is_set():
                    return
                self.log(f"    === 一键日常第 {cycle_index}/2 轮 ===")
                while not self.stop_event.is_set():
                    self._run_daily_battle(step, skill_key, ultimate_key, cycle_index)
                    if self.stop_event.is_set():
                        return
                    if self._collect_daily_reward(cycle_index):
                        break
                self._wait_for_daily_success(cycle_index)
                if cycle_index == 1:
                    self._click_daily_template("restart_challenge.png", "重新挑战", timeout=20.0)
                    self._click_optional_daily_template(
                        "insufficient_continue.png",
                        "体力不足继续提示的确认",
                        timeout=5.0,
                    )
                    self._sleep_interruptible(0.3)
                else:
                    self._click_daily_template("exit_instance.png", "退出副本", timeout=20.0)
                    self._confirm_daily_exit_if_present()
                    self._sleep_interruptible(0.3)
            self._collect_daily_activity_rewards()
            self._collect_daily_battlepass_rewards()
            self._continue_daily_into_weekly_travel()
            self.log("    一键日常与自动周常流程完成。")
        finally:
            try:
                self.controller.release_keys(("W", "A", "S", "D", "SPACE", "1", "2", "3", "4"))
            except Exception as exc:
                self.log(f"    释放日常任务按键时遇到问题: {exc}")

    def _capture_size(self, screenshot: Path | None = None) -> tuple[Path, int, int]:
        target = screenshot or (APP_DIR / "_runtime_screenshot.png")
        self._capture_for_matching(target)
        with Image.open(target) as captured:
            width, height = captured.size
        return target, width, height

    @staticmethod
    def _daily_exit_confirmation_present(screenshot: Path) -> bool:
        """Detect the white leave-confirmation panel and its two dark buttons."""
        with Image.open(screenshot) as source:
            image = np.asarray(source.convert("RGB"))
        height, width = image.shape[:2]

        def ratio(
            box: tuple[float, float, float, float],
            predicate,
        ) -> float:
            left, top, right, bottom = box
            crop = image[
                round(height * top):round(height * bottom),
                round(width * left):round(width * right),
            ]
            if crop.size == 0:
                return 0.0
            return float(predicate(crop).mean())

        bright_panel = ratio(
            (0.22, 0.29, 0.78, 0.71),
            lambda crop: crop.min(axis=2) > 205,
        )
        left_dark_button = ratio(
            (0.24, 0.59, 0.43, 0.68),
            lambda crop: crop.max(axis=2) < 90,
        )
        right_dark_button = ratio(
            (0.56, 0.59, 0.76, 0.68),
            lambda crop: crop.max(axis=2) < 90,
        )
        return bright_panel > 0.50 and left_dark_button > 0.28 and right_dark_button > 0.28

    def _confirm_daily_exit_if_present(self, timeout: float = 3.0) -> bool:
        screenshot = APP_DIR / "_runtime_screenshot.png"
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and not self.stop_event.is_set():
            self._capture_for_matching(screenshot)
            if self._daily_exit_confirmation_present(screenshot):
                with Image.open(screenshot) as captured:
                    width, height = captured.size
                self.log("    已识别“确认离开”二次提示，点击右侧确认。")
                self.controller.tap(round(width * 0.657), round(height * 0.628))
                self._sleep_interruptible(0.25)
                return True
            if self._overworld_hud_ready(screenshot):
                return False
            self._sleep_interruptible(0.10)
        return False

    def _tap_ratio(self, x_ratio: float, y_ratio: float, pause: float = 1.0) -> None:
        _screenshot, width, height = self._capture_size()
        self.controller.tap(round(width * x_ratio), round(height * y_ratio))
        self._sleep_interruptible(pause)

    def _swipe_ratio(
        self,
        x_ratio: float,
        y_ratio: float,
        x2_ratio: float,
        y2_ratio: float,
        duration_ms: int = 420,
        pause: float = 0.6,
    ) -> None:
        _screenshot, width, height = self._capture_size()
        start = (round(width * x_ratio), round(height * y_ratio))
        end = (round(width * x2_ratio), round(height * y2_ratio))
        if hasattr(self.controller, "screenshot_to_client"):
            start = self.controller.screenshot_to_client(*start)
            end = self.controller.screenshot_to_client(*end)
        self.controller.swipe(*start, *end, duration_ms)
        self._sleep_interruptible(pause)

    def _find_daily_template(
        self,
        template_name: str,
        *,
        threshold: float = 0.72,
        region: tuple[int, int, int, int] | None = None,
        template_crop: tuple[int, int, int, int] | None = None,
        scales: list[float] | None = None,
        screenshot: Path | None = None,
    ):
        target = screenshot or (APP_DIR / "_runtime_screenshot.png")
        if screenshot is None:
            self._capture_for_matching(target)
        best = None
        for scale in scales or self._fast_scales():
            try:
                candidate = self.matcher.find_fast(
                    target,
                    template_name,
                    threshold=-1.0,
                    scale=scale,
                    region=region,
                    template_crop=template_crop,
                )
            except Exception:
                continue
            if best is None or candidate.score > best.score:
                best = candidate
            # The controller's first scale is the measured window scale. Once it
            # already clears the threshold, scanning four nearby scales only adds
            # seconds without changing the decision.
            if candidate.score >= threshold:
                return candidate
        return best if best is not None and best.score >= threshold else None

    def _wait_for_daily_template(
        self,
        template_name: str,
        *,
        timeout: float,
        threshold: float = 0.72,
        region_ratio: tuple[float, float, float, float] | None = None,
    ):
        deadline = time.monotonic() + timeout
        screenshot = APP_DIR / "_runtime_screenshot.png"
        attempt = 0
        while time.monotonic() < deadline and not self.stop_event.is_set():
            _path, width, height = self._capture_size(screenshot)
            region = None
            if region_ratio is not None:
                region = (
                    round(width * region_ratio[0]),
                    round(height * region_ratio[1]),
                    round(width * region_ratio[2]),
                    round(height * region_ratio[3]),
                )
            match = self._find_daily_template(
                template_name,
                threshold=threshold,
                region=region,
                # The controller already knows the exact window scale. Use the
                # wider scale sweep only occasionally as a compatibility fallback.
                scales=None if attempt % 5 == 4 else [self._fast_scales()[0]],
                screenshot=screenshot,
            )
            if match is not None:
                return match
            attempt += 1
            self._sleep_interruptible(0.12)
        if self.stop_event.is_set():
            raise RuntimeError("一键日常已停止。")
        raise RuntimeError(f"等待界面元素超时：{template_name}")

    def _click_daily_template(
        self,
        template_name: str,
        label: str,
        *,
        timeout: float = 10.0,
        threshold: float = 0.72,
        region_ratio: tuple[float, float, float, float] | None = None,
    ) -> None:
        match = self._wait_for_daily_template(
            template_name,
            timeout=timeout,
            threshold=threshold,
            region_ratio=region_ratio,
        )
        self.log(f"    已识别{label}，相似度 {match.score:.3f}。")
        self.controller.tap(*match.center)
        self._sleep_interruptible(0.18)

    def _click_optional_daily_template(
        self,
        template_name: str,
        label: str,
        *,
        timeout: float = 3.0,
        threshold: float = 0.72,
    ) -> bool:
        try:
            self._click_daily_template(
                template_name,
                label,
                timeout=timeout,
                threshold=threshold,
            )
            return True
        except RuntimeError:
            return False

    def _open_terminal_destination(
        self,
        label: str,
        x_ratio: float,
        y_ratio: float,
        *,
        require_transition: bool = False,
    ) -> None:
        """Open the terminal from the overworld before entering a daily page."""
        self._wait_for_overworld_hud(minimum_wait=1.2 if require_transition else 0.0)
        self.log(f"    大世界按 Esc 打开终端，进入{label}。")
        self.controller.press_key("ESC", 70)
        self._sleep_interruptible(0.35)
        self._tap_ratio(x_ratio, y_ratio, 0.45)

    @staticmethod
    def _overworld_hud_ready(screenshot: Path) -> bool:
        """Recognize the normal game HUD and reject black/loading frames."""
        with Image.open(screenshot) as source:
            image = np.asarray(source.convert("RGB"))
        height, width = image.shape[:2]

        def bright_ratio(box: tuple[float, float, float, float]) -> float:
            left, top, right, bottom = box
            crop = image[
                round(height * top):round(height * bottom),
                round(width * left):round(width * right),
            ]
            if crop.size == 0:
                return 0.0
            bright = (crop[:, :, 0] > 205) & (crop[:, :, 1] > 205) & (crop[:, :, 2] > 205)
            return float(bright.mean())

        # Normal overworld HUD simultaneously has top-right menu icons, the party
        # portraits on the right and action icons at the bottom-right.
        return (
            bright_ratio((0.70, 0.025, 0.985, 0.18)) >= 0.012
            and bright_ratio((0.86, 0.16, 0.985, 0.64)) >= 0.008
            and bright_ratio((0.72, 0.80, 0.985, 0.985)) >= 0.010
        )

    def _wait_for_overworld_hud(self, timeout: float = 25.0, minimum_wait: float = 0.0) -> None:
        screenshot = APP_DIR / "_runtime_screenshot.png"
        started = time.monotonic()
        deadline = time.monotonic() + timeout
        confirmations = 0
        while time.monotonic() < deadline and not self.stop_event.is_set():
            self._capture_for_matching(screenshot)
            if self._overworld_hud_ready(screenshot):
                confirmations += 1
                if confirmations >= 2 and time.monotonic() - started >= minimum_wait:
                    self.log("    已确认回到大世界。")
                    return
            else:
                confirmations = 0
            self._sleep_interruptible(0.22)
        if self.stop_event.is_set():
            raise RuntimeError("一键日常已停止。")
        raise RuntimeError("退出副本后未确认回到大世界，已停止以避免在加载界面误按 Esc。")

    @staticmethod
    def _sola_guide_page_ready(screenshot: Path) -> bool:
        """Require the stable Sola Guide chrome before classifying its current page."""
        with Image.open(screenshot) as source:
            image = np.asarray(source.convert("RGB"))
        height, width = image.shape[:2]
        close_button = image[
            round(height * 0.02):round(height * 0.13),
            round(width * 0.92):round(width * 0.98),
        ]
        if close_button.size == 0:
            return False
        return float((close_button.min(axis=2) > 180).mean()) > 0.025

    @staticmethod
    def _daily_activity_page_present(screenshot: Path) -> bool:
        """The activity page is dominated by its large pale task rows."""
        with Image.open(screenshot) as source:
            image = np.asarray(source.convert("RGB"))
        height, width = image.shape[:2]
        task_rows = image[
            round(height * 0.23):round(height * 0.80),
            round(width * 0.10):round(width * 0.96),
        ]
        if task_rows.size == 0:
            return False
        return float((task_rows.min(axis=2) > 170).mean()) > 0.45

    @staticmethod
    def _weekly_travel_page_present(screenshot: Path) -> bool:
        """Detect the pale selected weekly-travel tab after activity auto-skips."""
        with Image.open(screenshot) as source:
            image = np.asarray(source.convert("RGB"))
        height, width = image.shape[:2]
        weekly_tab = image[
            round(height * 0.13):round(height * 0.19),
            round(width * 0.255):round(width * 0.41),
        ]
        if weekly_tab.size == 0:
            return False
        return float((weekly_tab.min(axis=2) > 170).mean()) > 0.18

    def _daily_activity_still_pending(self, timeout: float = 6.0) -> bool:
        """Return false when Sola Guide skips activity because today's score is full."""
        screenshot = APP_DIR / "_runtime_screenshot.png"
        deadline = time.monotonic() + timeout
        confirmations = 0
        last_state: bool | None = None
        while time.monotonic() < deadline and not self.stop_event.is_set():
            self._capture_for_matching(screenshot)
            if not self._sola_guide_page_ready(screenshot):
                confirmations = 0
                self._sleep_interruptible(0.15)
                continue
            state = self._daily_activity_page_present(screenshot)
            confirmations = confirmations + 1 if state == last_state else 1
            last_state = state
            if confirmations >= 2:
                return state
            self._sleep_interruptible(0.15)
        raise RuntimeError("进入索拉指南后未能确认当前页面，已停止以避免误打无音区。")

    def _open_daily_tacet_field(self, zone_template: str) -> bool:
        self.log("    打开索拉指南 → 素材获取 → 无音清剿。")
        self._open_terminal_destination("索拉指南", 0.515, 0.671)
        if not self._daily_activity_still_pending():
            return False
        self._tap_ratio(0.060, 0.302, 1.2)
        self._tap_ratio(0.209, 0.695, 1.5)

        screenshot = APP_DIR / "_runtime_screenshot.png"
        found = None
        numbered_huangshi = self.daily_zone_name in {
            "荒石高地无音区 I",
            "荒石高地无音区 II",
        }
        zone_threshold = 0.97 if numbered_huangshi else 0.90
        zone_crop = (6, 18, 304, 64) if numbered_huangshi else (6, 18, 190, 64)
        for page_index in range(32):
            _path, width, height = self._capture_size(screenshot)
            found = self._find_daily_template(
                zone_template,
                threshold=zone_threshold,
                region=(round(width * 0.34), round(height * 0.12), round(width * 0.98), round(height * 0.92)),
                template_crop=zone_crop,
                scales=[self._fast_scales()[0]],
                screenshot=screenshot,
            )
            if found is not None:
                if not self._daily_row_button_ready(screenshot, found.center[1]):
                    wheel_x, wheel_y = round(width * 0.91), round(height * 0.60)
                    if hasattr(self.controller, "screenshot_to_client"):
                        wheel_x, wheel_y = self.controller.screenshot_to_client(wheel_x, wheel_y)
                    self.log(f"    已看到“{self.daily_zone_name}”，等待同一行按钮完整出现。")
                    if found.center[1] > round(height * 0.68):
                        self.controller.wheel_at(wheel_x, wheel_y, -360)
                    self._sleep_interruptible(0.38)
                    found = None
                    continue
                button_x = round(width * 0.895)
                self._sleep_interruptible(0.32)
                self.log(
                    f"    精确找到“{self.daily_zone_name}”（第{page_index + 1}屏，相似度 {found.score:.3f}），"
                    "点击同一行的直接挑战/前往。"
                )
                self.controller.tap(button_x, found.center[1])
                self._sleep_interruptible(3.0)
                break
            wheel_x, wheel_y = round(width * 0.91), round(height * 0.60)
            if hasattr(self.controller, "screenshot_to_client"):
                wheel_x, wheel_y = self.controller.screenshot_to_client(wheel_x, wheel_y)
            self.controller.wheel_at(wheel_x, wheel_y, -720)
            self._sleep_interruptible(0.28)
        if found is None:
            raise RuntimeError(f"无音清剿列表中没有找到“{self.daily_zone_name}”。")
        self.log("    队伍界面点击“开启挑战”，不修改队伍。")
        self._tap_ratio(0.86, 0.92, 5.0)
        return True

    @staticmethod
    def _daily_row_button_ready(screenshot: Path, row_y: int) -> bool:
        """Require the dark challenge button to be visible, not hidden by the footer."""
        with Image.open(screenshot) as source:
            image = np.asarray(source.convert("RGB"))
        height, width = image.shape[:2]
        top = max(0, int(row_y) - round(height * 0.035))
        bottom = min(height, int(row_y) + round(height * 0.035))
        left, right = round(width * 0.82), round(width * 0.96)
        region = image[top:bottom, left:right]
        if region.size == 0:
            return False
        dark = region.max(axis=2) < 75
        return float(dark.mean()) > 0.12

    def _daily_battle_task_present(self, screenshot: Path) -> bool:
        with Image.open(screenshot) as captured:
            width, height = captured.size
        return self._find_daily_template(
            "battle_task_text.png",
            threshold=0.67,
            region=(0, round(height * 0.15), round(width * 0.43), round(height * 0.42)),
            scales=[self._fast_scales()[0]],
            screenshot=screenshot,
        ) is not None

    def _select_daily_slot_one_after_loading(self, screenshot: Path) -> None:
        """Wait for the battle HUD before forcing the active character to slot one."""
        deadline = time.monotonic() + 15.0
        hud_ready = False
        while time.monotonic() < deadline:
            if self.stop_event.is_set():
                return
            self._capture_for_matching(screenshot)
            if self._daily_battle_task_present(screenshot):
                hud_ready = True
                break
            self._sleep_interruptible(0.5)
        self.controller.press_key("1", 65)
        self._sleep_interruptible(0.35)
        if hud_ready:
            self.log("    战斗界面已加载，按 1 确保当前角色为一号位。")
        else:
            self.log("    等待战斗界面超时，仍按 1 强制切换至一号位。")

    def _run_daily_battle(
        self,
        step: Step,
        skill_key: str,
        ultimate_key: str,
        cycle_index: int,
    ) -> None:
        started = time.monotonic()
        deadline = started + max(180.0, step.timeout)
        last_skill = started
        last_q = started
        last_ultimate_check = started
        last_heal = started
        last_approach = 0.0
        last_task_check = 0.0
        task_seen = False
        screenshot = APP_DIR / "_runtime_screenshot.png"
        self._select_daily_slot_one_after_loading(screenshot)
        if self.stop_event.is_set():
            return
        self.controller.middle_click()
        self.log(
            f"    第{cycle_index}轮：中键锁定后，"
            f"{'按设置定时切三号位回血' if self.daily_heal_enabled else '仅使用一号位持续战斗'}。"
        )

        attack_enabled = threading.Event()
        attack_finished = threading.Event()
        attack_lock = threading.Lock()
        attack_enabled.set()
        attack_worker = threading.Thread(
            target=self._run_4c_continuous_attack,
            args=(attack_enabled, attack_finished, attack_lock),
            name="wwbs-daily-continuous-attack",
            daemon=True,
        )
        attack_worker.start()
        try:
            while time.monotonic() < deadline:
                if self.stop_event.is_set():
                    return
                now = time.monotonic()
                if now - last_task_check >= self.DAILY_BATTLE_END_CHECK_INTERVAL:
                    self._capture_for_matching(screenshot)
                    if self._daily_reward_stage_present(screenshot):
                        attack_enabled.clear()
                        with attack_lock:
                            pass
                        self.controller.release_keys()
                        self.log("    已识别到奖励光球或领取提示，停止战斗并进入奖励搜索。")
                        return
                    present = self._daily_battle_task_present(screenshot)
                    last_task_check = time.monotonic()
                    if present:
                        task_seen = True
                        if not attack_enabled.is_set():
                            attack_enabled.set()
                    elif task_seen:
                        attack_enabled.clear()
                        with attack_lock:
                            pass
                        self.controller.release_keys()
                        if self._confirm_daily_battle_finished(screenshot):
                            self.log("    左侧清理目标文字快速复核后仍消失，进入奖励获取阶段。")
                            return
                        attack_enabled.set()
                        last_task_check = time.monotonic()
                        continue
                if (
                    self.daily_heal_enabled
                    and task_seen
                    and now - last_heal >= self.HEAL_ROTATION_INTERVAL
                ):
                    attack_enabled.clear()
                    with attack_lock:
                        pass
                    self.controller.release_keys()
                    self._capture_for_matching(screenshot)
                    if self._daily_reward_stage_present(screenshot):
                        self.log("    回血前已识别到奖励阶段，跳过回血并停止战斗。")
                        return
                    if not self._daily_battle_task_present(screenshot):
                        if self._confirm_daily_battle_finished(screenshot):
                            self.log("    回血前确认战斗已经结束，跳过回血并进入奖励获取阶段。")
                            return
                        attack_enabled.set()
                        last_task_check = time.monotonic()
                        continue
                    self.log(
                        "    日常回血：切换三号位执行技能、跳跃与普攻连段，随后切回一号位。"
                    )
                    if not self._perform_4c_heal_rotation(skill_key):
                        return
                    last_heal = time.monotonic()
                    self._capture_for_matching(screenshot)
                    if self._daily_reward_stage_present(screenshot):
                        self.log("    回血完成时已识别到奖励阶段，不再恢复持续攻击。")
                        return
                    if not self._daily_battle_task_present(screenshot):
                        if self._confirm_daily_battle_finished(screenshot):
                            self.log("    回血完成时确认战斗已经结束，停止攻击并进入奖励获取阶段。")
                            return
                    attack_enabled.set()
                    last_task_check = time.monotonic()
                    continue
                if now - last_skill >= 10.0:
                    self.controller.press_binding(skill_key, 65)
                    last_skill = time.monotonic()
                if now - last_q >= self.MAIN_Q_INTERVAL:
                    self.controller.press_key("Q", 65)
                    last_q = time.monotonic()
                if now - last_ultimate_check >= self.ULTIMATE_READY_CHECK_INTERVAL:
                    self._capture_for_matching(screenshot)
                    if self._ultimate_indicator_ready(screenshot):
                        self.log(f"    检测到大招彩色完整亮环，施放大招：{ultimate_key}。")
                        self.controller.press_binding(ultimate_key, 65)
                    last_ultimate_check = time.monotonic()
                if now - last_approach >= 0.75:
                    self.controller.press_keys(("W",), 90)
                    last_approach = time.monotonic()
                self._sleep_interruptible(0.025)
            if not task_seen:
                raise RuntimeError("没有识别到无音区清理目标文字，请确认已进入无音区挑战。")
            raise RuntimeError("无音区单轮战斗达到安全时限，已自动停止。")
        finally:
            attack_enabled.clear()
            attack_finished.set()
            attack_worker.join(timeout=1.0)

    @classmethod
    def _ultimate_indicator_ready(cls, screenshot: Path) -> bool:
        """Classify the lower-right ultimate icon without matching character art."""
        with Image.open(screenshot) as source:
            frame = np.asarray(source.convert("RGB"))
        height, width = frame.shape[:2]
        left, top, right, bottom = cls.ULTIMATE_INDICATOR_REGION
        crop = frame[
            round(height * top):round(height * bottom),
            round(width * left):round(width * right),
        ]
        return cls._ultimate_indicator_crop_ready(crop, expected_radius=height * 0.034)

    @classmethod
    def _ultimate_indicator_crop_ready(
        cls,
        crop: np.ndarray,
        expected_radius: float | None = None,
    ) -> bool:
        """Recognize a charged colorful ring while rejecting gray/partial/cooldown rings."""
        image = np.asarray(crop, dtype=np.float32)
        if image.ndim != 3 or image.shape[2] < 3:
            return False
        image = image[:, :, :3]
        height, width = image.shape[:2]
        minimum = min(height, width)
        if minimum < 40:
            return False

        maximum = image.max(axis=2)
        minimum_channel = image.min(axis=2)
        saturation = (maximum - minimum_channel) / np.maximum(maximum, 1.0)
        brightness = maximum / 255.0
        angles = np.linspace(0.0, 2.0 * np.pi, 48, endpoint=False)
        step = max(2, round(minimum / 40))
        best: tuple[float, int, int, int] | None = None

        if expected_radius is None:
            radius_start = max(12, round(minimum * 0.22))
            radius_stop = max(radius_start + 1, round(minimum * 0.43))
        else:
            radius_start = max(12, round(expected_radius * 0.72))
            radius_stop = max(radius_start + 1, round(expected_radius * 1.28))
        for radius in range(radius_start, radius_stop + 1, step):
            for center_y in range(round(height * 0.15), round(height * 0.62) + 1, step):
                for center_x in range(round(width * 0.25), round(width * 0.75) + 1, step):
                    ring_values = []
                    for radius_factor in (0.86, 1.0, 1.14):
                        xs = np.clip(
                            np.rint(center_x + np.cos(angles) * radius * radius_factor).astype(int),
                            0,
                            width - 1,
                        )
                        ys = np.clip(
                            np.rint(center_y + np.sin(angles) * radius * radius_factor).astype(int),
                            0,
                            height - 1,
                        )
                        ring_values.append(brightness[ys, xs])
                    sampled_brightness = np.concatenate(ring_values)
                    bright_coverage = float((sampled_brightness > 0.55).mean())
                    glyph_top = min(height, center_y + radius + 1)
                    glyph_bottom = min(height, center_y + radius + round(radius * 0.8))
                    glyph_left = max(0, center_x - round(radius * 0.3))
                    glyph_right = min(width, center_x + round(radius * 0.3))
                    glyph = brightness[glyph_top:glyph_bottom, glyph_left:glyph_right]
                    glyph_coverage = float((glyph > 0.75).mean()) if glyph.size else 0.0
                    score = (
                        bright_coverage
                        + 0.35 * glyph_coverage
                        + 0.20 * float(sampled_brightness.mean())
                    )
                    if best is None or score > best[0]:
                        best = (score, center_x, center_y, radius)

        if best is None:
            return False
        _score, center_x, center_y, radius = best
        yy, xx = np.ogrid[:height, :width]
        distance = np.sqrt((xx - center_x) ** 2 + (yy - center_y) ** 2)
        ring = (distance > radius * 0.78) & (distance < radius * 1.18)
        if not ring.any():
            return False
        color_coverage = float(
            ((brightness > 0.50) & (saturation > 0.25) & ring).sum() / ring.sum()
        )
        mean_saturation = float(saturation[ring].mean())
        mean_brightness = float(brightness[ring].mean())
        return (
            color_coverage >= cls.ULTIMATE_RING_MIN_COLOR_COVERAGE
            and mean_saturation >= cls.ULTIMATE_RING_MIN_SATURATION
            and mean_brightness >= cls.ULTIMATE_RING_MIN_BRIGHTNESS
        )

    def _find_daily_reward_prompt(self, screenshot: Path):
        with Image.open(screenshot) as captured:
            width, height = captured.size
        return self._find_daily_template(
            "reward_prompt.png",
            threshold=0.72,
            region=(
                round(width * 0.38),
                round(height * 0.35),
                round(width * 0.96),
                round(height * 0.80),
            ),
            scales=[self._fast_scales()[0]],
            screenshot=screenshot,
        )

    def _daily_reward_stage_present(self, screenshot: Path) -> bool:
        if self._find_daily_reward_prompt(screenshot) is not None:
            return True
        target_x, _target_y, density = self._daily_reward_orb_location(screenshot)
        return target_x is not None and density > DAILY_REWARD_ORB_MIN_CONFIDENCE

    @staticmethod
    def _daily_reward_orb_location(screenshot: Path) -> tuple[int | None, int | None, float]:
        with Image.open(screenshot) as source:
            image = np.asarray(source.convert("RGB"))
        height, width = image.shape[:2]
        # Only inspect the 3D scene above the character. This excludes portraits,
        # skill icons and most text HUD elements that can otherwise look white.
        top, bottom = round(height * 0.13), round(height * 0.52)
        left, right = round(width * 0.08), round(width * 0.84)
        region = image[top:bottom, left:right]
        red = region[:, :, 0].astype(np.int16)
        green = region[:, :, 1].astype(np.int16)
        blue = region[:, :, 2].astype(np.int16)
        # Reward orb has a dense white core. The blue-black exit portal does not.
        white = (red > 218) & (green > 218) & (blue > 225) & ((np.maximum.reduce((red, green, blue)) - np.minimum.reduce((red, green, blue))) < 48)
        if not white.any():
            return None, None, 0.0
        block = 28
        usable_h = (white.shape[0] // block) * block
        usable_w = (white.shape[1] // block) * block
        if usable_h < block or usable_w < block:
            return None, None, 0.0
        counts = white[:usable_h, :usable_w].reshape(usable_h // block, block, usable_w // block, block).sum(axis=(1, 3))
        cell_y, cell_x = np.unravel_index(np.argmax(counts), counts.shape)
        density = float(counts[cell_y, cell_x] / (block * block))
        if density <= DAILY_REWARD_ORB_MIN_CONFIDENCE:
            return None, None, density
        return left + cell_x * block + block // 2, top + cell_y * block + block // 2, density

    def _collect_daily_reward(self, cycle_index: int) -> bool:
        screenshot = APP_DIR / "_runtime_screenshot.png"
        deadline = time.monotonic() + 75.0
        previous_forward_confidence: float | None = None
        search_misses = 0
        while time.monotonic() < deadline and not self.stop_event.is_set():
            self._capture_for_matching(screenshot)
            prompt = self._find_daily_reward_prompt(screenshot)
            target_x, _target_y, density = self._daily_reward_orb_location(screenshot)
            # Ultimate effects can temporarily cover the task text and cause the
            # fast battle loop to think combat ended. Recheck on every reward-search
            # frame. A visible reward prompt or orb takes precedence because the
            # old task text can linger after the enemies have already been cleared.
            if (
                prompt is None
                and target_x is None
                and self._daily_battle_task_present(screenshot)
            ):
                self.controller.release_keys()
                self.log("    奖励搜索时发现左侧清理目标文字仍在，判定战斗尚未结束，继续攻击。")
                return False
            with Image.open(screenshot) as captured:
                width, height = captured.size
            if prompt is not None:
                self.controller.release_keys()
                self.controller.press_key("F", 100)
                self.log(f"    第{cycle_index}轮：识别到“领取奖励”，已按 F。")
                self._sleep_interruptible(0.2)
                self._claim_daily_double_reward(cycle_index)
                return True
            if target_x is None or density <= DAILY_REWARD_ORB_MIN_CONFIDENCE:
                search_misses += 1
                vertical_adjustment = self._daily_reward_vertical_adjustment(search_misses)
                self.controller.move_mouse_relative(260, vertical_adjustment)
                if vertical_adjustment < 0:
                    height_action = "抬高一档并"
                elif vertical_adjustment > 0:
                    height_action = "恢复初始高度并"
                else:
                    height_action = ""
                self.log(
                    f"    奖励光球置信度 {density:.2f} 未超过"
                    f"{DAILY_REWARD_ORB_MIN_CONFIDENCE:.2f}，"
                    f"{height_action}向右转动搜索。"
                )
                previous_forward_confidence = None
            elif self._daily_reward_movement_stalled(previous_forward_confidence, density):
                self.controller.move_mouse_relative(260, 0)
                self.log(
                    f"    靠近后光球置信度未提升（{previous_forward_confidence:.2f} → {density:.2f}），"
                    "停止直走并转向重新寻找。"
                )
                previous_forward_confidence = None
            else:
                search_misses = 0
                offset = target_x - width * 0.5
                if abs(offset) > width * 0.05:
                    self.controller.move_mouse_relative(int(max(-300, min(300, offset * 0.40))), 0)
                self.controller.press_keys(("W",), 500)
                self.log(f"    已定位白色奖励光球（核心密度 {density:.2f}），正在靠近。")
                previous_forward_confidence = density
            self._sleep_interruptible(0.22)
        raise RuntimeError("奖励阶段未找到“领取奖励”提示，已停止以避免误操作。")

    @staticmethod
    def _daily_reward_movement_stalled(previous: float | None, current: float) -> bool:
        return previous is not None and current <= previous

    @staticmethod
    def _daily_reward_vertical_adjustment(search_misses: int) -> int:
        """Sweep several camera heights and always return to the starting pitch."""
        phase = max(1, int(search_misses)) % 18
        if phase in {5, 11}:
            return -180
        if phase == 17:
            return 360
        return 0

    def _claim_daily_double_reward(self, cycle_index: int) -> None:
        self._click_daily_template(
            "double_claim.png",
            "双倍领取",
            timeout=12.0,
            threshold=0.68,
            region_ratio=(0.50, 0.54, 0.80, 0.75),
        )
        state = self._wait_daily_claim_state(8.0)
        if state == "success":
            return
        if state != "refill":
            raise RuntimeError("点击双倍领取后没有进入奖励或体力补充界面。")
        self.log("    体力不足：只允许使用结晶单质或结晶溶剂，绝不选择星声。")
        if not self._safe_refill_daily_stamina():
            raise RuntimeError("结晶单质和结晶溶剂均不可用，已停止；不会使用星声兑换体力。")
        self._tap_ratio(0.14, 0.84, 0.35)  # 兑换成功页安全空白，不触碰物品卡。
        self._click_daily_template(
            "double_claim.png",
            "补充体力后的双倍领取",
            timeout=10.0,
            threshold=0.68,
            region_ratio=(0.50, 0.54, 0.80, 0.75),
        )
        state = self._wait_daily_claim_state(10.0)
        if state != "success":
            raise RuntimeError(f"第{cycle_index}轮补充体力后仍未出现挑战成功界面。")

    def _wait_daily_claim_state(self, timeout: float) -> str:
        deadline = time.monotonic() + timeout
        screenshot = APP_DIR / "_runtime_screenshot.png"
        while time.monotonic() < deadline and not self.stop_event.is_set():
            self._capture_for_matching(screenshot)
            with Image.open(screenshot) as captured:
                width, height = captured.size
            exact_scale = [self._fast_scales()[0]]
            if self._find_daily_template(
                "challenge_success.png",
                threshold=0.66,
                region=(round(width * 0.31), round(height * 0.20), round(width * 0.69), round(height * 0.43)),
                scales=exact_scale,
                screenshot=screenshot,
            ):
                return "success"
            if self._find_daily_template(
                "refill_dialog.png",
                threshold=0.62,
                region=(round(width * 0.14), round(height * 0.16), round(width * 0.48), round(height * 0.33)),
                scales=exact_scale,
                screenshot=screenshot,
            ):
                return "refill"
            self._sleep_interruptible(0.08)
        return ""

    def _safe_refill_daily_stamina(self) -> bool:
        # Left and middle cards are the only permitted resources. The star card is
        # at the right and is never selected, even as a fallback.
        screenshot = APP_DIR / "_runtime_screenshot.png"
        resources = [("结晶单质", 0.403), ("结晶溶剂", 0.505)]
        if self._daily_monomer_empty_after_settle(screenshot):
            self.log("    结晶单质数量为0，跳过绿色卡片，直接使用结晶溶剂。")
            resources = resources[1:]
        for label, x_ratio in resources:
            self.log(f"    尝试使用{label}，数量由游戏自动计算。")
            self._tap_ratio(x_ratio, 0.455, 0.25)
            # First confirmation enters the exchange screen; the game has already
            # calculated the required amount, so never touch its slider or MAX.
            self._tap_ratio(0.695, 0.745, 0.65)
            self._tap_ratio(0.695, 0.745, 0.75)
            state = self._wait_daily_refill_result()
            if state == "success":
                self.log(f"    {label}补充成功。")
                return True
            if state == "still_short":
                if label == "结晶单质":
                    self.log("    使用结晶单质后仍不足，继续改用结晶溶剂。")
                continue
            # An unknown screen must not be treated as a successful refill. Doing
            # so could make the next click land on the forbidden star-currency card.
            self.log(f"    无法确认{label}补充结果，停止以避免误用星声。")
            return False
        self._tap_ratio(0.30, 0.745, 0.5)
        return False

    def _daily_monomer_empty_after_settle(self, screenshot: Path, timeout: float = 0.7) -> bool:
        """Wait briefly for the resource counts to finish appearing before deciding."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and not self.stop_event.is_set():
            self._capture_for_matching(screenshot)
            if self._daily_monomer_empty(screenshot):
                return True
            self._sleep_interruptible(0.10)
        return False

    @staticmethod
    def _daily_monomer_empty(screenshot: Path) -> bool:
        """Detect the red zero at the lower-right of the green resource card."""
        with Image.open(screenshot) as source:
            image = np.asarray(source.convert("RGB"))
        height, width = image.shape[:2]
        crop = image[
            round(height * 0.46):round(height * 0.58),
            round(width * 0.400):round(width * 0.455),
        ]
        if crop.size == 0:
            return False
        red = crop[:, :, 0].astype(np.int16)
        green = crop[:, :, 1].astype(np.int16)
        blue = crop[:, :, 2].astype(np.int16)
        unavailable_red = (
            (red > 100)
            & (green < 125)
            & (blue < 125)
            & ((red - green) > 30)
            & ((red - blue) > 20)
        )
        return int(unavailable_red.sum()) >= 4

    @staticmethod
    def _daily_refill_chooser_present(screenshot: Path) -> bool:
        """Recognize the refill chooser geometrically when its title template shifts."""
        with Image.open(screenshot) as source:
            image = np.asarray(source.convert("RGB"))
        height, width = image.shape[:2]

        def crop(box: tuple[float, float, float, float]) -> np.ndarray:
            left, top, right, bottom = box
            return image[
                round(height * top):round(height * bottom),
                round(width * left):round(width * right),
            ]

        panel = crop((0.17, 0.16, 0.83, 0.80))
        cards = crop((0.35, 0.34, 0.64, 0.59))
        buttons = crop((0.20, 0.68, 0.80, 0.79))
        if not panel.size or not cards.size or not buttons.size:
            return False
        bright_panel = float((panel.min(axis=2) > 205).mean())
        dark_cards = float((cards.max(axis=2) < 180).mean())
        dark_buttons = float((buttons.max(axis=2) < 100).mean())
        return bright_panel > 0.42 and dark_cards > 0.20 and dark_buttons > 0.22

    def _wait_daily_refill_result(self, timeout: float = 3.5) -> str:
        """Wait until refill succeeds or the refill chooser is visibly still open."""
        deadline = time.monotonic() + timeout
        screenshot = APP_DIR / "_runtime_screenshot.png"
        attempt = 0
        while time.monotonic() < deadline and not self.stop_event.is_set():
            self._capture_for_matching(screenshot)
            with Image.open(screenshot) as captured:
                width, height = captured.size
            scales = None if attempt == 3 else [self._fast_scales()[0]]
            if self._find_daily_template(
                "refill_success.png",
                threshold=0.60,
                region=(round(width * 0.30), round(height * 0.16), round(width * 0.70), round(height * 0.34)),
                scales=scales,
                screenshot=screenshot,
            ):
                return "success"
            # The title moves slightly when the game adds the "still insufficient"
            # banner, so search every configured scale instead of only the first.
            if self._find_daily_template(
                "refill_dialog.png",
                threshold=0.56,
                region=(round(width * 0.14), round(height * 0.16), round(width * 0.48), round(height * 0.33)),
                scales=scales,
                screenshot=screenshot,
            ):
                return "still_short"
            if attempt >= 2 and self._daily_refill_chooser_present(screenshot):
                return "still_short"
            attempt += 1
            self._sleep_interruptible(0.08)
        return ""

    def _wait_for_daily_success(self, cycle_index: int) -> None:
        match = self._wait_for_daily_template(
            "challenge_success.png",
            timeout=15.0,
            threshold=0.64,
            region_ratio=(0.31, 0.20, 0.69, 0.43),
        )
        self.log(f"    第{cycle_index}轮挑战成功，相似度 {match.score:.3f}。")

    @staticmethod
    def _yellow_claim_rows(screenshot: Path) -> list[int]:
        with Image.open(screenshot) as source:
            image = np.asarray(source.convert("RGB"))
        height, width = image.shape[:2]
        left, right = round(width * 0.78), round(width * 0.97)
        top, bottom = round(height * 0.14), round(height * 0.84)
        region = image[top:bottom, left:right]
        red = region[:, :, 0].astype(np.int16)
        green = region[:, :, 1].astype(np.int16)
        blue = region[:, :, 2].astype(np.int16)
        yellow = (red > 215) & (green > 190) & (blue < 190) & ((red - blue) > 45)
        row_counts = yellow.sum(axis=1)
        active = row_counts > max(12, region.shape[1] * 0.08)
        rows: list[int] = []
        start = None
        for index, present in enumerate(active):
            if present and start is None:
                start = index
            elif not present and start is not None:
                if index - start >= 4:
                    rows.append(top + (start + index - 1) // 2)
                start = None
        if start is not None and len(active) - start >= 4:
            rows.append(top + (start + len(active) - 1) // 2)
        return rows

    def _dismiss_reward_overlay_safely(self) -> None:
        # Both the stamina exchange success and item reward overlays explicitly
        # allow a blank-area click. Bottom-left is outside every item card.
        self._tap_ratio(0.13, 0.86, 0.18)

    def _collect_daily_activity_rewards(self) -> None:
        self.log("    返回大世界后，经终端进入索拉指南领取活跃度奖励；只点击黄色“领取”，不点击“前往”。")
        self._open_terminal_destination("索拉指南", 0.515, 0.671, require_transition=True)
        screenshot = APP_DIR / "_runtime_screenshot.png"
        for _ in range(12):
            self._capture_for_matching(screenshot)
            rows = self._yellow_claim_rows(screenshot)
            if not rows:
                break
            with Image.open(screenshot) as captured:
                width = captured.width
            self.controller.tap(round(width * 0.88), rows[0])
            self._sleep_interruptible(0.25)
            self._dismiss_reward_overlay_safely()

        self._capture_for_matching(screenshot)
        full = self._find_daily_template("activity_full.png", threshold=0.62, screenshot=screenshot)
        if full is None:
            self.log("    未确认活跃度达到100，跳过里程碑宝箱，避免误领。")
        else:
            self.log("    已确认活跃度100，只点击100宝箱，其余里程碑奖励由游戏一并领取。")
            self._tap_ratio(0.945, 0.868, 0.25)
            self._dismiss_reward_overlay_safely()
        self._tap_ratio(0.957, 0.058, 0.4)

    def _collect_daily_battlepass_rewards(self) -> None:
        self.log("    退出活跃指南后已在终端，直接进入先约电台；只领取免费内容，不点击购买或解锁寰宇频道。")
        self._tap_ratio(0.744, 0.257, 0.7)
        self._tap_ratio(0.062, 0.296, 0.45)
        if self._click_optional_daily_template("one_click_claim.png", "电台任务一键领取", timeout=5.0, threshold=0.66):
            self._dismiss_reward_overlay_safely()
        self._tap_ratio(0.061, 0.192, 0.45)
        if self._click_optional_daily_template("one_click_claim.png", "大众频道一键领取", timeout=5.0, threshold=0.66):
            self._dismiss_reward_overlay_safely()
        self._tap_ratio(0.957, 0.058, 0.8)

    @staticmethod
    def _weekly_travel_completed(screenshot: Path) -> bool:
        """Detect the check mark on the inactive weekly-travel tab."""
        with Image.open(screenshot) as source:
            image = np.asarray(source.convert("RGB"))
        height, width = image.shape[:2]
        region = image[
            round(height * 0.151):round(height * 0.187),
            round(width * 0.385):round(width * 0.405),
        ]
        if region.size == 0:
            return False
        high = region.max(axis=2)
        low = region.min(axis=2)
        neutral_check = ((high - low) < 35) & (high > 110)
        return float(neutral_check.mean()) > 0.15

    @staticmethod
    def _weekly_skill_slot_empty(screenshot: Path) -> bool:
        """Detect the sparse cream plus sign shown by an empty blessing slot."""
        with Image.open(screenshot) as source:
            image = np.asarray(source.convert("RGB"))
        height, width = image.shape[:2]
        slot = image[
            round(height * 0.735):round(height * 0.845),
            round(width * 0.445):round(width * 0.507),
        ]
        if slot.size == 0:
            return False
        red = slot[:, :, 0].astype(np.int16)
        green = slot[:, :, 1].astype(np.int16)
        blue = slot[:, :, 2].astype(np.int16)
        cream = (red > 220) & (green > 195) & (blue > 120) & ((red - green) < 45)
        density = float(cream.mean())
        widest_row = int(cream.sum(axis=1).max(initial=0)) / max(1, cream.shape[1])
        tallest_column = int(cream.sum(axis=0).max(initial=0)) / max(1, cream.shape[0])
        return 0.015 < density < 0.11 and widest_row > 0.25 and tallest_column > 0.25

    @staticmethod
    def _weekly_skill_equipped(screenshot: Path) -> bool:
        """Any known weekly slot without the explicit plus sign is equipped."""
        return not TaskRunner._weekly_skill_slot_empty(screenshot)

    def _ensure_weekly_skill_selected(self) -> None:
        """Use one shared empty-slot rule for standalone and daily-triggered weekly runs."""
        screenshot = APP_DIR / "_runtime_screenshot.png"
        self._capture_for_matching(screenshot)
        if self._weekly_skill_equipped(screenshot):
            self.log("    已装备幻梦祝福，保留当前技能，不重复打开选择界面。")
            return
        self.log("    检测到“＋ / 选择祝福”空槽，打开技能选择并固定选择第一个技能。")
        self._tap_ratio(0.496, 0.768, 0.18)
        self._wait_for_weekly_skill_dialog()
        self._tap_ratio(0.371, 0.505, 0.18)
        self._tap_ratio(0.826, 0.858, 0.55)
        self._wait_for_daily_template("menu1.png", timeout=8.0, threshold=0.78)

    @staticmethod
    def _weekly_skill_dialog_present(screenshot: Path) -> bool:
        """Confirm that the four-card blessing selector is fully visible."""
        with Image.open(screenshot) as source:
            image = np.asarray(source.convert("RGB")).astype(np.float32)
        height, width = image.shape[:2]
        title = image[
            round(height * 0.20):round(height * 0.32),
            round(width * 0.43):round(width * 0.82),
        ]
        body = image[
            round(height * 0.30):round(height * 0.78),
            round(width * 0.27):round(width * 0.97),
        ]
        if title.size == 0 or body.size == 0:
            return False
        green_title = (
            (title[:, :, 1] > 100)
            & (title[:, :, 1] > title[:, :, 0] * 1.03)
            & (title[:, :, 1] > title[:, :, 2] * 1.12)
        )
        bright_body = body.max(axis=2) > 190
        return float(green_title.mean()) > 0.30 and float(bright_body.mean()) > 0.65

    def _wait_for_weekly_skill_dialog(self, timeout: float = 5.0) -> None:
        screenshot = APP_DIR / "_runtime_screenshot.png"
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and not self.stop_event.is_set():
            self._capture_for_matching(screenshot)
            if self._weekly_skill_dialog_present(screenshot):
                return
            self._sleep_interruptible(0.12)
        raise RuntimeError("点击祝福技能槽后未出现四技能选择界面，已停止以避免误点。")

    def _run_default_weekly_from_daily(self) -> None:
        """Reuse the established menu template chain for the 15-round reward run."""
        self.template_root = TEMPLATES_DIR
        self.matcher.templates_dir = TEMPLATES_DIR
        self.max_cycles = 15
        start_step = Step(
            action="tap_image",
            label="点击幻梦游园开始游戏",
            template="menu1.png",
            threshold=0.82,
            timeout=12.0,
            offset_x=80,
            seconds=0.15,
        )
        cycle_step = Step(
            action="tap_image_cycle",
            label="自动执行15轮幻梦游园",
            templates=self._numbered_templates("menu", 2, 99),
            loop=True,
            threshold=0.82,
            timeout=1.0,
            seconds=0.15,
        )
        self._run_step(start_step)
        self._run_image_cycle(cycle_step)

    def _start_weekly_travel_from_selected_page(self) -> None:
        """Enter Dream Park from an already selected unfinished weekly page."""
        self._tap_ratio(0.247, 0.505, 0.8)
        self.template_root = TEMPLATES_DIR
        self.matcher.templates_dir = TEMPLATES_DIR
        self._wait_for_daily_template("menu1.png", timeout=12.0, threshold=0.78)
        self._ensure_weekly_skill_selected()
        self.log("    小漂泊者界面准备完成，接续周常拿满奖励（15轮）。")
        self._run_default_weekly_from_daily()

    def _continue_daily_from_open_guide_page(self) -> None:
        """After activity auto-skips, run weekly only when weekly is the selected page."""
        screenshot = APP_DIR / "_runtime_screenshot.png"
        self._capture_for_matching(screenshot)
        if not self._weekly_travel_page_present(screenshot):
            self.log("    索拉指南已自动跳过周度游历，判定本周周常也已完成。")
            self._tap_ratio(0.957, 0.058, 0.35)
            return
        self.log("    日常已完成，但周度游历仍未完成；进入幻梦游园继续执行周常。")
        self._start_weekly_travel_from_selected_page()

    def _continue_daily_into_weekly_travel(self) -> None:
        """From the terminal, enter unfinished weekly travel and start Dream Park."""
        self.log("    回到终端后再次进入索拉指南，检查周度游历。")
        self._tap_ratio(0.515, 0.671, 0.65)
        screenshot = APP_DIR / "_runtime_screenshot.png"
        self._wait_for_daily_template("activity_full.png", timeout=5.0, threshold=0.62)
        self._capture_for_matching(screenshot)
        if self._weekly_travel_completed(screenshot):
            self.log("    周度游历已有勾，自动周常已完成，本次跳过幻梦游园。")
            self._tap_ratio(0.957, 0.058, 0.35)
            return

        self.log("    周度游历未完成，进入周度游历 → 幻梦游园。")
        self._tap_ratio(0.333, 0.170, 0.55)
        self._start_weekly_travel_from_selected_page()

    def _perform_4c_main_attack(self) -> None:
        """Keep a steady main-character attack rhythm matching the healer clicks."""
        self.controller.left_click()
        self._sleep_interruptible(self.MAIN_ATTACK_CLICK_INTERVAL)

    def _confirm_daily_battle_finished(self, screenshot: Path) -> bool:
        """Confirm an initial missing task marker before sending more combat input."""
        for _ in range(1, self.DAILY_TASK_MISSING_CONFIRMATIONS):
            self._sleep_interruptible(self.DAILY_TASK_MISSING_CONFIRMATION_INTERVAL)
            if self.stop_event.is_set():
                return True
            self._capture_for_matching(screenshot)
            if self._daily_battle_task_present(screenshot):
                return False
        return True

    def _perform_4c_heal_rotation(self, skill_key: str) -> bool:
        """Third-slot heal combo with short attack spacing and a clear return delay."""
        if self.stop_event.is_set():
            return False
        self.controller.press_key("3", 65)
        self._sleep_interruptible(self.HEAL_SWITCH_SETTLE_DELAY)
        if self.stop_event.is_set():
            return False
        self.controller.press_binding(skill_key, 65)
        self._sleep_interruptible(0.08)
        if self.stop_event.is_set():
            return False
        self.controller.press_key("SPACE", 50)
        self._sleep_interruptible(0.035)
        for click_index in range(3):
            if self.stop_event.is_set():
                return False
            self.controller.left_click()
            if click_index < 2:
                self._sleep_interruptible(self.HEAL_ATTACK_CLICK_INTERVAL)
        self._sleep_interruptible(self.HEAL_RETURN_DELAY)
        if self.stop_event.is_set():
            return False
        self.controller.press_key("SPACE", 50)
        self._sleep_interruptible(0.035)
        for click_index in range(3):
            if self.stop_event.is_set():
                return False
            self.controller.left_click()
            if click_index < 2:
                self._sleep_interruptible(self.HEAL_ATTACK_CLICK_INTERVAL)
        if self.stop_event.is_set():
            return False
        self.controller.press_key("Q", 65)
        self._sleep_interruptible(self.HEAL_Q_TO_RETURN_DELAY)
        if self.stop_event.is_set():
            return False
        self.controller.press_key("1", 65)
        self._sleep_interruptible(0.22)
        return not self.stop_event.is_set()

    def _collect_4c_reward(self, cycle_index: int) -> None:
        screenshot = APP_DIR / "_runtime_screenshot.png"
        deadline = time.monotonic() + self.REWARD_SEARCH_TIMEOUT
        last_target_x: int | None = None
        best_target_confidence = 0.0
        stalled_target_checks = 0
        self._sleep_interruptible(self.REWARD_INITIAL_CHECK_DELAY)
        while time.monotonic() < deadline:
            if self.stop_event.is_set():
                return
            self._capture_for_matching(screenshot)
            scale = float(getattr(self.controller, "scale", 1.0))
            prompt, prompt_name = self._find_4c_absorb_prompt(screenshot, scale)
            if prompt is not None:
                self.log(
                    f"    第{cycle_index}轮：发现吸收提示 {prompt_name}，"
                    f"相似度 {prompt.score:.3f}，立即按 F。"
                )
                self.controller.release_keys()
                self.controller.press_key("F", 100)
                self._sleep_interruptible(2.8)
                return

            gold_ratio, target_x, _target_y = self._gold_target_location(screenshot)
            with Image.open(screenshot) as captured:
                width = captured.width
            if target_x is not None and gold_ratio > 0.10:
                if last_target_x is not None and abs(target_x - last_target_x) <= width * 0.10:
                    if gold_ratio > best_target_confidence + 0.012:
                        best_target_confidence = gold_ratio
                        stalled_target_checks = 0
                    else:
                        stalled_target_checks += 1
                else:
                    best_target_confidence = gold_ratio
                    stalled_target_checks = 0
                last_target_x = target_x
                if stalled_target_checks >= 8:
                    self.controller.move_mouse_relative(self.REWARD_SEARCH_TURN_PIXELS, 0)
                    self.log(
                        f"    第{cycle_index}轮：同一金色目标连续多次没有变得更清晰且仍无吸收提示，"
                        "按固定场景物体处理并转向继续搜索。"
                    )
                    last_target_x = None
                    best_target_confidence = 0.0
                    stalled_target_checks = 0
                    self._sleep_interruptible(0.14)
                    continue
                offset_x = target_x - width * 0.5
                movement = self._approach_4c_gold_target(offset_x, width)
                self.log(
                    f"    第{cycle_index}轮：已看到金色待吸收声骸（目标强度 {gold_ratio:.4f}），"
                    f"{movement}。"
                )
            else:
                last_target_x = None
                best_target_confidence = 0.0
                stalled_target_checks = 0
                self.controller.move_mouse_relative(self.REWARD_SEARCH_TURN_PIXELS, 0)
                self.log(
                    f"    第{cycle_index}轮：目标置信度 {gold_ratio:.3f} 未超过0.1，固定向右大幅转动 "
                    f"{self.REWARD_SEARCH_TURN_PIXELS} 搜索。"
                )
            self._sleep_interruptible(0.14)
        raise RuntimeError("击败首领后未能找到“F / 吸收”提示，已停止循环。")

    def _approach_4c_gold_target(self, offset_x: float, screen_width: int) -> str:
        """Approach a visible echo without violating the right-only camera search."""
        centre_tolerance = screen_width * 0.045
        if offset_x < -centre_tolerance:
            # Keep the camera direction stable and strafe toward a visible target;
            # a full rightward wrap used to throw left-side echoes out of view.
            self.controller.press_keys(("W", "A"), 400)
            return "目标在左侧，向左前方靠近"
        if offset_x > centre_tolerance:
            turn = int(max(110, min(360, offset_x * 0.40)))
            self.controller.move_mouse_relative(turn, 0)
            self.controller.press_keys(("W",), 360)
            return "目标在右侧，向右微调并靠近"
        self.controller.press_keys(("W",), 500)
        return "目标已在中央，直线靠近"

    def _find_4c_absorb_prompt(self, screenshot: Path, scale: float):
        best = None
        best_name = ""
        with Image.open(screenshot) as captured:
            width, height = captured.size
        prompt_region = (
            round(width * 0.42),
            round(height * 0.22),
            round(width * 0.96),
            round(height * 0.86),
        )
        scales = []
        for candidate in (scale, scale * 0.94, scale * 0.97, scale * 1.03, scale * 1.06, scale * 0.88, scale * 1.12):
            if candidate > 0.2 and all(abs(candidate - known) > 0.01 for known in scales):
                scales.append(candidate)
        for template_name in self.ABSORB_PROMPT_TEMPLATES:
            text_crop = self.ABSORB_TEXT_CROPS[template_name]
            for candidate_scale in scales:
                try:
                    match = self.matcher.find_fast(
                        screenshot,
                        template_name,
                        threshold=0.80,
                        scale=candidate_scale,
                        region=prompt_region,
                        template_crop=text_crop,
                    )
                except Exception:
                    continue
                if best is None or match.score > best.score:
                    best = match
                    best_name = template_name
                if match.score >= 0.90:
                    return match, template_name
        return best, best_name

    def _restart_4c_challenge(self, next_cycle: int) -> None:
        self.log(f"    吸收完成，按 Esc 并准备第 {next_cycle} 轮。")
        self.controller.press_key("ESC", 70)
        self._sleep_interruptible(0.85)
        probe = Step(
            action="tap_image",
            template="restart_challenge.png",
            threshold=0.75,
            timeout=10.0,
            offset_x=0,
            offset_y=0,
        )
        x, y, score = self._find_image(probe)
        self.log(f"    找到重新挑战按钮：({x}, {y})，相似度 {score:.3f}。")
        self.controller.tap(x, y)
        self._sleep_interruptible(3.0)

    @staticmethod
    def _boss_health_ratio(screenshot: Path) -> float:
        with Image.open(screenshot) as source:
            image = np.asarray(source.convert("RGB"))
        height, width = image.shape[:2]
        expected_game_height = round(width * 9 / 16)
        titlebar_height = max(0, height - expected_game_height)
        game_height = height - titlebar_height
        top = max(0, titlebar_height + round(game_height * 0.035))
        bottom = min(height, titlebar_height + round(game_height * 0.070))
        left = max(0, round(width * 0.34))
        right = min(width, round(width * 0.66))
        region = image[top:bottom, left:right]
        if region.size == 0:
            return 0.0
        red = region[:, :, 0].astype(np.float32)
        green = region[:, :, 1].astype(np.float32)
        blue = region[:, :, 2].astype(np.float32)
        colored_health = (
            (red > 145)
            & (red > green * 1.12)
            & (red > blue * 1.22)
            & ((green > 55) | (red > 190))
        )
        return float(colored_health.mean())

    @staticmethod
    def _boss_name_ratio(screenshot: Path) -> float:
        with Image.open(screenshot) as source:
            image = np.asarray(source.convert("RGB")).astype(np.float32)
        height, width = image.shape[:2]
        titlebar_height = max(0, height - round(width * 9 / 16))
        game_height = height - titlebar_height
        top = titlebar_height + round(game_height * 0.008)
        bottom = titlebar_height + round(game_height * 0.045)
        left, right = round(width * 0.34), round(width * 0.66)
        region = image[top:bottom, left:right]
        if region.size == 0:
            return 0.0
        high = region.max(axis=2)
        low = region.min(axis=2)
        bright_name = (
            (region[:, :, 0] > 165)
            & (region[:, :, 1] > 155)
            & (region[:, :, 2] > 145)
            & ((high - low) < 95)
        )
        return float(bright_name.mean())

    @staticmethod
    def _boss_bar_track_score(screenshot: Path) -> float:
        with Image.open(screenshot) as source:
            image = np.asarray(source.convert("RGB")).astype(np.float32)
        height, width = image.shape[:2]
        titlebar_height = max(0, height - round(width * 9 / 16))
        game_height = height - titlebar_height
        top = titlebar_height + round(game_height * 0.035)
        bottom = titlebar_height + round(game_height * 0.075)
        left, right = round(width * 0.34), round(width * 0.66)
        region = image[top:bottom, left:right]
        if region.size == 0:
            return 0.0
        high = region.max(axis=2)
        low = region.min(axis=2)
        neutral_track = ((high - low) < 45) & (high > 85)
        return float(neutral_track.mean(axis=1).max())

    @staticmethod
    def _gold_target_location(screenshot: Path) -> tuple[float, int | None, int | None]:
        with Image.open(screenshot) as source:
            image = np.asarray(source.convert("RGB"))
        height, width = image.shape[:2]
        # High signs are excluded. The lower world view remains searchable because
        # a small echo can sit near the character; lower candidates must be more
        # solid so hollow golden combat rings are rejected.
        top, bottom = round(height * 0.18), round(height * 0.84)
        left, right = round(width * 0.08), round(width * 0.92)
        region = image[top:bottom, left:right]
        red = region[:, :, 0].astype(np.float32)
        green = region[:, :, 1].astype(np.float32)
        blue = region[:, :, 2].astype(np.float32)
        # Absorbable echoes are a saturated deep orange-gold. Pale yellow-white
        # reflections and floor lights must not be treated as navigation targets.
        maximum = np.maximum.reduce((red, green, blue))
        minimum = np.minimum.reduce((red, green, blue))
        saturation = (maximum - minimum) / np.maximum(maximum, 1.0)
        gold = (
            (red > 150)
            & (green > 85)
            & (blue < 145)
            & (saturation >= 0.42)
            & ((red - green) > 18)
            & ((green - blue) > 18)
        )
        if not gold.any():
            return 0.0, None, None

        # Downsample once and lightly join glow fragments. The component filter
        # below accepts small compact echoes, but rejects long rails and streaks.
        sample_step = 3
        sampled = gold[::sample_step, ::sample_step]
        padded = np.pad(sampled, 1, mode="constant")
        expanded = np.logical_or.reduce(
            [
                padded[dy : dy + sampled.shape[0], dx : dx + sampled.shape[1]]
                for dy in range(3)
                for dx in range(3)
            ]
        )

        visited = np.zeros(expanded.shape, dtype=bool)
        best_points: list[tuple[int, int]] = []
        best_score = 0.0
        best_confidence = 0.0
        rows, columns = expanded.shape
        for start_y, start_x in zip(*np.nonzero(expanded & ~visited)):
            if visited[start_y, start_x]:
                continue
            stack = [(int(start_y), int(start_x))]
            visited[start_y, start_x] = True
            points = []
            while stack:
                y, x = stack.pop()
                points.append((y, x))
                for dy in (-1, 0, 1):
                    for dx in (-1, 0, 1):
                        ny, nx = y + dy, x + dx
                        if 0 <= ny < rows and 0 <= nx < columns and expanded[ny, nx] and not visited[ny, nx]:
                            visited[ny, nx] = True
                            stack.append((ny, nx))
            ys = [point[0] for point in points]
            xs = [point[1] for point in points]
            component_height = max(ys) - min(ys) + 1
            component_width = max(xs) - min(xs) + 1
            aspect = max(component_width / component_height, component_height / component_width)
            compactness = len(points) / max(1, component_width * component_height)
            component_center_y = (sum(ys) / len(ys)) * sample_step + top
            component_center_x = (sum(xs) / len(xs)) * sample_step
            minimum_compactness = 0.68 if component_center_y > height * 0.60 else 0.43
            valid_shape = aspect <= 2.05 or (
                component_width > component_height and aspect <= 2.80
            )
            # A common false positive is the small gold ring mounted beneath the
            # large yellow MILITECH billboard. Reject a candidate when a broad,
            # dense gold panel occupies the area well above it. Real echoes do not
            # have a billboard-sized gold slab suspended over their position.
            overhead = gold[
                max(0, round(component_center_y - top - height * 0.40)):
                max(1, round(component_center_y - top - height * 0.10)),
                max(0, round(component_center_x - width * 0.16)):
                min(gold.shape[1], round(component_center_x + width * 0.16)),
            ]
            overhead_gold_ratio = float(overhead.mean()) if overhead.size else 0.0
            # Distant echoes form a medium-sized compact cluster. Tiny golden UI
            # marks and large billboards sit outside this range; a very close echo
            # is handled by the F/absorb prompt before colour navigation runs.
            if (
                len(points) < 100
                or len(points) > 1400
                or not valid_shape
                or compactness < minimum_compactness
                or overhead_gold_ratio > 0.055
            ):
                continue
            score = len(points) * compactness
            if score > best_score:
                best_score = score
                best_points = points
                best_confidence = compactness

        if not best_points:
            return float(len(best_points) / max(1, expanded.size)), None, None
        ys = np.fromiter((point[0] for point in best_points), dtype=np.float32)
        xs = np.fromiter((point[1] for point in best_points), dtype=np.float32)
        return (
            float(best_confidence),
            round(float(xs.mean()) * sample_step + left),
            round(float(ys.mean()) * sample_step + top),
        )

    def _run_visual_navigation(self, step: Step) -> None:
        if not hasattr(self.controller, "press_keys"):
            raise RuntimeError("群声共振模拟域目前只支持 PC 客户端窗口。")
        if not step.template:
            raise ValueError("视觉导航步骤需要填写交互提示模板。")
        target_templates = step.templates or ["npc_far.png", "npc_near.png"]
        deadline = time.monotonic() + max(5.0, step.timeout)
        misses = 0
        screenshot = APP_DIR / "_runtime_screenshot.png"
        try:
            while time.monotonic() < deadline:
                if self.stop_event.is_set():
                    self.log("    收到停止信号，已停止移动并释放方向键。")
                    return
                self._capture_for_matching(screenshot)
                scale = float(getattr(self.controller, "scale", 1.0))

                try:
                    prompt = self.matcher.find_fast(
                        screenshot,
                        step.template,
                        threshold=max(0.70, step.threshold),
                        scale=scale,
                    )
                except Exception:
                    prompt = None
                if prompt is not None:
                    self.log(f"    已靠近守岸人，交互提示相似度 {prompt.score:.3f}。")
                    if self.dry_run:
                        self.log("    干运行：已识别 F 交互提示，但不按键。")
                    else:
                        self.controller.release_keys()
                        self.controller.press_key("F", 90)
                        self.log("    已松开方向键并按下 F。")
                    return

                best = None
                best_name = ""
                for template_name in target_templates:
                    try:
                        candidate = self.matcher.find(screenshot, template_name, -1.0, [scale])
                    except Exception:
                        continue
                    if best is None or candidate.score > best.score:
                        best = candidate
                        best_name = template_name

                if best is None or best.score < step.threshold:
                    misses += 1
                    self.log(f"    暂未定位到蓝色守岸人（{misses}/4），保持原地重新观察。")
                    if misses >= 4:
                        raise RuntimeError("连续 4 次没有定位到蓝色守岸人，已停止移动。请让角色与守岸人同时出现在画面中。")
                    self._sleep_interruptible(0.18)
                    continue

                misses = 0
                with Image.open(screenshot) as captured:
                    width, height = captured.size
                target_x, target_y = best.center
                anchor_x, anchor_y = width * 0.52, height * 0.51
                dx, dy = target_x - anchor_x, target_y - anchor_y
                dead_x, dead_y = width * 0.025, height * 0.03
                keys: list[str] = []
                if dy < -dead_y:
                    keys.append("W")
                elif dy > dead_y:
                    keys.append("S")
                if dx < -dead_x:
                    keys.append("A")
                elif dx > dead_x:
                    keys.append("D")
                if not keys:
                    keys.append("W")

                distance = (dx * dx + dy * dy) ** 0.5
                pulse_ms = min(max(step.duration_ms, 60), 180)
                if distance < max(width, height) * 0.10:
                    pulse_ms = min(pulse_ms, 80)
                elif distance < max(width, height) * 0.20:
                    pulse_ms = min(pulse_ms, 120)
                self.log(
                    f"    {best_name} 相似度 {best.score:.3f}，目标偏移 "
                    f"({dx:+.0f}, {dy:+.0f})，短按 {'+'.join(keys)} {pulse_ms}ms。"
                )
                if self.dry_run:
                    self.log("    干运行：已算出移动方向，但不发送键盘操作。")
                    return
                self.controller.press_keys(keys, pulse_ms)
                self._sleep_interruptible(0.12)
            raise RuntimeError("靠近守岸人超时，已停止移动并释放方向键。")
        finally:
            if not self.dry_run:
                try:
                    self.controller.release_keys()
                except Exception as exc:
                    self.log(f"    释放方向键时遇到问题: {exc}")

    def _run_image_cycle(self, step: Step) -> None:
        templates = step.templates or self._numbered_templates("menu", 2, 99)
        if not templates:
            raise RuntimeError("循环模板列表为空。")
        previous_step = self.last_clicked_image_step
        round_index = 1
        while not self.stop_event.is_set():
            if self.max_cycles is not None and round_index > self.max_cycles:
                self.log(f"    已完成 {self.max_cycles} 轮循环，自动停止。")
                self.stop_event.set()
                return
            self.log(f"    开始第 {round_index} 轮循环。")
            for template_name in templates:
                if self.stop_event.is_set():
                    self.log("收到停止信号，循环任务已中断。")
                    return
                if not (self.template_root / template_name).exists():
                    if not step.skip_missing:
                        raise FileNotFoundError(f"模板不存在: {template_name}")
                    continue
                current = Step(
                    action="tap_image",
                    label=f"识别并点击 {template_name}",
                    template=template_name,
                    threshold=step.threshold,
                    timeout=step.timeout,
                    offset_x=self._template_offset(step, template_name, "x"),
                    offset_y=self._template_offset(step, template_name, "y"),
                    seconds=step.seconds,
                )
                x, y, score = self._wait_for_cycle_template(current, previous_step)
                self.log(f"    找到 {template_name}: ({x}, {y}) 相似度 {score:.3f}")
                if self.dry_run:
                    self.log("    干运行：已识别位置，但不点击。")
                else:
                    self._click_cycle_template(current, x, y)
                previous_step = current
                self._sleep_click_interval(step.seconds)
            if not step.loop:
                return
            if self.max_cycles is not None and round_index >= self.max_cycles:
                if previous_step is not None and not self.dry_run:
                    self._verify_final_cycle_click(previous_step)
                self.log(f"    已完成 {self.max_cycles} 轮循环，自动停止。")
                self.stop_event.set()
                return
            round_index += 1

    def _wait_for_cycle_template(
        self,
        step: Step,
        previous_step: Step | None = None,
    ) -> tuple[int, int, float]:
        misses = 0
        while not self.stop_event.is_set():
            try:
                return self._find_image(step)
            except Exception as exc:
                misses += 1
                if (
                    previous_step is not None
                    and not self.dry_run
                    and misses in CYCLE_FALLBACK_MISS_COUNTS
                ):
                    self._retry_previous_cycle_click(previous_step, step.template, misses)
                if misses >= CYCLE_MAX_MISSES:
                    self.stop_event.set()
                    raise RuntimeError(
                        f"累计 {CYCLE_MAX_MISSES} 次未找到 {step.template}，"
                        f"回退验证后仍无法推进，已自动停止。最后错误: {exc}"
                    )
                self.log(f"    等待 {step.template} 出现（第 {misses}/{CYCLE_MAX_MISSES} 次）: {exc}")
                self._sleep_interruptible(0.15)
        raise RuntimeError("循环任务已停止。")

    def _retry_previous_cycle_click(self, previous_step: Step, expected_template: str, misses: int) -> bool:
        probe = replace(previous_step, timeout=min(max(previous_step.timeout, 0.5), 1.0))
        self.log(
            f"    回退验证：{expected_template} 已连续 {misses} 次未出现，"
            f"检查上一张 {previous_step.template}。"
        )
        try:
            x, y, score = self._find_image(probe)
        except Exception as exc:
            self.log(f"    回退验证：上一张已不在画面，继续等待 {expected_template}: {exc}")
            return False

        self.log(
            f"    回退验证命中 {previous_step.template}: ({x}, {y}) "
            f"相似度 {score:.3f}，执行补点。"
        )
        self._click_cycle_template(previous_step, x, y, recovery=True)
        self._sleep_click_interval(previous_step.seconds)
        return True

    def _click_cycle_template(self, step: Step, x: int, y: int, recovery: bool = False) -> None:
        action = "回退补点" if recovery else "正在点击识别坐标"
        self.log(f"    {action}: ({x}, {y})")
        result = self.controller.tap(x, y)
        if isinstance(result, dict):
            self.log(
                "    鼠标移动结果: "
                f"目标{result.get('target')}，"
                f"移动后{result.get('after_move')}，"
                f"SetCursorPos={result.get('set_cursor_ok')}"
            )
            if not result.get("set_cursor_ok"):
                self.log("    鼠标没有移动成功：请尝试右键桌面快捷方式，以管理员身份运行。")
        self.last_clicked_image_step = step

    def _verify_final_cycle_click(self, final_step: Step) -> None:
        probe = replace(final_step, timeout=min(max(final_step.timeout, 0.5), 1.0))
        self.log(f"    最终轮验证：确认 {final_step.template} 已响应点击。")
        for retry_index in range(CYCLE_FINAL_MAX_RETRIES + 1):
            try:
                x, y, score = self._find_image(probe)
            except Exception:
                self.log(f"    最终轮验证通过：{final_step.template} 已离开当前画面。")
                return

            if retry_index >= CYCLE_FINAL_MAX_RETRIES:
                self.stop_event.set()
                raise RuntimeError(
                    f"最终模板 {final_step.template} 补点 {CYCLE_FINAL_MAX_RETRIES} 次后仍停留在画面，"
                    "任务已自动停止，请检查游戏状态。"
                )

            self.log(
                f"    最终轮回退命中 {final_step.template}: ({x}, {y}) "
                f"相似度 {score:.3f}，执行第 {retry_index + 1}/{CYCLE_FINAL_MAX_RETRIES} 次补点。"
            )
            self._click_cycle_template(final_step, x, y, recovery=True)
            self._sleep_click_interval(final_step.seconds)

    def _sleep_interruptible(self, seconds: float) -> None:
        deadline = time.time() + seconds
        while time.time() < deadline:
            if self.stop_event.is_set():
                return
            time.sleep(min(0.1, deadline - time.time()))

    def _sleep_click_interval(self, base_seconds: float) -> None:
        minimum = max(0.0, base_seconds - CLICK_DELAY_JITTER_SECONDS)
        maximum = max(minimum, base_seconds + CLICK_DELAY_JITTER_SECONDS)
        self._sleep_interruptible(random.uniform(minimum, maximum))

    def _numbered_templates(self, prefix: str, start: int, end: int) -> list[str]:
        names = []
        for path in self.template_root.glob(f"{prefix}*.png"):
            match = re.fullmatch(rf"{re.escape(prefix)}(\d+)\.png", path.name)
            if not match:
                continue
            number = int(match.group(1))
            if start <= number <= end:
                names.append((number, path.name))
        return [name for _number, name in sorted(names)]

    @staticmethod
    def _template_offset(step: Step, template_name: str, axis: str) -> int:
        specific = step.template_offsets.get(template_name, {})
        value = specific.get(axis)
        if value is not None:
            return int(value)
        return step.offset_x if axis == "x" else step.offset_y

    def _find_image(self, step: Step) -> tuple[int, int, float]:
        if not step.template:
            raise ValueError("tap_image 步骤需要 template 字段")
        deadline = time.time() + step.timeout
        last_error: Exception | None = None
        while time.time() <= deadline:
            if self.stop_event.is_set():
                raise RuntimeError("已停止模板识别。")
            screenshot = APP_DIR / "_runtime_screenshot.png"
            self._capture_for_matching(screenshot)
            try:
                scales = self._fast_scales()
                match = self.matcher.find(screenshot, step.template, step.threshold, scales)
                image_x, image_y = self._random_click_point(match, step.offset_x, step.offset_y)
                if self.debug_matches:
                    self._save_match_debug(screenshot, step.template, match, image_x, image_y)
                if hasattr(self.controller, "screenshot_to_screen"):
                    screen_x, screen_y = self.controller.screenshot_to_screen(image_x, image_y)
                    self.log(f"    截图坐标 ({image_x}, {image_y}) 将点击屏幕坐标 ({screen_x}, {screen_y})")
                    return image_x, image_y, match.score
                if hasattr(self.controller, "screenshot_to_client"):
                    client_x, client_y = self.controller.screenshot_to_client(image_x, image_y)
                    self.log(f"    截图坐标 ({image_x}, {image_y}) 已换算为窗口坐标 ({client_x}, {client_y})")
                    return client_x, client_y, match.score
                return image_x, image_y, match.score
            except Exception as exc:
                last_error = exc
                time.sleep(0.6)
        raise RuntimeError(str(last_error) if last_error else f"识别超时: {step.template}")

    @staticmethod
    def _random_click_point(match, offset_x: int, offset_y: int) -> tuple[int, int]:
        margin_x = min(max(1, int(round(match.width * CLICK_EDGE_MARGIN_RATIO))), max(1, (match.width - 1) // 2))
        margin_y = min(max(1, int(round(match.height * CLICK_EDGE_MARGIN_RATIO))), max(1, (match.height - 1) // 2))
        safe_left = match.x + margin_x
        safe_right = match.x + match.width - 1 - margin_x
        safe_top = match.y + margin_y
        safe_bottom = match.y + match.height - 1 - margin_y

        anchor_x = min(max(match.center[0] + offset_x, safe_left), safe_right)
        anchor_y = min(max(match.center[1] + offset_y, safe_top), safe_bottom)
        jitter_x = max(1, int(round(match.width * CLICK_JITTER_RATIO)))
        jitter_y = max(1, int(round(match.height * CLICK_JITTER_RATIO)))

        left = max(safe_left, anchor_x - jitter_x)
        right = min(safe_right, anchor_x + jitter_x)
        top = max(safe_top, anchor_y - jitter_y)
        bottom = min(safe_bottom, anchor_y + jitter_y)
        return random.randint(left, right), random.randint(top, bottom)

    def _fast_scales(self) -> list[float]:
        if hasattr(self.controller, "template_scales"):
            scales = self.controller.template_scales()
            if isinstance(scales, (list, tuple)) and scales:
                return [float(scale) for scale in scales]
        return [1.0]

    def _save_match_debug(self, screenshot: Path, template_name: str, match, click_x: int, click_y: int) -> None:
        try:
            debug_dir = APP_DIR / "debug"
            debug_dir.mkdir(exist_ok=True)
            image = Image.open(screenshot).convert("RGB")
            draw = ImageDraw.Draw(image)
            draw.rectangle(
                [match.x, match.y, match.x + match.width, match.y + match.height],
                outline="red",
                width=4,
            )
            size = 28
            draw.line([click_x - size, click_y, click_x + size, click_y], fill="yellow", width=4)
            draw.line([click_x, click_y - size, click_x, click_y + size], fill="yellow", width=4)
            safe_name = template_name.replace("/", "_").replace("\\", "_")
            target = debug_dir / f"last_match_{safe_name}"
            image.save(target)
            self.log(f"    调试图已保存: {target}")
        except Exception as exc:
            self.log(f"    调试图保存失败: {exc}")

    def _capture_for_matching(self, target: Path) -> None:
        try:
            self.controller.screencap(target, bring_to_front=not self.dry_run)
        except TypeError:
            self.controller.screencap(target)

    @staticmethod
    def _require_xy(step: Step) -> None:
        if step.x is None or step.y is None:
            raise ValueError("tap 步骤需要 x/y")


class TemplateCropper:
    def __init__(self, parent: Tk, source_path: Path, templates_dir: Path, log):
        self.source_path = source_path
        self.templates_dir = templates_dir
        self.log = log
        self.window = Toplevel(parent)
        self.window.title("制作识别模板")
        self.window.geometry("1120x760")
        self.image = Image.open(source_path).convert("RGB")
        self.scale = min(1060 / self.image.width, 660 / self.image.height, 1.0)
        preview_size = (int(self.image.width * self.scale), int(self.image.height * self.scale))
        self.preview = self.image.resize(preview_size, Image.Resampling.BILINEAR)
        self.photo = ImageTk.PhotoImage(self.preview)
        self.start_x = 0
        self.start_y = 0
        self.rect_id: int | None = None
        self.selection: tuple[int, int, int, int] | None = None

        Label(self.window, text="在截图上拖框选择按钮或图标，建议包含文字/边框等明显特征。").pack(side=TOP, fill=X, padx=10, pady=6)
        self.canvas = Canvas(self.window, width=preview_size[0], height=preview_size[1], cursor="crosshair")
        self.canvas.pack(side=TOP, padx=10, pady=6)
        self.canvas.create_image(0, 0, anchor="nw", image=self.photo)
        self.canvas.bind("<ButtonPress-1>", self._start)
        self.canvas.bind("<B1-Motion>", self._drag)
        self.canvas.bind("<ButtonRelease-1>", self._finish)

        buttons = Frame(self.window, padx=10, pady=8)
        buttons.pack(side=TOP, fill=X)
        Button(buttons, text="保存模板", command=self._save).pack(side=LEFT)
        Button(buttons, text="关闭", command=self.window.destroy).pack(side=LEFT, padx=8)

    def _start(self, event) -> None:
        self.start_x = event.x
        self.start_y = event.y
        if self.rect_id is not None:
            self.canvas.delete(self.rect_id)
        self.rect_id = self.canvas.create_rectangle(event.x, event.y, event.x, event.y, outline="#00d084", width=2)

    def _drag(self, event) -> None:
        if self.rect_id is not None:
            self.canvas.coords(self.rect_id, self.start_x, self.start_y, event.x, event.y)

    def _finish(self, event) -> None:
        x1, x2 = sorted((self.start_x, event.x))
        y1, y2 = sorted((self.start_y, event.y))
        self.selection = (x1, y1, x2, y2)

    def _save(self) -> None:
        if not self.selection:
            messagebox.showinfo("提示", "请先拖框选择一个模板区域。", parent=self.window)
            return
        name = simpledialog.askstring("模板文件名", "输入模板文件名，例如 menu.png", parent=self.window)
        if not name:
            return
        if not name.lower().endswith(".png"):
            name += ".png"
        safe_name = Path(name).name
        x1, y1, x2, y2 = self.selection
        if abs(x2 - x1) < 8 or abs(y2 - y1) < 8:
            messagebox.showinfo("提示", "选择区域太小，请框大一点。", parent=self.window)
            return
        crop_box = (
            int(x1 / self.scale),
            int(y1 / self.scale),
            int(x2 / self.scale),
            int(y2 / self.scale),
        )
        target = self.templates_dir / safe_name
        self.image.crop(crop_box).save(target)
        self.log(f"模板已保存: {target}")
        messagebox.showinfo("已保存", f"模板已保存:\n{target}", parent=self.window)
        self.window.destroy()


class App:
    def __init__(self, root: Tk):
        self.root = root
        self.pet_id = self._load_pet_preference()
        self.theme_id = self._load_theme_preference()
        if self.theme_id in PET_DEFINITIONS and self.pet_id != self.theme_id:
            self.pet_id = self.theme_id
            PET_CONFIG.write_text(json.dumps({"pet": self.pet_id}, ensure_ascii=False), encoding="utf-8")
        self.pet_definition = PET_DEFINITIONS[self.pet_id]
        self.pet_name = str(self.pet_definition["name"])
        COLORS.clear()
        COLORS.update(THEME_DEFINITIONS.get(self.theme_id, {}).get("colors", SIMPLE_COLORS))
        self.root.title(f"wwbs {APP_VERSION}")
        self._app_icon_photo = None
        if APP_ICON.exists():
            self.root.iconbitmap(str(APP_ICON))
            try:
                with Image.open(APP_ICON) as icon_image:
                    self._app_icon_photo = ImageTk.PhotoImage(icon_image.convert("RGBA"))
                self.root.iconphoto(True, self._app_icon_photo)
            except Exception:
                pass
        apply_windows_taskbar_icon(self.root, APP_ICON)
        self.root.after(250, lambda: apply_windows_taskbar_icon(self.root, APP_ICON))
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        reference_screen = (2560, 1440)
        window_scale = min(1.0, screen_width / reference_screen[0], screen_height / reference_screen[1])
        target_size = round(1280 * window_scale)
        target_size = min(target_size, screen_width - 60, screen_height - 60)
        target_size = max(640, target_size)
        position_x = max(0, (screen_width - target_size) // 2)
        position_y = max(0, (screen_height - target_size) // 2)
        self.root.geometry(f"{target_size}x{target_size}+{position_x}+{position_y}")
        self.root.minsize(
            min(900, max(640, screen_width - 80)),
            min(720, max(560, screen_height - 80)),
        )
        self.config_path = StringVar(value=str(DEFAULT_CONFIG))
        self.target_mode = StringVar(value="client")
        self.window_title = StringVar(value="自动")
        self.expected_resolution = StringVar(value="1920x1080")
        self.adb_path = StringVar(value="adb")
        self.device_id = StringVar(value="")
        self.combat_skill_key = StringVar(value=self._load_combat_skill_key())
        self.combat_ultimate_key = StringVar(value=self._load_combat_ultimate_key())
        self.daily_heal_enabled = BooleanVar(value=self._load_daily_heal_enabled())
        self.daily_zone = StringVar(value=self._load_daily_zone())
        self.pet_size = StringVar(value=f"{self._load_pet_size_percent()}%")
        self.pet_visible = self._load_pet_visible()
        self.dry_run = BooleanVar(value=True)
        self.status = StringVar(value="准备就绪")
        self.device_status = StringVar(value="窗口未检测")
        self.template_status = StringVar(value="模板 0 个")
        self.prob_astrite = StringVar(value="0")
        self.prob_pulls = StringVar(value="0")
        self.prob_character_pity = StringVar(value="0")
        self.prob_character_guaranteed = BooleanVar(value=False)
        self.prob_weapon_pity = StringVar(value="0")
        self.prob_character_target = StringVar(value="0")
        self.prob_weapon_target = StringVar(value="0")
        self.prob_result = StringVar(value="输入星声、角色水位、武器水位和目标数量后，点击计算。")
        self._syncing_probability_inputs = False
        self.prob_astrite.trace_add("write", self._sync_pulls_from_astrite)
        self.prob_pulls.trace_add("write", self._sync_astrite_from_pulls)
        self.template_group = StringVar(value=DEFAULT_GROUP_NAME)
        self.log_queue: queue.Queue[str] = queue.Queue()
        self.tasks: list[WeeklyTask] = []
        self.stop_event = threading.Event()
        self.worker: threading.Thread | None = None
        self.max_cycles: int | None = None
        self.preview_photo = None
        self.preview_source: Path | None = None
        self.preview_title = ""
        self.desktop_pet: DesktopPet | None = None
        self.theme_status = StringVar(value=self._theme_status_text())
        self.pet_status = StringVar(value=f"当前：{self.pet_name}")
        self.theme_banner_photo = None
        self.theme_banner_source = None
        self._theme_banner_resize_job = None
        self._hotkey_thread_id: int | None = None
        self._hotkey_registered = False
        self._hotkey_ready = threading.Event()
        self._hotkey_triggered = threading.Event()
        self._hotkey_status_reported = False
        self._hotkey_poll_job = None
        self._hotkey_was_down = False
        self._last_hotkey_stop_at = 0.0
        self._last_mouse_admin_warning_at = 0.0
        self._admin_restart_requested = False
        self._preflight_running = False
        self._last_started_tasks: list[WeeklyTask] = []
        self._last_task_started_at = 0.0

        self._build_ui()
        self._load_config(silent=True)
        self._refresh_templates()
        self._drain_logs()
        self.root.protocol("WM_DELETE_WINDOW", self._close_app)
        self._start_stop_hotkey()
        self.root.after(120, self._start_desktop_pet)
        self.root.after(300, self._show_update_notice)

    @staticmethod
    def _theme_pack_valid(theme_id: str, path: Path | None = None) -> bool:
        definition = THEME_DEFINITIONS.get(theme_id)
        if definition is None:
            return False
        candidate = path or Path(definition["pack"])
        try:
            with zipfile.ZipFile(candidate) as archive:
                names = set(archive.namelist())
                if not {"theme.json", "background.webp"}.issubset(names):
                    return False
                manifest = json.loads(archive.read("theme.json").decode("utf-8"))
                return manifest.get("id") == definition["manifest_id"]
        except (OSError, ValueError, KeyError, zipfile.BadZipFile, json.JSONDecodeError):
            return False

    @classmethod
    def _load_theme_preference(cls) -> str:
        try:
            saved = json.loads(THEME_CONFIG.read_text(encoding="utf-8"))
            # Older beta packages stored a character theme beside the executable.
            # When users extracted a new build over that folder, the stale file
            # incorrectly replaced the intended simple default. Only preferences
            # explicitly written by the current build are now restored.
            if saved.get("explicit") is not True or saved.get("source") != "theme-picker":
                return "simple"
            selected = saved.get("theme", "simple")
        except (OSError, ValueError, json.JSONDecodeError):
            selected = "simple"
        if selected in THEME_DEFINITIONS and cls._theme_pack_valid(selected):
            return selected
        return "simple"

    @staticmethod
    def _load_pet_preference() -> str:
        try:
            selected = json.loads(PET_CONFIG.read_text(encoding="utf-8")).get("pet", "daniya")
        except (OSError, ValueError, json.JSONDecodeError):
            selected = "daniya"
        definition = PET_DEFINITIONS.get(selected)
        if definition and Path(definition["frames"]).exists():
            return selected
        return "daniya"

    @staticmethod
    def _normalize_pet_size_percent(value: object) -> int:
        try:
            percent = int(round(float(str(value).strip().rstrip("%"))))
        except (TypeError, ValueError):
            return 100
        return max(60, min(160, percent))

    @classmethod
    def _load_pet_size_percent(cls) -> int:
        saved = cls._load_pet_display_settings().get("percent", 100)
        return cls._normalize_pet_size_percent(saved)

    @staticmethod
    def _load_pet_display_settings() -> dict[str, object]:
        try:
            saved = json.loads(PET_DISPLAY_CONFIG.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            return {}
        return saved if isinstance(saved, dict) else {}

    @classmethod
    def _load_pet_visible(cls) -> bool:
        return cls._load_pet_display_settings().get("visible", True) is not False

    def _save_pet_display_settings(self, **changes: object) -> None:
        saved = self._load_pet_display_settings()
        saved.update(changes)
        PET_DISPLAY_CONFIG.write_text(
            json.dumps(saved, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _save_pet_visibility(self, visible: bool) -> None:
        self.pet_visible = bool(visible)
        self._save_pet_display_settings(visible=self.pet_visible)

    def _apply_pet_size(self, _event=None) -> None:
        percent = self._normalize_pet_size_percent(self.pet_size.get())
        self.pet_size.set(f"{percent}%")
        self._save_pet_display_settings(percent=percent)
        if self.desktop_pet is not None:
            base_scale = float(self.pet_definition.get("scale", 1.15))
            self.desktop_pet.set_scale(base_scale * percent / 100.0)
        self.status.set(f"桌宠大小已调整为 {percent}%")
        self._log(f"桌宠大小已调整为 {percent}%，设置已自动保存。")

    def _set_pet_size_percent(self, percent: int) -> None:
        self.pet_size.set(f"{self._normalize_pet_size_percent(percent)}%")
        self._apply_pet_size()

    @staticmethod
    def _load_combat_skill_key() -> str:
        try:
            selected = json.loads(COMBAT_CONFIG.read_text(encoding="utf-8")).get("skill_key", "E")
            normalized = ClientWindowController.normalize_input_binding(str(selected))
            return App._combat_binding_display(normalized)
        except (OSError, ValueError, json.JSONDecodeError):
            return "E"

    @staticmethod
    def _load_combat_ultimate_key() -> str:
        try:
            selected = json.loads(COMBAT_CONFIG.read_text(encoding="utf-8")).get("ultimate_key", "R")
            normalized = ClientWindowController.normalize_input_binding(str(selected))
            return App._combat_binding_display(normalized)
        except (OSError, ValueError, json.JSONDecodeError):
            return "R"

    @staticmethod
    def _load_daily_heal_enabled() -> bool:
        try:
            saved = json.loads(COMBAT_CONFIG.read_text(encoding="utf-8"))
            return saved.get("daily_heal_enabled") is True
        except (OSError, ValueError, json.JSONDecodeError):
            return False

    @staticmethod
    def _load_daily_zone() -> str:
        try:
            selected = str(json.loads(DAILY_CONFIG.read_text(encoding="utf-8")).get("zone", ""))
        except (OSError, ValueError, json.JSONDecodeError):
            selected = ""
        return selected if selected in DAILY_ZONE_TEMPLATES else DAILY_ZONE_NAMES[0]

    def _save_daily_zone(self, _event=None) -> None:
        selected = self.daily_zone.get()
        if selected not in DAILY_ZONE_TEMPLATES:
            return
        DAILY_CONFIG.write_text(
            json.dumps({"zone": selected}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self.status.set(f"一键日常无音区：{selected}")

    def _scroll_daily_zone(self, event) -> str:
        selected = self.daily_zone.get()
        try:
            index = DAILY_ZONE_NAMES.index(selected)
        except ValueError:
            index = 0
        direction = -1 if event.delta > 0 else 1
        index = max(0, min(len(DAILY_ZONE_NAMES) - 1, index + direction))
        self.daily_zone.set(DAILY_ZONE_NAMES[index])
        self._save_daily_zone()
        return "break"

    @staticmethod
    def _combat_binding_display(binding: str) -> str:
        normalized = str(binding).upper()
        return {
            "XBUTTON1": "鼠标侧键1",
            "XBUTTON2": "鼠标侧键2",
            "SPACE": "空格键",
            "ESC": "Esc",
        }.get(normalized, normalized)

    def _save_combat_settings(self) -> None:
        try:
            normalized_skill = ClientWindowController.normalize_input_binding(self.combat_skill_key.get())
            normalized_ultimate = ClientWindowController.normalize_input_binding(self.combat_ultimate_key.get())
        except ValueError as exc:
            messagebox.showerror("键位不可用", str(exc), parent=self.root)
            return
        self.combat_skill_key.set(self._combat_binding_display(normalized_skill))
        self.combat_ultimate_key.set(self._combat_binding_display(normalized_ultimate))
        COMBAT_CONFIG.write_text(
            json.dumps(
                {
                    "skill_key": normalized_skill,
                    "ultimate_key": normalized_ultimate,
                    "daily_heal_enabled": self.daily_heal_enabled.get(),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        heal_text = "开启" if self.daily_heal_enabled.get() else "关闭"
        self._log(
            f"4C技能键位已保存为：{normalized_skill}；大招键位：{normalized_ultimate}；"
            f"日常三号位回血：{heal_text}。"
        )
        messagebox.showinfo(
            "已保存",
            f"4C技能键位：{normalized_skill}\n4C大招键位：{normalized_ultimate}"
            f"\n日常三号位回血：{heal_text}",
            parent=self.root,
        )

    def _theme_status_text(self) -> str:
        if self.theme_id in THEME_DEFINITIONS:
            return f"当前：{THEME_DEFINITIONS[self.theme_id]['name']}"
        ready = [definition["name"] for key, definition in THEME_DEFINITIONS.items() if self._theme_pack_valid(key)]
        return "当前：原版简约主题" + (f" · 已就绪：{'、'.join(ready)}" if ready else "")

    def _build_ui(self) -> None:
        self._setup_style()
        self.root.configure(bg=COLORS["app_bg"])

        if self.theme_id in THEME_DEFINITIONS:
            self._build_theme_banner()

        self.header = Frame(self.root, padx=24, pady=18, bg=COLORS["app_bg"])
        self.header.pack(side=TOP, fill=X)
        Label(self.header, text="wwbs", font=(FONT_FAMILY, 22, "bold"), fg=COLORS["text"], bg=COLORS["app_bg"]).pack(side=LEFT)
        Button(self.header, text="检查更新", command=self._check_for_updates).pack(side=RIGHT, padx=(0, 8))
        Button(self.header, text="关于", command=self._show_about).pack(side=RIGHT, padx=(0, 8))
        Button(self.header, text="更新公告", command=self._show_update_history).pack(side=RIGHT, padx=(0, 14))
        Label(self.header, textvariable=self.status, font=(FONT_FAMILY, 10), fg=COLORS["muted"], bg=COLORS["app_bg"]).pack(side=RIGHT)

        summary = Frame(self.root, padx=24, pady=4, bg=COLORS["app_bg"])
        summary.pack(side=TOP, fill=X)
        self._summary_label(summary, "目标状态", self.device_status).pack(side=LEFT, padx=(0, 10))
        self._summary_label(summary, "识别模板", self.template_status).pack(side=LEFT, padx=(0, 10))
        self._summary_label(summary, "运行模式", StringVar(value="手动点击后执行")).pack(side=LEFT)

        self.tabs = ttk.Notebook(self.root)
        self.tabs.pack(fill=BOTH, expand=True, padx=24, pady=(12, 22))

        self.start_tab = Frame(self.tabs, padx=20, pady=18, bg=COLORS["panel"])
        self.template_tab = Frame(self.tabs, padx=20, pady=18, bg=COLORS["panel"])
        self.probability_tab = Frame(self.tabs, padx=20, pady=18, bg=COLORS["panel"])
        settings_shell = Frame(self.tabs, bg=COLORS["panel"])
        self.settings_tab, self.settings_scroll_canvas = self._create_scrollable_tab(settings_shell)
        self.log_tab = Frame(self.tabs, padx=20, pady=18, bg=COLORS["panel"])
        self.tabs.add(self.start_tab, text="开始")
        self.tabs.add(self.template_tab, text="模板")
        self.tabs.add(self.probability_tab, text="概率")
        self.tabs.add(settings_shell, text="设置")
        self.tabs.add(self.log_tab, text="日志")

        self._build_start_tab()
        self._build_template_tab()
        self._build_probability_tab()
        self._build_settings_tab()
        self._build_log_tab()
        self._polish_widgets(self.root)

    def _create_scrollable_tab(self, parent: Frame) -> tuple[Frame, Canvas]:
        canvas = Canvas(parent, highlightthickness=0, bg=COLORS["panel"])
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        content = Frame(canvas, padx=20, pady=18, bg=COLORS["panel"])
        content_window = canvas.create_window((0, 0), window=content, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side=LEFT, fill=BOTH, expand=True)
        scrollbar.pack(side=RIGHT, fill="y")

        content.bind(
            "<Configure>",
            lambda _event: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.bind(
            "<Configure>",
            lambda event: canvas.itemconfigure(content_window, width=max(1, event.width)),
        )
        return content, canvas

    @staticmethod
    def _bind_mousewheel_tree(widget, canvas: Canvas) -> None:
        def scroll(event) -> str:
            delta = -1 if event.delta > 0 else 1
            canvas.yview_scroll(delta * 3, "units")
            return "break"

        widget.bind("<MouseWheel>", scroll, add="+")
        for child in widget.winfo_children():
            App._bind_mousewheel_tree(child, canvas)

    def _build_theme_banner(self) -> None:
        definition = THEME_DEFINITIONS[self.theme_id]
        try:
            with zipfile.ZipFile(Path(definition["pack"])) as archive:
                image_bytes = archive.read("background.webp")
            with Image.open(io.BytesIO(image_bytes)) as source:
                self.theme_banner_source = source.convert("RGB")
        except (OSError, KeyError, zipfile.BadZipFile) as exc:
            self.log_queue.put(f"{definition['name']}背景读取失败：{exc}")
            return

        self.theme_banner = Canvas(
            self.root,
            height=THEME_BANNER_HEIGHT,
            bg=COLORS["preview"],
            highlightthickness=0,
        )
        self.theme_banner.pack(side=TOP, fill=X)
        self.theme_banner.bind("<Configure>", self._schedule_theme_banner_render)
        self.root.after_idle(self._render_theme_banner)

    def _schedule_theme_banner_render(self, _event=None) -> None:
        if self._theme_banner_resize_job is not None:
            self.root.after_cancel(self._theme_banner_resize_job)
        self._theme_banner_resize_job = self.root.after(80, self._render_theme_banner)

    def _render_theme_banner(self) -> None:
        self._theme_banner_resize_job = None
        source = self.theme_banner_source
        canvas = getattr(self, "theme_banner", None)
        if source is None or canvas is None or not canvas.winfo_exists():
            return
        width = max(canvas.winfo_width(), 1100)
        height = THEME_BANNER_HEIGHT
        source_width, source_height = source.size
        definition = THEME_DEFINITIONS[self.theme_id]
        target_ratio = width / height
        source_ratio = source_width / source_height
        if source_ratio < target_ratio:
            crop_height = max(1, round(source_width / target_ratio))
            focus_y = round(source_height * float(definition["focus_y"]))
            top = min(max(0, focus_y - crop_height // 2), source_height - crop_height)
            crop_box = (0, top, source_width, top + crop_height)
        else:
            crop_width = max(1, round(source_height * target_ratio))
            left = max(0, (source_width - crop_width) // 2)
            crop_box = (left, 0, left + crop_width, source_height)

        banner = source.crop(crop_box).resize((width, height), Image.Resampling.LANCZOS).convert("RGBA")
        overlay = Image.new("RGBA", banner.size, tuple(definition["banner_overlay"]))
        banner = Image.alpha_composite(banner, overlay).convert("RGB")
        self.theme_banner_photo = ImageTk.PhotoImage(banner)
        canvas.delete("all")
        canvas.create_image(0, 0, image=self.theme_banner_photo, anchor="nw")
        text_x = width - 38
        canvas.create_text(text_x, 67, text=definition["banner_title"], anchor="e", fill=definition["banner_text"], font=(FONT_FAMILY, 22, "bold"))
        canvas.create_text(
            text_x,
            108,
            text=definition["banner_subtitle"],
            anchor="e",
            fill=definition["banner_muted"],
            font=(FONT_FAMILY, 11),
        )

    def _setup_style(self) -> None:
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass
        self.root.option_add("*Font", f"{{{FONT_FAMILY}}} 10")
        self.root.option_add("*selectBackground", COLORS["primary"])
        self.root.option_add("*selectForeground", "#ffffff")
        style.configure("TNotebook", background=COLORS["app_bg"], borderwidth=0, tabmargins=(0, 0, 0, 0))
        style.configure("TNotebook.Tab", padding=(18, 9), font=(FONT_FAMILY, 10, "bold"), background=COLORS["panel_alt"], foreground=COLORS["muted"], borderwidth=0)
        style.map("TNotebook.Tab", background=[("selected", COLORS["panel"]), ("active", COLORS["panel"])], foreground=[("selected", COLORS["text"]), ("active", COLORS["text"])])
        style.configure("Primary.TButton", padding=(18, 11), font=(FONT_FAMILY, 11, "bold"), background=COLORS["primary"], foreground="#ffffff", borderwidth=0, focusthickness=0)
        style.map("Primary.TButton", background=[("active", COLORS["primary_hover"]), ("pressed", COLORS["primary"])], foreground=[("disabled", COLORS["line_soft"]), ("!disabled", "#ffffff")])
        style.configure("TButton", padding=(12, 7), font=(FONT_FAMILY, 10), background=COLORS["panel"], foreground=COLORS["text"], bordercolor=COLORS["line"], lightcolor=COLORS["panel"], darkcolor=COLORS["line"], focusthickness=0)
        style.map("TButton", background=[("active", COLORS["panel_alt"]), ("pressed", COLORS["line_soft"])])
        style.configure("TRadiobutton", background=COLORS["panel"], foreground=COLORS["text"], font=(FONT_FAMILY, 10))
        style.map("TRadiobutton", background=[("active", COLORS["panel"])])
        style.configure("Vertical.TScrollbar", background=COLORS["line_soft"], troughcolor=COLORS["panel"], borderwidth=0, arrowcolor=COLORS["muted"])

    def _summary_label(self, parent: Frame, title: str, value: StringVar) -> Frame:
        box = Frame(parent, padx=16, pady=11, bg=COLORS["panel"], highlightthickness=1, highlightbackground=COLORS["line_soft"])
        Label(box, text=title, font=(FONT_FAMILY, 9), fg=COLORS["muted"], bg=COLORS["panel"]).pack(anchor="w")
        Label(box, textvariable=value, font=(FONT_FAMILY, 10, "bold"), fg=COLORS["text"], bg=COLORS["panel"]).pack(anchor="w")
        return box

    def _polish_widgets(self, widget) -> None:
        for child in widget.winfo_children():
            klass = child.winfo_class()
            if klass == "Frame":
                current_bg = child.cget("bg")
                if current_bg not in (COLORS["app_bg"], COLORS["panel"], COLORS["panel_alt"]):
                    child.configure(bg=COLORS["panel"])
            elif klass == "Label":
                parent_bg = child.master.cget("bg") if hasattr(child.master, "cget") else COLORS["panel"]
                child.configure(bg=parent_bg, fg=child.cget("fg") if child.cget("fg") not in ("SystemButtonText", "black") else COLORS["text"])
            elif klass == "Button":
                child.configure(
                    bg=COLORS["panel"],
                    fg=COLORS["text"],
                    activebackground=COLORS["panel_alt"],
                    activeforeground=COLORS["text"],
                    relief="flat",
                    bd=0,
                    highlightthickness=1,
                    highlightbackground=COLORS["line"],
                    padx=12,
                    pady=7,
                    cursor="hand2",
                )
            elif klass == "Entry":
                child.configure(
                    bg=COLORS["panel"],
                    fg=COLORS["text"],
                    insertbackground=COLORS["text"],
                    relief="flat",
                    bd=0,
                    highlightthickness=1,
                    highlightbackground=COLORS["line"],
                    highlightcolor=COLORS["primary"],
                )
            elif klass == "Listbox":
                child.configure(
                    bg=COLORS["panel"],
                    fg=COLORS["text"],
                    selectbackground=COLORS["primary"],
                    selectforeground="#ffffff",
                    relief="flat",
                    bd=0,
                    highlightthickness=1,
                    highlightbackground=COLORS["line_soft"],
                    activestyle="none",
                )
            elif klass == "Text":
                child.configure(
                    bg=COLORS["panel"],
                    fg=COLORS["text"],
                    insertbackground=COLORS["text"],
                    relief="flat",
                    bd=0,
                    highlightthickness=1,
                    highlightbackground=COLORS["line_soft"],
                    padx=10,
                    pady=8,
                )
            elif klass == "Checkbutton":
                parent_bg = child.master.cget("bg") if hasattr(child.master, "cget") else COLORS["panel"]
                child.configure(bg=parent_bg, fg=COLORS["text"], activebackground=parent_bg, activeforeground=COLORS["text"], selectcolor=COLORS["panel"])
            elif klass == "Canvas":
                if (
                    child not in (getattr(self, "preview_canvas", None), getattr(self, "theme_banner", None))
                    and not getattr(child, "_keep_canvas_style", False)
                ):
                    child.configure(bg=COLORS["panel"], highlightthickness=0)
            self._polish_widgets(child)

    def _build_start_tab(self) -> None:
        scroll_canvas = Canvas(self.start_tab, highlightthickness=0, bg=COLORS["panel"])
        content = Frame(scroll_canvas, bg=COLORS["panel"])
        content_window = scroll_canvas.create_window((0, 0), window=content, anchor="nw")

        scroll_canvas.pack(side=LEFT, fill=BOTH, expand=True)

        def update_scroll_region(_event=None) -> None:
            scroll_canvas.configure(scrollregion=scroll_canvas.bbox("all"))

        def update_content_width(event) -> None:
            content_width = max(event.width - (START_CONTENT_SIDE_PADDING * 2), 1040)
            scroll_canvas.itemconfigure(content_window, width=content_width)
            scroll_canvas.coords(content_window, START_CONTENT_SIDE_PADDING, 0)

        content.bind("<Configure>", update_scroll_region)
        scroll_canvas.bind("<Configure>", update_content_width)

        content.columnconfigure(0, minsize=ACTION_PANEL_WIDTH)
        content.columnconfigure(1, weight=1)
        content.rowconfigure(0, weight=1)

        left = Frame(content, bg=COLORS["panel"])
        left.grid(row=0, column=0, sticky="new", padx=(0, 28))
        left.configure(width=ACTION_PANEL_WIDTH)
        left.grid_propagate(False)
        right = Frame(content, bg=COLORS["panel"])
        right.grid(row=0, column=1, sticky="nsew")

        self.task_list = Listbox(content, height=1, activestyle="none", font=(FONT_FAMILY, 10))
        self.task_list.bind("<<ListboxSelect>>", lambda _event: self._show_selected_task())

        Label(left, text="一键操作", font=(FONT_FAMILY, 13, "bold")).pack(anchor="w")
        action_box = Frame(left, padx=14, pady=14, bg=COLORS["panel_alt"], highlightthickness=1, highlightbackground=COLORS["line_soft"])
        action_box.pack(fill=X, pady=(8, 10))
        action_box.columnconfigure(0, weight=1)
        action_box.columnconfigure(1, minsize=42)
        ttk.Button(action_box, text="周常拿满奖励", style="Primary.TButton", command=lambda: self._start_enabled_real(15)).grid(row=0, column=0, sticky="ew", pady=(0, 10))
        self._run_notice_button(action_box, "weekly").grid(row=0, column=1, sticky="e", padx=(8, 0), pady=(0, 10))
        ttk.Button(action_box, text="周常拿满星声", style="Primary.TButton", command=lambda: self._start_enabled_real(13)).grid(row=1, column=0, sticky="ew", pady=(0, 10))
        self._run_notice_button(action_box, "weekly").grid(row=1, column=1, sticky="e", padx=(8, 0), pady=(0, 10))
        Label(
            action_box,
            text="一键日常 · 滑动选取无音区",
            bg=COLORS["panel_alt"],
            fg=COLORS["muted"],
            anchor="w",
        ).grid(row=2, column=0, columnspan=2, sticky="ew", pady=(0, 4))
        daily_zone_picker = ttk.Combobox(
            action_box,
            textvariable=self.daily_zone,
            values=DAILY_ZONE_NAMES,
            state="readonly",
            width=25,
        )
        daily_zone_picker.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        daily_zone_picker.bind("<<ComboboxSelected>>", self._save_daily_zone)
        daily_zone_picker.bind("<MouseWheel>", self._scroll_daily_zone)
        ttk.Button(
            action_box,
            text="一键日常（2轮双倍）",
            style="Primary.TButton",
            command=self._start_daily_routine,
        ).grid(row=4, column=0, sticky="ew", pady=(0, 10))
        self._run_notice_button(action_box, "daily").grid(row=4, column=1, sticky="e", padx=(8, 0), pady=(0, 10))
        ttk.Button(action_box, text="4C刷取（10次）", style="Primary.TButton", command=lambda: self._start_named_task_real("4C刷取", 10)).grid(row=5, column=0, sticky="ew", pady=(0, 10))
        self._run_notice_button(action_box, "combat_4c").grid(row=5, column=1, sticky="e", padx=(8, 0), pady=(0, 10))
        ttk.Button(action_box, text="4C刷取（30次）", style="Primary.TButton", command=lambda: self._start_named_task_real("4C刷取", 30)).grid(row=6, column=0, sticky="ew", pady=(0, 10))
        self._run_notice_button(action_box, "combat_4c").grid(row=6, column=1, sticky="e", padx=(8, 0), pady=(0, 10))
        Button(action_box, text=f"停止当前任务（{STOP_HOTKEY_LABEL}）", command=self._stop).grid(row=7, column=0, columnspan=2, sticky="ew")

        Label(left, text=self.pet_name, font=(FONT_FAMILY, 12, "bold")).pack(anchor="w", pady=(10, 0))
        pet_box = Frame(left, padx=14, pady=14, bg=COLORS["panel_alt"], highlightthickness=1, highlightbackground=COLORS["line_soft"])
        pet_box.pack(fill=X, pady=(8, 10))
        Button(pet_box, text="显示 / 隐藏", command=self._toggle_desktop_pet).pack(fill=X)
        Label(
            left,
            text=f"提示：右键{self.pet_name}可直接执行一键操作",
            fg=COLORS["muted"],
            bg=COLORS["panel"],
            wraplength=ACTION_PANEL_WIDTH - 10,
            justify=LEFT,
        ).pack(anchor="w", pady=(0, 10))

        Label(right, text="游戏窗口预览", font=("Microsoft YaHei UI", 12, "bold")).pack(anchor="w", pady=(12, 4))
        self.preview_canvas = Canvas(right, width=900, height=506, bg=COLORS["preview"], highlightthickness=1, highlightbackground=COLORS["line_soft"])
        self.preview_canvas.pack(anchor="w", pady=(0, 8))
        self.preview_canvas.create_text(
            210,
            120,
            text="任务运行时显示游戏画面",
            fill="#f5f5f7",
            font=(FONT_FAMILY, 10),
        )
        self.preview_canvas.bind("<Configure>", self._resize_preview_canvas)
        right.bind("<Configure>", self._resize_preview_canvas)

        Label(right, text="运行状态", font=(FONT_FAMILY, 12, "bold")).pack(anchor="w", pady=(16, 4))
        self.detail = Text(right, height=12, wrap="word", font=(FONT_FAMILY, 10), relief="solid", bd=1)
        self.detail.pack(fill=BOTH, expand=True)
        self.detail.bind("<MouseWheel>", self._scroll_detail_log, add="+")
        self.detail.bind("<Button-4>", lambda _event: self._scroll_detail_log_units(-3), add="+")
        self.detail.bind("<Button-5>", lambda _event: self._scroll_detail_log_units(3), add="+")

    def _run_notice_button(self, parent: Frame, notice_key: str) -> Canvas:
        button = Canvas(
            parent,
            width=30,
            height=30,
            bg=COLORS["panel_alt"],
            highlightthickness=0,
            cursor="hand2",
            takefocus=True,
        )
        button._keep_canvas_style = True

        def draw(hovered: bool = False) -> None:
            button.delete("all")
            color = COLORS["primary"] if hovered else COLORS["muted"]
            button.create_oval(4, 4, 26, 26, outline=color, width=2)
            button.create_text(15, 15, text="?", fill=color, font=(FONT_FAMILY, 10, "bold"))

        draw()
        button.bind("<Enter>", lambda _event: draw(True))
        button.bind("<Leave>", lambda _event: draw(False))
        button.bind("<Button-1>", lambda _event: self._show_run_notice(notice_key))
        button.bind("<Return>", lambda _event: self._show_run_notice(notice_key))
        button.bind("<space>", lambda _event: self._show_run_notice(notice_key))
        return button

    def _show_run_notice(self, notice_key: str) -> None:
        notice = RUN_NOTICES.get(notice_key)
        if notice is None:
            return
        title, image_path = notice
        if not image_path.exists():
            messagebox.showerror("示例图缺失", f"没有找到运行提示图片：\n{image_path}", parent=self.root)
            return

        window = Toplevel(self.root)
        window.title(title)
        window.transient(self.root)
        window.resizable(False, False)
        if APP_ICON.exists():
            try:
                window.iconbitmap(str(APP_ICON))
            except Exception:
                pass

        screen_width = window.winfo_screenwidth()
        screen_height = window.winfo_screenheight()
        image_width = min(960, max(640, screen_width - 160))
        image_height = round(image_width * 9 / 16)
        maximum_height = max(360, screen_height - 260)
        if image_height > maximum_height:
            image_height = maximum_height
            image_width = round(image_height * 16 / 9)

        container = Frame(window, padx=22, pady=18, bg=COLORS["panel"])
        container.pack(fill=BOTH, expand=True)
        Label(
            container,
            text="请先将游戏调整至对应画面，再开始运行",
            font=(FONT_FAMILY, 15, "bold"),
            fg=COLORS["text"],
            bg=COLORS["panel"],
        ).pack(anchor="w", pady=(0, 12))
        with Image.open(image_path) as source:
            preview = source.convert("RGB").resize(
                (image_width, image_height),
                Image.Resampling.LANCZOS,
            )
        photo = ImageTk.PhotoImage(preview, master=window)
        Label(
            container,
            image=photo,
            bg=COLORS["preview"],
            bd=1,
            relief="solid",
        ).pack()
        window._notice_photo = photo
        ttk.Button(container, text="知道了", command=window.destroy).pack(anchor="e", pady=(12, 0))
        window.bind("<Escape>", lambda _event: window.destroy())
        window.update_idletasks()
        x = max(0, (screen_width - window.winfo_width()) // 2)
        y = max(0, (screen_height - window.winfo_height()) // 2)
        window.geometry(f"+{x}+{y}")
        window.grab_set()

    def _scroll_detail_log(self, event) -> str:
        self.detail.yview_scroll(int(-1 * (event.delta / 120)), "units")
        return "break"

    def _scroll_detail_log_units(self, units: int) -> str:
        self.detail.yview_scroll(units, "units")
        return "break"

    def _build_template_tab(self) -> None:
        Label(self.template_tab, text="制作识别模板", font=("Microsoft YaHei UI", 13, "bold")).pack(anchor="w")
        Label(
            self.template_tab,
            text="让游戏停在目标界面，点击“制作新模板”，在截图上框住按钮或图标。保存后任务就可以自动找图点击。",
            fg="#5f6b7a",
        ).pack(anchor="w", pady=(2, 10))

        top = Frame(self.template_tab)
        top.pack(fill=X, pady=(0, 10))
        ttk.Button(top, text="制作新模板", style="Primary.TButton", command=self._make_template).pack(side=LEFT)
        Button(top, text="刷新模板列表", command=self._refresh_templates).pack(side=LEFT, padx=8)
        Button(top, text="删除当前模板组", command=self._delete_selected_template).pack(side=LEFT)
        Button(top, text="测试选中任务识别", command=self._preview_selected).pack(side=LEFT, padx=8)

        group_row = Frame(self.template_tab)
        group_row.pack(fill=X, pady=(0, 8))
        Label(group_row, text="当前模板组", width=12, anchor="w").pack(side=LEFT)
        self.template_group_combo = ttk.Combobox(group_row, textvariable=self.template_group, state="readonly", width=24)
        self.template_group_combo.pack(side=LEFT, padx=(0, 8))
        self.template_group_combo.bind("<<ComboboxSelected>>", self._on_template_group_selected)
        Button(group_row, text="新建模板组", command=self._create_template_group).pack(side=LEFT, padx=(0, 8))
        Button(group_row, text="绑定到选中任务", command=self._assign_selected_task_group).pack(side=LEFT)

        Label(self.template_tab, text="当前已有模板", font=("Microsoft YaHei UI", 11, "bold")).pack(anchor="w")
        self.template_list = Listbox(self.template_tab, height=14, font=(FONT_FAMILY, 10))
        self.template_list.pack(fill=BOTH, expand=True, pady=6)

        Label(
            self.template_tab,
            text="提示：选择模板组会同步切换普通启动任务；选择幻梦游园后不会再执行群声。4C请使用专用按钮。",
            fg="#5f6b7a",
        ).pack(anchor="w", pady=(6, 0))

    def _build_probability_tab(self) -> None:
        Label(self.probability_tab, text="抽取概率计算", font=("Microsoft YaHei UI", 13, "bold")).pack(anchor="w")
        Label(
            self.probability_tab,
            text="按 160 星声 = 1 抽计算。角色池会计算 50% 和大保底；武器池默认出 5 星就是 UP。",
            fg="#5f6b7a",
        ).pack(anchor="w", pady=(2, 14))

        form = Frame(self.probability_tab, bg=COLORS["panel"])
        form.pack(anchor="w", fill=X)

        rows = [
            ("星声数量", self.prob_astrite, "当前可用于抽取的星声数量"),
            ("抽数", self.prob_pulls, "与星声数量二选一输入，按 160 星声 = 1 抽换算"),
            ("角色水位", self.prob_character_pity, "角色池距离上一次 5 星后已经抽了多少发，0 到 79"),
            ("武器水位", self.prob_weapon_pity, "武器池距离上一次 5 星后已经抽了多少发，0 到 79"),
            ("想要获得角色数", self.prob_character_target, "想要拿到几个 UP 角色"),
            ("想要获得武器数", self.prob_weapon_target, "想要拿到几个 UP 武器"),
        ]
        for row_index, (label, value, hint) in enumerate(rows):
            row = Frame(form, bg=COLORS["panel"])
            row.grid(row=row_index, column=0, sticky="ew", pady=6)
            Label(row, text=label, width=18, anchor="w").pack(side=LEFT)
            Entry(row, textvariable=value, width=18).pack(side=LEFT, padx=(0, 10))
            Label(row, text=hint, fg="#697386").pack(side=LEFT)

        guarantee_row = Frame(form, bg=COLORS["panel"])
        guarantee_row.grid(row=len(rows), column=0, sticky="ew", pady=6)
        Label(guarantee_row, text="角色大保底", width=18, anchor="w").pack(side=LEFT)
        Checkbutton(
            guarantee_row,
            text="现在拥有大保底",
            variable=self.prob_character_guaranteed,
            bg=COLORS["panel"],
            activebackground=COLORS["panel"],
        ).pack(side=LEFT, padx=(0, 10))
        Label(guarantee_row, text="勾选后，下一次角色池 5 星必定为 UP", fg="#697386").pack(side=LEFT)

        ttk.Button(form, text="计算概率", style="Primary.TButton", command=self._calculate_probability).grid(row=len(rows) + 1, column=0, sticky="w", pady=(16, 12))

        result_box = Frame(self.probability_tab, padx=18, pady=16, bg=COLORS["panel_alt"], highlightthickness=1, highlightbackground=COLORS["line_soft"])
        result_box.pack(fill=X, pady=(4, 14))
        Label(result_box, text="计算结果", font=(FONT_FAMILY, 11, "bold"), bg=COLORS["panel_alt"]).pack(anchor="w")
        Label(result_box, textvariable=self.prob_result, justify=LEFT, anchor="w", bg=COLORS["panel_alt"], wraplength=920).pack(anchor="w", fill=X, pady=(8, 0))

        Label(
            self.probability_tab,
            text="说明：角色目标使用角色水位，武器目标使用武器水位。若同时填写角色和武器目标，默认先完成角色目标，再用剩余抽数计算武器目标。",
            fg="#5f6b7a",
            wraplength=960,
            justify=LEFT,
        ).pack(anchor="w", pady=(2, 0))

    def _build_settings_tab(self) -> None:
        Label(self.settings_tab, text="高级设置", font=("Microsoft YaHei UI", 13, "bold")).pack(anchor="w")
        Label(self.settings_tab, text="普通使用 PC 客户端模式即可。只有使用模拟器时才需要切换到 ADB。", fg="#5f6b7a").pack(anchor="w", pady=(2, 12))

        theme_box = Frame(
            self.settings_tab,
            padx=16,
            pady=14,
            bg=COLORS["panel_alt"],
            highlightthickness=1,
            highlightbackground=COLORS["line_soft"],
        )
        theme_box.pack(fill=X, pady=(0, 14))
        Label(theme_box, text="程序主题", font=(FONT_FAMILY, 11, "bold"), bg=COLORS["panel_alt"]).pack(anchor="w")
        Label(theme_box, textvariable=self.theme_status, fg=COLORS["muted"], bg=COLORS["panel_alt"]).pack(anchor="w", pady=(3, 10))
        theme_actions = Frame(theme_box, bg=COLORS["panel_alt"])
        theme_actions.pack(fill=X)
        Button(theme_actions, text="使用原版简约主题", command=lambda: self._select_theme("simple")).pack(side=LEFT)
        Button(theme_actions, text="使用达妮娅主题", command=lambda: self._select_theme("daniya")).pack(side=LEFT, padx=(10, 0))
        Button(theme_actions, text="使用爱弥斯主题", command=lambda: self._select_theme("aemeath")).pack(side=LEFT, padx=(10, 0))
        Button(theme_actions, text="使用景燃主题", command=lambda: self._select_theme("jingran")).pack(side=LEFT, padx=(10, 0))
        Label(
            theme_box,
            text="角色主题会自动绑定同名桌宠；原版简约主题不强制更换角色。切换后会自动重启程序。",
            fg=COLORS["muted"],
            bg=COLORS["panel_alt"],
        ).pack(anchor="w", pady=(10, 0))

        pet_select_box = Frame(
            self.settings_tab,
            padx=16,
            pady=14,
            bg=COLORS["panel_alt"],
            highlightthickness=1,
            highlightbackground=COLORS["line_soft"],
        )
        pet_select_box.pack(fill=X, pady=(0, 14))
        Label(pet_select_box, text="桌宠角色", font=(FONT_FAMILY, 11, "bold"), bg=COLORS["panel_alt"]).pack(anchor="w")
        Label(pet_select_box, textvariable=self.pet_status, fg=COLORS["muted"], bg=COLORS["panel_alt"]).pack(anchor="w", pady=(3, 10))
        pet_actions = Frame(pet_select_box, bg=COLORS["panel_alt"])
        pet_actions.pack(fill=X)
        Button(pet_actions, text="使用达妮娅", command=lambda: self._select_pet("daniya")).pack(side=LEFT)
        Button(pet_actions, text="使用爱弥斯", command=lambda: self._select_pet("aemeath")).pack(side=LEFT, padx=(10, 0))
        Button(pet_actions, text="使用景燃", command=lambda: self._select_pet("jingran")).pack(side=LEFT, padx=(10, 0))
        Label(
            pet_select_box,
            text="选择桌宠会同时切换对应角色主题；三款桌宠使用相同功能、右键菜单和排版。",
            fg=COLORS["muted"],
            bg=COLORS["panel_alt"],
        ).pack(anchor="w", pady=(10, 0))
        pet_size_row = Frame(pet_select_box, bg=COLORS["panel_alt"])
        pet_size_row.pack(fill=X, pady=(12, 0))
        Label(pet_size_row, text="桌宠大小", width=12, anchor="w", bg=COLORS["panel_alt"]).pack(side=LEFT)
        pet_size_picker = ttk.Combobox(
            pet_size_row,
            textvariable=self.pet_size,
            values=("70%", "85%", "100%", "115%", "130%", "150%"),
            state="readonly",
            width=10,
        )
        pet_size_picker.pack(side=LEFT, padx=(0, 10))
        pet_size_picker.bind("<<ComboboxSelected>>", self._apply_pet_size)
        Label(
            pet_size_row,
            text="选择后立即生效，下次启动会保持当前大小",
            fg=COLORS["muted"],
            bg=COLORS["panel_alt"],
        ).pack(side=LEFT)

        mode_row = Frame(self.settings_tab)
        mode_row.pack(fill=X, pady=5)
        Label(mode_row, text="操作目标", width=12, anchor="w").pack(side=LEFT)
        ttk.Radiobutton(mode_row, text="PC 客户端窗口", variable=self.target_mode, value="client", command=self._update_mode_label).pack(side=LEFT, padx=6)
        ttk.Radiobutton(mode_row, text="模拟器 / ADB", variable=self.target_mode, value="adb", command=self._update_mode_label).pack(side=LEFT, padx=6)

        client_row = Frame(self.settings_tab)
        client_row.pack(fill=X, pady=5)
        Label(client_row, text="窗口标题", width=12, anchor="w").pack(side=LEFT)
        Entry(client_row, textvariable=self.window_title, width=24).pack(side=LEFT, padx=6)
        Label(client_row, text="“自动”同时识别国服与国际服 Steam 端", fg="#697386").pack(side=LEFT, padx=6)
        Label(client_row, text="标题包含这些字就会被识别", fg="#697386").pack(side=LEFT)

        size_row = Frame(self.settings_tab)
        size_row.pack(fill=X, pady=5)
        Label(size_row, text="模板基准", width=12, anchor="w").pack(side=LEFT)
        Entry(size_row, textvariable=self.expected_resolution, width=24).pack(side=LEFT, padx=6)
        Label(size_row, text="模板按这个分辨率制作，窗口可等比例缩小，例如 1536x864", fg="#697386").pack(side=LEFT)

        combat_row = Frame(self.settings_tab)
        combat_row.pack(fill=X, pady=5)
        Label(combat_row, text="4C 技能键位", width=12, anchor="w").pack(side=LEFT)
        combat_key_picker = ttk.Combobox(
            combat_row,
            textvariable=self.combat_skill_key,
            values=("E", "Q", "R", "T", "鼠标侧键1", "鼠标侧键2"),
            width=21,
        )
        combat_key_picker.pack(side=LEFT, padx=6)
        Button(combat_row, text="保存键位", command=self._save_combat_settings).pack(side=LEFT, padx=(0, 8))
        Label(combat_row, text="支持 E、Q 等单键，以及鼠标侧键1 / 鼠标侧键2", fg="#697386").pack(side=LEFT)

        ultimate_row = Frame(self.settings_tab)
        ultimate_row.pack(fill=X, pady=5)
        Label(ultimate_row, text="4C 大招键位", width=12, anchor="w").pack(side=LEFT)
        ttk.Combobox(
            ultimate_row,
            textvariable=self.combat_ultimate_key,
            values=("R", "E", "Q", "T", "鼠标侧键1", "鼠标侧键2"),
            width=21,
        ).pack(side=LEFT, padx=6)
        Label(ultimate_row, text="默认 R；与技能键一起点击“保存键位”", fg="#697386").pack(side=LEFT)

        daily_heal_row = Frame(self.settings_tab)
        daily_heal_row.pack(fill=X, pady=5)
        Label(daily_heal_row, text="日常战斗回血", width=12, anchor="w").pack(side=LEFT)
        Checkbutton(
            daily_heal_row,
            text="启用三号位回血连段（默认关闭）",
            variable=self.daily_heal_enabled,
        ).pack(side=LEFT, padx=6)
        Label(
            daily_heal_row,
            text="勾选后点击上方“保存键位”；日常战斗会定时切三号位并自动切回一号位",
            fg="#697386",
        ).pack(side=LEFT)

        row1 = Frame(self.settings_tab)
        row1.pack(fill=X, pady=5)
        Label(row1, text="ADB 路径", width=12, anchor="w").pack(side=LEFT)
        Entry(row1, textvariable=self.adb_path, width=42).pack(side=LEFT, padx=6)
        Button(row1, text="检测目标", command=self._check_target).pack(side=LEFT)

        row2 = Frame(self.settings_tab)
        row2.pack(fill=X, pady=5)
        Label(row2, text="设备 ID", width=12, anchor="w").pack(side=LEFT)
        Entry(row2, textvariable=self.device_id, width=42).pack(side=LEFT, padx=6)
        Label(row2, text="只有连接多个设备时才需要填写", fg="#697386").pack(side=LEFT)

        row3 = Frame(self.settings_tab)
        row3.pack(fill=X, pady=5)
        Label(row3, text="任务配置", width=12, anchor="w").pack(side=LEFT)
        Entry(row3, textvariable=self.config_path, width=58).pack(side=LEFT, padx=6)
        Button(row3, text="选择", command=self._choose_config).pack(side=LEFT)
        Button(row3, text="加载", command=lambda: self._load_config(silent=False)).pack(side=LEFT, padx=6)

        row4 = Frame(self.settings_tab)
        row4.pack(fill=X, pady=12)
        Checkbutton(row4, text="预演模式：识别模板但不点击设备", variable=self.dry_run).pack(side=LEFT)
        Button(row4, text="保存一张当前截图", command=self._screenshot).pack(side=LEFT, padx=12)
        Button(row4, text="查看程序目录", command=self._open_config_dir).pack(side=LEFT)

        self._update_mode_label()
        self._bind_mousewheel_tree(self.settings_tab, self.settings_scroll_canvas)

    def _select_theme(self, theme_id: str) -> None:
        if theme_id in THEME_DEFINITIONS and not self._theme_pack_valid(theme_id):
            definition = THEME_DEFINITIONS[theme_id]
            source = filedialog.askopenfilename(
                title=f"选择{definition['name']}包",
                filetypes=[("wwbs 主题包", "*.wwbstheme"), ("所有文件", "*.*")],
                parent=self.root,
            )
            if not source:
                return
            source_path = Path(source)
            if not self._theme_pack_valid(theme_id, source_path):
                messagebox.showerror("主题包不可用", f"这个文件不是有效的{definition['name']}包。", parent=self.root)
                return
            target_path = Path(definition["pack"])
            target_path.parent.mkdir(parents=True, exist_ok=True)
            if source_path.resolve() != target_path.resolve():
                shutil.copy2(source_path, target_path)

        bound_pet_id = theme_id if theme_id in PET_DEFINITIONS else self.pet_id
        if theme_id == self.theme_id and bound_pet_id == self.pet_id:
            messagebox.showinfo("主题", "已经在使用这个主题了。", parent=self.root)
            return
        THEME_CONFIG.write_text(
            json.dumps(
                {"theme": theme_id, "explicit": True, "source": "theme-picker"},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        if theme_id in PET_DEFINITIONS:
            PET_CONFIG.write_text(json.dumps({"pet": bound_pet_id}, ensure_ascii=False), encoding="utf-8")
        display_name = THEME_DEFINITIONS.get(theme_id, {}).get("name", "原版简约主题")
        binding_text = f"，并绑定{PET_DEFINITIONS[bound_pet_id]['name']}桌宠" if theme_id in PET_DEFINITIONS else ""
        if messagebox.askyesno("切换主题", f"已选择{display_name}{binding_text}。现在重启程序查看效果吗？", parent=self.root):
            self._restart_app()

    def _select_pet(self, pet_id: str) -> None:
        definition = PET_DEFINITIONS.get(pet_id)
        if definition is None or not Path(definition["frames"]).exists():
            messagebox.showerror("桌宠不可用", "桌宠动画资源不完整。", parent=self.root)
            return
        if pet_id == self.pet_id:
            messagebox.showinfo("桌宠", "已经在使用这款桌宠了。", parent=self.root)
            return
        PET_CONFIG.write_text(json.dumps({"pet": pet_id}, ensure_ascii=False), encoding="utf-8")
        if messagebox.askyesno("切换桌宠", f"已选择{definition['name']}桌宠，程序主题保持不变。现在重启程序查看效果吗？", parent=self.root):
            self._restart_app()

    def _restart_app(self) -> None:
        if getattr(sys, "frozen", False):
            command = [sys.executable]
        else:
            command = [sys.executable, str(Path(__file__).resolve())]
        subprocess.Popen(command, cwd=str(APP_DIR))
        self._close_app()

    @staticmethod
    def _elevated_launch_command() -> tuple[str, str]:
        if getattr(sys, "frozen", False):
            executable = sys.executable
            arguments = list(sys.argv[1:])
        else:
            executable = sys.executable
            arguments = [str(Path(__file__).resolve()), *sys.argv[1:]]
        return executable, subprocess.list2cmdline(arguments)

    def _request_admin_restart(self, log_message: str) -> bool:
        if is_running_as_admin() or self._admin_restart_requested:
            return False
        self._admin_restart_requested = True
        executable, parameters = self._elevated_launch_command()
        self._log(log_message)
        try:
            result = ctypes.windll.shell32.ShellExecuteW(
                None,
                "runas",
                executable,
                parameters or None,
                str(APP_DIR),
                1,
            )
        except Exception as exc:
            self._admin_restart_requested = False
            self._log(f"无法请求管理员权限：{exc}")
            return False
        if int(result) > 32:
            self.stop_event.set()
            self.root.after(120, self._close_app)
            return True
        self._admin_restart_requested = False
        self._log(f"管理员重启未获批准或启动失败（返回值 {int(result)}）。")
        return False

    def _restart_as_admin_after_error(self, error_text: str) -> bool:
        return self._request_admin_restart(
            "检测到任务执行失败且程序未使用管理员权限，正在请求管理员权限并自动重启。"
        )

    def _ensure_admin_for_real_run(self) -> bool:
        if self.dry_run.get() or is_running_as_admin():
            return True
        restarted = self._request_admin_restart(
            "真实任务开始前检测到程序未使用管理员权限，正在请求管理员权限并自动重启。"
        )
        if not restarted:
            messagebox.showerror(
                "需要管理员权限",
                "真实任务需要以管理员身份运行。请允许 Windows 权限请求后重试。",
                parent=self.root,
            )
        return False

    def _handle_task_failure(self, error_text: str) -> None:
        if self._restart_as_admin_after_error(error_text):
            return
        if is_running_as_admin() or not self._admin_restart_requested:
            self._show_task_error_feedback(error_text)

    def _build_log_tab(self) -> None:
        Label(self.log_tab, text="运行日志", font=("Microsoft YaHei UI", 13, "bold")).pack(anchor="w")
        log_body = Frame(self.log_tab, bg=COLORS["panel"])
        log_body.pack(fill=BOTH, expand=True, pady=8)
        log_scrollbar = ttk.Scrollbar(log_body, orient="vertical")
        self.log_text = Text(
            log_body,
            wrap="word",
            font=(MONO_FONT, 10),
            relief="solid",
            bd=1,
            yscrollcommand=log_scrollbar.set,
        )
        log_scrollbar.configure(command=self.log_text.yview)
        self.log_text.pack(side=LEFT, fill=BOTH, expand=True)
        log_scrollbar.pack(side=RIGHT, fill="y")
        Button(self.log_tab, text="清空日志", command=lambda: self.log_text.delete("1.0", END)).pack(anchor="e")

    def _show_update_notice(self) -> None:
        messagebox.showinfo(
            f"wwbs {APP_VERSION} 更新公告",
            "1.4.7 正式版\n\n"
            "- 4C刷取次数调整为10次和30次。\n"
            "- 桌宠隐藏状态会自动保存，任务反馈不再强制显示桌宠。\n"
            "- 日常战斗新增奖励阶段判定，修复目标文字残留时一直攻击的问题。\n"
            "- 三号位回血会在结束前后复核，不再阻塞正常收尾。\n"
            "- 大招每5秒检查一次，只在彩色完整亮环就绪时施放。",
            parent=self.root,
        )

    def _start_desktop_pet(self) -> None:
        if self.desktop_pet is not None:
            return
        try:
            self.desktop_pet = DesktopPet(
                self.root,
                Path(self.pet_definition["frames"]),
                scale=(
                    float(self.pet_definition.get("scale", 1.15))
                    * self._normalize_pet_size_percent(self.pet_size.get())
                    / 100.0
                ),
                commands={
                    "diagnose": self._diagnose_runtime,
                    "check_target": self._check_target,
                    "run_rewards": lambda: self._start_enabled_real(15, require_confirmation=False),
                    "run_astrite": lambda: self._start_enabled_real(13, require_confirmation=False),
                    "run_daily": lambda: self._start_daily_routine(require_confirmation=False),
                    "run_4c_10": lambda: self._start_named_task_real("4C刷取", 10, require_confirmation=False),
                    "run_4c_30": lambda: self._start_named_task_real("4C刷取", 30, require_confirmation=False),
                    "stop_task": self._stop,
                    **{
                        f"pet_size_{percent}": lambda value=percent: self._set_pet_size_percent(value)
                        for percent in (70, 85, 100, 115, 130, 150)
                    },
                },
                pet_name=self.pet_name,
                app_version=APP_VERSION,
                app_icon=APP_ICON,
                idle_line_factory=self.pet_definition["idle_line"],
                bubble_palette=self.pet_definition["bubble_palette"],
                look_spritesheet=self.pet_definition.get("look_spritesheet"),
                visible=self.pet_visible,
                on_visibility_changed=self._save_pet_visibility,
            )
            self.log_queue.put(f"{self.pet_name}已启动：拖动移动，双击互动，右键执行功能或运行诊断。")
            welcome_factory = self.pet_definition.get("welcome_dialogue")
            if callable(welcome_factory):
                welcome = welcome_factory()
                self.root.after(
                    420,
                    lambda: self._pet_feedback(
                        str(getattr(welcome, "action", "waving")),
                        str(getattr(welcome, "text", welcome)),
                        4800,
                    ),
                )
        except Exception as exc:
            self.log_queue.put(f"{self.pet_name}启动失败：{exc}")

    def _toggle_desktop_pet(self) -> None:
        if self.desktop_pet is None:
            self._save_pet_visibility(True)
            self._start_desktop_pet()
        elif self.desktop_pet.window.winfo_exists():
            self.desktop_pet.toggle_visible()

    def _play_pet(self, state: str) -> None:
        if self.desktop_pet is None:
            self._start_desktop_pet()
        if self.desktop_pet is not None:
            self.desktop_pet.play(state)

    def _set_pet_working(self, working: bool) -> None:
        if self.desktop_pet is not None:
            self.desktop_pet.set_working(working)

    def _pet_feedback(self, state: str, message: str, duration: int = 3200) -> None:
        if self.desktop_pet is None:
            self._start_desktop_pet()
        if self.desktop_pet is not None:
            self.desktop_pet.play(state)
            self.desktop_pet.say(message, duration)

    def _event_line(self, event: str, **values: str) -> str:
        return self.pet_definition["event_line"](event, **values)

    def _show_task_error_feedback(self, error_text: str) -> None:
        detail = self._friendly_runtime_error(error_text)
        self._pet_feedback("failed", self._event_line("diagnose_error", detail=detail), 5200)
        self._log(f"自动周本启动条件未满足，已快速报告并进入后台诊断：{detail}")
        self._diagnose_runtime(announce=False)

    @staticmethod
    def _friendly_runtime_error(error_text: str) -> str:
        if "未找到模板" in error_text or "识别超时" in error_text:
            return f"当前画面没有匹配到任务需要的按钮或界面。{error_text}"
        if "模板不存在" in error_text or "模板组不存在" in error_text:
            return f"任务需要的模板文件不完整。{error_text}"
        if "等比例缩放" in error_text:
            return f"游戏窗口比例不符合模板基准。{error_text}"
        return error_text

    def _diagnose_runtime(self, announce: bool = True) -> None:
        if announce:
            self._pet_feedback("review", self._event_line("diagnose_start"), 3000)
        mode = self.target_mode.get()
        window_title = self.window_title.get()
        expected_resolution = self.expected_resolution.get()
        adb_path = self.adb_path.get()
        device_id = self.device_id.get()
        config_path = Path(self.config_path.get())
        task_count = len(self.tasks)
        enabled_tasks = [task for task in self.tasks if task.enabled]
        due_tasks = [task for task in enabled_tasks if self._is_due(task)]
        worker_running = bool(self.worker and self.worker.is_alive())
        last_started_tasks = list(getattr(self, "_last_started_tasks", []))
        last_started_at = float(getattr(self, "_last_task_started_at", 0.0))
        use_recent_task = bool(last_started_tasks) and (
            worker_running or time.monotonic() - last_started_at <= 300.0
        )
        diagnostic_tasks = last_started_tasks if use_recent_task else due_tasks
        combat_task = self._task_with_action(diagnostic_tasks, "combat_4c")
        navigation_task = None if combat_task is not None else self._task_with_action(
            diagnostic_tasks,
            "move_to_visual_target",
        )
        diagnostic_task = combat_task or navigation_task or (diagnostic_tasks[0] if diagnostic_tasks else None)
        template_dir = self._template_group_dir(
            diagnostic_task.template_group if diagnostic_task is not None else self.template_group.get()
        )

        def work() -> None:
            findings: list[tuple[str, str]] = []

            if diagnostic_task is not None:
                findings.append(("ok", f"本次诊断对象：{diagnostic_task.name}。"))

            try:
                is_admin = bool(ctypes.windll.shell32.IsUserAnAdmin())
            except Exception:
                is_admin = False
            if is_admin:
                findings.append(("ok", "程序已使用管理员权限运行。"))
            else:
                findings.append(("warning", "程序没有以管理员身份运行，鼠标点击可能会被游戏拦截。"))

            if config_path.exists():
                try:
                    configured_tasks = ConfigStore(config_path).load()
                    findings.append(("ok", f"任务配置可读取，共 {len(configured_tasks)} 个任务。"))
                except Exception as exc:
                    findings.append(("error", f"任务配置读取失败：{exc}"))
            else:
                findings.append(("error", f"任务配置不存在：{config_path}"))

            template_count = len(list(template_dir.glob("*.png"))) if template_dir.exists() else 0
            if template_count:
                findings.append(("ok", f"当前模板组有 {template_count} 张模板。"))
            else:
                findings.append(("error", f"当前模板组没有可用 PNG 模板：{template_dir}"))

            if task_count:
                findings.append(("ok", f"程序内已加载 {task_count} 个任务。"))
            else:
                findings.append(("error", "程序内没有加载任何任务。"))
            if task_count and not enabled_tasks:
                findings.append(("error", "当前没有启用的自动周本任务。请先在任务列表中启用至少一项。"))
            elif enabled_tasks and not due_tasks:
                findings.append(
                    (
                        "error",
                        "今天没有符合执行日条件的启用任务。请检查任务的执行日设置。",
                    )
                )
            elif due_tasks:
                findings.append(("ok", f"今天有 {len(due_tasks)} 个启用任务符合执行条件。"))
            if worker_running:
                findings.append(("warning", "当前已有任务线程正在运行，不需要重复启动。"))

            try:
                if mode == "adb":
                    output = AdbClient(adb_path, device_id).devices()
                    connected = [line for line in output.splitlines()[1:] if line.strip().endswith("device")]
                    if connected:
                        findings.append(("ok", f"ADB 已连接 {len(connected)} 台设备。"))
                    else:
                        findings.append(("error", "ADB 没有发现可用设备。"))
                else:
                    resolution_text = expected_resolution.strip().lower().replace("×", "x")
                    if resolution_text:
                        width_text, height_text = resolution_text.split("x", 1)
                        base_size = (int(width_text), int(height_text))
                    else:
                        base_size = None
                    controller = ClientWindowController(window_title, base_size)
                    connection_message = controller.connect()
                    findings.append(("ok", connection_message + "。"))
                    preview = APP_DIR / "_diagnostic_preview.png"
                    recent_runtime_preview = APP_DIR / "_runtime_screenshot.png"
                    can_reuse_runtime_preview = (
                        recent_runtime_preview.exists()
                        and time.time() - recent_runtime_preview.stat().st_mtime <= 12.0
                    )
                    if can_reuse_runtime_preview:
                        shutil.copy2(recent_runtime_preview, preview)
                        with Image.open(preview) as captured:
                            capture_size = captured.size
                        capture_method = "复用刚才的任务截图"
                    else:
                        capture_method = controller.screencap(preview)
                        capture_size = controller.last_capture_size or controller.client_size()
                    findings.append(("ok", f"游戏截图成功：{capture_size[0]}x{capture_size[1]}，方式 {capture_method}。"))
                    if combat_task is not None:
                        required_templates = (
                            "absorb_prompt_dark.png",
                            "absorb_prompt.png",
                            "restart_challenge.png",
                        )
                        missing = [name for name in required_templates if not (template_dir / name).exists()]
                        if missing:
                            findings.append(("error", f"4C刷取模板不完整：{', '.join(missing)}。"))
                        health_ratio = TaskRunner._boss_health_ratio(preview)
                        name_ratio = TaskRunner._boss_name_ratio(preview)
                        bar_track_score = TaskRunner._boss_bar_track_score(preview)
                        if name_ratio >= 0.015 or bar_track_score >= 0.18:
                            findings.append(
                                (
                                    "ok",
                                    f"已识别到4C首领名字或完整血条轨道：名字 {name_ratio:.3f}，"
                                    f"轨道 {bar_track_score:.3f}，血量色彩 {health_ratio:.3f}。",
                                )
                            )
                        else:
                            findings.append(
                                ("warning", "当前首领名字与整条血条都未出现：可能已经击败，或尚未进入4C战斗。")
                            )
                    elif navigation_task is not None:
                        navigation_step = next(
                            step for step in navigation_task.steps if step.action == "move_to_visual_target"
                        )
                        required_templates = [
                            name
                            for task_step in navigation_task.steps
                            for name in ([task_step.template] if task_step.template else []) + task_step.templates
                        ]
                        missing = [name for name in required_templates if not (template_dir / name).exists()]
                        if missing:
                            findings.append(("error", f"群声共振模拟域模板不完整：{', '.join(missing)}。"))
                        else:
                            matcher = TemplateMatcher(template_dir)
                            try:
                                prompt = matcher.find_fast(
                                    preview,
                                    navigation_step.template,
                                    threshold=max(0.70, navigation_step.threshold),
                                    scale=controller.scale,
                                )
                                findings.append(("ok", f"已经出现守岸人交互提示，相似度 {prompt.score:.3f}。"))
                            except Exception:
                                candidates = [
                                    matcher.find(preview, name, -1.0, [controller.scale])
                                    for name in navigation_step.templates
                                ]
                                best = max(candidates, key=lambda item: item.score)
                                if best.score >= navigation_step.threshold:
                                    findings.append(("ok", f"已定位到蓝色守岸人，相似度 {best.score:.3f}，可以开始靠近。"))
                                else:
                                    findings.append(("error", "当前画面没有定位到蓝色守岸人，请让角色和守岸人同时出现在画面中。"))
                    else:
                        start_template = template_dir / DIAGNOSTIC_START_TEMPLATE
                        if not start_template.exists():
                            findings.append(("error", f"缺少起始界面模板：{DIAGNOSTIC_START_TEMPLATE}。"))
                        else:
                            try:
                                start_match = TemplateMatcher(template_dir).find_fast(
                                    preview,
                                    DIAGNOSTIC_START_TEMPLATE,
                                    threshold=0.82,
                                    scale=controller.scale,
                                )
                                findings.append(
                                    (
                                        "ok",
                                        f"已确认位于无存档的小漂泊者初始界面，相似度 {start_match.score:.3f}。",
                                    )
                                )
                            except Exception as exc:
                                if "未找到模板" in str(exc):
                                    findings.append(
                                        (
                                            "error",
                                            "当前不是小漂泊者的初始界面，或界面已经存在存档。"
                                            "请返回带“开始游戏”按钮的小漂泊者页面，并确保没有存档。",
                                        )
                                    )
                                else:
                                    findings.append(("error", f"起始界面识别失败：{exc}"))
                    self.root.after(0, lambda: self._show_preview(preview, "诊断截图"))
            except Exception as exc:
                error_text = str(exc)
                if "等比例缩放" in error_text:
                    findings.append(("error", f"游戏窗口比例不对：{error_text}"))
                elif mode == "adb":
                    findings.append(("error", f"ADB 检查失败：{error_text}"))
                else:
                    findings.append(("error", f"游戏窗口检查失败：{error_text}"))

            self._log(f"=== {self.pet_name}运行诊断 ===")
            icons = {"ok": "[正常]", "warning": "[注意]", "error": "[问题]"}
            for level, message in findings:
                self._log(f"{icons[level]} {message}")
            self._log("=== 诊断结束 ===")

            errors = [message for level, message in findings if level == "error"]
            warnings = [message for level, message in findings if level == "warning"]
            if errors:
                primary = errors[0]
                self.root.after(
                    0,
                    lambda text=primary: self._pet_feedback(
                        "failed",
                        self._event_line("diagnose_error", detail=text),
                        6200,
                    ),
                )
            elif warnings:
                primary = warnings[0]
                self.root.after(
                    0,
                    lambda text=primary: self._pet_feedback(
                        "waiting",
                        self._event_line("diagnose_warning", detail=text),
                        6200,
                    ),
                )
            else:
                self.root.after(
                    0,
                    lambda: self._pet_feedback(
                        "waving",
                        self._event_line("diagnose_ok"),
                        4600,
                    ),
                )

        threading.Thread(target=work, daemon=True).start()

    def _close_app(self) -> None:
        self.stop_event.set()
        if self.pet_id == "aemeath":
            record_aemeath_departure()
        if self._hotkey_poll_job is not None:
            try:
                self.root.after_cancel(self._hotkey_poll_job)
            except Exception:
                pass
            self._hotkey_poll_job = None
        if self._hotkey_thread_id is not None:
            try:
                ctypes.windll.user32.PostThreadMessageW(self._hotkey_thread_id, WM_QUIT, 0, 0)
            except Exception:
                pass
        if self.desktop_pet is not None:
            self.desktop_pet.close()
        self.root.destroy()

    def _start_stop_hotkey(self) -> None:
        self.root.bind_all("<Control-Alt-s>", self._handle_local_stop_hotkey, add="+")

        def listen() -> None:
            try:
                self._hotkey_thread_id = int(ctypes.windll.kernel32.GetCurrentThreadId())
                modifiers = MOD_CONTROL | MOD_ALT | MOD_NOREPEAT
                self._hotkey_registered = bool(
                    ctypes.windll.user32.RegisterHotKey(None, STOP_HOTKEY_ID, modifiers, VK_S)
                )
            except Exception:
                self._hotkey_registered = False
            finally:
                self._hotkey_ready.set()

            if not self._hotkey_registered:
                return
            message = wintypes.MSG()
            try:
                while ctypes.windll.user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
                    if message.message == WM_HOTKEY and message.wParam == STOP_HOTKEY_ID:
                        self._hotkey_triggered.set()
            finally:
                ctypes.windll.user32.UnregisterHotKey(None, STOP_HOTKEY_ID)

        threading.Thread(target=listen, name="wwbs-stop-hotkey", daemon=True).start()
        self._hotkey_poll_job = self.root.after(100, self._poll_stop_hotkey)

    def _handle_local_stop_hotkey(self, _event=None):
        if not self._hotkey_registered:
            self._stop_from_hotkey()
        return "break"

    def _poll_stop_hotkey(self) -> None:
        self._hotkey_poll_job = None
        if self._hotkey_ready.is_set() and not self._hotkey_status_reported:
            self._hotkey_status_reported = True
            if self._hotkey_registered:
                self._log(f"全局停止快捷键已启用：{STOP_HOTKEY_LABEL}")
            else:
                self._log(f"全局快捷键注册失败；{STOP_HOTKEY_LABEL} 仍可在程序窗口内使用。")
        registered_trigger = self._hotkey_triggered.is_set()
        if registered_trigger:
            self._hotkey_triggered.clear()
        key_down = self._stop_hotkey_is_down()
        async_trigger = key_down and not self._hotkey_was_down
        self._hotkey_was_down = key_down
        if registered_trigger or async_trigger:
            self._stop_from_hotkey()
        if self.root.winfo_exists():
            self._hotkey_poll_job = self.root.after(100, self._poll_stop_hotkey)

    def _stop_from_hotkey(self) -> None:
        now = time.monotonic()
        if now - self._last_hotkey_stop_at < 0.5:
            return
        self._last_hotkey_stop_at = now
        self._log(f"收到快捷键 {STOP_HOTKEY_LABEL}。")
        self._stop()

    @staticmethod
    def _stop_hotkey_is_down() -> bool:
        """Fallback polling when RegisterHotKey is unavailable or loses a message."""
        try:
            get_key = ctypes.windll.user32.GetAsyncKeyState
            return all(get_key(key) & 0x8000 for key in (VK_CONTROL, VK_ALT, VK_S))
        except Exception:
            return False

    def _show_about(self) -> None:
        window = Toplevel(self.root)
        window.title("关于 wwbs")
        window.geometry("500x300")
        window.resizable(False, False)
        window.transient(self.root)
        window.grab_set()
        if APP_ICON.exists():
            window.iconbitmap(str(APP_ICON))

        container = Frame(window, padx=28, pady=24, bg=COLORS["panel"])
        container.pack(fill=BOTH, expand=True)
        Label(
            container,
            text="wwbs",
            font=(FONT_FAMILY, 22, "bold"),
            fg=COLORS["text"],
            bg=COLORS["panel"],
        ).pack(anchor="w")
        Label(
            container,
            text=f"版本号：{APP_VERSION}",
            font=(FONT_FAMILY, 11),
            fg=COLORS["muted"],
            bg=COLORS["panel"],
        ).pack(anchor="w", pady=(4, 20))

        Button(
            container,
            text="打开 B 站视频",
            command=lambda: self._open_external_link(ABOUT_BILIBILI_URL),
        ).pack(fill=X, pady=(0, 10))
        Button(
            container,
            text="打开 GitHub",
            command=lambda: self._open_external_link(ABOUT_GITHUB_URL),
        ).pack(fill=X)
        Button(container, text="关闭", command=window.destroy).pack(anchor="e", pady=(20, 0))

    def _open_external_link(self, url: str) -> None:
        try:
            if not webbrowser.open(url, new=2):
                raise RuntimeError("系统没有返回可用的浏览器。")
        except Exception as exc:
            messagebox.showerror("无法打开链接", f"请检查默认浏览器设置。\n\n{exc}", parent=self.root)

    def _show_update_history(self) -> None:
        window = Toplevel(self.root)
        window.title("wwbs 更新公告")
        window.geometry("720x560")
        window.minsize(560, 400)
        window.transient(self.root)

        container = Frame(window, padx=16, pady=16)
        container.pack(fill=BOTH, expand=True)
        Label(container, text="更新公告记录", font=(FONT_FAMILY, 14, "bold")).pack(anchor="w", pady=(0, 10))

        text_frame = Frame(container)
        text_frame.pack(fill=BOTH, expand=True)
        scrollbar = ttk.Scrollbar(text_frame, orient="vertical")
        history_text = Text(text_frame, wrap="word", font=(FONT_FAMILY, 10), yscrollcommand=scrollbar.set)
        scrollbar.config(command=history_text.yview)
        scrollbar.pack(side=RIGHT, fill="y")
        history_text.pack(side=LEFT, fill=BOTH, expand=True)
        for version, notice in UPDATE_HISTORY:
            history_text.insert(END, f"{version}\n{notice}\n\n")
        history_text.configure(state="disabled")
        Button(container, text="关闭", command=window.destroy).pack(anchor="e", pady=(10, 0))

    @staticmethod
    def _version_tuple(value: str) -> tuple[int, ...]:
        numbers = re.findall(r"\d+", value or "")
        return tuple(int(number) for number in numbers) or (0,)

    def _check_for_updates(self) -> None:
        if getattr(self, "update_worker", None) and self.update_worker.is_alive():
            messagebox.showinfo("检查更新", "正在检查更新，请稍候。", parent=self.root)
            return
        self.status.set("正在检查远程更新...")

        def work() -> None:
            try:
                request = urllib.request.Request(
                    UPDATE_API_URL,
                    headers={"User-Agent": f"wwbs/{APP_VERSION}"},
                )
                with urllib.request.urlopen(request, timeout=15) as response:
                    release = json.loads(response.read().decode("utf-8"))
                tag = str(release.get("tag_name", "")).strip()
                asset = next(
                    (item for item in release.get("assets", []) if item.get("name") == UPDATE_ASSET_NAME),
                    None,
                )
                if not tag or not asset:
                    raise RuntimeError("最新 Release 中没有找到 wwbs-exe.zip。")
                self.root.after(0, lambda: self._show_available_update(tag, release, asset))
            except Exception as exc:
                error_text = str(exc)
                self.root.after(0, lambda: self._show_update_error(error_text))

        self.update_worker = threading.Thread(target=work, daemon=True)
        self.update_worker.start()

    def _show_available_update(self, tag: str, release: dict, asset: dict) -> None:
        self.status.set("远程更新检查完成")
        if self._version_tuple(tag) <= self._version_tuple(APP_VERSION):
            messagebox.showinfo("检查更新", f"当前已经是最新版本：wwbs {APP_VERSION}", parent=self.root)
            return
        notes = str(release.get("body", "")).strip() or "该版本没有填写更新说明。"
        prompt = f"发现新版本：{tag}\n\n{notes}\n\n是否下载并安装？"
        if not messagebox.askyesno("发现新版本", prompt, parent=self.root):
            return
        if not getattr(sys, "frozen", False):
            messagebox.showinfo("开发模式", "源码运行模式可以检查更新，但请使用打包版 wwbs.exe 执行自动替换。", parent=self.root)
            return
        self.status.set(f"正在下载 {tag}...")
        threading.Thread(target=self._download_and_install_update, args=(tag, asset), daemon=True).start()

    def _show_update_error(self, error_text: str) -> None:
        self.status.set("远程更新检查失败")
        messagebox.showerror("检查更新失败", f"无法连接 GitHub Releases：\n{error_text}", parent=self.root)

    def _download_and_install_update(self, tag: str, asset: dict) -> None:
        work_dir = Path(tempfile.mkdtemp(prefix="wwbs_update_"))
        zip_path = work_dir / UPDATE_ASSET_NAME
        try:
            request = urllib.request.Request(
                str(asset["browser_download_url"]),
                headers={"User-Agent": f"wwbs/{APP_VERSION}"},
            )
            with urllib.request.urlopen(request, timeout=120) as response, zip_path.open("wb") as output:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    output.write(chunk)

            def ps_quote(value: str) -> str:
                return "'" + value.replace("'", "''") + "'"

            target_dir = Path(sys.executable).resolve().parent
            current_exe = Path(sys.executable).resolve()
            script_path = work_dir / "update.ps1"
            script = f"""
$ErrorActionPreference = 'Stop'
$work = {ps_quote(str(work_dir))}
$target = {ps_quote(str(target_dir))}
$zip = {ps_quote(str(zip_path))}
$exe = {ps_quote(str(current_exe))}
while (Get-Process -Id {os.getpid()} -ErrorAction SilentlyContinue) {{ Start-Sleep -Milliseconds 500 }}
$extract = Join-Path $work 'extract'
Expand-Archive -LiteralPath $zip -DestinationPath $extract -Force
Get-ChildItem -LiteralPath $extract -Force | ForEach-Object {{ Copy-Item -LiteralPath $_.FullName -Destination $target -Recurse -Force }}
Start-Process -FilePath $exe
Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue
"""
            script_path.write_text(script, encoding="utf-8")
            subprocess.Popen(
                ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script_path)],
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            self.root.after(0, self.root.destroy)
        except Exception as exc:
            error_text = str(exc)
            self.root.after(0, lambda: self._show_update_error(f"下载 {tag} 失败：{error_text}"))

    def _calculate_probability(self) -> None:
        try:
            astrite = self._read_non_negative_int(self.prob_astrite.get(), "星声数量")
            pulls = self._read_non_negative_int(self.prob_pulls.get(), "抽数")
            if pulls > 1000:
                raise ValueError("抽数不能超过 1000 抽。")
            character_pity = self._read_non_negative_int(self.prob_character_pity.get(), "角色水位")
            weapon_pity = self._read_non_negative_int(self.prob_weapon_pity.get(), "武器水位")
            character_target = self._read_non_negative_int(self.prob_character_target.get(), "想要获得角色数")
            weapon_target = self._read_non_negative_int(self.prob_weapon_target.get(), "想要获得武器数")
            if character_pity > 79 or weapon_pity > 79:
                raise ValueError("水位不能超过 79，因为第 80 抽必出 5 星。")
            if character_target == 0 and weapon_target == 0:
                raise ValueError("角色和武器目标不能同时为 0。")
            guaranteed = self.prob_character_guaranteed.get()
            self.prob_result.set("正在计算概率，界面仍可操作；复杂目标可能需要一些时间。")

            def work() -> None:
                try:
                    leftover = astrite % 160
                    probability = self._target_probability(
                        pulls,
                        character_pity,
                        weapon_pity,
                        character_target,
                        weapon_target,
                        guaranteed,
                    )
                    probability_text = self._format_probability(probability)
                    result = (
                        f"可用抽数：{pulls} 抽，剩余星声：{leftover}\n"
                        f"角色水位：{character_pity}，武器水位：{weapon_pity}\n"
                        f"角色大保底：{'是' if guaranteed else '否'}\n"
                        f"达成目标概率：{probability_text}\n"
                        f"目标：{character_target} 个 UP 角色，{weapon_target} 把 UP 武器"
                    )
                    guarantee_text = "有大保底" if guaranteed else "无大保底"
                    self._log(f"概率计算：{pulls} 抽，角色水位 {character_pity}，{guarantee_text}，武器水位 {weapon_pity}，目标 {character_target} 角色 + {weapon_target} 武器，结果 {probability_text}。")
                    self.root.after(0, lambda: self.prob_result.set(result))
                except Exception as exc:
                    error_text = str(exc)
                    self.root.after(0, lambda: self.prob_result.set(f"无法计算：{error_text}"))

            threading.Thread(target=work, daemon=True).start()
        except Exception as exc:
            self.prob_result.set(f"无法计算：{exc}")

    def _sync_pulls_from_astrite(self, *_args) -> None:
        if self._syncing_probability_inputs:
            return
        value = self.prob_astrite.get().strip()
        if not value.isdigit():
            return
        self._syncing_probability_inputs = True
        try:
            self.prob_pulls.set(str(int(value) // 160))
        finally:
            self._syncing_probability_inputs = False

    def _sync_astrite_from_pulls(self, *_args) -> None:
        if self._syncing_probability_inputs:
            return
        value = self.prob_pulls.get().strip()
        if not value.isdigit():
            return
        self._syncing_probability_inputs = True
        try:
            self.prob_astrite.set(str(int(value) * 160))
        finally:
            self._syncing_probability_inputs = False

    def _format_probability(self, probability: float) -> str:
        if probability <= 0:
            return "0%"
        percent = probability * 100
        if percent >= 0.01:
            return f"{percent:.2f}%"
        if percent >= 0.000001:
            return f"{percent:.6f}%（约 {self._format_one_in(probability)}）"
        return f"{percent:.2e}%（约 {self._format_one_in(probability)}）"

    def _format_one_in(self, probability: float) -> str:
        if probability <= 0:
            return "不可达"
        one_in = round(1 / probability)
        return f"{one_in:,} 次里成功 1 次"

    def _read_non_negative_int(self, value: str, label: str) -> int:
        text = value.strip()
        if not re.fullmatch(r"\d+", text):
            raise ValueError(f"{label}必须是 0 或正整数。")
        return int(text)

    def _target_probability(self, pulls: int, character_pity: int, weapon_pity: int, character_target: int, weapon_target: int, character_guaranteed: bool) -> float:
        if character_target == 0:
            return self._weapon_goal_probability(pulls, weapon_pity, weapon_target)
        if weapon_target == 0:
            return self._character_goal_cumulative(pulls, character_pity, character_target, character_guaranteed)[pulls]

        first_reach = self._character_goal_first_reach(pulls, character_pity, character_target, character_guaranteed)
        total = 0.0
        weapon_cache: dict[int, float] = {}
        for used_pulls, chance in enumerate(first_reach):
            if chance <= 0:
                continue
            remaining = pulls - used_pulls
            if remaining not in weapon_cache:
                weapon_cache[remaining] = self._weapon_goal_probability(remaining, weapon_pity, weapon_target)
            total += chance * weapon_cache[remaining]
        return total

    def _five_star_rate(self, pity: int) -> float:
        return 1.0 if pity >= 79 else 0.008

    def _character_goal_first_reach(self, pulls: int, pity: int, target: int, guaranteed: bool) -> list[float]:
        cumulative = self._character_goal_cumulative(pulls, pity, target, guaranteed)
        first = [0.0] * (pulls + 1)
        previous = 0.0
        for index, value in enumerate(cumulative):
            first[index] = max(0.0, value - previous)
            previous = value
        return first

    def _character_goal_cumulative(self, pulls: int, pity: int, target: int, guaranteed: bool = False) -> list[float]:
        if target <= 0:
            return [1.0] * (pulls + 1)
        states: dict[tuple[int, int, bool], float] = {(0, pity, guaranteed): 1.0}
        cumulative = [0.0] * (pulls + 1)
        cumulative[0] = 1.0 if target <= 0 else 0.0
        for pull_index in range(1, pulls + 1):
            next_states: dict[tuple[int, int, bool], float] = {}
            for (owned, current_pity, guaranteed), chance in states.items():
                if owned >= target:
                    next_states[(owned, current_pity, guaranteed)] = next_states.get((owned, current_pity, guaranteed), 0.0) + chance
                    continue
                five_rate = self._five_star_rate(current_pity)
                miss_rate = 1.0 - five_rate
                if miss_rate > 0:
                    miss_state = (owned, min(current_pity + 1, 79), guaranteed)
                    next_states[miss_state] = next_states.get(miss_state, 0.0) + chance * miss_rate
                if guaranteed:
                    up_state = (min(owned + 1, target), 0, False)
                    next_states[up_state] = next_states.get(up_state, 0.0) + chance * five_rate
                else:
                    up_state = (min(owned + 1, target), 0, False)
                    off_state = (owned, 0, True)
                    next_states[up_state] = next_states.get(up_state, 0.0) + chance * five_rate * 0.5
                    next_states[off_state] = next_states.get(off_state, 0.0) + chance * five_rate * 0.5
            states = next_states
            cumulative[pull_index] = sum(chance for (owned, _pity, _guaranteed), chance in states.items() if owned >= target)
        return cumulative

    def _weapon_goal_probability(self, pulls: int, pity: int, target: int) -> float:
        if target <= 0:
            return 1.0
        states: dict[tuple[int, int], float] = {(0, pity): 1.0}
        for _ in range(pulls):
            next_states: dict[tuple[int, int], float] = {}
            for (owned, current_pity), chance in states.items():
                if owned >= target:
                    next_states[(owned, current_pity)] = next_states.get((owned, current_pity), 0.0) + chance
                    continue
                five_rate = self._five_star_rate(current_pity)
                miss_rate = 1.0 - five_rate
                if miss_rate > 0:
                    miss_state = (owned, min(current_pity + 1, 79))
                    next_states[miss_state] = next_states.get(miss_state, 0.0) + chance * miss_rate
                up_state = (min(owned + 1, target), 0)
                next_states[up_state] = next_states.get(up_state, 0.0) + chance * five_rate
            states = next_states
        return sum(chance for (owned, _pity), chance in states.items() if owned >= target)

    def _choose_config(self) -> None:
        selected = filedialog.askopenfilename(
            title="选择周历配置",
            filetypes=[("JSON", "*.json"), ("所有文件", "*.*")],
            initialdir=str(APP_DIR),
        )
        if selected:
            self.config_path.set(selected)

    def _load_config(self, silent: bool) -> None:
        try:
            store = ConfigStore(Path(self.config_path.get()))
            self.tasks = store.load()
            self._sync_template_group_to_enabled_task()
            self._refresh_task_list()
            self._log(f"已加载配置: {store.path}")
        except Exception as exc:
            if not silent:
                messagebox.showerror("加载失败", str(exc))
            self._log(f"加载配置失败: {exc}")

    def _refresh_task_list(self) -> None:
        self.task_list.delete(0, END)
        for task in self.tasks:
            mark = "已启用" if task.enabled else "已停用"
            self.task_list.insert(END, f"{mark}  |  {self._weekday_label(task.weekday)}  |  {task.name}")
        if self.tasks:
            if not self.task_list.curselection():
                self.task_list.selection_set(0)

    def _show_selected_task(self) -> None:
        task = self._selected_task()
        if task:
            self._show_task(task)

    def _show_task(self, task: WeeklyTask) -> None:
        self.detail.delete("1.0", END)
        self.detail.insert(END, f"{task.name}\n\n")
        self.detail.insert(END, f"状态：{'会执行' if task.enabled else '不会执行'}\n")
        self.detail.insert(END, f"执行日：{self._weekday_label(task.weekday)}\n")
        self.detail.insert(END, f"模板组：{self._template_group_name(task.template_group)}\n")
        self.detail.insert(END, f"说明：{task.description or '暂无说明'}\n\n")
        self.detail.insert(END, "执行步骤：\n")
        for index, step in enumerate(task.steps, start=1):
            self.detail.insert(END, f"{index}. {self._describe_step(step)}\n")

    def _selected_task(self) -> WeeklyTask | None:
        selection = self.task_list.curselection()
        if not selection:
            return None
        return self.tasks[selection[0]]

    def _run_selected(self) -> None:
        task = self._selected_task()
        if not task:
            messagebox.showinfo("提示", "请先选择一个任务。")
            return
        self._start_worker([task])

    def _run_enabled(self) -> None:
        enabled_tasks = [task for task in self.tasks if task.enabled]
        tasks = [task for task in enabled_tasks if self._is_due(task)]
        if not tasks:
            reason = "当前没有启用任务。" if not enabled_tasks else "今天没有符合执行日条件的启用任务。"
            self._log(f"{reason}已直接进入运行诊断。")
            self._diagnose_runtime()
            return
        self._start_worker(tasks)

    def _preview_enabled(self) -> None:
        self.max_cycles = None
        self.dry_run.set(True)
        self._run_enabled()

    def _preview_selected(self) -> None:
        self.max_cycles = None
        self.dry_run.set(True)
        self._run_selected()

    def _start_enabled_real(self, max_cycles: int | None = None, require_confirmation: bool = True) -> None:
        if require_confirmation:
            target = "PC 客户端窗口" if self.target_mode.get() == "client" else "模拟器 / ADB"
            if not messagebox.askyesno("确认开始", f"程序将操作 {target}。请确认游戏已打开并停在正确界面。"):
                return
        else:
            self._log(f"由{self.pet_name}触发任务，已跳过开始确认。")
        self.max_cycles = max_cycles
        self.dry_run.set(False)
        if not self._ensure_admin_for_real_run():
            return
        self._preflight_enabled_run()

    def _start_named_task_real(
        self,
        task_name: str,
        cycles: int | None = None,
        require_confirmation: bool = True,
    ) -> None:
        task = next((item for item in self.tasks if item.name == task_name), None)
        if task is None:
            messagebox.showerror("任务不可用", f"没有找到任务：{task_name}", parent=self.root)
            return
        if task_name == "4C刷取":
            # The dedicated launcher always uses the packaged 4C resources. It must
            # not depend on, or alter, the template group selected in the UI.
            task = replace(task, template_group="4c", enabled=True)
        if self.target_mode.get() != "client":
            messagebox.showerror("模式不支持", "4C刷取目前只支持 PC 客户端窗口。", parent=self.root)
            return
        if require_confirmation and not messagebox.askyesno(
            "确认开始",
            f"将开始4C刷取（{cycles or 1}次）并操作游戏键盘与鼠标。请确认已经进入首领战斗。",
            parent=self.root,
        ):
            return
        self.max_cycles = cycles
        self.dry_run.set(False)
        if not self._ensure_admin_for_real_run():
            return
        self._start_worker([task])

    def _start_daily_routine(self, require_confirmation: bool = True) -> None:
        selected = self.daily_zone.get()
        if selected not in DAILY_ZONE_TEMPLATES:
            messagebox.showerror("请选择无音区", "请先滑动选择要挑战的无音区。", parent=self.root)
            return
        if self.target_mode.get() != "client":
            messagebox.showerror("模式不支持", "一键日常目前只支持 PC 客户端窗口。", parent=self.root)
            return
        if require_confirmation:
            if not messagebox.askyesno(
                "确认开始一键日常",
                f"将挑战“{selected}”两轮并领取日常奖励。\n\n"
                "体力不足时只会使用结晶单质或结晶溶剂；两者都没有就停止，绝不会使用星声。\n"
                "请确认角色当前位于可按 Esc 打开终端的大世界。",
                parent=self.root,
            ):
                return
        else:
            self._log(f"由{self.pet_name}触发一键日常，目标为“{selected}”，已跳过开始确认。")
        self._save_daily_zone()
        task = WeeklyTask(
            name="一键日常",
            enabled=True,
            weekday="any",
            description=(
                f"自动挑战 {selected} 两轮并领取活跃度与先约电台奖励；"
                "周度游历未完成时自动进入幻梦游园并执行15轮周常。"
            ),
            template_group="daily",
            steps=[
                Step(
                    action="daily_routine",
                    label=f"一键日常：{selected}",
                    timeout=600.0,
                )
            ],
        )
        self.max_cycles = 2
        self.dry_run.set(False)
        if not self._ensure_admin_for_real_run():
            return
        self._start_worker([task])

    def _preflight_enabled_run(self) -> None:
        """Catch common start-condition failures before the task's 8-second template timeout."""
        if self._preflight_running:
            self._pet_feedback("waiting", self._event_line("diagnose_start"), 2600)
            return
        if self.target_mode.get() != "client":
            self._run_enabled()
            return

        enabled_tasks = [task for task in self.tasks if task.enabled and self._is_due(task)]
        if not enabled_tasks:
            self._run_enabled()
            return
        if all(
            any(step.action == "move_to_visual_target" for step in getattr(task, "steps", []))
            for task in enabled_tasks
        ):
            self._log("群声共振模拟域使用场景识别，将在任务运行时直接检查目标与交互提示。")
            self._run_enabled()
            return

        self._preflight_running = True
        self._pet_feedback("review", self._event_line("check_start"), 2600)
        window_title = self.window_title.get()
        base_size = self._parse_resolution()
        template_dir = self._template_group_dir(self.template_group.get())

        def finish_success(elapsed: float) -> None:
            self._preflight_running = False
            self._log(f"快速启动检查通过，用时 {elapsed:.2f} 秒。")
            self._run_enabled()

        def finish_failure(error_text: str, elapsed: float) -> None:
            self._preflight_running = False
            self._log(f"快速启动检查失败，用时 {elapsed:.2f} 秒。")
            self._handle_task_failure(error_text)

        def work() -> None:
            started = time.perf_counter()
            try:
                controller = ClientWindowController(window_title, base_size)
                controller.connect()
                preview = APP_DIR / "_runtime_screenshot.png"
                controller.screencap(preview)
                TemplateMatcher(template_dir).find_fast(
                    preview,
                    DIAGNOSTIC_START_TEMPLATE,
                    threshold=0.82,
                    scale=controller.scale,
                )
            except Exception as exc:
                elapsed = time.perf_counter() - started
                self.root.after(0, lambda text=str(exc), seconds=elapsed: finish_failure(text, seconds))
                return
            elapsed = time.perf_counter() - started
            self.root.after(0, lambda seconds=elapsed: finish_success(seconds))

        threading.Thread(target=work, daemon=True).start()

    def _toggle_selected_enabled(self) -> None:
        task = self._selected_task()
        if not task:
            messagebox.showinfo("提示", "请先选择一个任务。")
            return
        task.enabled = not task.enabled
        ConfigStore(Path(self.config_path.get())).save(self.tasks)
        self._refresh_task_list()
        self._show_task(task)
        self._log(f"{task.name} 已{'启用' if task.enabled else '停用'}。")

    def _delete_selected_task(self) -> None:
        selection = self.task_list.curselection()
        if not selection:
            messagebox.showinfo("提示", "请先选择一个任务。")
            return
        index = selection[0]
        task = self.tasks[index]
        if not messagebox.askyesno("删除任务", f"确定删除任务“{task.name}”吗？"):
            return
        del self.tasks[index]
        ConfigStore(Path(self.config_path.get())).save(self.tasks)
        self._refresh_task_list()
        self.detail.delete("1.0", END)
        if self.tasks:
            next_index = min(index, len(self.tasks) - 1)
            self.task_list.selection_set(next_index)
            self._show_task(self.tasks[next_index])
        self._log(f"已删除任务：{task.name}")

    def _start_worker(self, tasks: list[WeeklyTask]) -> None:
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("提示", "任务正在运行中。")
            return
        if not self._ensure_admin_for_real_run():
            return
        self._last_started_tasks = list(tasks)
        self._last_task_started_at = time.monotonic()
        if len(tasks) == 1:
            task = tasks[0]
            self.template_status.set(
                f"当前任务 {task.name} · 模板组 {self._template_group_name(task.template_group)}"
            )
        self.stop_event.clear()
        self._pet_feedback("running", self._event_line("task_start"))
        self._set_pet_working(True)
        self.worker = threading.Thread(target=self._run_tasks, args=(tasks,), daemon=True)
        self.worker.start()

    def _run_tasks(self, tasks: list[WeeklyTask]) -> None:
        target = "PC 客户端窗口" if self.target_mode.get() == "client" else "模拟器 / ADB"
        self._log("预演模式：会识别模板，但不会点击。" if self.dry_run.get() else f"真实执行模式：将操作 {target}。")
        try:
            controller = self._make_controller()
            if hasattr(controller, "connect"):
                self._log(controller.connect())
            runner = TaskRunner(
                controller,
                self._log,
                self.dry_run.get(),
                self.stop_event,
                self.max_cycles,
                self.combat_skill_key.get(),
                self.combat_ultimate_key.get(),
                self.daily_zone.get(),
                self.daily_heal_enabled.get(),
                notice=lambda message: self.root.after(
                    0,
                    lambda text=message: messagebox.showinfo("提示", text, parent=self.root),
                ),
            )
            for task in tasks:
                runner.run_task(task)
            self._log("执行结束。")
            self.root.after(0, lambda: self._pet_feedback("review", self._event_line("task_complete")))
        except Exception as exc:
            error_text = str(exc)
            self._log(f"执行失败: {error_text}")
            self.root.after(0, lambda text=error_text: self._handle_task_failure(text))
        finally:
            self.max_cycles = None
            self.root.after(0, lambda: self._set_pet_working(False))

    def _is_due(self, task: WeeklyTask) -> bool:
        if task.weekday == "any":
            return True
        today = datetime.now(LOCAL_TZ).strftime("%a").lower()
        aliases = {
            "mon": "mon",
            "tue": "tue",
            "wed": "wed",
            "thu": "thu",
            "fri": "fri",
            "sat": "sat",
            "sun": "sun",
            "周一": "mon",
            "周二": "tue",
            "周三": "wed",
            "周四": "thu",
            "周五": "fri",
            "周六": "sat",
            "周日": "sun",
            "周天": "sun",
        }
        return aliases.get(task.weekday.lower(), task.weekday.lower()) == today

    @staticmethod
    def _task_with_action(tasks: list[WeeklyTask], action: str) -> WeeklyTask | None:
        return next(
            (task for task in tasks if any(step.action == action for step in task.steps)),
            None,
        )

    def _make_controller(self):
        if self.target_mode.get() == "adb":
            return AdbClient(self.adb_path.get(), self.device_id.get())
        return ClientWindowController(self.window_title.get(), self._parse_resolution())

    def _parse_resolution(self) -> tuple[int, int] | None:
        text = self.expected_resolution.get().strip().lower().replace("×", "x")
        if not text:
            return None
        try:
            width, height = text.split("x", 1)
            return int(width), int(height)
        except Exception:
            raise RuntimeError("模板基准格式应为 1920x1080。")

    def _check_target(self) -> None:
        self._pet_feedback("review", self._event_line("check_start"), 2600)

        def work() -> None:
            try:
                if self.target_mode.get() == "adb":
                    output = AdbClient(self.adb_path.get(), self.device_id.get()).devices()
                    connected = [line for line in output.splitlines()[1:] if line.strip().endswith("device")]
                    self.device_status.set(f"已连接 {len(connected)} 台设备" if connected else "未发现可用设备")
                    self._log("ADB 设备列表:\n" + output)
                    if not connected:
                        raise RuntimeError("未发现可用设备")
                    preview = APP_DIR / "_target_preview.png"
                    AdbClient(self.adb_path.get(), self.device_id.get()).screencap(preview)
                    self.root.after(0, lambda: self._show_preview(preview, "模拟器画面"))
                else:
                    controller = ClientWindowController(self.window_title.get(), self._parse_resolution())
                    message = controller.connect()
                    preview = APP_DIR / "_target_preview.png"
                    capture_method = controller.screencap(preview)
                    self.device_status.set("已找到 PC 窗口")
                    self._log(message)
                    self._log(f"PC 截图方式: {capture_method}")
                    self.root.after(0, lambda: self._show_preview(preview, "PC 客户端画面"))
                self.root.after(0, lambda: self._pet_feedback("waving", self._event_line("check_success")))
            except Exception as exc:
                self.device_status.set("检测失败")
                self._log(f"检测失败: {exc}")
                self.root.after(0, lambda: self._pet_feedback("failed", self._event_line("check_failure"), 4600))

        threading.Thread(target=work, daemon=True).start()

    def _screenshot(self) -> None:
        def work() -> None:
            try:
                target = APP_DIR / f"screenshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
                controller = self._make_controller()
                if hasattr(controller, "connect"):
                    self._log(controller.connect())
                capture_method = controller.screencap(target)
                if capture_method:
                    self._log(f"PC 截图方式: {capture_method}")
                self._log(f"截图已保存: {target}")
            except Exception as exc:
                self._log(f"截图失败: {exc}")

        threading.Thread(target=work, daemon=True).start()

    def _make_template(self) -> None:
        def work() -> None:
            try:
                TEMPLATES_DIR.mkdir(exist_ok=True)
                target = APP_DIR / "_template_source.png"
                controller = self._make_controller()
                if hasattr(controller, "connect"):
                    self._log(controller.connect())
                capture_method = controller.screencap(target)
                if capture_method:
                    self._log(f"模板来源截图方式: {capture_method}")
                group_dir = self._template_group_dir(self.template_group.get())
                group_dir.mkdir(parents=True, exist_ok=True)
                self.root.after(0, lambda: TemplateCropper(self.root, target, group_dir, self._after_template_saved))
            except Exception as exc:
                self._log(f"制作模板失败: {exc}")

        threading.Thread(target=work, daemon=True).start()

    def _after_template_saved(self, message: str) -> None:
        self._log(message)
        self._refresh_templates()
        template_path = message.split("模板已保存:", 1)[-1].strip()
        template_name = Path(template_path).name
        if template_name.lower().endswith(".png"):
            self._ensure_template_task(template_name, self._template_group_key(self.template_group.get()))

    def _stop(self) -> None:
        self.stop_event.set()
        self._pet_feedback("waiting", self._event_line("stop_requested"))
        self._log("正在请求停止...")

    def _open_config_dir(self) -> None:
        messagebox.showinfo("程序目录", f"程序文件都在这里：\n{APP_DIR}")

    def _refresh_templates(self) -> None:
        TEMPLATES_DIR.mkdir(exist_ok=True)
        groups = self._template_groups()
        current_group = self._template_group_key(self.template_group.get())
        if current_group not in groups:
            current_group = groups[0] if groups else DEFAULT_GROUP_KEY
        self.template_group.set(self._template_group_name(current_group))
        if hasattr(self, "template_group_combo"):
            self.template_group_combo["values"] = [self._template_group_name(group) for group in groups]
        group_dir = self._template_group_dir(self.template_group.get())
        templates = sorted(path.name for path in group_dir.glob("*.png")) if group_dir.exists() else []
        self.template_status.set(f"模板组 {self._template_group_name(current_group)} · {len(templates)} 张图片")
        if hasattr(self, "template_list"):
            self.template_list.delete(0, END)
            if templates:
                for name in templates:
                    self.template_list.insert(END, name)
            else:
                self.template_list.insert(END, "当前模板组还没有图片，请点击“制作新模板”。")

    @staticmethod
    def _is_dedicated_launcher_task(task: WeeklyTask) -> bool:
        return any(step.action == "combat_4c" for step in task.steps)

    @classmethod
    def _activate_template_group_task(
        cls,
        tasks: list[WeeklyTask],
        group: str,
    ) -> WeeklyTask | None:
        group_key = cls._template_group_key(group)
        ordinary_tasks = [task for task in tasks if not cls._is_dedicated_launcher_task(task)]
        active = next((task for task in ordinary_tasks if task.template_group == group_key), None)
        if active is None:
            return None
        for task in ordinary_tasks:
            task.enabled = task is active
        return active

    def _sync_template_group_to_enabled_task(self) -> None:
        active = next(
            (
                task
                for task in self.tasks
                if task.enabled and not self._is_dedicated_launcher_task(task)
            ),
            None,
        )
        if active is not None:
            self.template_group.set(self._template_group_name(active.template_group))

    def _on_template_group_selected(self, _event=None) -> None:
        selected_group = self._template_group_key(self.template_group.get())
        active = self._activate_template_group_task(self.tasks, selected_group)
        self._refresh_templates()
        if active is None:
            self._log(
                f"模板组 {self._template_group_name(selected_group)} 没有普通启动任务；"
                "4C请使用10次或30次专用按钮。"
            )
            return
        ConfigStore(Path(self.config_path.get())).save(self.tasks)
        self._refresh_task_list()
        index = self.tasks.index(active)
        self.task_list.selection_clear(0, END)
        self.task_list.selection_set(index)
        self.task_list.see(index)
        self._show_task(active)
        self.status.set(f"当前任务：{active.name}")
        self._log(
            f"已切换到 {self._template_group_name(selected_group)}，"
            f"普通启动按钮将执行：{active.name}。"
        )

    def _template_groups(self) -> list[str]:
        groups = [DEFAULT_GROUP_KEY] if any(TEMPLATES_DIR.glob("*.png")) else []
        groups.extend(sorted(path.name for path in TEMPLATES_DIR.iterdir() if path.is_dir() and not path.name.startswith(".")))
        return groups or [DEFAULT_GROUP_KEY]

    @staticmethod
    def _template_group_key(group: str) -> str:
        return DEFAULT_GROUP_KEY if group == DEFAULT_GROUP_NAME else group

    @staticmethod
    def _template_group_name(group: str) -> str:
        return DEFAULT_GROUP_NAME if group == DEFAULT_GROUP_KEY else group

    @classmethod
    def _template_group_dir(cls, group: str) -> Path:
        group_key = cls._template_group_key(group)
        return TEMPLATES_DIR if group_key == DEFAULT_GROUP_KEY else TEMPLATES_DIR / group_key

    def _create_template_group(self) -> None:
        name = simpledialog.askstring("新建模板组", "输入模板组名称，例如 周本任务2", parent=self.root)
        if not name:
            return
        safe_name = re.sub(r"[^\w\u4e00-\u9fff-]+", "_", name.strip()).strip("._")
        if not safe_name or safe_name in (DEFAULT_GROUP_KEY, DEFAULT_GROUP_NAME):
            messagebox.showerror("模板组名称无效", "请使用有效的模板组名称。")
            return
        group_dir = self._template_group_dir(safe_name)
        if group_dir.exists():
            messagebox.showinfo("提示", "这个模板组已经存在。")
            self.template_group.set(safe_name)
        else:
            group_dir.mkdir(parents=True)
            self.template_group.set(safe_name)
        self._refresh_templates()

    def _assign_selected_task_group(self) -> None:
        task = self._selected_task()
        if not task:
            messagebox.showinfo("提示", "请先在开始页面选择要绑定的任务。")
            return
        task.template_group = self._template_group_key(self.template_group.get())
        ConfigStore(Path(self.config_path.get())).save(self.tasks)
        self._show_task(task)
        self._log(f"任务 {task.name} 已切换到模板组 {self._template_group_name(task.template_group)}。")

    def _delete_selected_template(self) -> None:
        if not hasattr(self, "template_list"):
            return
        selection = self.template_list.curselection()
        if not selection:
            messagebox.showinfo("提示", "请先在模板列表里选择一个模板。")
            return
        group = self._template_group_key(self.template_group.get())
        if group == DEFAULT_GROUP_KEY:
            messagebox.showinfo("提示", "默认模板组不能整体删除。你可以先新建并切换到其他模板组。")
            return
        target = self._template_group_dir(group)
        if not target.exists():
            self._refresh_templates()
            return
        if not messagebox.askyesno("删除模板组", f"确定删除模板组 {group} 及其中的全部图片吗？"):
            return
        shutil.rmtree(target)
        affected = 0
        for task in self.tasks:
            if task.template_group == group:
                task.template_group = "default"
                affected += 1
        if affected:
            ConfigStore(Path(self.config_path.get())).save(self.tasks)
            self._refresh_task_list()
        self._refresh_templates()
        self._log(f"已删除模板组 {group}。" + (f" 已将 {affected} 个任务切回默认模板组。" if affected else ""))

    def _update_mode_label(self) -> None:
        if self.target_mode.get() == "client":
            self.device_status.set("PC 窗口未检测")
        else:
            self.device_status.set("ADB 设备未检测")

    def _ensure_template_task(self, template_name: str, template_group: str = "default") -> None:
        for task in self.tasks:
            for step in task.steps:
                if step.action == "tap_image":
                    step.template = template_name
                    task.template_group = template_group
                    task.enabled = True
                    ConfigStore(Path(self.config_path.get())).save(self.tasks)
                    self._refresh_task_list()
                    self._log(f"已把任务“{task.name}”绑定到模板 {template_name}。")
                    return
        task = WeeklyTask(
            name=f"点击模板 {template_name}",
            enabled=True,
            weekday="any",
            description="自动创建的图像识别点击任务。",
            template_group=template_group,
            steps=[
                Step(action="wait", label="等待画面稳定", seconds=1),
                Step(action="tap_image", label=f"识别并点击 {template_name}", template=template_name, threshold=0.82, timeout=8, seconds=1),
            ],
        )
        self.tasks.insert(0, task)
        ConfigStore(Path(self.config_path.get())).save(self.tasks)
        self._refresh_task_list()
        self._log(f"已创建任务：点击模板 {template_name}。")

    def _show_preview(self, image_path: Path, title: str) -> None:
        if not hasattr(self, "preview_canvas") or not image_path.exists():
            return
        self.preview_source = image_path
        self.preview_title = title
        image = Image.open(image_path).convert("RGB")
        canvas_width, canvas_height = self._preview_canvas_size()
        current_width = self.preview_canvas.winfo_width()
        current_height = self.preview_canvas.winfo_height()
        if abs(current_width - canvas_width) > 2 or abs(current_height - canvas_height) > 2:
            self.preview_canvas.configure(width=canvas_width, height=canvas_height)
        scale = min(canvas_width / image.width, canvas_height / image.height)
        preview_size = (max(1, int(image.width * scale)), max(1, int(image.height * scale)))
        preview = image.resize(preview_size, Image.Resampling.BILINEAR)
        self.preview_photo = ImageTk.PhotoImage(preview)
        self.preview_canvas.delete("all")
        x = (canvas_width - preview_size[0]) // 2
        y = (canvas_height - preview_size[1]) // 2
        self.preview_canvas.create_image(x, y, anchor="nw", image=self.preview_photo)
        self.preview_canvas.create_text(
            10,
            10,
            anchor="nw",
            text=title,
            fill="#ffffff",
            font=(FONT_FAMILY, 9, "bold"),
        )

    def _resize_preview_canvas(self, _event) -> None:
        if not hasattr(self, "preview_canvas"):
            return
        width, height = self._preview_canvas_size()
        if abs(self.preview_canvas.winfo_width() - width) > 2 or abs(self.preview_canvas.winfo_height() - height) > 2:
            self.preview_canvas.configure(width=width, height=height)
        if self.preview_source and self.preview_source.exists():
            self._show_preview(self.preview_source, self.preview_title)

    def _preview_canvas_size(self) -> tuple[int, int]:
        parent_width = max(self.preview_canvas.master.winfo_width(), 640)
        available_height = min(PREVIEW_MAX_HEIGHT, max(PREVIEW_MIN_HEIGHT, int(self.root.winfo_height() * 0.52)))
        target_width = min(parent_width, int(available_height * PREVIEW_ASPECT))
        target_height = int(target_width / PREVIEW_ASPECT)
        if target_height < PREVIEW_MIN_HEIGHT and parent_width >= int(PREVIEW_MIN_HEIGHT * PREVIEW_ASPECT):
            target_height = PREVIEW_MIN_HEIGHT
            target_width = int(target_height * PREVIEW_ASPECT)
        return target_width, target_height

    def _describe_step(self, step: Step) -> str:
        label = f"{step.label}：" if step.label else ""
        if step.action == "wait":
            return f"{label}等待 {step.seconds} 秒"
        if step.action == "tap_image":
            return f"{label}寻找模板 {step.template}，找到后点击"
        if step.action == "tap_image_cycle":
            count = len(step.templates) if step.templates else len(
                [path for path in TEMPLATES_DIR.glob("menu*.png") if re.fullmatch(r"menu\d+\.png", path.name)]
            )
            loop_text = "循环执行，直到达到已选择的轮数或手动停止" if step.loop else "执行一轮"
            return f"{label}按顺序识别 {count} 个模板，每步间隔 {step.seconds} 秒，{loop_text}"
        if step.action == "move_to_visual_target":
            return f"{label}固定视角下用 W/A/S/D 靠近目标，出现 {step.template} 后按 F"
        if step.action == "combat_4c":
            return f"{label}持续战斗，击败后寻找并吸收金色目标，再点击重新挑战；支持10次或30次循环"
        if step.action == "tap":
            return f"{label}点击固定位置 ({step.x}, {step.y})"
        if step.action == "swipe":
            return f"{label}从 ({step.x}, {step.y}) 滑到 ({step.x2}, {step.y2})"
        if step.action == "text":
            return f"{label}输入文字"
        return f"{label}{step.action}"

    def _weekday_label(self, weekday: str) -> str:
        labels = {
            "any": "每天",
            "mon": "周一",
            "tue": "周二",
            "wed": "周三",
            "thu": "周四",
            "fri": "周五",
            "sat": "周六",
            "sun": "周日",
        }
        return labels.get(weekday.lower(), weekday)

    def _log(self, message: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        self.log_queue.put(f"[{stamp}] {message}")

    def _notify_mouse_move_failure(self) -> None:
        now = time.monotonic()
        if now - self._last_mouse_admin_warning_at < 12.0:
            return
        self._last_mouse_admin_warning_at = now
        self._pet_feedback("failed", self._event_line("mouse_move_failed"), 6800)

    def _drain_logs(self) -> None:
        while True:
            try:
                line = self.log_queue.get_nowait()
            except queue.Empty:
                break
            if "鼠标没有移动成功" in line:
                self._notify_mouse_move_failure()
            self.detail.insert(END, "\n" + line)
            self.detail.see(END)
            if hasattr(self, "log_text"):
                self.log_text.insert(END, line + "\n")
                self.log_text.see(END)
            self.status.set(line)
        self.root.after(120, self._drain_logs)


def ensure_default_config() -> None:
    TEMPLATES_DIR.mkdir(exist_ok=True)
    if DEFAULT_CONFIG.exists():
        return
    sample = [
        WeeklyTask(
            name="图像识别点击示例",
            enabled=False,
            weekday="any",
            description="先点主界面的“制作模板”保存 menu.png，再启用本任务。",
            steps=[
                Step(action="wait", label="等待画面稳定", seconds=1),
                Step(action="tap_image", label="识别并点击菜单按钮", template="menu.png", threshold=0.82, timeout=8, seconds=1),
            ],
        ),
        WeeklyTask(
            name="领取周常奖励示例",
            weekday="mon",
            description="示例坐标基于 1920x1080 横屏，需要按你的设备截图调整。",
            steps=[
                Step(action="wait", label="等待游戏主界面稳定", seconds=2),
                Step(action="tap", label="打开终端/菜单", x=1760, y=80, seconds=1),
                Step(action="tap", label="进入活动或任务入口", x=1480, y=460, seconds=1),
                Step(action="tap", label="领取可领取奖励", x=1650, y=920, seconds=1),
            ],
        ),
        WeeklyTask(
            name="周本路线占位",
            weekday="any",
            description="把这里替换为你的副本入口、传送和挑战确认步骤。",
            steps=[
                Step(action="wait", label="确认角色可操作", seconds=1.5),
                Step(action="tap", label="打开地图", x=120, y=80, seconds=1),
                Step(action="swipe", label="地图拖动示例", x=1000, y=540, x2=700, y2=540, duration_ms=400, seconds=1),
            ],
        ),
    ]
    ConfigStore(DEFAULT_CONFIG).save(sample)


def main() -> None:
    ensure_default_config()
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ybpan34.wwbs.1.4.7")
    except Exception:
        pass
    root = Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
