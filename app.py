import json
import ctypes
from ctypes import wintypes
import io
import os
import queue
import random
import re
import secrets
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
from tkinter import BOTH, END, LEFT, RIGHT, TOP, X, BooleanVar, Canvas, Checkbutton, Entry, Frame, Label, Listbox, StringVar, Text, Tk, Toplevel, TclError, filedialog, messagebox, simpledialog, ttk
from tkinter import font as tkfont

from PIL import Image, ImageDraw, ImageTk
import numpy as np

from image_matcher import TemplateMatcher
from windows_client import ClientWindowController
from desktop_pet import DesktopPet
from chat_history import ChatHistory
from update_manager import prepare_update, install_script, signal_update_ready
from weekly_rewards import WeeklyLimitReached, WeeklyRewardsVision
from combat_rotation import ACTION_SPECS, COMBAT_MODES, SLOT_NAMES, BattleMonitor, IdleAttackWorker, RotationClock, active_modules, default_store, load_store, new_module, save_store, validate_store
from combat_seed import decode_seed, export_seed, import_seed
from ui_controls import RoundedButton, ThinScrollbar
from daniya_persona import (
    CHARACTER_PROMPT as daniya_character_prompt,
    DIALOGUE_PROMPT as daniya_dialogue_prompt,
    PERSONALITY_PROMPT as daniya_personality_prompt,
    SYSTEM_PROMPT as daniya_system_prompt,
    event_line as daniya_event_line,
    idle_line as daniya_idle_line,
    respond_to_user as daniya_respond_to_user,
)
from aemeath_persona import (
    CHARACTER_PROMPT as aemeath_character_prompt,
    DIALOGUE_PROMPT as aemeath_dialogue_prompt,
    PERSONALITY_PROMPT as aemeath_personality_prompt,
    SYSTEM_PROMPT as aemeath_system_prompt,
    event_line as aemeath_event_line,
    idle_dialogue as aemeath_idle_dialogue,
    record_departure as record_aemeath_departure,
    respond_to_user as aemeath_respond_to_user,
    welcome_dialogue as aemeath_welcome_dialogue,
)
from jingran_persona import (
    CHARACTER_PROMPT as jingran_character_prompt,
    DIALOGUE_PROMPT as jingran_dialogue_prompt,
    PERSONALITY_PROMPT as jingran_personality_prompt,
    SYSTEM_PROMPT as jingran_system_prompt,
    event_line as jingran_event_line,
    idle_line as jingran_idle_line,
    respond_to_user as jingran_respond_to_user,
    welcome_dialogue as jingran_welcome_dialogue,
)
from cartethyia_persona import (
    CHARACTER_PROMPT as cartethyia_character_prompt,
    DIALOGUE_PROMPT as cartethyia_dialogue_prompt,
    PERSONALITY_PROMPT as cartethyia_personality_prompt,
    SYSTEM_PROMPT as cartethyia_system_prompt,
    event_line as cartethyia_event_line,
    idle_line as cartethyia_idle_line,
    respond_to_user as cartethyia_respond_to_user,
    welcome_dialogue as cartethyia_welcome_dialogue,
)
from local_agent import (AgentReply, LocalAgentConfig, LocalCartethyiaAgent,
                         discover_local_models, list_service_models, service_base)
from sillytavern_bridge import PORT as SILLYTAVERN_BRIDGE_PORT, SillyTavernBridge


APP_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG = APP_DIR / "weekly_tasks.json"
TEMPLATES_DIR = APP_DIR / "templates"
DEFAULT_GROUP_KEY = "default"
DEFAULT_GROUP_NAME = "幻梦游园"
WEEKLY_TEMPLATE_THRESHOLD = 0.5
APP_ICON = APP_DIR / "wwbs.ico"
APP_VERSION = "1.5.4 beta1"
COMBAT_PRESETS_CONFIG = (Path(sys.executable).resolve().parent
                         if getattr(sys, "frozen", False) else APP_DIR) / "combat-presets.json"
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
    "tower": ("深塔挑战启动页面", RUN_NOTICE_DIR / "tower-start.png"),
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
UI_CONFIG = APP_DIR / "ui-settings.json"
APP_SETTINGS_CONFIG = APP_DIR / "app-settings.json"
UPDATE_NOTICE_CONFIG = COMBAT_PRESETS_CONFIG.with_name('update-notice.json')
CARTETHYIA_AGENT_CONFIG = APP_DIR / "cartethyia-agent-settings.json"
DANIYA_THEME_PACK = APP_DIR / "optional-themes" / "daniya-theme.wwbstheme"
AEMEATH_THEME_PACK = APP_DIR / "optional-themes" / "aemeath-theme.wwbstheme"
JINGRAN_THEME_PACK = APP_DIR / "optional-themes" / "jingran-theme.wwbstheme"
CARTETHYIA_THEME_PACK = APP_DIR / "optional-themes" / "cartethyia-theme.wwbstheme"
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
    ("v1.5.4 beta1", """v1.5.4 beta1 · 日常领取和普攻衔接修复
修复0活跃度误认为100：只匹配左下当前分数，连续复核，先领取上方黄色任务奖励再判断宝箱。
黄色领取按钮合并文字和花纹造成的断段，点击按钮中央；领取页加载和奖励弹层关闭后都等待页面稳定。
先约电台点击左侧图标中心，连续确认标签已选中，失败重试；不会跳过第一个免费奖励标签。
启用空闲普攻时，技能、大招和声骸按键释放后恢复普攻，继续并行查询模块，去除叠加的固定待机。
显式等待、实际施放、切人和结算仍暂停普攻。
页面切换减少导航重绘，隐藏截图暂停处理，日志分批刷新；圆角大小沿用原样式，修复按钮边框缺口。
大招过渡期间血条隐藏不判结束；发现吸收立即中断战斗长按，继续吸收及剩余4C轮次。
完整说明见 release-notes-v1.5.4-beta1.md。"""),
    ("v1.5.3", """v1.5.3 正式版 · 战斗轴分享与执行提速
角色整列可拖动排序，模块支持快速删除；技能、大招和声骸按间隔循环，离场继续计时。
新增深塔挑战和独立预设分配；战斗轴可生成短种子互换，导入新增预设并保留原名，兼容三代旧种子。
沉心域、烬心域置顶，改进名称和同行按钮识别。4C结束后直接进入吸收，不再调整视角。
开局去除重复切人确认，头像识别只处理小区域；前台截图缩短等待，切人保留确认与失败重试。
修复滚轮空白、窗口居中和公告弹出；快捷任务默认直接运行。完整说明见 release-notes-v1.5.3.md。"""),
    ("v1.5.3 beta6", """v1.5.3 beta6 · 切人确认与日常识别修复
切人后检查头像栏并重试，确认角色上场后才开始驻场计时；失败会停止，不跳过二号位执行一号位。
日志记录启动时的轴名、角色顺序及驻场时间，运行中保存会提示下次启动生效。
新无音区兼容原始与缩放字体，识别同一行前往／直接挑战按钮；按钮未完整出现时小幅滚动再识别。
新建排轴输入窗口居中；快捷任务取消开始确认，公告仅在当前版本首次启动时自动显示。
保留三代旧种子兼容检查。完整说明见 release-notes-v1.5.3-beta6.md。"""),
    ("v1.5.3 beta5", """v1.5.3 beta5 · 深塔挑战与更短种子
沉心域、烬心域无音区移到选择列表最上方，已保存的选择保留。
新增深塔挑战快捷任务：靠近光球，识别开始挑战后按F，持续执行专属排轴；只用挑战成功结算判断完成。
排轴增加深塔预设分配，可单独选择预设；结算后停止操作，不点击确认成绩，不自动关机。
默认轴种子约40字符，使用固定字典继续压缩；保留名字、精确参数、独立标识及校验，兼容前两种种子。
完整说明见 release-notes-v1.5.3-beta5.md。"""),
    ("v1.5.3 beta4", """v1.5.3 beta4 · 短种子与直接导入
改用紧凑的种子编码，默认轴约105字符，保留完整排轴、独立标识和完整性校验；兼容旧长种子导入。
种子生成与导入窗口居中于程序，创建时隐藏再定位，避免先闪到屏幕左上角。
粘贴种子即可直接导入，预览改为可选；修改输入后会校验并导入当前内容，不再强制重新预览。
继续新增独立预设、保留原名加“（导入）”，同名追加编号。
完整说明见 release-notes-v1.5.3-beta4.md。"""),
    ("v1.5.3 beta3", """v1.5.3 beta3 · 战斗轴种子分享
战斗排轴新增“生成种子”和“导入种子”，离线文字码携带角色顺序、驻场时间及全部模块参数。
每次生成有独立标识，可一键复制；导入先预览，再选择仅新增或用于4C、日常。
导入保留原轴名字并加“（导入）”，重复导入追加编号；新增独立预设，不覆盖已有轴。
提供完整性与参数校验，长名字保留开头与后缀显示，种子复制换行也可导入。
新增沉心域、烬心域无音区及对应名称识别，校准同一行前往按钮位置。
完整说明见 release-notes-v1.5.3-beta3.md。"""),
    ("v1.5.3 beta2", """v1.5.3 beta2 · 角色卡排序与吸收流程
每个角色的整列战斗轴显示为圆角卡片，拖动标题前的三点调整顺序；按从左到右轮换，开战先切到首个非空角色。
模块箭头左侧新增×，点击快速删除；保留拖动排序与点击修改。
修复短模块列表滚动后顶部出现空白的问题。
4C战斗中出现吸收提示立即转入吸收；吸收流程未出现提示时向前走一小段再检查，不再转头或调整视角。
日常光球保留水平搜索、靠近和领取，去除抬高与降低视角。
完整说明见 release-notes-v1.5.3-beta2.md。"""),
    ("v1.5.3 beta1", """v1.5.3 beta1 · 循环施放与4C结束识别
技能、大招和声骸按间隔循环施放，取消次数参数；驻场内按卡片顺序检查，未到间隔则跳过。
默认驻场改为25／15／5秒，技能5秒、大招15秒、声骸20秒；一号位每20次普攻穿插重击，保留三号位回血流程。
排轴三列随窗口高度伸展，修复最大化后下方留白。
4C左侧出现“领取奖励”时停止战斗并进入声骸吸收；没有提示时保留首领名字与血条消失复核。
周常流程模板阈值改为0.5，旧配置也生效；首个匹配成功的尺度立即返回，减少重复计算。
完整说明见 release-notes-v1.5.3-beta1.md。"""),
    ("v1.5.2", """v1.5.2 正式版 · 自定义战斗排轴与界面统一
- 新增三列战斗排轴：每个角色独立设置驻场秒数、模块参数和顺序，支持拖动排序、跨列移动、预设新建与切换；4C与日常分别分配预设。
- 普攻可选按次数、按秒数或空闲持续输出，恢复跳跃普攻。默认技能10秒、大招15秒，一号位每15次普攻穿插重击；三号位补齐可编辑回血连段。
- 普攻与战斗截图独立执行，减少识别造成的待机；修复驻场时间点击与保存、添加模块误弹窗、拖动卡死及浮层不跟手。
- 周常点击额外等待缩短到约0.06至0.10秒；目标丢失按本次、上一张、下一张、本次各2次重新识别，匹配成功才点击，仍未匹配则停止并反馈。
- 修复日常结算后再次打开索拉指南，素材获取页被误认成周度游历并报错的问题，按正常结算收尾。
- 模板、设置、概率、日志、聊天记录和输入窗口统一圆角控件、细滚动条与主题配色；按钮换行与整页滚动改善放大字体和窄窗口显示。
- 保留已有自定义预设及模式分配；仅未修改的旧默认战斗轴自动补齐。
完整更新说明与使用方法见安装包内 release-notes-v1.5.2.md。
"""),
    ("v1.5.2 beta9", """v1.5.2 beta9 更新内容
- 周常点击后的额外等待缩短为约0.06至0.10秒，旧配置也自动应用。
- 找不到目标时，重新截图依次识别：本次2次、上一张2次、下一张2次、本次再2次。
- 只在新识别匹配成功后点击；匹配到下一张时从下一步接续，仍未匹配则停止并反馈具体模板。
- 保留周常上限检测、最后一轮确认和任务停止响应。
"""),
    ("v1.5.2 beta8", """v1.5.2 beta8 更新内容
- 战斗截图识别独立执行，不再阻塞跳跃普攻、技能、切人和驻场计时。
- 默认三号位回血连段后继续空闲普攻，缩短重复切人等待；显式等待模块接管技能和声骸的收招时间，避免重复等待。
- 战斗结束仍暂停攻击并复核，截图检查失败会停止任务并报告原因。
- 未修改的旧默认轴自动更新，自定义模块、等待时间和模式分配保留。
"""),
    ("v1.5.2 beta7", """v1.5.2 beta7 更新内容
- 修复驻场时间输入框被下拉菜单覆盖、关闭菜单后无法获得输入焦点的问题。
- 下拉菜单优先缩短并向下展开，同时只保留一个菜单；切换页面会关闭菜单。
- 默认战斗轴补回三号位回血流程：技能、两组跳跃普攻、声骸Q及动作等待，三号位默认驻场8秒。
- 未修改的旧默认轴自动补齐回血模块，已自定义的战斗轴保留原设置。
"""),
    ("v1.5.2 beta3", """v1.5.2 beta3 更新内容
- 修复排轴拖动时浮层停止跟随光标；模块列表支持滚轮，滚动条与卡片样式统一到开始页。
- 移除固定“三号位回血”模块与开关；每个模块都可指定一、二、三号位，执行前自动切换。
- 4C 与一键日常可分别选用预设；切换编辑中的预设不会改变模式分配。
- 默认大招间隔改为15秒，默认持续普攻在15次普攻后穿插一次重击。
- 兼容旧预设文件：保留自建预设与排序，移除旧回血模块，为旧模块补齐一号位。
"""),
    ("v1.5.2 beta2", """v1.5.2 beta2 更新内容
- 新增“战斗排轴”：日常与4C共用可切换的战斗预设，可添加、移除和拖动圆角模块，并编辑普攻时长、重击次数、技能次数与触发间隔。
- 默认预设延续原有战斗节奏；战斗结束判断、领奖和安全停止仍由原任务流程处理。
- 调整顶部导航、任务卡、按钮、选择器和设置说明文字的布局，修复放大字体时显示不全。
- “概率”页改为随主题配色的圆角分区布局，并支持窄窗口滚动查看。
"""),
    ("v1.5.2 beta1", """v1.5.2 beta1 更新内容
- 修复一键日常结算后的素材获取页被误认成周度游历：改为识别选中标签的“周度游历”文字，避免点击错误入口并报告识别超时。
- 日常结算后再次进入索拉指南，若显示素材获取页，按正常结算结束，不再尝试点击幻梦游园入口或报告超时。
"""),
    ("v1.5.1", """v1.5.1 更新内容
- 新增 SillyTavern 酒馆桥接扩展和四位桌宠角色卡，保留角色剧情与项目原有后续关系设定。
- 桌宠 Agent 增加 DeepSeek API 与 OpenAI 兼容 API；填写密钥后获取服务模型，在下拉框直接选择。
- 增加本机模型检测：发现 Ollama、LM Studio 常用本地服务与默认模型目录，区分可用模型和需启动服务的模型。
- 检测结果可直接选用并填入连接信息，模型名仍可手动填写；原有 Ollama 设置保持兼容。
- API Key 仅在本次运行中保留，不写入配置文件；API 模式不会发送 Ollama 预热或卸载请求。
- 聊天输入框显示历史消息，桌宠右键可查看记录；按角色在本机保留最近500条，重启后仍可查看。
- 开启 Agent 时停止随机自言自语，只回复聊天与任务消息；关闭后恢复原有主动发言。
- 4C“30次”入口改为自定义次数，自动记住上次输入；保留10次快捷入口。
- 移除面向用户的 ADB、设备ID、任务配置路径与调试工具控件，内部使用默认配置。
- 周常识别“已达到上限”后返回主页、关闭游园并返回周度游历；从右向左选择带红点的发光宝箱，领取后确认对勾，跳过已领取宝箱。
- 一键日常改为在索拉指南左侧栏精确识别交叉武器“战斗”按钮，新手日志等额外入口不会再造成固定位置错点。
- 修复索拉指南记住上次“素材获取”页面时，一键日常误以为活跃度已完成并跳过无音区的问题。
- 进入“战斗”分类后按文字定位并复核“无音清剿”子菜单，避免固定点击落在行边缘。
- 修复圆角下拉菜单贴近屏幕底部时跑出可视区域并拦截其他控件；现可向上展开、点外部关闭。
- 快捷任务卡拖动时跟随光标显示，列表保留落点提示；左侧三点使用小手光标。
- 4C技能、大招、日常回血和完成后关机移动到开始页左侧任务设置；移除“保存键位”按钮，修改后自动保存并在重启后恢复。
- 修复绿色结晶材料已消耗但体力仍不足时不继续黄色材料的问题；补充窗口仍存在就继续第二种安全材料，始终不使用星声。
- 4C 和日常战斗改为每10秒尝试施放大招，持续普攻每10次穿插一次长按重击；三号位按Q前后增加收招时间，避免过早切人。
- “快捷任务”页改为圆角整行可点击卡片、细滚动条、扁平导航与紧凑状态栏；右侧实时截图和运行状态分卡呈现，预览缩小，主题颜色保持不变。
- 更新器修复中文路径脚本编码；安装前校验并解压完整运行库，替换前备份，失败保留日志并尝试回滚，不覆盖用户配置和聊天记录。
"""),
    ("v1.5.0", """v1.5.0 更新内容
- 新增卡提希娅Q版桌宠、专属冰蓝潮汐主题、16向鼠标注视和完整人格对话，桌宠与程序主题可独立切换。
- 本地 Agent 正式扩展到达妮娅、爱弥斯、景燃与卡提希娅；右键桌宠即可聊天，四位分别载入自己的完整人格并用桌宠气泡回复。
- 支持用明确自然语言启动日常、周常、周常星声、4C、停止与诊断白名单任务，回复会明确说明正在执行的目标。
- 桌宠聊天可安全修改三号位回血、任务完成自动关机，以及景燃/卡提希娅的盯鼠标和定时跳跃开关。
- 新增“任务正常完成后自动关机”选项，默认关闭；手动停止、执行失败和预演不会关机，触发时保留30秒取消时间。
- 输入框打开时后台预热 Ollama 模型，移除发送后的等待占位气泡；连续聊天复用模型60秒，自动任务开始前立即释放显存。
- “你是谁”“年龄多少”等稳定角色事实改为专属本地回答，避免小模型把不同问题重复成同一句或编造年龄。
- 景燃与卡提希娅新增鼠标注视、定时向前跳跃及右键开关；空中持续保持跳跃姿态，落地蹲姿延长并轻微缩小。
- 修复四款桌宠所有大小档位的透明边缘与缩放毛边，并修复长角色名气泡徽章遮挡。
- 修复一键日常结束后的周常页面判断，未进入周度游历页时按本周已完成处理，不再误报。
"""),
    ("v1.4.13", """v1.4.13 更新内容
- 本地 Agent 扩展到达妮娅、爱弥斯、景燃与卡提希娅四位桌宠；四位均可从右键菜单直接聊天，并通过自己的桌宠气泡回复。
- 四位桌宠分别载入历史版本中已经建立的人格文本，聊天时不会串角色；达妮娅补齐完整的系统、角色、性格与对话四层提示词。
- 为四位桌宠分别制作日常、周常、周常星声、4C、停止与诊断回复，任务气泡会明确说明正在处理的目标。
- 聊天输入框会随当前角色切换专属配色、标题与开场提示；四位共享同一套 Ollama 地址、模型和显存释放策略。
"""),
    ("v1.4.12", """v1.4.12 更新内容
- 将系统默认聊天输入框替换为卡提希娅冰蓝主题对话框，使用完整中文标题与“发送/取消”按钮，支持回车发送、Shift+Enter换行，并自动显示在桌宠附近。
- 优化 qwen3:4b 回复速度：关闭思考模式、限制短回复长度、缩短短期历史，并让连续聊天复用模型60秒。
- 首次聊天以及模型重新载入时，都会自动携带完整的卡提希娅角色设定；连续聊天保留最近三轮上下文。
- 日常、周常与4C等任务开始前仍会立即卸载模型，避免与《鸣潮》争抢显存；连接检测结束后同样立即释放。
"""),
    ("v1.4.11", """v1.4.11 更新内容
- 本地 Agent 每次回复后立即卸载 Ollama 模型，执行日常、周常、4C等任务前也会再次释放，避免与《鸣潮》争抢显存。
- 移除独立的 Agent 聊天窗口和设置页“打开聊天”按钮；现在从卡提希娅桌宠右键选择聊天，输入后由桌宠气泡直接回复。
- 调整任务指令回复，使卡提希娅明确说出正在执行的日常、周常、星声或4C目标，不再使用含糊的通用开场白。
"""),
    ("v1.4.10", """v1.4.10 更新内容
- 修复 qwen3.5:9b 等大型本地模型首次冷启动时，检测按钮20秒即误报 timed out 的问题；检测与聊天现在最多等待180秒。
- Ollama 对话成功后让模型保持热加载30分钟，减少连续聊天时反复载入造成的等待。
- 本地 Agent 超时提示改为中文，并明确给出首次加载、内存和小模型排查建议。
- 卡提希娅聊天窗口改为微信风格：角色消息左侧白色气泡、用户消息右侧绿色气泡，系统提示居中显示，并支持滚动浏览。
"""),
    ("v1.4.9", """v1.4.9 更新内容
- 新增卡提希娅Q版桌宠、16向鼠标注视、专属台词与冰蓝潮汐主题。
- 修复四款桌宠在 Windows 透明窗口中的黑边、杂色与缩放边缘模糊，覆盖全部大小档位。
- 修复单独切换桌宠后被当前主题强制改回的问题，桌宠与程序主题现在可独立选择。
- 景燃与卡提希娅新增“盯鼠标”和“定时跳跃”开关，设置页与桌宠右键菜单双向同步。
- 跳跃会沿当前朝向向前腾空，空中保持跳跃动画，接地后播放落地缓冲动作。
- 定时跳跃首次使用默认开启，每45至90秒尝试触发一次；已经保存的开关选择保持不变。
- 精简桌宠右键菜单，移除“检测游戏窗口”；主程序原有窗口检测功能保持不变。
- 完善卡提希娅人格、分级称呼、亲密与守护对话，并严格区分日常卡提希娅与低频芙露德莉斯形态。
- 重做景燃人格与对话：强化寻幽客、怪谈讲述、《寻幽记》写作及剧情后的同行者关系，危险时会切换为简短可靠的表达。
- 提高景燃主动说话频率，双击会立即说出台词；景燃与卡提希娅双击高跳时，腾空阶段固定使用真正的跳跃姿态。
- 新增卡提希娅本地 Agent 试用：用户可选择是否连接自行部署的 Ollama 兼容模型，通过聊天调用受限的日常、周常、4C、停止与诊断白名单。
- 修复一键日常结束后的周常检查：未自动进入周度游历页时直接判定周常已完成，不再等待错误页面并报错。
- 桌宠气泡姓名徽章改为自适应宽度与顶部留白，修复“卡提希娅”等长名字被遮挡。
"""),
    ("v1.4.8", """v1.4.8 更新内容
- 修复日常完成后索拉指南自动切换到周度游历时的衔接超时。
- 修复日常诊断错误提示缺少 menu1.png，分别检查日常与周常模板。
- 管理员模式自动重启后跳过更新公告，仅记录“检测到未开启管理员模式，已通过管理员模式打开”。
- 日常战斗结束检查改为每1秒一次，不再将白色怪物或技能特效作为奖励光球结束信号。
- 加长目标消失复核间隔；奖励搜索发现清怪目标仍在时恢复战斗，减少误判打断。
"""),
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
PREVIEW_MAX_HEIGHT = 300
PREVIEW_MIN_HEIGHT = 170
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
CYCLE_PROBE_ATTEMPTS = 2
CYCLE_PROBE_INTERVAL = 0.15
WEEKLY_CLICK_INTERVAL = 0.08
WEEKLY_CLICK_JITTER = 0.02
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
CARTETHYIA_COLORS = {
    "app_bg": "#edf4ff",
    "panel": "#f9fbff",
    "panel_alt": "#e3edfb",
    "line": "#9db6d8",
    "line_soft": "#cbd9ec",
    "text": "#1c2c4a",
    "muted": "#587096",
    "primary": "#315faf",
    "primary_hover": "#4778ca",
    "danger": "#9d5366",
    "preview": "#09152b",
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
    "cartethyia": {
        "pack": CARTETHYIA_THEME_PACK,
        "manifest_id": "cartethyia-fate-tide",
        "name": "卡提希娅主题",
        "colors": CARTETHYIA_COLORS,
        "banner_title": "卡提希娅",
        "banner_subtitle": "“即便身处命运的漩涡，我也有想要坚持的事。”——卡提希娅",
        "banner_overlay": (4, 16, 42, 92),
        "banner_text": "#f8fbff",
        "banner_muted": "#d9e8ff",
        "focus_y": 0.43,
    },
}
PET_DEFINITIONS = {
    "daniya": {
        "name": "达妮娅",
        "frames": APP_DIR / "pet-assets" / "pink-lace-chibi" / "frames",
        "scale": 1.15,
        "alpha_cutoff": 128,
        "event_line": daniya_event_line,
        "idle_line": daniya_idle_line,
        "bubble_palette": {},
    },
    "aemeath": {
        "name": "爱弥斯",
        "frames": APP_DIR / "pet-assets" / "aemeath-chibi" / "frames-sharp",
        "scale": 1.0,
        "alpha_cutoff": 128,
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
        "alpha_cutoff": 128,
        "event_line": jingran_event_line,
        "idle_line": jingran_idle_line,
        "welcome_dialogue": jingran_welcome_dialogue,
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
    "cartethyia": {
        "name": "卡提希娅",
        "frames": APP_DIR / "pet-assets" / "cartethyia-chibi" / "frames",
        "look_spritesheet": APP_DIR / "pet-assets" / "cartethyia-chibi" / "spritesheet.webp",
        "scale": 1.0,
        "alpha_cutoff": 128,
        "event_line": cartethyia_event_line,
        "idle_line": cartethyia_idle_line,
        "welcome_dialogue": cartethyia_welcome_dialogue,
        "bubble_palette": {
            "shadow": "#17233d",
            "body": "#f8fbff",
            "outline": "#6687c7",
            "badge": "#315baf",
            "badge_outline": "#d1b978",
            "ornament": "#7fc9ee",
            "ornament_outline": "#3e75bb",
            "text": "#24324e",
        },
    },
}

PET_AGENT_PROMPT_LAYERS = {
    "daniya": (daniya_system_prompt, daniya_character_prompt, daniya_personality_prompt, daniya_dialogue_prompt),
    "aemeath": (aemeath_system_prompt, aemeath_character_prompt, aemeath_personality_prompt, aemeath_dialogue_prompt),
    "jingran": (jingran_system_prompt, jingran_character_prompt, jingran_personality_prompt, jingran_dialogue_prompt),
    "cartethyia": (
        cartethyia_system_prompt,
        cartethyia_character_prompt,
        cartethyia_personality_prompt,
        cartethyia_dialogue_prompt,
    ),
}

PET_AGENT_FALLBACKS = {
    "daniya": daniya_respond_to_user,
    "aemeath": lambda message: aemeath_respond_to_user(message).text,
    "jingran": lambda message: jingran_respond_to_user(message).text,
    "cartethyia": lambda message: cartethyia_respond_to_user(message).text,
}

AGENT_TASK_LABELS = {
    "run_daily": "一键日常（2轮双倍）",
    "run_weekly_rewards": "周常拿满奖励（15轮）",
    "run_weekly_astrite": "周常拿满星声（13轮）",
    "run_4c_10": "4C刷取（10次）",
    "run_4c_30": "4C刷取（30次）",
    "stop_task": "停止当前任务",
    "diagnose": "运行诊断",
}

PET_AGENT_DIALOG_THEMES = {
    "daniya": {
        "background": "#fff3fa", "header": "#f7dbea", "title": "#713954", "muted": "#9b6480",
        "border": "#df8fbc", "editor": "#fffafd", "accent": "#d75f9d", "accent_active": "#bd4f89",
        "cancel": "#f3e1eb", "cancel_text": "#765469", "subtitle": "嗯……想和我说什么？",
    },
    "aemeath": {
        "background": "#f5fbff", "header": "#e4f6fb", "title": "#365b76", "muted": "#668ba2",
        "border": "#70ddeb", "editor": "#ffffff", "accent": "#d75f9d", "accent_active": "#bd4f89",
        "cancel": "#e3f2f7", "cancel_text": "#4e7187", "subtitle": "漂泊者，今天想和我聊什么？",
    },
    "jingran": {
        "background": "#101a22", "header": "#162732", "title": "#edf7f7", "muted": "#8db3ba",
        "border": "#4ac8d8", "editor": "#1b2b35", "accent": "#b99455", "accent_active": "#9f7b40",
        "cancel": "#243640", "cancel_text": "#c2d7d9", "subtitle": "有话直说，我听着。",
    },
    "cartethyia": {
        "background": "#eef7ff", "header": "#dceeff", "title": "#173d6b", "muted": "#56779d",
        "border": "#8ab9e8", "editor": "#ffffff", "accent": "#4a91d2", "accent_active": "#397fbe",
        "cancel": "#e5eef7", "cancel_text": "#476582", "subtitle": "义人，想和我说些什么？",
    },
}

COLORS = dict(SIMPLE_COLORS)

# “一键日常”无音区使用精确名称匹配。相似名称（尤其荒石高地 I / II）
# 必须各自对应独立模板，避免滑动列表时误点相邻条目。
DAILY_ZONE_TEMPLATES = {
    "沉心域无音区": "zone_chenxin_yu.png",
    "烬心域无音区": "zone_jinxin_yu.png",
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
# The new references are tight title crops; their row buttons sit lower.
DAILY_ZONE_BUTTON_Y_OFFSETS = {"zone_chenxin_yu.png": 37, "zone_jinxin_yu.png": 37}


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
    HEAVY_ATTACK_EVERY = 15
    HEAVY_ATTACK_HOLD_MS = 800
    MAIN_Q_INTERVAL = 20.0
    COMBAT_ULTIMATE_INTERVAL = 15.0
    ECHO_ACTION_SETTLE_DELAY = 1.0
    ULTIMATE_INDICATOR_REGION = (0.755, 0.74, 0.875, 0.95)
    ULTIMATE_RING_MIN_SATURATION = 0.27
    ULTIMATE_RING_MIN_COLOR_COVERAGE = 0.30
    ULTIMATE_RING_MIN_BRIGHTNESS = 0.58
    HEAL_ROTATION_INTERVAL = 9.0
    HEAL_SWITCH_SETTLE_DELAY = 2.0
    HEAL_ATTACK_CLICK_INTERVAL = ATTACK_CLICK_INTERVAL
    HEAL_RETURN_DELAY = 1.0
    HEAL_ATTACK_TO_Q_DELAY = 0.30
    HEAL_Q_TO_RETURN_DELAY = 0.80
    REWARD_INITIAL_CHECK_DELAY = 0.15
    REWARD_SEARCH_TURN_PIXELS = 950
    REWARD_SEARCH_TIMEOUT = 90.0
    EMPTY_HEALTH_CONFIRMATIONS = 3
    EMPTY_HEALTH_CONFIRMATION_INTERVAL = 0.15
    BOSS_HEADER_CHECK_INTERVAL = 0.15
    DAILY_BATTLE_END_CHECK_INTERVAL = 1.0
    DAILY_TASK_MISSING_CONFIRMATIONS = 3
    DAILY_TASK_MISSING_CONFIRMATION_INTERVAL = 0.75
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
        rotation_modules: list[dict] | None = None,
        rotation_presets: dict[str, list[dict]] | None = None,
        rotation_times: dict[str, dict] | None = None,
        rotation_orders: dict[str, list[int]] | None = None,
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
        self.rotation_modules = rotation_modules if rotation_modules is not None else active_modules(default_store())
        self.rotation_presets = rotation_presets or {}
        self.rotation_times = rotation_times or {}
        self.rotation_orders = rotation_orders or {}
        self._rotation_slot = 1
        self._rotation_end_check = None
        self._rotation_battle_finished = False
        self._combat_animation_until = 0.
        self._combat_input_cancel = threading.Event()
        self._rotation_continuous_started = False
        self.matcher = TemplateMatcher(TEMPLATES_DIR)
        self.template_root = TEMPLATES_DIR
        self.debug_matches = False
        self.last_clicked_image_step: Step | None = None
        self._weekly_monitoring = False
        self.weekly_rewards_pending = False

    def run_task(self, task: WeeklyTask) -> None:
        self._weekly_monitoring = task.template_group == "default" and task.name == DEFAULT_GROUP_NAME
        try:
            if self._weekly_monitoring and not self.dry_run:
                screenshot = APP_DIR / "_runtime_screenshot.png"
                self._capture_for_matching(screenshot)
                self._check_weekly_cap(screenshot)
            self._run_task_impl(task)
        except WeeklyLimitReached:
            self.log("周常已达到本周上限，已结束循环并返回周度游历。")
        finally:
            self._weekly_monitoring = False

    def _run_task_impl(self, task: WeeklyTask) -> None:
        group_dir = TEMPLATES_DIR / task.template_group if task.template_group != "default" else TEMPLATES_DIR
        if not group_dir.exists():
            raise FileNotFoundError(f"模板组不存在: {task.template_group}")
        self.template_root = group_dir
        self.matcher.templates_dir = group_dir
        self.log(f"使用模板组: {task.template_group}")
        self.log(f"开始任务: {task.name}")
        if self._weekly_monitoring:
            self.log(f"周常模板识别阈值：{WEEKLY_TEMPLATE_THRESHOLD:.2f}，匹配成功立即返回。")
        if task.template_group == "default" and task.name == DEFAULT_GROUP_NAME and not self.dry_run:
            self._wait_for_daily_template("menu1.png", timeout=8.0, threshold=WEEKLY_TEMPLATE_THRESHOLD)
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
        elif step.action == "tower_challenge":
            self._run_tower_challenge(step)
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

    def _tower_template_present(self, screenshot: Path, name: str, region) -> bool:
        with Image.open(screenshot) as source:
            width, height = source.size
        scale = min(height, width*9/16) / 1080
        return self._find_daily_template(
            str(TEMPLATES_DIR / "tower" / name), threshold=.86,
            region=tuple(round(v * (width if i % 2 == 0 else height)) for i, v in enumerate(region)),
            scales=[scale, scale*.97, scale*1.03], screenshot=screenshot,
        ) is not None

    def _tower_success_present(self, screenshot: Path) -> bool:
        return (self._tower_template_present(screenshot, "success_title.png", (.35, .18, .65, .40))
                and self._tower_template_present(screenshot, "confirm_score.png", (.35, .76, .66, .94)))

    def _approach_tower_start(self, screenshot: Path) -> bool:
        """Return True only if the challenge was started; never press F blindly."""
        deadline = time.monotonic() + 45
        while not self.stop_event.is_set() and time.monotonic() < deadline:
            self._capture_for_matching(screenshot)
            if self._tower_success_present(screenshot):
                self.log("    已显示深塔挑战成功，保持结算界面。")
                return False
            if self._tower_template_present(screenshot, "start_prompt.png", (.50, .32, .95, .75)):
                if self.stop_event.is_set():
                    return False
                self.controller.release_keys()
                self.controller.press_key("F", 100)
                self.log("    已识别“开始挑战”，按 F 开始深塔挑战。")
                self._sleep_interruptible(.4)
                return not self.stop_event.is_set()
            target_x, _target_y, _confidence = self._daily_reward_orb_location(screenshot)
            with Image.open(screenshot) as source:
                width = source.width
            keys = ("W",)
            if target_x is not None and abs(target_x-width*.5) > width*.05:
                keys = ("W", "A" if target_x < width*.5 else "D")
            if self.stop_event.is_set():
                return False
            self.controller.press_keys(keys, 300)
            self._sleep_interruptible(.08)
        if self.stop_event.is_set():
            return False
        raise RuntimeError("靠近深塔光球后未识别到“开始挑战”，请从塔内光球前的画面启动。")

    def _run_tower_challenge(self, step: Step) -> None:
        required = ("press_keys", "press_key", "press_binding", "left_click", "hold_left_button",
                    "middle_click", "release_keys")
        if any(not hasattr(self.controller, name) for name in required):
            raise RuntimeError("深塔挑战目前只支持 PC 客户端窗口。")
        if self.dry_run:
            self.log("    干运行：靠近光球，识别开始挑战后按 F，按深塔预设持续战斗至挑战成功。")
            return
        screenshot = APP_DIR / "_runtime_screenshot.png"
        try:
            if self._approach_tower_start(screenshot):
                self._run_tower_battle(step, screenshot)
        finally:
            self.controller.release_keys()

    def _run_tower_battle(self, step: Step, screenshot: Path) -> None:
        modules = self.rotation_presets.get("tower", self.rotation_modules)
        skill = self.controller.normalize_input_binding(self.combat_skill_key)
        ultimate = self.controller.normalize_input_binding(self.combat_ultimate_key)
        self._rotation_slot = None
        self._rotation_battle_finished = False
        self._rotation_end_check = self._tower_success_present
        self._combat_animation_until = 0.
        enabled, lock = threading.Event(), threading.Lock()
        idle = IdleAttackWorker(self.controller, self.stop_event, lock,
                                attack_interval=self.MAIN_ATTACK_CLICK_INTERVAL,
                                heavy_hold_ms=self.HEAVY_ATTACK_HOLD_MS)
        self._rotation_idle_worker = idle
        monitor = None
        try:
            def inspect():
                self._capture_for_matching(screenshot)
                return self._tower_success_present(screenshot)
            initial = inspect()
            if initial:
                self.log("    已识别挑战成功，停止操作并保持结算界面。")
                return
            # The clock's first select action confirms the role before any attack.
            # Confirming here as well would repeat the same two screenshot checks.
            self.controller.middle_click()
            rotation = RotationClock(modules, time.monotonic(), self.MAIN_ATTACK_CLICK_INTERVAL,
                                     self.rotation_times.get("tower"), background_idle=True,
                                     slot_order=self.rotation_orders.get("tower"))
            monitor = BattleMonitor(inspect, initial, self.stop_event)
            deadline = time.monotonic() + max(180, step.timeout)
            checked_at = 0.0
            while not self.stop_event.is_set() and time.monotonic() < deadline:
                checked = monitor.poll()
                if checked is not None:
                    checked_at = time.monotonic()
                    if checked[0]:
                        idle.pause()
                        monitor.pause()
                        enabled.clear()
                        self.controller.release_keys()
                        self.log("    深塔挑战成功，停止战斗；不点击确认成绩，保持结算界面。")
                        return
                elif time.monotonic()-checked_at >= .4:
                    monitor.request()
                if not self._run_rotation_action(rotation.next_action(time.monotonic()), rotation,
                                                 skill, ultimate, enabled, lock):
                    return
                self._sleep_interruptible(.025)
            if not self.stop_event.is_set():
                raise RuntimeError("深塔挑战达到安全时限，未识别到挑战成功，已停止操作。")
        finally:
            idle.close()
            self._rotation_end_check = None
            self._rotation_idle_worker = None
            enabled.clear()
            self.controller.release_keys()
            if monitor is not None:
                monitor.close()
                if monitor.error is not None:
                    raise RuntimeError(f"深塔画面检查失败：{monitor.error}") from monitor.error
            if idle.error is not None:
                raise RuntimeError(f"深塔战斗输入失败：{idle.error}") from idle.error

    def _run_4c_combat(self, step: Step) -> None:
        required = (
            "press_keys",
            "press_key",
            "press_binding",
            "left_click",
            "hold_left_button",
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
                f"然后按4C预设依次执行 {len(self.rotation_presets.get('combat_4c', self.rotation_modules))} 个模块；"
                f"技能键 {skill_key}，大招键 {ultimate_key}。"
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
        modules = self.rotation_presets.get("combat_4c", self.rotation_modules)
        self._rotation_slot = None
        self._rotation_battle_finished = False
        self._rotation_end_check = self._4c_switch_end_present
        self._combat_animation_until = 0.
        self._combat_input_cancel.clear()
        self._rotation_continuous_started = False
        last_header_check = 0.0
        boss_header_seen = False
        screenshot = APP_DIR / "_runtime_screenshot.png"
        self.log(f"    第{cycle_index}轮：鼠标中键锁定敌人。")
        self.controller.middle_click()
        attack_enabled = threading.Event()
        attack_lock = threading.Lock()
        idle_worker = IdleAttackWorker(self.controller, self.stop_event, attack_lock,
                                       attack_interval=self.MAIN_ATTACK_CLICK_INTERVAL,
                                       heavy_hold_ms=self.HEAVY_ATTACK_HOLD_MS,
                                       on_error=lambda exc: self.log(f"    空闲普攻失败：{exc}"))
        self._rotation_idle_worker = idle_worker
        monitor = None
        try:
            inspect = lambda: self._inspect_4c_battle_state(screenshot, cycle_index, 0, log_result=False)
            initial = inspect()
            rotation = RotationClock(modules, time.monotonic(), self.MAIN_ATTACK_CLICK_INTERVAL,
                                     self.rotation_times.get("combat_4c"), background_idle=True,
                                     slot_order=self.rotation_orders.get("combat_4c"))
            def stop_on_prompt(result):
                if result[1]:
                    self._rotation_battle_finished = True
                    self._combat_input_cancel.set()
                    idle_worker.close()
                    attack_enabled.clear()
                    self.controller.release_keys(("W", "A", "S", "D", "SPACE", "1", "2", "3"))
                    self.log(f"    识别到{result[1]}，立即停止战斗输入，进入吸收。")
            monitor = BattleMonitor(inspect, initial, self.stop_event, on_result=stop_on_prompt)
            while time.monotonic() < deadline:
                if self.stop_event.is_set():
                    return
                now = time.monotonic()
                checked = monitor.poll()
                if checked is not None:
                    header_present, reward_hint = checked[0]
                    last_header_check = time.monotonic()
                    if reward_hint:
                        idle_worker.pause()
                        monitor.pause()
                        attack_enabled.clear()
                        self.controller.release_keys()
                        hint = reward_hint if isinstance(reward_hint, str) else "领取奖励"
                        self.log(f"    第{cycle_index}轮：出现{hint}提示，战斗已结束，进入声骸吸收流程。")
                        return
                    elif header_present:
                        boss_header_seen = True
                    elif header_present is None or time.monotonic() < self._combat_animation_until:
                        # Ultimate cutscenes hide the HUD. Keep the current axis
                        # and idle attacks running; this frame is not a defeat.
                        pass
                    elif boss_header_seen:
                        idle_worker.pause()
                        monitor.pause()
                        attack_enabled.clear()
                        with attack_lock:
                            pass
                        missing_header_checks = 1
                        self.controller.release_keys()
                        self.log("    战斗监测发现首领名字与血条疑似消失，暂停攻击并快速复核。")
                        while missing_header_checks < self.EMPTY_HEALTH_CONFIRMATIONS:
                            self._sleep_interruptible(self.EMPTY_HEALTH_CONFIRMATION_INTERVAL)
                            header_present, reward_hint = self._inspect_4c_battle_state(
                                screenshot,
                                cycle_index,
                                missing_header_checks,
                            )
                            if reward_hint:
                                self.log(f"    第{cycle_index}轮：复核发现结束提示，进入声骸吸收流程。")
                                return
                            if header_present is None or time.monotonic() < self._combat_animation_until:
                                missing_header_checks = 0
                                break
                            if header_present:
                                missing_header_checks = 0
                                break
                            missing_header_checks += 1
                        if missing_header_checks >= self.EMPTY_HEALTH_CONFIRMATIONS:
                            self.controller.release_keys()
                            self.log(
                                f"    第{cycle_index}轮：已确认首领名字与整条血条彻底消失，进入吸收流程。"
                            )
                            return
                        monitor.resume()
                        last_header_check = time.monotonic()
                    elif now - started >= 15.0:
                        raise RuntimeError("没有检测到屏幕顶部的首领名字和血条，已停止4C刷取。请先进入战斗。")
                elif now - last_header_check >= self.BOSS_HEADER_CHECK_INTERVAL:
                    monitor.request()
                action = rotation.next_action(time.monotonic())
                if not self._run_rotation_action(action, rotation, skill_key, ultimate_key,
                                                 attack_enabled, attack_lock):
                    return
                self._sleep_interruptible(0.025)
            raise RuntimeError("单轮4C战斗达到安全时限，已自动停止。")
        finally:
            idle_worker.close()
            self._rotation_end_check = None
            self._rotation_idle_worker = None
            attack_enabled.clear()
            try:
                self.controller.release_keys()
            finally:
                if monitor is not None:
                    monitor.close()
            if monitor is not None and monitor.error is not None:
                raise RuntimeError(f"战斗画面检查失败：{monitor.error}") from monitor.error
            if idle_worker.error is not None:
                raise RuntimeError(f"空闲普攻失败：{idle_worker.error}") from idle_worker.error

    def _inspect_4c_battle_state(
        self, screenshot: Path, cycle_index: int, missing_checks: int, *, log_result: bool = True,
    ) -> tuple[bool | None, bool | str]:
        # Both signals use the same fresh frame; the reward hint is optional.
        inspected_at = time.monotonic()
        header_present = self._inspect_4c_boss_header(
            screenshot, cycle_index, missing_checks, log_result=log_result,
        )
        if self._4c_reward_hint_present(screenshot):
            return header_present, "领取奖励"
        try:
            with Image.open(screenshot) as captured:
                scale = captured.width / 1920.0
            prompt, _name = self._find_4c_absorb_prompt(screenshot, scale, fast=True)
        except (OSError, ValueError):
            prompt = None
        if prompt is not None:
            return header_present, "吸收"
        if not header_present:
            native_check = callable(getattr(type(self.controller), 'active_character_slot', None))
            if (inspected_at < self._combat_animation_until
                    or (native_check and (not self._overworld_hud_ready(screenshot)
                                          or self.controller.active_character_slot(screenshot) is None))):
                return None, False
        return header_present, False

    def _4c_reward_hint_present(self, screenshot: Path) -> bool:
        try:
            with Image.open(screenshot) as source:
                width, height = source.size
        except (OSError, ValueError):
            return False
        scale = height / 1080.0
        match = self._find_daily_template(
            str(TEMPLATES_DIR / "4c" / "claim_reward_hint.png"), threshold=0.86,
            region=(0, round(height * 0.12), round(width * 0.20), round(height * 0.65)),
            scales=[scale, scale * 0.96, scale * 1.04], screenshot=screenshot,
        )
        return match is not None

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
        heavy_every: int | None = None,
    ) -> None:
        """Attack on its own clock so screenshots and movement never form click bursts."""
        attack_count = 0
        while not attack_finished.is_set() and not self.stop_event.is_set():
            if not attack_enabled.wait(timeout=0.05):
                continue
            if attack_finished.is_set() or self.stop_event.is_set():
                return
            try:
                with attack_lock:
                    if attack_enabled.is_set():
                        if attack_count >= (heavy_every or self.HEAVY_ATTACK_EVERY):
                            self.controller.hold_left_button(self.HEAVY_ATTACK_HOLD_MS)
                            attack_count = 0
                        else:
                            self.controller.left_click()
                            attack_count += 1
            except Exception as exc:
                self.log(f"    持续普攻失败：{exc}")
                self.stop_event.set()
                return
            attack_finished.wait(self.MAIN_ATTACK_CLICK_INTERVAL)

    def _rotation_first_slot(self, modules: list[dict], mode: str) -> int:
        occupied = {item.get("slot", 1) for item in modules}
        return next(slot for slot in self.rotation_orders.get(mode, [1, 2, 3]) if slot in occupied)

    def _4c_switch_end_present(self, screenshot: Path) -> bool:
        if self._4c_reward_hint_present(screenshot):
            return True
        with Image.open(screenshot) as image:
            scale = image.width / 1920
        return self._find_4c_absorb_prompt(screenshot, scale, fast=True)[0] is not None

    def _read_rotation_slot(self, *, check_end: bool = True) -> int | None:
        screenshot = APP_DIR / '_role_screenshot.png'
        self._capture_for_matching(screenshot)
        observed = self.controller.active_character_slot(screenshot)
        # The first frame checks settlement. On the second, inspect it again only
        # when the HUD disappeared; a valid portrait does not need another full scan.
        if ((check_end or observed is None) and self._rotation_end_check is not None
                and self._rotation_end_check(screenshot)):
            self._rotation_battle_finished = True
            self.log("    切人确认时发现战斗结束，停止切人并进入任务收尾。")
            return None
        return observed

    def _select_rotation_slot(self, slot: int, *, verify: bool = False) -> bool:
        if self.stop_event.is_set():
            return False
        if self._rotation_battle_finished:
            return False
        native_check = callable(getattr(type(self.controller), 'active_character_slot', None))
        if native_check and (verify or self._rotation_slot != slot):
            deadline = time.monotonic()+6.0
            attempt, observed = 0, None
            while time.monotonic() < deadline and not self.stop_event.is_set():
                observed = self._read_rotation_slot()
                if self._rotation_battle_finished or self.stop_event.is_set():
                    return False
                if observed is None and time.monotonic() < self._combat_animation_until:
                    self._sleep_interruptible(.08)
                    continue
                if observed == slot:
                    self._sleep_interruptible(.025)
                    if self.stop_event.is_set():
                        return False
                    if (self._read_rotation_slot(check_end=False) == slot and not self._rotation_battle_finished
                            and not self.stop_event.is_set()):
                        self._rotation_slot = slot
                        self.log(f"    已确认{SLOT_NAMES[slot]}上场，开始执行该角色模块。")
                        return True
                    if self._rotation_battle_finished:
                        return False
                attempt += 1
                self.controller.release_keys(("W", "A", "S", "D", "SPACE", "1", "2", "3"))
                self.controller.press_key(str(slot), 65)
                self.log(f"    请求切到{SLOT_NAMES[slot]}（第{attempt}次），等待头像栏确认。")
                self._sleep_interruptible(.08)
            if self.stop_event.is_set():
                return False
            current = SLOT_NAMES.get(observed, '未识别')
            raise RuntimeError(f"未能确认切到{SLOT_NAMES[slot]}，最后识别为{current}。已停止，不会跳过此角色继续切人。")
        if self._rotation_slot != slot:
            self.controller.press_key(str(slot), 65)
            self._rotation_slot = slot
            self._sleep_interruptible(0.08)
        return not self.stop_event.is_set()

    def _run_rotation_action(self, action: dict | None, rotation: RotationClock,
                             skill_key: str, ultimate_key: str,
                             attack_enabled: threading.Event, attack_lock: threading.Lock,
                             *, daily: bool = False, task_seen: bool = True,
                             screenshot: Path | None = None) -> bool:
        if self._rotation_battle_finished or self.stop_event.is_set():
            return False
        if action is None:
            return not self.stop_event.is_set()
        kind, item = action["kind"], action["module"]
        idle_worker = getattr(self, "_rotation_idle_worker", None)
        if kind == "idle_attack":
            if idle_worker is not None and self._rotation_slot == item.get("slot", 1):
                idle_worker.arm(item, rotation.visit_deadline)
            return not self.stop_event.is_set()
        if idle_worker is not None:
            idle_worker.pause()
        attack_enabled.clear()
        if not self._select_rotation_slot(item.get("slot", 1), verify=kind == "select_slot"):
            return False
        if kind == "select_slot":
            rotation.start_visit(time.monotonic())
            return True
        if kind == "wait":
            return True
        if time.monotonic() >= rotation.visit_deadline:
            return True
        if kind == "left_click":
            self.controller.left_click()
        elif kind == "hold_left":
            remaining_ms = max(1, round((rotation.visit_deadline - time.monotonic()) * 1000))
            duration = min(self.HEAVY_ATTACK_HOLD_MS, remaining_ms)
            if callable(getattr(type(self.controller), 'hold_left_button_cancelable', None)):
                self.controller.hold_left_button_cancelable(duration, self._combat_input_cancel)
            else:
                self.controller.hold_left_button(duration)
        elif kind == "jump":
            self.controller.press_key("SPACE", 50)
        elif kind in {"skill", "ultimate", "echo"}:
            if self.stop_event.is_set():
                return False
            rotation.last_run[item["id"]] = time.monotonic()
            explicit_wait = rotation.has_following_wait(time.monotonic())
            idle_module = next((module for module in rotation.columns[rotation.slot]
                                if module['kind'] == 'idle_attack'), None)
            resume_idle = (idle_worker is not None and rotation.background_idle
                           and idle_module is not None and not explicit_wait)
            if kind == "skill":
                self.controller.press_binding(skill_key, 65)
                if not (explicit_wait or resume_idle):
                    self._sleep_interruptible(min(0.20, max(0, rotation.visit_deadline - time.monotonic())))
            elif kind == "ultimate":
                self._cast_timed_ultimate(ultimate_key, attack_enabled, attack_lock, resume_attacks=False,
                                         settle_delay=0 if explicit_wait or resume_idle else min(0.8, max(0, rotation.visit_deadline - time.monotonic())))
            else:
                self.controller.press_key("Q", 120)
                if not (explicit_wait or resume_idle):
                    self._sleep_interruptible(min(self.ECHO_ACTION_SETTLE_DELAY,
                                                  max(0, rotation.visit_deadline - time.monotonic())))
            # Resume only after the cast key is released. Due-module inspection
            # then runs alongside the idle worker; actual actions pause it again.
            if resume_idle and not self.stop_event.is_set() and not self._rotation_battle_finished:
                # Preserve the skill-to-skill cadence, but represent it in the
                # scheduler so idle clicks and ending checks remain responsive.
                delay = {'skill': .2, 'ultimate': .8, 'echo': self.ECHO_ACTION_SETTLE_DELAY}[kind]
                rotation.defer_cast_followup(time.monotonic(), delay)
                idle_worker.arm(idle_module, rotation.visit_deadline)
        elif kind == "approach":
            duration = min(float(item["value"]), max(0, rotation.visit_deadline - time.monotonic()))
            if callable(getattr(type(self.controller), 'press_keys_cancelable', None)):
                self.controller.press_keys_cancelable(("W",), max(1, round(duration*1000)), self._combat_input_cancel)
            else:
                self.controller.press_keys(("W",), max(1, round(duration * 1000)))
        return not self.stop_event.is_set()

    def _run_daily_routine(self, step: Step) -> None:
        """Run the two-round daily tacet-field flow with optional healing."""
        required = (
            "press_keys",
            "press_key",
            "press_binding",
            "left_click",
            "hold_left_button",
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
        self.log("    日常战斗将按已分配的预设切换角色并执行模块。")
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
        """Require the selected tab's text, not a pale training-target card."""
        return WeeklyRewardsVision(TEMPLATES_DIR / "weekly").weekly_page(screenshot)

    @staticmethod
    def _guide_material_page_present(screenshot: Path) -> bool:
        """Identify the normal material page reached after guide rewards are done."""
        with Image.open(screenshot) as source:
            width, height = source.size
        if abs(width / height - 16 / 9) > 0.04:
            return False
        try:
            TemplateMatcher(TEMPLATES_DIR / "daily").find_fast(
                screenshot, "guide_material_title.png", threshold=0.82, scale=width / 1920,
                region=(round(width * 0.05), round(height * 0.03),
                        round(width * 0.16), round(height * 0.11)),
            )
            return True
        except (RuntimeError, FileNotFoundError):
            return False

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
            screenshot = APP_DIR / "_runtime_screenshot.png"
            if self._weekly_travel_page_present(screenshot):
                self.log("    索拉指南自动进入周度游历，今日日常已完成。")
                return False
            # The guide may reopen on its previously selected material page.
            # That page is not evidence that the daily activity is complete.
            self.log("    索拉指南未停留在活跃度页，尝试切回左侧活跃度入口。")
            self._tap_ratio(0.04, 0.18, 0.45)
            if not self._daily_activity_still_pending():
                if self._weekly_travel_page_present(screenshot):
                    self.log("    活跃度入口已自动跳转周度游历，今日日常已完成。")
                    return False
                raise RuntimeError("索拉指南未显示活跃度或周度游历页面，已停止以避免跳过日常。")
        self._click_daily_template(
            "guide_battle_tab.png",
            "索拉指南左侧战斗按钮",
            timeout=8.0,
            threshold=0.78,
            region_ratio=(0.015, 0.10, 0.095, 0.88),
        )
        self._sleep_interruptible(1.0)
        self._select_daily_tacet_section()

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
            if zone_template in DAILY_ZONE_BUTTON_Y_OFFSETS:
                result = self._find_new_daily_zone(screenshot, zone_template)
                found = result[0] if result else None
                if found is None and page_index == 0:
                    wx, wy = round(width*.91), round(height*.60)
                    if hasattr(self.controller, 'screenshot_to_client'):
                        wx, wy = self.controller.screenshot_to_client(wx, wy)
                    self.controller.wheel_at(wx, wy, 7200)
                    self._sleep_interruptible(.25)
                    continue
            else:
                found = self._find_daily_template(
                zone_template,
                threshold=zone_threshold,
                region=(round(width * 0.34), round(height * 0.12), round(width * 0.98), round(height * 0.92)),
                template_crop=zone_crop,
                scales=[self._fast_scales()[0]],
                screenshot=screenshot,
            )
            if found is not None:
                if zone_template in DAILY_ZONE_BUTTON_Y_OFFSETS:
                    _title, button = result
                    if button is None:
                        self.log(f"    已看到“{self.daily_zone_name}”，同行按钮尚未完整可点，小幅滚动后重新识别。")
                        wx, wy = round(width*.91), round(height*.60)
                        if hasattr(self.controller, 'screenshot_to_client'):
                            wx, wy = self.controller.screenshot_to_client(wx, wy)
                        self.controller.wheel_at(wx, wy, -120)
                        self._sleep_interruptible(.25)
                        continue
                    self.log(f"    已识别“{self.daily_zone_name}”及同一行前往按钮，点击 {button.center}。")
                    self.controller.tap(*button.center)
                    self._sleep_interruptible(3.0)
                    break
                row_y = found.center[1] + round(DAILY_ZONE_BUTTON_Y_OFFSETS.get(zone_template, 0) * self._fast_scales()[0])
                if not self._daily_row_button_ready(screenshot, row_y):
                    wheel_x, wheel_y = round(width * 0.91), round(height * 0.60)
                    if hasattr(self.controller, "screenshot_to_client"):
                        wheel_x, wheel_y = self.controller.screenshot_to_client(wheel_x, wheel_y)
                    self.log(f"    已看到“{self.daily_zone_name}”，等待同一行按钮完整出现。")
                    if row_y > round(height * 0.68):
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
                self.controller.tap(button_x, row_y)
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
    def _guide_tacet_section_selected(screenshot: Path, row_y: int) -> bool:
        """The selected sidebar row is pale; other material rows are dark."""
        with Image.open(screenshot) as source:
            image = np.asarray(source.convert("RGB"))
        height, width = image.shape[:2]
        top = max(0, row_y - round(height * 0.03))
        bottom = min(height, row_y + round(height * 0.03))
        row = image[top:bottom, round(width * 0.105):round(width * 0.34)]
        return bool(row.size and float((row.min(axis=2) > 170).mean()) > 0.5)

    def _select_daily_tacet_section(self) -> None:
        screenshot = APP_DIR / "_runtime_screenshot.png"
        for attempt in range(3):
            _path, width, height = self._capture_size(screenshot)
            if self._guide_tacet_section_selected(screenshot, round(height * 0.73)):
                self.log("    已确认战斗分类中的“无音清剿”处于选中状态。")
                return
            match = self._find_daily_template(
                "guide_tacet_section.png",
                threshold=0.72,
                region=(round(width * 0.10), round(height * 0.58),
                        round(width * 0.36), round(height * 0.88)),
                scales=[self._fast_scales()[0]],
                screenshot=screenshot,
            )
            if match is None:
                self._sleep_interruptible(0.4)
                continue
            # Click the row center, below the label. Its old hardcoded y=0.695
            # landed on the upper edge and could leave the wrong category open.
            click_y = min(height - 1, match.center[1] + round(height * 0.015))
            self.log(f"    已找到“无音清剿”子菜单（相似度 {match.score:.3f}），点击并复核选中状态。")
            self._tap_ratio(0.22, click_y / height, 0.65)
            self._capture_for_matching(screenshot)
            if self._guide_tacet_section_selected(screenshot, click_y):
                return
            self._sleep_interruptible(0.3)
        raise RuntimeError("战斗分类中未能选中“无音清剿”，已停止以避免点击错误副本。")

    def _find_new_daily_zone(self, screenshot: Path, template: str):
        with Image.open(screenshot) as source:
            width, height = source.size
        base = self._fast_scales()[0]
        region = (round(width*.10), round(height*.08), round(width*.98), round(height*.94))
        native = template.replace('.png', '_native.png')
        best_title = None
        # Keep the original 37px reference as well as the older 24px variant.
        # A cropped screenshot's font size is not determined by game width alone.
        for factor in (1., .8, 1.15, .65, 1.3, 1.5):
            for name, crop, reference in ((template, (0, 0, 82, 29), 24.),
                                          (native, (0, 0, 127, 45), 37.)):
                scale = base*factor
                title = self._find_daily_template(name, threshold=.85, region=region,
                                                  template_crop=crop, scales=[scale], screenshot=screenshot)
                if title is None:
                    continue
                if best_title is None or title.score > best_title.score:
                    best_title = title
                predicted_y = title.center[1] + round(57*reference/37*scale)
                row_region = (round(width*.58), max(0, predicted_y-round(38*scale)),
                              round(width*.98), min(height, predicted_y+round(38*scale)))
                for button_name, button_reference in (('zone_go_native.png', 37.),
                                                       ('zone_direct_challenge.png', 24.)):
                    button = self._find_daily_template(button_name, threshold=.82,
                                                       region=row_region, scales=[scale*reference/button_reference],
                                                       screenshot=screenshot)
                    if button is not None and self._daily_row_button_ready(screenshot, button.center[1], center_x=button.center[0]):
                        return title, button
        return (best_title, None) if best_title is not None else None

    @staticmethod
    def _daily_row_button_ready(screenshot: Path, row_y: int, *, center_x: int | None = None) -> bool:
        """Require the dark challenge button to be visible, not hidden by the footer."""
        with Image.open(screenshot) as source:
            image = np.asarray(source.convert("RGB"))
        height, width = image.shape[:2]
        top = max(0, int(row_y) - round(height * 0.035))
        bottom = min(height, int(row_y) + round(height * 0.035))
        left, right = round(width * 0.82), round(width * 0.96)
        if center_x is not None:
            left, right = max(0, center_x-round(width*.065)), min(width, center_x+round(width*.065))
        region = image[top:bottom, left:right]
        if region.size == 0:
            return False
        dark = region.max(axis=2) < 75
        lines = np.flatnonzero(dark.mean(axis=1) >= .30)
        if not len(lines):
            return False
        runs = np.split(lines, np.where(np.diff(lines) != 1)[0]+1)
        minimum = max(12, round(height*.03))
        local_y = int(row_y)-top
        return any(len(run) >= minimum and run[0] <= local_y <= run[-1] for run in runs)

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

    def _select_daily_slot_after_loading(self, screenshot: Path, slot: int = 1) -> None:
        """Wait for the battle HUD, then ensure the first configured character is active."""
        deadline = time.monotonic() + 15.0
        hud_ready = False
        while time.monotonic() < deadline:
            if self.stop_event.is_set():
                return
            self._capture_for_matching(screenshot)
            if self._daily_battle_task_present(screenshot):
                hud_ready = True
                break
            self._sleep_interruptible(0.15)
        self.controller.press_key(str(slot), 65)
        self._sleep_interruptible(0.08)
        if hud_ready:
            self.log(f"    战斗界面已加载，按 {slot} 确保当前角色为{SLOT_NAMES[slot]}。")
        else:
            self.log(f"    等待战斗界面超时，仍按 {slot} 强制切换至{SLOT_NAMES[slot]}。")

    def _run_daily_battle(
        self,
        step: Step,
        skill_key: str,
        ultimate_key: str,
        cycle_index: int,
    ) -> None:
        started = time.monotonic()
        deadline = started + max(180.0, step.timeout)
        modules = self.rotation_presets.get("daily", self.rotation_modules)
        first_slot = self._rotation_first_slot(modules, "daily")
        self._rotation_slot = first_slot
        self._rotation_battle_finished = False
        self._rotation_end_check = self._daily_reward_stage_present
        self._combat_animation_until = 0.
        self._rotation_continuous_started = False
        last_task_check = 0.0
        task_seen = False
        screenshot = APP_DIR / "_runtime_screenshot.png"
        self._select_daily_slot_after_loading(screenshot, first_slot)
        if self.stop_event.is_set():
            return
        self.controller.middle_click()
        self.log(
            f"    第{cycle_index}轮：中键锁定后，"
            f"按日常预设执行 {len(modules)} 个战斗模块。"
        )

        attack_enabled = threading.Event()
        attack_lock = threading.Lock()
        rotation = RotationClock(modules, time.monotonic(), self.MAIN_ATTACK_CLICK_INTERVAL,
                                 self.rotation_times.get("daily"), background_idle=True,
                                 slot_order=self.rotation_orders.get("daily"))
        idle_worker = IdleAttackWorker(self.controller, self.stop_event, attack_lock,
                                       attack_interval=self.MAIN_ATTACK_CLICK_INTERVAL,
                                       heavy_hold_ms=self.HEAVY_ATTACK_HOLD_MS,
                                       on_error=lambda exc: self.log(f"    空闲普攻失败：{exc}"))
        self._rotation_idle_worker = idle_worker
        monitor = None
        try:
            def inspect():
                self._capture_for_matching(screenshot)
                reward = self._daily_reward_stage_present(screenshot)
                return reward, False if reward else self._daily_battle_task_present(screenshot)

            monitor = BattleMonitor(inspect, inspect(), self.stop_event)
            while time.monotonic() < deadline:
                if self.stop_event.is_set():
                    return
                now = time.monotonic()
                checked = monitor.poll()
                if checked is not None:
                    reward, present = checked[0]
                    if reward:
                        idle_worker.pause()
                        attack_enabled.clear()
                        with attack_lock:
                            pass
                        self.controller.release_keys()
                        self.log("    已识别到领取奖励提示，停止战斗并进入奖励搜索。")
                        return
                    last_task_check = time.monotonic()
                    if present:
                        task_seen = True
                    elif time.monotonic() < self._combat_animation_until:
                        pass
                    elif task_seen:
                        idle_worker.pause()
                        monitor.pause()
                        attack_enabled.clear()
                        with attack_lock:
                            pass
                        self.controller.release_keys()
                        if self._confirm_daily_battle_finished(screenshot):
                            self.log("    左侧清理目标文字快速复核后仍消失，进入奖励获取阶段。")
                            return
                        monitor.resume()
                        last_task_check = time.monotonic()
                        continue
                elif now - last_task_check >= self.DAILY_BATTLE_END_CHECK_INTERVAL:
                    monitor.request()
                action = rotation.next_action(time.monotonic())
                if not self._run_rotation_action(action, rotation, skill_key, ultimate_key,
                                                 attack_enabled, attack_lock, daily=True,
                                                 task_seen=task_seen, screenshot=screenshot):
                    return
                self._sleep_interruptible(0.025)
            if not task_seen:
                raise RuntimeError("没有识别到无音区清理目标文字，请确认已进入无音区挑战。")
            raise RuntimeError("无音区单轮战斗达到安全时限，已自动停止。")
        finally:
            idle_worker.close()
            self._rotation_idle_worker = None
            self._rotation_end_check = None
            attack_enabled.clear()
            try:
                self.controller.release_keys()
            finally:
                if monitor is not None:
                    monitor.close()
            if monitor is not None and monitor.error is not None:
                raise RuntimeError(f"战斗画面检查失败：{monitor.error}") from monitor.error
            if idle_worker.error is not None:
                raise RuntimeError(f"空闲普攻失败：{idle_worker.error}") from idle_worker.error

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
        # White enemies and skill effects are not evidence that combat ended.
        # Colour navigation is only used after the battle-end confirmation.
        return self._find_daily_reward_prompt(screenshot) is not None

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
        while time.monotonic() < deadline and not self.stop_event.is_set():
            self._capture_for_matching(screenshot)
            prompt = self._find_daily_reward_prompt(screenshot)
            target_x, _target_y, density = self._daily_reward_orb_location(screenshot)
            # A white object must never override evidence of ongoing combat.
            if (
                prompt is None
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
                self.controller.move_mouse_relative(260, 0)
                self.log(
                    f"    奖励光球置信度 {density:.2f} 未超过"
                    f"{DAILY_REWARD_ORB_MIN_CONFIDENCE:.2f}，向右转动搜索。"
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
        # A successful resource-consumption toast does not prove that the total
        # stamina is sufficient. Retry the claim and, if the chooser reopens,
        # continue with the next safe resource (green -> yellow).
        for refill_pass in range(2):
            if not self._safe_refill_daily_stamina():
                raise RuntimeError("结晶单质和结晶溶剂均不可用，已停止；不会使用星声兑换体力。")
            self._tap_ratio(0.14, 0.84, 0.35)  # 安全空白，不触碰物品卡。
            self._click_daily_template(
                "double_claim.png",
                "补充体力后的双倍领取",
                timeout=10.0,
                threshold=0.68,
                region_ratio=(0.50, 0.54, 0.80, 0.75),
            )
            state = self._wait_daily_claim_state(10.0)
            if state == "success":
                return
            if state == "refill" and refill_pass == 0:
                self.log("    已使用一种补充材料但体力仍不足，继续选择下一种安全材料。")
                continue
            break
        raise RuntimeError(f"第{cycle_index}轮使用绿色与黄色材料后体力仍不足，已停止且不会使用星声。")

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
        chooser_confirmations = 0
        success_confirmations = 0
        while time.monotonic() < deadline and not self.stop_event.is_set():
            self._capture_for_matching(screenshot)
            with Image.open(screenshot) as captured:
                width, height = captured.size
            scales = None if attempt == 3 else [self._fast_scales()[0]]
            # The title moves slightly when the game adds the "still insufficient"
            # banner. The chooser takes priority over the temporary "successfully
            # consumed" toast: the latter does not mean stamina is sufficient.
            chooser_visible = bool(self._find_daily_template(
                "refill_dialog.png",
                threshold=0.56,
                region=(round(width * 0.14), round(height * 0.16), round(width * 0.48), round(height * 0.33)),
                scales=scales,
                screenshot=screenshot,
            )) or (attempt >= 2 and self._daily_refill_chooser_present(screenshot))
            chooser_confirmations = chooser_confirmations + 1 if chooser_visible else 0
            if chooser_confirmations >= 2:
                return "still_short"
            success_visible = bool(self._find_daily_template(
                "refill_success.png",
                threshold=0.60,
                region=(round(width * 0.30), round(height * 0.16), round(width * 0.70), round(height * 0.34)),
                scales=scales,
                screenshot=screenshot,
            ))
            success_confirmations = success_confirmations + 1 if success_visible and not chooser_visible else 0
            if success_confirmations >= 2:
                return "success"
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
        yellow = (red > 225) & (green > 215) & (blue < 235) & ((red - blue) > 25)
        row_counts = yellow.sum(axis=1)
        active = np.flatnonzero(row_counts > max(12, region.shape[1] * 0.15))
        if not len(active):
            return []
        # Pale yellow buttons contain dark text and patterned highlights. Join
        # those gaps so one button produces one centre, not several edge clicks.
        groups = np.split(active, np.flatnonzero(np.diff(active) > max(4, round(height*.015)))+1)
        return [top+int((group[0]+group[-1])//2) for group in groups
                if group[-1]-group[0]+1 >= max(12, round(height*.018))]

    def _daily_activity_score_full(self, screenshot: Path) -> bool:
        with Image.open(screenshot) as source:
            width, height = source.size
        # Only the current score beside the bottom-left activity emblem counts.
        # A loose full-screen match mistakes the visible zero for "100".
        return self._find_daily_template(
            "activity_full.png", threshold=.88, screenshot=screenshot,
            region=(round(width*.15), round(height*.77), round(width*.29), round(height*.94)),
        ) is not None

    def _wait_daily_reward_page(self, template: str, label: str, *, dismiss_overlay: bool = False) -> None:
        screenshot = APP_DIR / "_runtime_screenshot.png"
        deadline = time.monotonic()+8
        confirmations = 0
        while time.monotonic() < deadline and not self.stop_event.is_set():
            _path, width, height = self._capture_size(screenshot)
            title = self._find_daily_template(template, threshold=.82, screenshot=screenshot,
                region=(round(width*.02), round(height*.025), round(width*.26), round(height*.13)))
            ready = title is not None and self._daily_activity_page_present(screenshot)
            confirmations = confirmations+1 if ready else 0
            if confirmations >= 2:
                return
            # Reward overlays can finish appearing after the blank-area click.
            # This spot is outside task buttons and milestone chests.
            if title is None and dismiss_overlay:
                self._dismiss_reward_overlay_safely()
            self._sleep_interruptible(.15)
        raise RuntimeError(f"未确认{label}页面已稳定显示，已停止以避免跳过领取。")

    def _dismiss_reward_overlay_safely(self) -> None:
        # Both the stamina exchange success and item reward overlays explicitly
        # allow a blank-area click. Bottom-left is outside every item card.
        self._tap_ratio(0.13, 0.86, 0.18)

    def _collect_daily_activity_rewards(self) -> None:
        self.log("    返回大世界后，经终端进入索拉指南领取活跃度奖励；只点击黄色“领取”，不点击“前往”。")
        self._open_terminal_destination("索拉指南", 0.515, 0.671, require_transition=True)
        # The guide can remember a different category. Select activity explicitly
        # and wait for its title rather than treating an unpainted frame as empty.
        self._tap_ratio(.039, .174, .15)
        self._wait_daily_reward_page("activity_title.png", "活跃行迹")
        self.log("    已确认活跃行迹页面，先领取上方任务奖励。")
        screenshot = APP_DIR / "_runtime_screenshot.png"
        empty_frames = 0
        for _ in range(36):
            if self.stop_event.is_set():
                return
            self._capture_for_matching(screenshot)
            rows = self._yellow_claim_rows(screenshot)
            if not rows:
                empty_frames += 1
                if empty_frames >= 2:
                    break
                self._sleep_interruptible(.15)
                continue
            empty_frames = 0
            with Image.open(screenshot) as captured:
                width = captured.width
            self.controller.tap(round(width * 0.88), rows[0])
            self._sleep_interruptible(.35)
            self._dismiss_reward_overlay_safely()
            self._wait_daily_reward_page("activity_title.png", "活跃行迹", dismiss_overlay=True)
        else:
            raise RuntimeError("活跃度领取多次后仍未完成，已停止；不会提前点击100宝箱。")

        self._capture_for_matching(screenshot)
        full = self._daily_activity_score_full(screenshot)
        if full:
            self._sleep_interruptible(.15)
            self._capture_for_matching(screenshot)
            full = self._daily_activity_score_full(screenshot) and not self._yellow_claim_rows(screenshot)
        if not full:
            self.log("    未确认活跃度达到100，跳过里程碑宝箱，避免误领。")
        else:
            self.log("    已确认活跃度100，只点击100宝箱，其余里程碑奖励由游戏一并领取。")
            self._tap_ratio(0.945, 0.868, 0.25)
            self._dismiss_reward_overlay_safely()
        self._tap_ratio(0.957, 0.058, 0.4)

    def _collect_daily_battlepass_rewards(self) -> None:
        self.log("    退出活跃指南后已在终端，直接进入先约电台；只领取免费内容，不点击购买或解锁寰宇频道。")
        self._tap_ratio(0.744, 0.257, 0.7)
        self._wait_daily_battlepass_tab(2)
        if self._click_optional_daily_template("one_click_claim.png", "电台任务一键领取", timeout=5.0, threshold=0.66):
            self._dismiss_reward_overlay_safely()
        self._wait_daily_battlepass_tab(1)
        if self._click_optional_daily_template("one_click_claim.png", "大众频道一键领取", timeout=5.0, threshold=0.66):
            self._dismiss_reward_overlay_safely()
        self._tap_ratio(0.957, 0.058, 0.8)

    def _daily_battlepass_tab_selected(self, screenshot: Path, tab: int) -> bool:
        with Image.open(screenshot) as source:
            width, height = source.size
            y = .174 if tab == 1 else .299
            icon = np.asarray(source.crop((round(width*.025), round(height*(y-.028)),
                                           round(width*.055), round(height*(y+.028)))).convert('RGB'))
        red, green, blue = (icon[:, :, i].astype(np.int16) for i in range(3))
        selected = (red > 150) & (green > 135) & (blue < green-25) & (red > blue+40)
        if float(selected.mean()) < .08:
            return False
        if tab == 2:
            return self._find_daily_template("battlepass_tasks.png", threshold=.82, screenshot=screenshot,
                region=(round(width*.015), round(height*.025), round(width*.25), round(height*.13))) is not None
        # Ensure the selected icon is the radio's reward channel, not a similarly
        # positioned guide icon. Its shape remains recognizable when highlighted.
        return self._find_daily_template("battlepass_rewards_tab.png", threshold=.72, screenshot=screenshot,
            region=(round(width*.02), round(height*.135), round(width*.06), round(height*.215))) is not None

    def _wait_daily_battlepass_tab(self, tab: int) -> None:
        screenshot = APP_DIR / "_runtime_screenshot.png"
        deadline = time.monotonic()+8
        confirmations = 0
        next_click = 0.
        while time.monotonic() < deadline and not self.stop_event.is_set():
            self._capture_for_matching(screenshot)
            if self._daily_battlepass_tab_selected(screenshot, tab):
                confirmations += 1
                if confirmations >= 2:
                    self.log(f"    已确认先约电台左侧第{tab}个标签。")
                    return
            else:
                confirmations = 0
                if time.monotonic() >= next_click:
                    self._tap_ratio(.039, .174 if tab == 1 else .299, .15)
                    next_click = time.monotonic()+.6
            self._sleep_interruptible(.12)
        raise RuntimeError(f"未确认先约电台左侧第{tab}个标签已打开，已停止以避免跳过奖励。")

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
        self._wait_for_daily_template("menu1.png", timeout=8.0, threshold=WEEKLY_TEMPLATE_THRESHOLD)

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
        self._weekly_monitoring = True
        self.template_root = TEMPLATES_DIR
        self.matcher.templates_dir = TEMPLATES_DIR
        self.max_cycles = 15
        start_step = Step(
            action="tap_image",
            label="点击幻梦游园开始游戏",
            template="menu1.png",
            threshold=WEEKLY_TEMPLATE_THRESHOLD,
            timeout=12.0,
            offset_x=80,
            seconds=WEEKLY_CLICK_INTERVAL,
        )
        cycle_step = Step(
            action="tap_image_cycle",
            label="自动执行15轮幻梦游园",
            templates=self._numbered_templates("menu", 2, 99),
            loop=True,
            threshold=WEEKLY_TEMPLATE_THRESHOLD,
            timeout=1.0,
            seconds=WEEKLY_CLICK_INTERVAL,
        )
        self._run_step(start_step)
        self._run_image_cycle(cycle_step)

    def _start_weekly_travel_from_selected_page(self) -> None:
        """Enter Dream Park from an already selected unfinished weekly page."""
        self._tap_ratio(0.247, 0.505, 0.8)
        self.template_root = TEMPLATES_DIR
        self.matcher.templates_dir = TEMPLATES_DIR
        self._wait_for_daily_template("menu1.png", timeout=12.0, threshold=WEEKLY_TEMPLATE_THRESHOLD)
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
        """Run weekly only when Sola Guide automatically selects its unfinished page."""
        self.log("    回到终端后再次进入索拉指南，检查周度游历。")
        self._tap_ratio(0.515, 0.671, 0.65)
        screenshot = APP_DIR / "_runtime_screenshot.png"
        self._capture_for_matching(screenshot)
        if self._weekly_travel_page_present(screenshot):
            self.log("    索拉指南已选中未完成的周度游历，直接进入幻梦游园。")
            self._start_weekly_travel_from_selected_page()
            return
        if self._guide_material_page_present(screenshot):
            self.log("    日常结算后二次进入索拉指南，已显示素材获取页；正常结算完成，跳过幻梦游园。")
        else:
            self.log("    索拉指南未自动进入周度游历页，判定本周周常已经完成；本次跳过幻梦游园。")
        self._tap_ratio(0.957, 0.058, 0.35)

    def _perform_4c_main_attack(self) -> None:
        """Keep a steady main-character attack rhythm matching the healer clicks."""
        self.controller.left_click()
        self._sleep_interruptible(self.MAIN_ATTACK_CLICK_INTERVAL)

    def _cast_timed_ultimate(
        self,
        ultimate_key: str,
        attack_enabled: threading.Event,
        attack_lock: threading.Lock,
        *, resume_attacks: bool = True, settle_delay: float = 0.8,
    ) -> None:
        """Give the ultimate input a quiet window without competing attack clicks."""
        attack_enabled.clear()
        with attack_lock:
            pass
        try:
            if self.stop_event.is_set():
                return
            self._combat_animation_until = time.monotonic()+5.
            self.controller.press_binding(ultimate_key, 120)
            self._sleep_interruptible(settle_delay)
        finally:
            if resume_attacks and not self.stop_event.is_set():
                attack_enabled.set()

    def _confirm_daily_battle_finished(self, screenshot: Path) -> bool:
        """Confirm an initial missing task marker before sending more combat input."""
        for _ in range(1, self.DAILY_TASK_MISSING_CONFIRMATIONS):
            self._sleep_interruptible(self.DAILY_TASK_MISSING_CONFIRMATION_INTERVAL)
            if self.stop_event.is_set():
                return True
            self._capture_for_matching(screenshot)
            if time.monotonic() < self._combat_animation_until:
                return False
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
        self._sleep_interruptible(self.HEAL_ATTACK_TO_Q_DELAY)
        if self.stop_event.is_set():
            return False
        self.controller.press_key("Q", 120)
        self._sleep_interruptible(self.HEAL_Q_TO_RETURN_DELAY)
        if self.stop_event.is_set():
            return False
        self.controller.press_key("1", 65)
        self._sleep_interruptible(0.22)
        return not self.stop_event.is_set()

    def _collect_4c_reward(self, cycle_index: int) -> None:
        screenshot = APP_DIR / "_runtime_screenshot.png"
        deadline = time.monotonic() + self.REWARD_SEARCH_TIMEOUT
        while time.monotonic() < deadline:
            if self.stop_event.is_set():
                return
            self._capture_for_matching(screenshot)
            with Image.open(screenshot) as captured:
                scale = captured.width / 1920.0
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
            if self.stop_event.is_set():
                return
            self.controller.press_keys(("W",), 400)
            self.log(f"    第{cycle_index}轮：未出现吸收提示，向前移动一小段后重新检查。")
            self._sleep_interruptible(0.10)
        raise RuntimeError("击败首领后向前搜索仍未找到“F / 吸收”提示，已停止循环。")

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

    def _find_4c_absorb_prompt(self, screenshot: Path, scale: float, *, fast: bool = False):
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
        candidates = ((scale, scale * 0.97, scale * 1.03) if fast else
                      (scale, scale * 0.94, scale * 0.97, scale * 1.03, scale * 1.06, scale * 0.88, scale * 1.12))
        for candidate in candidates:
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
                if fast or match.score >= 0.90:
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
        steps = []
        for template_name in templates:
            if not (self.template_root / template_name).exists():
                if not step.skip_missing:
                    raise FileNotFoundError(f"模板不存在: {template_name}")
                continue
            steps.append(Step(
                action="tap_image", label=f"识别并点击 {template_name}", template=template_name,
                threshold=step.threshold, timeout=step.timeout,
                offset_x=self._template_offset(step, template_name, "x"),
                offset_y=self._template_offset(step, template_name, "y"), seconds=step.seconds))
        if not steps:
            raise RuntimeError("没有可用的循环模板，请检查模板组。")
        previous_step = self.last_clicked_image_step
        round_index = 1
        while not self.stop_event.is_set():
            if self.max_cycles is not None and round_index > self.max_cycles:
                self.log(f"    已完成 {self.max_cycles} 轮循环，自动停止。")
                self.stop_event.set()
                return
            self.log(f"    开始第 {round_index} 轮循环。")
            cursor = 0
            while cursor < len(steps):
                if self.stop_event.is_set():
                    self.log("收到停止信号，循环任务已中断。")
                    return
                current = steps[cursor]
                next_step = steps[cursor + 1] if cursor + 1 < len(steps) else None
                wraps = next_step is None and step.loop and (self.max_cycles is None or round_index < self.max_cycles)
                if wraps and len(steps) > 1:
                    next_step = steps[0]
                matched, x, y, score = self._wait_for_cycle_template(current, previous_step, next_step)
                if self.stop_event.is_set():
                    return
                self.log(f"    找到 {matched.template}: ({x}, {y}) 相似度 {score:.3f}")
                if self.dry_run:
                    self.log("    干运行：已识别位置，但不点击。")
                else:
                    self._click_cycle_template(matched, x, y)
                previous_step = matched
                self._sleep_click_interval(step.seconds)
                if matched is next_step:
                    if wraps:
                        round_index += 1
                        self.log(f"    已进入第 {round_index} 轮，从已匹配的首张模板接续。")
                        cursor = 1
                        continue
                    cursor += 2
                else:
                    cursor += 1
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
        next_step: Step | None = None,
    ) -> tuple[Step, int, int, float]:
        found = self._probe_cycle_template(step, "本次")
        if found is not None:
            return step, *found
        if previous_step is not None:
            found = self._probe_cycle_template(previous_step, "上一张")
            if found is not None:
                if self.dry_run:
                    self.log("    干运行：上一张匹配成功，不点击。")
                else:
                    self.log(f"    上一张 {previous_step.template} 重新匹配成功，按新识别坐标点击后回到本次步骤。")
                    self._click_cycle_template(previous_step, *found[:2], recovery=True)
                    self._sleep_click_interval(previous_step.seconds)
                found = self._probe_cycle_template(step, "本次（上一张匹配后）")
                if found is not None:
                    return step, *found
        if next_step is not None:
            found = self._probe_cycle_template(next_step, "下一张")
            if found is not None:
                self.log(f"    已显示下一张 {next_step.template}，跳过本次 {step.template}，从下一张接续。")
                return next_step, *found
        found = self._probe_cycle_template(step, "本次（最终复核）")
        if found is not None:
            return step, *found
        previous_name = previous_step.template if previous_step else "无上一张"
        next_name = next_step.template if next_step else "无下一张"
        message = (f"周常模板流程无法继续：本次 {step.template}、上一张 {previous_name}、"
                   f"下一张 {next_name} 已按每组2次识别并最终复核本次，仍未匹配。已停止，请检查当前游戏页面。")
        self.stop_event.set()
        self.log(message)
        self.notice(message)
        raise RuntimeError(message)

    def _probe_cycle_template(self, step: Step, stage: str) -> tuple[int, int, float] | None:
        for attempt in range(CYCLE_PROBE_ATTEMPTS):
            if self.stop_event.is_set():
                raise RuntimeError("循环任务已停止。")
            try:
                found = self._find_image(step, single_attempt=True)
                if self.stop_event.is_set():
                    raise RuntimeError("循环任务已停止。")
                return found
            except WeeklyLimitReached:
                raise
            except (FileNotFoundError, OSError):
                raise
            except Exception as exc:
                if self.stop_event.is_set():
                    raise RuntimeError("循环任务已停止。") from exc
                self.log(f"    {stage}识别 {step.template}（{attempt+1}/{CYCLE_PROBE_ATTEMPTS}）未匹配: {exc}")
                if attempt + 1 < CYCLE_PROBE_ATTEMPTS:
                    self._sleep_interruptible(CYCLE_PROBE_INTERVAL)
        return None

    def _click_cycle_template(self, step: Step, x: int, y: int, recovery: bool = False) -> None:
        if self.stop_event.is_set():
            return
        action = "重新识别匹配后点击" if recovery else "正在点击识别坐标"
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
            except WeeklyLimitReached:
                raise
            except Exception:
                self.log(f"    最终轮验证通过：{final_step.template} 已离开当前画面。")
                return

            if retry_index >= CYCLE_FINAL_MAX_RETRIES:
                self.stop_event.set()
                raise RuntimeError(
                    f"最终模板 {final_step.template} 重新匹配并点击 {CYCLE_FINAL_MAX_RETRIES} 次后仍停留在画面，"
                    "任务已自动停止，请检查游戏状态。"
                )

            self.log(
                f"    最终轮回退命中 {final_step.template}: ({x}, {y}) "
                f"相似度 {score:.3f}，匹配成功后执行第 {retry_index + 1}/{CYCLE_FINAL_MAX_RETRIES} 次点击。"
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
        jitter = CLICK_DELAY_JITTER_SECONDS
        if self._weekly_monitoring:
            base_seconds = min(base_seconds, WEEKLY_CLICK_INTERVAL)
            jitter = WEEKLY_CLICK_JITTER
        minimum = max(0.0, base_seconds - jitter)
        maximum = max(minimum, base_seconds + jitter)
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

    def _find_image(self, step: Step, *, single_attempt: bool = False) -> tuple[int, int, float]:
        if not step.template:
            raise ValueError("tap_image 步骤需要 template 字段")
        deadline = time.time() + step.timeout
        last_error: Exception | None = None
        while single_attempt or time.time() <= deadline:
            if self.stop_event.is_set():
                raise RuntimeError("已停止模板识别。")
            screenshot = APP_DIR / "_runtime_screenshot.png"
            self._capture_for_matching(screenshot)
            if self._weekly_monitoring and not self.dry_run:
                self._check_weekly_cap(screenshot)
            try:
                scales = self._fast_scales()
                if self._weekly_monitoring:
                    match = self.matcher.find(screenshot, step.template, WEEKLY_TEMPLATE_THRESHOLD,
                                              scales, first_match=True)
                else:
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
                if single_attempt:
                    raise
                last_error = exc
                time.sleep(0.6)
        raise RuntimeError(str(last_error) if last_error else f"识别超时: {step.template}")

    def _check_weekly_cap(self, screenshot: Path) -> None:
        vision = WeeklyRewardsVision(TEMPLATES_DIR / "weekly")
        page = vision.cap_page(screenshot)
        if page is None:
            return
        if self.stop_event.is_set():
            raise RuntimeError("周常收尾已停止。")
        self.log("识别到本周游历值已达到上限，不再点击重新挑战。")

        def wait_for(predicate, label):
            deadline = time.monotonic() + 12
            while time.monotonic() < deadline:
                if self.stop_event.is_set():
                    raise RuntimeError("周常收尾已停止。")
                self._capture_for_matching(screenshot)
                if predicate(screenshot):
                    return
                self._sleep_interruptible(0.25)
            raise RuntimeError(f"周常收尾等待{label}超时，已停止点击。")

        if page == "result":
            self._tap_ratio(0.664, 0.848, 0.4)
            wait_for(lambda path: vision.cap_page(path) == "home", "幻梦游园主页")
        if self.stop_event.is_set():
            raise RuntimeError("周常收尾已停止。")
        self._tap_ratio(0.940, 0.0565, 0.4)
        wait_for(vision.weekly_page, "周度游历页面")
        claimed_any = False
        for _ in range(6):
            if self.stop_event.is_set():
                raise RuntimeError("周常领奖已停止。")
            if vision.all_claimed(screenshot):
                self.log("所有周常宝箱均已领取，跳过点击。")
                raise WeeklyLimitReached()
            target = vision.rightmost_claimable(screenshot)
            if target is None:
                if claimed_any:
                    self.log("已确认宝箱变为已领取状态，当前没有其他发光宝箱。")
                    raise WeeklyLimitReached()
                break
            self.log(f"领取当前最右侧可领取宝箱：{target}。")
            self.controller.tap(*target)
            self._sleep_interruptible(0.6)
            self._dismiss_reward_overlay_safely()
            wait_for(vision.weekly_page, "领奖后的周度游历页面")
            wait_for(lambda path: vision.claimed_at(path, target), "宝箱领取状态确认")
            claimed_any = True
        if claimed_any and vision.rightmost_claimable(screenshot) is None:
            raise WeeklyLimitReached()
        self.weekly_rewards_pending = True
        self.log("本周游历已达上限；暂无法确认可领取宝箱，请手动检查，本次不会自动关机。")
        self.notice("周常已达到上限，已回到周度游历。无法确认宝箱领取状态，请检查是否需要手动领取；本次不会自动关机。")
        raise WeeklyLimitReached()

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
    def __init__(self, parent: Tk, source_path: Path, templates_dir: Path, log, ui=None):
        self.ui = ui
        self.source_path = source_path
        self.templates_dir = templates_dir
        self.log = log
        self.window = Toplevel(parent)
        self.window.title("制作识别模板")
        self.window.geometry("1120x760")
        self.window.configure(bg=COLORS["panel"])
        self.image = Image.open(source_path).convert("RGB")
        self.scale = min(1060 / self.image.width, 660 / self.image.height, 1.0)
        preview_size = (int(self.image.width * self.scale), int(self.image.height * self.scale))
        self.preview = self.image.resize(preview_size, Image.Resampling.BILINEAR)
        self.photo = ImageTk.PhotoImage(self.preview)
        self.start_x = 0
        self.start_y = 0
        self.rect_id: int | None = None
        self.selection: tuple[int, int, int, int] | None = None

        Label(self.window, text="在截图上拖框选择按钮或图标，建议包含文字/边框等明显特征。", bg=COLORS["panel"], fg=COLORS["text"]).pack(side=TOP, fill=X, padx=10, pady=6)
        self.canvas = Canvas(self.window, width=preview_size[0], height=preview_size[1], cursor="crosshair")
        self.canvas.pack(side=TOP, padx=10, pady=6)
        self.canvas.create_image(0, 0, anchor="nw", image=self.photo)
        self.canvas.bind("<ButtonPress-1>", self._start)
        self.canvas.bind("<B1-Motion>", self._drag)
        self.canvas.bind("<ButtonRelease-1>", self._finish)

        buttons = Frame(self.window, padx=10, pady=8, bg=COLORS["panel"])
        buttons.pack(side=TOP, fill=X)
        RoundedButton(buttons, colors=COLORS, text="保存模板", primary=True, command=self._save).pack(side=LEFT)
        RoundedButton(buttons, colors=COLORS, text="关闭", command=self.window.destroy).pack(side=LEFT, padx=8)

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
        name = self.ui._ask_text("模板文件名", "输入模板文件名，例如 menu.png", parent=self.window) if self.ui else simpledialog.askstring("模板文件名", "输入模板文件名，例如 menu.png", parent=self.window)
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
        preferred_pet_id = self._load_pet_preference()
        self.theme_id = self._load_theme_preference()
        self.pet_id = self._select_startup_pet(preferred_pet_id, self.theme_id)
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
        self.daily_zone = StringVar(value=self._load_daily_zone())
        self.auto_shutdown_enabled = BooleanVar(value=self._load_auto_shutdown_enabled())
        self.pet_size = StringVar(value=f"{self._load_pet_size_percent()}%")
        self.pet_visible = self._load_pet_visible()
        self.pet_supports_look_controls = self.pet_id in {"jingran", "cartethyia"}
        self.pet_look_enabled = BooleanVar(
            value=(
                self._load_pet_feature_enabled(self.pet_id, "look_at_pointer", True)
                if self.pet_supports_look_controls
                else False
            )
        )
        self.pet_auto_jump_enabled = BooleanVar(
            value=self._load_pet_feature_enabled(self.pet_id, "auto_jump", True)
        )
        agent_config = LocalAgentConfig.load(CARTETHYIA_AGENT_CONFIG)
        if not agent_config.bridge_token:
            agent_config = replace(agent_config, bridge_token=secrets.token_urlsafe(24))
        self.sillytavern_bridge = SillyTavernBridge(agent_config.bridge_token)
        self.cartethyia_agent_enabled = BooleanVar(value=agent_config.enabled)
        self.cartethyia_agent_endpoint = StringVar(value=agent_config.endpoint)
        self.cartethyia_agent_model = StringVar(value=agent_config.model)
        self.agent_provider = StringVar(value={"openai": "OpenAI 兼容 API", "deepseek": "DeepSeek API", "sillytavern": "SillyTavern 酒馆"}.get(agent_config.provider, "Ollama 本地"))
        self.agent_api_key = StringVar(value=agent_config.api_key)
        self.agent_bridge_token = StringVar(value=agent_config.bridge_token)
        self.agent_discovered_choice = StringVar()
        self._discovered_models = {}
        self._model_scan_busy = False
        self.cartethyia_agent_status = StringVar(
            value="已启用，等待连接测试" if agent_config.enabled else "未启用，不会发送聊天请求或下载模型"
        )
        persona_prompt = "\n\n".join(PET_AGENT_PROMPT_LAYERS[self.pet_id])
        self.cartethyia_agent = LocalCartethyiaAgent(
            agent_config,
            persona_prompt,
            character_name=self.pet_name,
            fallback_reply=PET_AGENT_FALLBACKS[self.pet_id],
            bridge=self.sillytavern_bridge,
        )
        self._agent_chat_busy = False
        self.chat_history = ChatHistory(APP_DIR / "pet-chat-history.json")
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
        self.rotation_choice = StringVar()
        self._syncing_probability_inputs = False
        self.prob_astrite.trace_add("write", self._sync_pulls_from_astrite)
        self.prob_pulls.trace_add("write", self._sync_astrite_from_pulls)
        self.template_group = StringVar(value=DEFAULT_GROUP_NAME)
        self.log_queue: queue.Queue[str] = queue.Queue()
        try:
            self.rotation_store = load_store(COMBAT_PRESETS_CONFIG)
        except (OSError, ValueError, TypeError) as exc:
            self.rotation_store = default_store()
            self.log_queue.put(f"战斗排轴配置读取失败，已使用默认轴：{exc}")
        self.tasks: list[WeeklyTask] = []
        self.stop_event = threading.Event()
        self._manual_stop_requested = False
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
        self.root.after(800, self._scan_local_models)
        if "--admin-restarted" in sys.argv and is_running_as_admin():
            self._log("检测到未开启管理员模式，已通过管理员模式打开")
        else:
            self.root.after(300, self._show_startup_notice_once)

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
    def _select_startup_pet(preferred_pet_id: str, _theme_id: str) -> str:
        """Keep an explicit pet choice independent from the selected program theme."""
        return preferred_pet_id

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

    @classmethod
    def _load_pet_feature_enabled(
        cls,
        pet_id: str,
        feature: str,
        default: bool,
    ) -> bool:
        saved = cls._load_pet_display_settings().get(feature)
        if not isinstance(saved, dict):
            return default
        value = saved.get(pet_id, default)
        return value if isinstance(value, bool) else default

    def _save_pet_feature_enabled(self, feature: str, enabled: bool) -> None:
        saved = self._load_pet_display_settings()
        feature_settings = saved.get(feature)
        if not isinstance(feature_settings, dict):
            feature_settings = {}
        feature_settings[self.pet_id] = bool(enabled)
        saved[feature] = feature_settings
        PET_DISPLAY_CONFIG.write_text(
            json.dumps(saved, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _apply_pet_look_setting(self) -> None:
        if not self.pet_supports_look_controls:
            return
        enabled = bool(self.pet_look_enabled.get())
        self._save_pet_feature_enabled("look_at_pointer", enabled)
        if self.desktop_pet is not None:
            self.desktop_pet.set_look_enabled(enabled)
        state = "开启" if enabled else "关闭"
        self.status.set(f"{self.pet_name}盯鼠标：{state}")

    def _apply_pet_auto_jump_setting(self) -> None:
        if not self.pet_supports_look_controls:
            return
        enabled = bool(self.pet_auto_jump_enabled.get())
        self._save_pet_feature_enabled("auto_jump", enabled)
        if self.desktop_pet is not None:
            self.desktop_pet.set_auto_jump_enabled(enabled)
        state = "开启" if enabled else "关闭"
        self.status.set(f"{self.pet_name}定时跳跃：{state}")

    def _set_pet_look_enabled(self, enabled: bool) -> None:
        self.pet_look_enabled.set(bool(enabled))
        self._apply_pet_look_setting()

    def _set_pet_auto_jump_enabled(self, enabled: bool) -> None:
        self.pet_auto_jump_enabled.set(bool(enabled))
        self._apply_pet_auto_jump_setting()

    def _save_pet_look_from_menu(self, enabled: bool) -> None:
        self.pet_look_enabled.set(bool(enabled))
        self._save_pet_feature_enabled("look_at_pointer", bool(enabled))
        state = "开启" if enabled else "关闭"
        self.status.set(f"{self.pet_name}盯鼠标：{state}")

    def _save_pet_auto_jump_from_menu(self, enabled: bool) -> None:
        self.pet_auto_jump_enabled.set(bool(enabled))
        self._save_pet_feature_enabled("auto_jump", bool(enabled))
        state = "开启" if enabled else "关闭"
        self.status.set(f"{self.pet_name}定时跳跃：{state}")

    def _save_pet_visibility(self, visible: bool) -> None:
        self.pet_visible = bool(visible)
        self._save_pet_display_settings(visible=self.pet_visible)

    def _current_cartethyia_agent_config(self) -> LocalAgentConfig:
        return LocalAgentConfig(
            enabled=bool(self.cartethyia_agent_enabled.get()),
            endpoint=self.cartethyia_agent_endpoint.get().strip(),
            model=self.cartethyia_agent_model.get().strip(),
            provider={"OpenAI 兼容 API": "openai", "DeepSeek API": "deepseek", "SillyTavern 酒馆": "sillytavern"}.get(self.agent_provider.get(), "ollama"),
            api_key=self.agent_api_key.get().strip(),
            bridge_token=self.agent_bridge_token.get().strip(),
        )

    def _save_cartethyia_agent_settings(self, announce: bool = True) -> bool:
        config = self._current_cartethyia_agent_config()
        try:
            if config.enabled and config.provider == "sillytavern":
                if not config.bridge_token:
                    raise ValueError("酒馆桥接密钥不能为空。")
                self.sillytavern_bridge.token = config.bridge_token
                self.sillytavern_bridge.start()
            elif config.enabled:
                service_base(config)
                self.sillytavern_bridge.stop()
            else:
                self.sillytavern_bridge.stop()
            config.save(CARTETHYIA_AGENT_CONFIG)
        except (OSError, ValueError) as exc:
            self.cartethyia_agent_status.set(f"保存失败：{exc}")
            if announce:
                messagebox.showerror("保存失败", f"无法保存本地 Agent 设置：\n{exc}", parent=self.root)
            return False
        self.cartethyia_agent.update_config(config)
        state = "已启用，随机发言已暂停" if config.enabled else "未启用，已恢复主动发言；不会发送聊天请求"
        self.cartethyia_agent_status.set(state)
        if announce:
            self.status.set("桌宠 Agent 设置已保存；API Key 仅保留在本次运行中")
            self._log("桌宠 Agent 连接设置已保存。")
        return True

    def _change_agent_provider(self, _event=None) -> None:
        self.agent_model_picker.set_choices(())
        self.cartethyia_agent_model.set("")
        endpoint = self.cartethyia_agent_endpoint.get().strip()
        if self.agent_provider.get() == "SillyTavern 酒馆":
            self.cartethyia_agent_endpoint.set("")
            self.agent_api_key.set("")
            self.cartethyia_agent_status.set("酒馆模式：保持对应角色会话打开，安装并启用 wwbs 桥接扩展。")
            return
        if self.agent_provider.get() == "DeepSeek API":
            self.cartethyia_agent_endpoint.set("https://api.deepseek.com")
        elif endpoint in {"", "http://127.0.0.1:11434", "http://127.0.0.1:1234/v1", "https://api.deepseek.com"}:
            self.cartethyia_agent_endpoint.set(
                "http://127.0.0.1:1234/v1" if self.agent_provider.get() == "OpenAI 兼容 API"
                else "http://127.0.0.1:11434")
        self.agent_api_key.set("")

    def _scan_local_models(self) -> None:
        if self._model_scan_busy:
            return
        self._model_scan_busy = True
        self.agent_discovery_status.set("正在检测本机模型……")
        def finish(models, error):
            self._model_scan_busy = False
            self._discovered_models = {item.label: item for item in models}
            self.agent_discovery_picker.set_choices(tuple(self._discovered_models))
            self.agent_discovered_choice.set(next(iter(self._discovered_models), ""))
            self.agent_discovery_status.set(error or (
                f"发现 {len(models)} 个模型，从本机模型下拉框直接选择即可。" if models
                else "未发现模型；可启动 Ollama/LM Studio 后重试，或手动填写自定义服务地址。"))
            if models and not self.cartethyia_agent_model.get().strip() and self.agent_provider.get() == "Ollama 本地":
                self._use_discovered_model()
        def work():
            try:
                models = discover_local_models()
            except Exception:
                self.root.after(0, lambda: finish([], "本机检测失败，请手动填写服务地址或稍后重试。"))
            else:
                self.root.after(0, lambda: finish(models, None))
        threading.Thread(target=work, name="pet-model-discovery", daemon=True).start()

    def _use_discovered_model(self, _event=None) -> None:
        model = self._discovered_models.get(self.agent_discovered_choice.get())
        if model is None:
            return
        self.agent_provider.set("OpenAI 兼容 API" if model.provider == "openai" else "Ollama 本地")
        self.cartethyia_agent_endpoint.set(model.endpoint)
        self.cartethyia_agent_model.set(model.model)
        self.agent_api_key.set("")
        self.agent_model_picker.set_choices(tuple(item.model for item in self._discovered_models.values()
                                                       if item.endpoint == model.endpoint))
        self.cartethyia_agent_status.set("已填入模型，请保存设置。" if model.available else
                                       "已填入模型；请先启动对应服务。LM Studio 请先载入模型，再获取服务模型列表选择。")

    def _fetch_agent_models(self) -> None:
        config = self._current_cartethyia_agent_config()
        if config.provider == "sillytavern":
            self.cartethyia_agent_status.set("酒馆模式使用当前会话的模型，无需在这里获取模型。")
            return
        self.cartethyia_agent_status.set("正在获取服务模型列表……")
        def finish(names, error=None):
            if config != self._current_cartethyia_agent_config():
                return
            self.agent_model_picker.set_choices(names)
            if names and config.model not in names:
                self.cartethyia_agent_model.set(names[0])
            self.cartethyia_agent_status.set(error or (f"发现 {len(names)} 个模型，请从模型名称下拉框选择。" if names else "服务未返回模型，请手动填写。"))
        def work():
            try:
                names = list_service_models(config)
            except (RuntimeError, ValueError) as exc:
                self.root.after(0, lambda error=str(exc): finish([], error))
            else:
                self.root.after(0, lambda: finish(names))
        threading.Thread(target=work, name="pet-service-models", daemon=True).start()

    def _test_cartethyia_agent(self) -> None:
        if not self._save_cartethyia_agent_settings(announce=False):
            return
        config = self.cartethyia_agent.config
        if not config.enabled:
            self.cartethyia_agent_status.set("请先勾选“启用桌宠 Agent”并保存。")
            return
        self.cartethyia_agent_status.set("正在测试酒馆会话……" if config.provider == "sillytavern" else "正在测试模型连接……本地模型首次载入可能需要较长时间")

        def work() -> None:
            try:
                reply = self.cartethyia_agent.test_connection()
            except Exception as exc:
                error_text = str(exc)
                self.root.after(0, lambda text=error_text: self.cartethyia_agent_status.set(f"连接失败：{text}"))
                return
            self.root.after(0, lambda: self.cartethyia_agent_status.set(f"连接成功：{reply}"))

        threading.Thread(target=work, name="cartethyia-agent-test", daemon=True).start()

    def _record_pet_chat(self, speaker: str, text: str, pet_id: str | None = None) -> None:
        try:
            self.chat_history.append(pet_id or self.pet_id, speaker, text)
        except OSError:
            self._log("聊天记录暂存于内存；文件写入失败，请检查程序目录权限。")

    def _build_pet_chat_history(self, parent, height: int = 9) -> None:
        outer, shell = self._rounded_panel(parent, color=COLORS['panel'], outer_color=parent.cget('bg'))
        outer.pack(fill=BOTH, expand=True, pady=(0, 10))
        history = Text(shell, height=height, width=44, wrap="word", relief="flat",
                       font=(FONT_FAMILY, 10), padx=10, pady=8, bg=COLORS["panel"], fg=COLORS["text"], bd=0, highlightthickness=0)
        scrollbar = self._thin_scrollbar(shell, command=history.yview)
        history.configure(yscrollcommand=scrollbar.set)
        history.pack(side=LEFT, fill=BOTH, expand=True)
        scrollbar.pack(side=RIGHT, fill="y")
        history.tag_configure("user", justify="right", foreground=COLORS["primary"], spacing3=12)
        history.tag_configure("pet", justify="left", foreground=COLORS["text"], spacing3=12)
        records = self.chat_history.messages(self.pet_id)
        for item in records:
            history.insert(END, f"{item['speaker']}\n{item['text']}\n\n",
                           "user" if item["speaker"] == "你" else "pet")
        if not records:
            history.insert(END, "还没有聊天记录。")
        history.configure(state="disabled")
        history.see(END)

    def _show_pet_chat_history(self) -> None:
        window = Toplevel(self.root)
        window.title(f"{self.pet_name} · 聊天记录")
        window.geometry("520x560")
        window.configure(bg=COLORS['panel'])
        Label(window, text="记录保存在本机，按角色分别保留最近500条。", pady=8,
              bg=COLORS['panel'], fg=COLORS['muted']).pack(fill=X)
        self._build_pet_chat_history(window, height=20)

    def _ask_cartethyia_chat_message(self) -> str | None:
        """Show a compact, themed composer beside the desktop pet."""
        result: dict[str, str | None] = {"value": None}
        theme = PET_AGENT_DIALOG_THEMES[self.pet_id]
        dialog = Toplevel(self.root)
        dialog.title(f"和{self.pet_name}聊天")
        dialog.configure(bg=theme["background"])
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.attributes("-topmost", True)
        if APP_ICON.exists():
            try:
                dialog.iconbitmap(str(APP_ICON))
            except Exception:
                pass

        header = Frame(dialog, bg=theme["header"], padx=18, pady=13)
        header.pack(fill=X)
        Label(
            header,
            text=self.pet_name,
            font=(FONT_FAMILY, 13, "bold"),
            fg=theme["title"],
            bg=theme["header"],
        ).pack(anchor="w")
        Label(
            header,
            text=theme["subtitle"],
            font=(FONT_FAMILY, 9),
            fg=theme["muted"],
            bg=theme["header"],
        ).pack(anchor="w", pady=(2, 0))

        body = Frame(dialog, bg=theme["background"], padx=18, pady=14)
        body.pack(fill=BOTH, expand=True)
        self._build_pet_chat_history(body)
        input_shell, input_border = self._rounded_panel(body, padding=6,
            color=theme['editor'], outer_color=theme['background'])
        input_shell.pack(fill=X)
        editor = Text(
            input_border,
            width=44,
            height=3,
            wrap="word",
            font=(FONT_FAMILY, 10),
            relief="flat",
            bd=0,
            padx=9,
            pady=7,
            bg=theme["editor"],
            fg=theme["title"],
            insertbackground=theme["accent"],
        )
        editor.pack(fill=X)
        Label(
            body,
            text="Enter 发送 · Shift+Enter 换行",
            font=(FONT_FAMILY, 8),
            fg=theme["muted"],
            bg=theme["background"],
        ).pack(anchor="w", pady=(5, 9))

        actions = Frame(body, bg=theme["background"])
        actions.pack(fill=X)

        def close_dialog() -> None:
            result["value"] = None
            dialog.destroy()

        def submit(_event=None) -> str:
            value = editor.get("1.0", "end-1c").strip()
            if value:
                result["value"] = value
                dialog.destroy()
            return "break"

        def handle_enter(event) -> str | None:
            if event.state & 0x0001:
                return None
            return submit(event)

        self._ui_button(
            actions,
            text="取消",
            width=9,
            command=close_dialog,
            bg=theme["cancel"],
            fg=theme["cancel_text"],
            activebackground=theme["border"],
            relief="flat",
            bd=0,
        ).pack(side=RIGHT)
        self._ui_button(
            actions,
            text="发送",
            width=9,
            command=submit,
            bg=theme["accent"],
            fg="white",
            activebackground=theme["accent_active"],
            activeforeground="white",
            relief="flat",
            bd=0,
        ).pack(side=RIGHT, padx=(0, 9))

        dialog.protocol("WM_DELETE_WINDOW", close_dialog)
        dialog.bind("<Escape>", lambda _event: close_dialog())
        editor.bind("<Return>", handle_enter)
        dialog.update_idletasks()
        width = max(440, dialog.winfo_reqwidth())
        height = max(240, dialog.winfo_reqheight())
        screen_w = dialog.winfo_screenwidth()
        screen_h = dialog.winfo_screenheight()
        if self.desktop_pet is not None:
            anchor_x = self.desktop_pet.window.winfo_x() + self.desktop_pet.width // 2
            anchor_y = self.desktop_pet.window.winfo_y()
            x = anchor_x - width // 2
            y = anchor_y - height - 12
            if y < 20:
                y = self.desktop_pet.window.winfo_y() + self.desktop_pet.height + 12
        else:
            x = self.root.winfo_x() + max(0, (self.root.winfo_width() - width) // 2)
            y = self.root.winfo_y() + max(0, (self.root.winfo_height() - height) // 2)
        x = max(10, min(screen_w - width - 10, x))
        y = max(10, min(screen_h - height - 50, y))
        dialog.geometry(f"{width}x{height}+{x}+{y}")
        dialog.grab_set()
        editor.focus_force()
        self.root.wait_window(dialog)
        return result["value"]

    def _open_cartethyia_chat(self) -> None:
        if self._agent_chat_busy:
            self._pet_feedback("waiting", "我还在整理刚才的话，稍等我一下。", 3200)
            return
        if not self.cartethyia_agent_enabled.get():
            self._pet_feedback("failed", "本地 Agent 还没有启用，请先到设置页完成配置。", 5200)
            return
        if not self._save_cartethyia_agent_settings(announce=False):
            return
        # Start loading the model while the user is composing the message.  The
        # request is best-effort and the normal chat request still reports any
        # connection error.  Ollama releases an unused warm model after 60s.
        threading.Thread(
            target=self.cartethyia_agent.warmup,
            name="pet-agent-warmup",
            daemon=True,
        ).start()
        message = self._ask_cartethyia_chat_message()
        if message is None or not message.strip():
            return
        message = message.strip()
        self._pending_chat_pet = (self.pet_id, self.pet_name)
        self._record_pet_chat("你", message)
        self._agent_chat_busy = True

        def pet_chat_work() -> None:
            try:
                reply = self.cartethyia_agent.respond(message)
            except Exception as exc:
                error_text = str(exc)
                self.root.after(0, lambda text=error_text: self._finish_cartethyia_pet_chat(None, text))
                return
            self.root.after(0, lambda: self._finish_cartethyia_pet_chat(reply, None))

        threading.Thread(target=pet_chat_work, name="cartethyia-pet-chat", daemon=True).start()
        return

        if self._agent_chat_window is not None and self._agent_chat_window.winfo_exists():
            self._agent_chat_window.deiconify()
            self._agent_chat_window.lift()
            if self._agent_chat_entry is not None:
                self._agent_chat_entry.focus_set()
            return
        window = Toplevel(self.root)
        window.title("与卡提希娅聊天 · 本地 Agent 试用")
        window.geometry("680x600")
        window.minsize(560, 460)
        window.transient(self.root)
        if APP_ICON.exists():
            try:
                window.iconbitmap(str(APP_ICON))
            except Exception:
                pass
        chat_background = COLORS["app_bg"]
        shell = Frame(window, bg=chat_background)
        shell.pack(fill=BOTH, expand=True)
        header = Frame(shell, padx=16, pady=12, bg=COLORS["panel"], highlightthickness=1, highlightbackground=COLORS["line_soft"])
        header.pack(fill=X)
        Label(
            header,
            text="卡提希娅 · 本地 Agent",
            font=(FONT_FAMILY, 13, "bold"),
            bg=COLORS["panel"],
            fg=COLORS["text"],
        ).pack(anchor="w")
        Label(
            header,
            text="普通聊天由本地模型生成；明确的一键日常等命令只会调用安全白名单。",
            bg=COLORS["panel"],
            fg=COLORS["muted"],
        ).pack(anchor="w", pady=(2, 0))

        history_shell = Frame(shell, bg=chat_background)
        history_shell.pack(fill=BOTH, expand=True)
        history_canvas = Canvas(history_shell, bg=chat_background, highlightthickness=0, bd=0)
        history_scrollbar = self._thin_scrollbar(history_shell, orient="vertical", command=history_canvas.yview)
        history_canvas.configure(yscrollcommand=history_scrollbar.set)
        history_canvas.pack(side=LEFT, fill=BOTH, expand=True)
        history_scrollbar.pack(side=RIGHT, fill="y")
        history = Frame(history_canvas, bg=chat_background, padx=14, pady=12)
        history_window = history_canvas.create_window((0, 0), window=history, anchor="nw")

        def resize_history(_event=None) -> None:
            history_canvas.itemconfigure(history_window, width=history_canvas.winfo_width())
            history_canvas.configure(scrollregion=history_canvas.bbox("all"))

        def scroll_history(event) -> str:
            history_canvas.yview_scroll(int(-event.delta / 120), "units")
            return "break"

        history.bind("<Configure>", resize_history)
        history_canvas.bind("<Configure>", resize_history)
        history_canvas.bind("<MouseWheel>", scroll_history)
        history.bind("<MouseWheel>", scroll_history)

        input_row = Frame(shell, padx=12, pady=11, bg=COLORS["panel"], highlightthickness=1, highlightbackground=COLORS["line_soft"])
        input_row.pack(fill=X)
        entry = self._rounded_entry(input_row, font=(FONT_FAMILY, 11), relief="flat", bd=0)
        entry.pack(side=LEFT, fill=X, expand=True, ipady=8, padx=(2, 10))
        send = self._ui_button(
            input_row,
            text="发送",
            width=9,
            command=self._send_cartethyia_chat,
            bg=COLORS["primary"],
            fg="white",
            activebackground=COLORS["primary_hover"],
            activeforeground="white",
            relief="flat",
            bd=0,
        )
        send.pack(side=LEFT, ipady=5)
        self._agent_chat_window = window
        self._agent_chat_canvas = history_canvas
        self._agent_chat_text = history
        self._agent_chat_entry = entry
        self._agent_chat_send_button = send
        self._append_cartethyia_chat("卡提希娅", "义人，你来啦。想聊点什么，还是准备开始新的冒险？")
        if not self.cartethyia_agent_enabled.get():
            self._append_cartethyia_chat("系统", "本地 Agent 尚未启用。请先到设置页填写服务地址和模型名称。")
        entry.bind("<Return>", lambda _event: self._send_cartethyia_chat())
        entry.focus_set()

        def on_destroy(event) -> None:
            if event.widget is window:
                self._agent_chat_window = None
                self._agent_chat_canvas = None
                self._agent_chat_text = None
                self._agent_chat_entry = None
                self._agent_chat_send_button = None

        window.bind("<Destroy>", on_destroy)

    def _append_cartethyia_chat(self, speaker: str, text: str) -> None:
        widget = self._agent_chat_text
        if widget is None or not widget.winfo_exists():
            return
        if speaker == "系统":
            Label(
                widget,
                text=text,
                font=(FONT_FAMILY, 9),
                fg=COLORS["muted"],
                bg=COLORS["panel_alt"],
                padx=9,
                pady=4,
                wraplength=470,
                justify=LEFT,
            ).pack(pady=7)
        else:
            is_user = speaker == "你"
            row = Frame(widget, bg=COLORS["app_bg"])
            row.pack(fill=X, pady=6)
            side = RIGHT if is_user else LEFT
            message_column = Frame(row, bg=COLORS["app_bg"])
            message_column.pack(side=side, anchor="e" if is_user else "w")
            Label(
                message_column,
                text=speaker,
                font=(FONT_FAMILY, 8),
                fg=COLORS["muted"],
                bg=COLORS["app_bg"],
            ).pack(anchor="e" if is_user else "w", padx=3, pady=(0, 2))
            bubble = Label(
                message_column,
                text=text,
                font=(FONT_FAMILY, 10),
                fg=COLORS["text"],
                bg=COLORS["panel_alt"] if is_user else COLORS["panel"],
                padx=12,
                pady=8,
                wraplength=390,
                justify=LEFT,
                relief="flat",
                bd=0,
            )
            bubble.pack(anchor="e" if is_user else "w")
            canvas = self._agent_chat_canvas
            if canvas is not None:
                row.bind("<MouseWheel>", lambda event, target=canvas: (target.yview_scroll(int(-event.delta / 120), "units"), "break")[1])
                bubble.bind("<MouseWheel>", lambda event, target=canvas: (target.yview_scroll(int(-event.delta / 120), "units"), "break")[1])
        widget.update_idletasks()
        canvas = self._agent_chat_canvas
        if canvas is not None and canvas.winfo_exists():
            canvas.configure(scrollregion=canvas.bbox("all"))
            canvas.yview_moveto(1.0)

    def _send_cartethyia_chat(self) -> None:
        if self._agent_chat_busy or self._agent_chat_entry is None:
            return
        message = self._agent_chat_entry.get().strip()
        if not message:
            return
        if not self.cartethyia_agent_enabled.get():
            self._append_cartethyia_chat("系统", "本地 Agent 尚未启用，请先在设置页完成配置。")
            return
        if not self._save_cartethyia_agent_settings(announce=False):
            self._append_cartethyia_chat("系统", self.cartethyia_agent_status.get())
            return
        self._agent_chat_entry.delete(0, END)
        self._append_cartethyia_chat("你", message)
        self._agent_chat_busy = True
        if self._agent_chat_send_button is not None:
            self._agent_chat_send_button.configure(state="disabled")

        def work() -> None:
            try:
                reply = self.cartethyia_agent.respond(message)
            except Exception as exc:
                error_text = str(exc)
                self.root.after(0, lambda text=error_text: self._finish_cartethyia_chat(None, text))
                return
            self.root.after(0, lambda: self._finish_cartethyia_chat(reply, None))

        threading.Thread(target=work, name="cartethyia-agent-chat", daemon=True).start()

    def _finish_cartethyia_chat(self, reply: AgentReply | None, error: str | None) -> None:
        self._agent_chat_busy = False
        if self._agent_chat_send_button is not None and self._agent_chat_send_button.winfo_exists():
            self._agent_chat_send_button.configure(state="normal")
        if error is not None:
            self._append_cartethyia_chat("系统", error)
            return
        if reply is None:
            return
        display_text = self._agent_reply_with_action(reply)
        self._append_cartethyia_chat(self.pet_name, display_text)
        self._pet_feedback("waving", display_text, 5200)
        if reply.tool is not None:
            self._execute_cartethyia_agent_tool(reply.tool)

    @staticmethod
    def _agent_reply_with_action(reply: AgentReply) -> str:
        task_label = AGENT_TASK_LABELS.get(reply.tool or "")
        if task_label is None:
            return reply.text
        return f"{reply.text}\n现在执行：{task_label}。"

    def _finish_cartethyia_pet_chat(self, reply: AgentReply | None, error: str | None) -> None:
        self._agent_chat_busy = False
        pet_id, pet_name = getattr(self, "_pending_chat_pet", (self.pet_id, self.pet_name))
        if error is not None:
            self._record_pet_chat("系统", error, pet_id)
            self._pet_feedback("failed", error, 7200)
            return
        if reply is None:
            return
        display_text = self._agent_reply_with_action(reply)
        self._record_pet_chat(pet_name, display_text, pet_id)
        duration = max(5200, min(11000, 2600 + len(display_text) * 115))
        self._pet_feedback("waving", display_text, duration)
        if reply.tool is not None:
            self._execute_cartethyia_agent_tool(reply.tool)

    def _execute_cartethyia_agent_tool(self, tool: str) -> None:
        actions = {
            "run_daily": lambda: self._start_daily_routine(require_confirmation=False),
            "run_weekly_rewards": lambda: self._start_enabled_real(15, require_confirmation=False),
            "run_weekly_astrite": lambda: self._start_enabled_real(13, require_confirmation=False),
            "run_4c_10": lambda: self._start_named_task_real("4C刷取", 10, require_confirmation=False),
            "run_4c_30": lambda: self._start_named_task_real("4C刷取", 30, require_confirmation=False),
            "stop_task": self._stop,
            "diagnose": self._diagnose_runtime,
            "set_auto_shutdown_on": lambda: self._set_auto_shutdown_enabled(True),
            "set_auto_shutdown_off": lambda: self._set_auto_shutdown_enabled(False),
            "set_pointer_look_on": lambda: self._set_pet_look_enabled(True),
            "set_pointer_look_off": lambda: self._set_pet_look_enabled(False),
            "set_auto_jump_on": lambda: self._set_pet_auto_jump_enabled(True),
            "set_auto_jump_off": lambda: self._set_pet_auto_jump_enabled(False),
        }
        action = actions.get(tool)
        if action is None:
            self._pet_feedback("failed", "这个操作不在允许列表中，我不能执行。", 5200)
            return
        self._log(f"{self.pet_name}本地 Agent 调用白名单操作：{tool}")

        if tool.startswith("set_"):
            action()
            return

        def release_then_run() -> None:
            self.cartethyia_agent.unload()
            self.root.after(0, action)

        threading.Thread(
            target=release_then_run,
            name="cartethyia-agent-release-before-task",
            daemon=True,
        ).start()

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
    def _load_auto_shutdown_enabled() -> bool:
        try:
            saved = json.loads(APP_SETTINGS_CONFIG.read_text(encoding="utf-8"))
            return saved.get("shutdown_after_task") is True
        except (OSError, ValueError, json.JSONDecodeError):
            return False

    def _save_auto_shutdown_setting(self) -> None:
        try:
            saved = json.loads(APP_SETTINGS_CONFIG.read_text(encoding="utf-8"))
            if not isinstance(saved, dict):
                saved = {}
        except (OSError, ValueError):
            saved = {}
        saved["shutdown_after_task"] = bool(self.auto_shutdown_enabled.get())
        APP_SETTINGS_CONFIG.write_text(
            json.dumps(
                saved,
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def _start_custom_4c(self) -> None:
        try:
            settings = json.loads(APP_SETTINGS_CONFIG.read_text(encoding="utf-8"))
            if not isinstance(settings, dict):
                settings = {}
        except (OSError, ValueError):
            settings = {}
        saved_count = settings.get("four_c_count", 30)
        if type(saved_count) is not int or not 1 <= saved_count <= 9999:
            saved_count = 30
        count = self._ask_4c_count(saved_count)
        if count is None:
            return
        settings["four_c_count"] = count
        try:
            APP_SETTINGS_CONFIG.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            messagebox.showerror("保存失败", "无法记住刷取次数，请检查程序目录权限。", parent=self.root)
            return
        self._start_named_task_real("4C刷取", count)

    def _ask_4c_count(self, initial: int) -> int | None:
        dialog = Toplevel(self.root)
        dialog.title("4C刷取次数")
        dialog.transient(self.root)
        dialog.resizable(False, False)
        dialog.configure(bg=COLORS["app_bg"])
        dialog.geometry("390x210")
        shell, body = self._rounded_panel(dialog, padding=18, outer_color=COLORS["app_bg"])
        shell.pack(fill=BOTH, expand=True, padx=14, pady=14)
        Label(body, text="4C刷取次数", font=(FONT_FAMILY, 13, "bold"),
              bg=COLORS["panel_alt"], fg=COLORS["text"]).pack(anchor="w")
        Label(body, text="要刷取多少次？会自动记住上次的次数（1–9999）。",
              bg=COLORS["panel_alt"], fg=COLORS["muted"]).pack(anchor="w", pady=(6, 12))
        value = StringVar(value=str(initial))
        input_shell, input_body = self._rounded_panel(body, padding=6,
                                                      color=COLORS["panel"],
                                                      outer_color=COLORS["panel_alt"])
        input_shell.pack(fill=X)
        entry = Entry(input_body, textvariable=value, font=(FONT_FAMILY, 11),
                      bg=COLORS["panel"], fg=COLORS["text"],
                      insertbackground=COLORS["text"], relief="flat", bd=0)
        entry.pack(fill=X, padx=4)
        error = Label(body, text="", bg=COLORS["panel_alt"], fg=COLORS["primary"])
        error.pack(anchor="w", pady=(4, 0))
        result = {"count": None}

        def accept() -> None:
            try:
                count = int(value.get().strip())
            except ValueError:
                count = 0
            if not 1 <= count <= 9999:
                error.configure(text="请输入 1 到 9999 之间的整数。")
                return
            result["count"] = count
            dialog.destroy()

        actions = Frame(body, bg=COLORS["panel_alt"])
        actions.pack(side="bottom", fill=X, pady=(3, 0))
        self._rounded_button(actions, "取消", dialog.destroy, width=84).pack(side=RIGHT)
        self._rounded_button(actions, "确定", accept, width=84, primary=True).pack(side=RIGHT, padx=(0, 8))
        dialog.bind("<Return>", lambda _event: accept())
        dialog.bind("<Escape>", lambda _event: dialog.destroy())
        dialog.protocol("WM_DELETE_WINDOW", dialog.destroy)
        entry.focus_set()
        entry.select_range(0, END)
        dialog.grab_set()
        self.root.wait_window(dialog)
        return result["count"]

    def _apply_auto_shutdown_setting(self) -> None:
        self._save_auto_shutdown_setting()
        state = "开启" if self.auto_shutdown_enabled.get() else "关闭"
        self.status.set(f"任务完成后自动关机：{state}")
        self._log(f"任务正常完成后自动关机已{state}。")

    def _set_auto_shutdown_enabled(self, enabled: bool) -> None:
        self.auto_shutdown_enabled.set(bool(enabled))
        self._apply_auto_shutdown_setting()

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

    def _save_combat_settings(self, announce: bool = True) -> None:
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
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        self._log(
            f"战斗技能键位已保存为：{normalized_skill}；大招键位：{normalized_ultimate}。"
        )
        if announce:
            messagebox.showinfo(
                "已保存",
                f"战斗技能键位：{normalized_skill}\n战斗大招键位：{normalized_ultimate}",
                parent=self.root,
            )

    def _autosave_combat_settings(self, _event=None) -> None:
        self._save_combat_settings(announce=False)
        self.status.set("战斗键位已自动保存")

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

        self.header = Frame(self.root, padx=24, pady=12, bg=COLORS["app_bg"])
        self.header.pack(side=TOP, fill=X)
        Label(self.header, text="wwbs", font=(FONT_FAMILY, 22, "bold"), fg=COLORS["text"], bg=COLORS["app_bg"]).pack(side=LEFT)
        self._rounded_button(self.header, "检查更新", self._check_for_updates, width=92).pack(side=RIGHT, padx=(0, 8))
        self._rounded_button(self.header, "关于", self._show_about, width=66).pack(side=RIGHT, padx=(0, 8))
        self._rounded_button(self.header, "更新公告", self._show_update_history, width=92).pack(side=RIGHT, padx=(0, 14))
        Label(self.header, textvariable=self.status, font=(FONT_FAMILY, 10), fg=COLORS["muted"], bg=COLORS["app_bg"]).pack(side=RIGHT)

        nav = Frame(self.root, padx=24, bg=COLORS["app_bg"])
        nav.pack(side=TOP, fill=X, pady=(0, 8))

        summary_shell, summary = self._rounded_panel(
            self.root, padding=9, color=COLORS["panel"], outer_color=COLORS["app_bg"])
        summary_shell.pack(side=TOP, fill=X, padx=24, pady=(0, 10))
        summary.configure(padx=16)
        Label(summary, text="●", fg=COLORS["primary"], bg=COLORS["panel"]).pack(side=LEFT)
        Label(summary, textvariable=self.device_status, fg=COLORS["text"],
              bg=COLORS["panel"]).pack(side=LEFT, padx=(4, 22))
        Label(summary, textvariable=self.template_status, fg=COLORS["muted"],
              bg=COLORS["panel"]).pack(side=LEFT, padx=(0, 22))
        Label(summary, text="手动点击后执行", fg=COLORS["muted"],
              bg=COLORS["panel"]).pack(side=LEFT)

        tabs_shell, self.tabs = self._rounded_panel(
            self.root, padding=0, color=COLORS["panel"], outer_color=COLORS["app_bg"])
        tabs_shell.pack(fill=BOTH, expand=True, padx=24, pady=(0, 22))
        self.tabs.columnconfigure(0, weight=1)
        self.tabs.rowconfigure(0, weight=1)

        self.start_tab = Frame(self.tabs, padx=20, pady=18, bg=COLORS["panel"])
        self.template_tab = Frame(self.tabs, padx=20, pady=18, bg=COLORS["panel"])
        rotation_shell = Frame(self.tabs, bg=COLORS["panel"])
        self.rotation_tab, self.rotation_scroll_canvas = self._create_scrollable_tab(rotation_shell, stretch=True)
        probability_shell = Frame(self.tabs, bg=COLORS["panel"])
        self.probability_tab, self.probability_scroll_canvas = self._create_scrollable_tab(probability_shell)
        settings_shell = Frame(self.tabs, bg=COLORS["panel"])
        self.settings_tab, self.settings_scroll_canvas = self._create_scrollable_tab(settings_shell)
        self.log_tab = Frame(self.tabs, padx=20, pady=18, bg=COLORS["panel"])
        self._tab_panels = (self.start_tab, rotation_shell, self.template_tab,
                            probability_shell, settings_shell, self.log_tab)
        self._nav_buttons = []
        nav_font = tkfont.Font(root=self.root, family=FONT_FAMILY, size=11)
        for index, title in enumerate(("快捷任务", "战斗排轴", "模板", "概率", "设置", "日志")):
            button = Canvas(nav, width=max(84, nav_font.measure(title) + 34),
                            height=max(48, nav_font.metrics("linespace") + 19),
                            bg=COLORS["app_bg"], highlightthickness=0,
                            cursor="hand2", takefocus=True)
            button._keep_canvas_style = True
            button.pack(side=LEFT, padx=(0, 4))
            button.bind("<Button-1>", lambda _event, position=index: self._select_top_tab(position))
            button.bind("<Return>", lambda _event, position=index: self._select_top_tab(position))
            button.bind("<space>", lambda _event, position=index: self._select_top_tab(position))
            button.bind("<Enter>", lambda _event, position=index: self._draw_nav_button(position, True))
            button.bind("<Leave>", lambda _event, position=index: self._draw_nav_button(position))
            button.bind("<Configure>", lambda _event, position=index: self._draw_nav_button(position))
            self._nav_buttons.append((button, title))
            self._draw_nav_button(index)
        for panel in self._tab_panels:
            panel.grid(row=0, column=0, sticky="nsew")
        self._selected_top_tab = 0
        self._select_top_tab(0)

        self._build_start_tab()
        self._build_rotation_tab()
        self._build_template_tab()
        self._build_probability_tab()
        self._build_settings_tab()
        self._build_log_tab()
        self._polish_widgets(self.root)

    def _create_scrollable_tab(self, parent: Frame, *, padding: int = 20,
                               modern: bool = True, stretch: bool = False) -> tuple[Frame, Canvas]:
        canvas = Canvas(parent, highlightthickness=0, bg=COLORS["panel"])
        if modern:
            scrollbar = Canvas(parent, width=7, highlightthickness=0, bd=0,
                               bg=COLORS["panel"], cursor="hand2")
            scrollbar._keep_canvas_style = True
            canvas._scroll_range = (0.0, 1.0)

            def draw_scrollbar(_event=None) -> None:
                scrollbar.delete("all")
                first, last = canvas._scroll_range
                height = scrollbar.winfo_height()
                if height <= 1 or last - first >= 0.999:
                    return
                scrollbar.create_line(3, 0, 3, height, fill=COLORS["line_soft"], width=2)
                top = max(2, int(first * height))
                bottom = min(height - 2, max(top + 24, int(last * height)))
                scrollbar.create_line(3, top, 3, bottom, fill=COLORS["line"], width=5, capstyle="round")

            def update_scrollbar(first, last) -> None:
                canvas._scroll_range = (float(first), float(last))
                draw_scrollbar()

            def drag_scrollbar(event) -> None:
                first, last = canvas._scroll_range
                visible = min(1.0, last - first)
                height = max(1, scrollbar.winfo_height())
                thumb = max(24, int(visible * height))
                travel = max(1, height - thumb)
                top = max(0, min(travel, event.y - thumb // 2))
                canvas.yview_moveto(top / travel * (1.0 - visible))

            scrollbar.bind("<Configure>", draw_scrollbar)
            scrollbar.bind("<Button-1>", drag_scrollbar)
            scrollbar.bind("<B1-Motion>", drag_scrollbar)
            canvas.configure(yscrollcommand=update_scrollbar)
        else:
            scrollbar = self._thin_scrollbar(parent, orient="vertical", command=canvas.yview)
            canvas.configure(yscrollcommand=scrollbar.set)
        canvas._scrollbar = scrollbar
        content = Frame(canvas, padx=padding, pady=18 if padding else 0, bg=COLORS["panel"])
        content_window = canvas.create_window((0, 0), window=content, anchor="nw")
        canvas.pack(side=LEFT, fill=BOTH, expand=True)
        scrollbar.pack(side=RIGHT, fill="y")

        def resize_content(_event=None):
            options = {'width': max(1, canvas.winfo_width())}
            if stretch:
                options['height'] = max(canvas.winfo_height(), content.winfo_reqheight())
            canvas.itemconfigure(content_window, **options)
            # Prevent short lists from exposing a blank band above their cards.
            bounds = canvas.bbox(content_window)
            if bounds:
                canvas.configure(scrollregion=(0, 0, max(1, canvas.winfo_width()),
                                               max(canvas.winfo_height(), bounds[3])))
                if bounds[3] <= canvas.winfo_height():
                    canvas.yview_moveto(0)
        content.bind('<Configure>', resize_content)
        canvas.bind('<Configure>', resize_content)
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

    def _scroll_start_left(self, event) -> str:
        direction = -1 if getattr(event, "delta", 0) > 0 else 1
        self.start_left_canvas.yview_scroll(direction * 3, "units")
        return "break"

    def _bind_start_left_mousewheel(self, widget) -> None:
        if isinstance(widget, ttk.Combobox) or getattr(widget, "_is_rounded_picker", False):
            return  # Keep the zone picker's own wheel selection behavior.
        widget.bind("<MouseWheel>", self._scroll_start_left, add="+")
        for child in widget.winfo_children():
            self._bind_start_left_mousewheel(child)

    def _update_start_scrollbar(self, first: str, last: str) -> None:
        self._start_scroll_range = (float(first), float(last))
        self._draw_start_scrollbar()

    def _draw_start_scrollbar(self) -> None:
        bar = self.start_left_scrollbar
        bar.delete("all")
        height = bar.winfo_height()
        width = bar.winfo_width()
        first, last = self._start_scroll_range
        if height <= 1 or last - first >= 0.999:
            return
        bar.create_line(width // 2, 0, width // 2, height,
                        fill=COLORS["line_soft"], width=2)
        top = max(2, int(first * height))
        bottom = min(height - 2, max(top + 24, int(last * height)))
        bar.create_line(width // 2, top, width // 2, bottom,
                        fill=COLORS["line"], width=5, capstyle="round")

    def _drag_start_scrollbar(self, event) -> None:
        first, last = self._start_scroll_range
        visible = min(1.0, last - first)
        height = max(1, self.start_left_scrollbar.winfo_height())
        thumb = max(24, int(visible * height))
        travel = max(1, height - thumb)
        top = max(0, min(travel, event.y - thumb // 2))
        self.start_left_canvas.yview_moveto((top / travel) * (1.0 - visible))

    @staticmethod
    def _paint_rounded_card(canvas: Canvas, x0: int, y0: int, x1: int, y1: int,
                            radius: int, color: str) -> None:
        from ui_controls import paint_round
        paint_round(canvas, x0, y0, x1, y1, radius, color)

    def _rounded_panel(self, parent, *, padding: int = 12, color: str | None = None,
                       outer_color: str | None = None):
        """Return a rounded shell and a normal Frame for its contents."""
        color = color or COLORS["panel_alt"]
        outer_color = outer_color or COLORS["panel"]
        shell = Frame(parent, bg=outer_color)
        backdrop = Canvas(shell, bg=outer_color, highlightthickness=0, bd=0)
        backdrop.place(relx=0, rely=0, relwidth=1, relheight=1)
        backdrop._keep_canvas_style = True
        content = Frame(shell, bg=color, padx=max(0, padding-6), pady=max(0, padding-6))
        content.pack(fill=BOTH, expand=True, padx=8, pady=8)

        def redraw(event) -> None:
            backdrop.delete("all")
            self._paint_rounded_card(backdrop, 0, 0, event.width, event.height, 14,
                                     COLORS["line_soft"])
            self._paint_rounded_card(backdrop, 1, 1, event.width - 1, event.height - 1,
                                     13, color)

        shell.bind("<Configure>", redraw)
        return shell, content

    def _close_rounded_picker(self) -> None:
        picker = getattr(self, "_active_rounded_picker", None)
        close = getattr(picker, "_popup_close", None)
        if close:
            close()

    def _ui_button(self, parent, *, text, command, width=None, **options):
        primary = options.pop('style', '') == 'Primary.TButton' or options.get('fg') in ('white', '#ffffff')
        colors = dict(COLORS)
        if primary and options.get('bg'):
            colors['primary'] = options['bg']
            colors['primary_hover'] = options.get('activebackground', options['bg'])
        return RoundedButton(parent, text=text, command=command, colors=colors,
                             width=width*9+24 if width else 100, primary=primary,
                             state=options.get('state', 'normal'), font_family=FONT_FAMILY)

    def _thin_scrollbar(self, parent, **options):
        return ThinScrollbar(parent, colors=COLORS, **options)

    def _rounded_entry(self, parent, **options):
        font = options.pop('font', (FONT_FAMILY, 10))
        measure = tkfont.Font(root=self.root, font=font)
        fill = options.pop('bg', COLORS['panel'])
        width = options.pop('width', 20)
        for key in ('relief', 'bd', 'highlightthickness', 'highlightbackground', 'highlightcolor'):
            options.pop(key, None)
        height = max(30, measure.metrics('linespace')+10)
        shell = Canvas(parent, width=measure.measure('0')*width+20, height=height,
                       bg=parent.cget('bg'), highlightthickness=0, bd=0)
        shell._keep_canvas_style = True
        shell._is_rounded_entry = True
        entry = Entry(shell, font=font, bg=fill, relief='flat', bd=0, highlightthickness=0,
                      insertbackground=options.pop('insertbackground', COLORS['text']),
                      fg=options.pop('fg', COLORS['text']), readonlybackground=fill, **options)
        entry._rounded_shell = shell
        entry.place(x=10, y=5, relwidth=1, width=-20, relheight=1, height=-10)

        def draw(_event=None):
            shell.delete('shape')
            w, h = max(20, shell.winfo_width()), max(height, shell.winfo_height())
            self._paint_rounded_card(shell, 0, 0, w, h, 8,
                                     COLORS['primary'] if self.root.focus_get() is entry else COLORS['line'])
            self._paint_rounded_card(shell, 1, 1, w-1, h-1, 7, fill)

        shell.bind('<Configure>', draw)
        entry.bind('<FocusIn>', draw, add='+')
        entry.bind('<FocusOut>', draw, add='+')
        for method in ('pack', 'pack_configure', 'pack_forget', 'grid', 'grid_configure', 'grid_remove', 'place'):
            setattr(entry, method, getattr(shell, method))
        return entry

    def _card_body(self, parent):
        shell, body = self._rounded_panel(parent, padding=16, color=COLORS['panel_alt'])
        body.pack = shell.pack
        return body

    def _wrap_button_row(self, parent):
        """Keep action labels readable when the window or font size changes."""
        buttons = [child for child in parent.winfo_children()
                   if getattr(child, '_is_rounded_button', False)]
        for button in buttons:
            button.pack_forget()
        previous = {'columns': 0}
        def layout(event=None):
            width = event.width if event else parent.winfo_width()
            cell = max((button.winfo_reqwidth() for button in buttons), default=100)+10
            columns = max(1, min(len(buttons), int(width/cell)))
            if columns == previous['columns']:
                return
            for column in range(max(columns, previous['columns'])):
                parent.columnconfigure(column, weight=0, minsize=0)
            for index, button in enumerate(buttons):
                button.grid(row=index//columns, column=index%columns, sticky='w', padx=(0, 10), pady=4)
            previous['columns'] = columns
        parent.bind('<Configure>', layout, add='+')
        layout()

    @staticmethod
    def _reserve_row_controls(parent, stretch):
        """Allocate action widths before giving remaining space to a picker."""
        children = parent.winfo_children()
        for child in children:
            child.pack_forget()
        for column, child in enumerate(children):
            child.grid(row=0, column=column, sticky='ew', padx=(0, 8))
            parent.columnconfigure(column, weight=1 if child is stretch else 0)

    def _ask_text(self, title, prompt, *, initialvalue='', parent=None):
        owner = parent or self.root
        dialog = Toplevel(owner)
        dialog.withdraw()
        dialog.title(title)
        dialog.transient(owner)
        dialog.configure(bg=COLORS['app_bg'])
        dialog.resizable(False, False)
        shell, body = self._rounded_panel(dialog, padding=18, outer_color=COLORS['app_bg'])
        shell.pack(fill=BOTH, expand=True, padx=14, pady=14)
        Label(body, text=prompt, bg=COLORS['panel_alt'], fg=COLORS['text'],
              font=(FONT_FAMILY, 11), wraplength=440, justify=LEFT).pack(anchor='w', pady=(0, 12))
        value = StringVar(value=initialvalue)
        entry = self._rounded_entry(body, textvariable=value, width=34)
        entry.pack(fill=X)
        result = {'value': None}
        def accept():
            result['value'] = value.get()
            dialog.destroy()
        actions = Frame(body, bg=COLORS['panel_alt'])
        actions.pack(fill=X, pady=(14, 0))
        self._rounded_button(actions, '取消', dialog.destroy, width=84).pack(side=RIGHT)
        self._rounded_button(actions, '确定', accept, width=84, primary=True).pack(side=RIGHT, padx=(0, 8))
        dialog.bind('<Return>', lambda _: accept())
        dialog.bind('<Escape>', lambda _: dialog.destroy())
        dialog.update_idletasks()
        width, height = dialog.winfo_reqwidth(), dialog.winfo_reqheight()
        x = owner.winfo_x() + (owner.winfo_width()-width)//2
        y = owner.winfo_y() + (owner.winfo_height()-height)//2
        x = max(owner.winfo_vrootx(), min(x, owner.winfo_vrootx()+owner.winfo_vrootwidth()-width))
        y = max(owner.winfo_vrooty(), min(y, owner.winfo_vrooty()+owner.winfo_vrootheight()-height-32))
        dialog.geometry(f'{width}x{height}+{x}+{y}')
        dialog.deiconify()
        entry.focus_force()
        entry.select_range(0, END)
        dialog.grab_set()
        self.root.wait_window(dialog)
        return result['value']

    def _rounded_picker(self, parent, variable: StringVar, values, on_change,
                        *, height: int = 31, editable: bool = False) -> Canvas:
        """A rounded selector with a compact scrollable popup and wheel selection."""
        height = max(height, tkfont.Font(root=self.root, family=FONT_FAMILY,
                                         size=13, weight="bold").metrics("linespace") + 8)
        choices = list(values)
        label_font = tkfont.Font(root=self.root, family=FONT_FAMILY, size=10)
        def display_label(value, available):
            if label_font.measure(value) <= available:
                return value
            # Keep both the start of a preset name and its import suffix visible.
            for kept in range(len(value)-1, -1, -1):
                front, back = (kept+1)//2, kept//2
                shortened = value[:front] + "…" + (value[-back:] if back else "")
                if label_font.measure(shortened) <= available:
                    return shortened
            return ""
        picker = Canvas(parent, height=height, bg=parent.cget("bg"),
                        highlightthickness=0, bd=0, cursor="hand2", takefocus=True)
        picker._keep_canvas_style = True
        picker._is_rounded_picker = True
        def set_choices(values):
            self._close_rounded_picker()
            choices[:] = list(values)
        picker.set_choices = set_choices

        def draw(_event=None) -> None:
            picker.delete("all")
            width = max(80, picker.winfo_width())
            self._paint_rounded_card(picker, 0, 0, width, height, 8, COLORS["line"])
            self._paint_rounded_card(picker, 1, 1, width - 1, height - 1, 7, COLORS["panel"])
            picker.create_text(12, height // 2, text=display_label(variable.get(), max(1, width-40)), anchor="w",
                               width=width - 40, fill=COLORS["text"],
                               font=(FONT_FAMILY, 10))
            picker.create_text(width - 17, height // 2, text="⌄", fill=COLORS["muted"],
                               font=(FONT_FAMILY, 13, "bold"))

        def wheel(event) -> str:
            if not choices:
                return 'break'
            try:
                index = choices.index(variable.get())
            except ValueError:
                index = 0
            direction = -1 if event.delta > 0 else 1
            selected = choices[max(0, min(len(choices) - 1, index + direction))]
            if selected != variable.get():
                variable.set(selected)
                on_change()
            return "break"

        def popup(_event=None) -> str:
            previous = getattr(picker, "_popup_window", None)
            if previous is not None and previous.winfo_exists():
                picker._popup_close()
                return "break"
            self._close_rounded_picker()
            window = Toplevel(picker)
            window.overrideredirect(True)
            window.transient(self.root)
            picker._popup_window = window
            self._active_rounded_picker = picker
            width = max(180, picker.winfo_width())
            visible = min(8, len(choices))
            row_height = max(32, tkfont.Font(root=self.root, family=FONT_FAMILY,
                                             size=10).metrics("linespace") + 12)
            entry_height = max(40, row_height + 8) if editable else 0
            screen_left = picker.winfo_vrootx()
            screen_top = picker.winfo_vrooty()
            screen_right = screen_left + picker.winfo_vrootwidth()
            screen_bottom = screen_top + picker.winfo_vrootheight()
            x = max(screen_left + 8, min(picker.winfo_rootx(), screen_right - width - 8))
            below = picker.winfo_rooty() + height + 2
            # A shorter list below the picker keeps controls above it clickable.
            below_rows = (screen_bottom - 8 - below - 8 - entry_height) // row_height
            if below_rows >= 1:
                visible = min(visible, below_rows)
                y = below
            else:
                above_rows = (picker.winfo_rooty() - screen_top - 18 - entry_height) // row_height
                visible = min(visible, max(1, above_rows))
                y = picker.winfo_rooty() - (visible * row_height + 8 + entry_height) - 2
            total_height = visible * row_height + 8 + entry_height
            y = max(screen_top + 8, min(y, screen_bottom - total_height - 8))
            window.geometry(f"{width}x{total_height}+{x}+{y}")
            outside_binding = None

            def close_popup() -> None:
                nonlocal outside_binding
                if outside_binding is not None:
                    self.root.unbind("<Button-1>", outside_binding)
                    outside_binding = None
                if window.winfo_exists():
                    window.destroy()
                picker._popup_window = None
                picker._popup_close = None
                if getattr(self, "_active_rounded_picker", None) is picker:
                    self._active_rounded_picker = None

            def close_if_outside(event) -> None:
                if not (x <= event.x_root < x + width and y <= event.y_root < y + total_height):
                    close_popup()

            picker._popup_close = close_popup

            def bind_outside() -> None:
                nonlocal outside_binding
                if window.winfo_exists():
                    outside_binding = self.root.bind("<Button-1>", close_if_outside, add="+")

            picker.after_idle(bind_outside)
            surface = Canvas(window, width=width, height=total_height,
                             bg=COLORS["panel"], highlightthickness=0, bd=0)
            surface.pack(fill=BOTH, expand=True)
            try:
                selected_index = choices.index(variable.get())
            except ValueError:
                selected_index = 0
            offset = max(0, min(len(choices) - visible, selected_index - visible // 2))
            custom = None

            def redraw() -> None:
                surface.delete("all")
                self._paint_rounded_card(surface, 0, 0, width, total_height, 9, COLORS["line"])
                self._paint_rounded_card(surface, 1, 1, width - 1, total_height - 1,
                                         8, COLORS["panel"])
                for row, value in enumerate(choices[offset:offset + visible]):
                    top = row * row_height + 4 + entry_height
                    if value == variable.get():
                        self._paint_rounded_card(surface, 5, top, width - 13, top + row_height,
                                                 6, COLORS["panel_alt"])
                    surface.create_text(14, top + row_height // 2, text=display_label(value, width-38), anchor="w",
                                        width=width - 38, fill=COLORS["text"],
                                        font=(FONT_FAMILY, 10))
                if len(choices) > visible:
                    track_top, track_bottom = 8 + entry_height, total_height - 8
                    track_height = track_bottom - track_top
                    thumb_height = max(22, int(track_height * visible / len(choices)))
                    thumb_top = track_top + int((track_height - thumb_height) * offset / (len(choices) - visible))
                    surface.create_line(width - 6, track_top, width - 6, track_bottom,
                                        fill=COLORS["line_soft"], width=2)
                    surface.create_line(width - 6, thumb_top, width - 6, thumb_top + thumb_height,
                                        fill=COLORS["muted"], width=4, capstyle="round")
                if custom is not None:
                    surface.create_window(7, 7, window=custom, anchor="nw", width=width - 20,
                                          height=27)

            def scroll_list(event) -> str:
                nonlocal offset
                offset = max(0, min(len(choices) - visible, offset + (-1 if event.delta > 0 else 1)))
                redraw()
                return "break"

            def choose(event) -> None:
                nonlocal offset
                if not 0 <= event.x < width or not 0 <= event.y < total_height:
                    close_popup()
                    return
                if event.x >= width - 13 and len(choices) > visible:
                    offset = max(0, min(len(choices) - visible,
                                        int((event.y - entry_height) / (total_height - entry_height)
                                            * (len(choices) - visible + 1))))
                    redraw()
                    return
                if event.y < entry_height:
                    return
                index = offset + max(0, min(visible - 1,
                                             (event.y - 4 - entry_height) // row_height))
                if 0 <= index < len(choices):
                    variable.set(choices[index])
                    on_change()
                close_popup()

            redraw()
            if editable:
                custom = Entry(surface, font=(FONT_FAMILY, 10), relief="flat", bd=0,
                               bg=COLORS["panel_alt"], fg=COLORS["text"],
                               insertbackground=COLORS["text"])
                custom.insert(0, variable.get())
                redraw()

                def save_custom(_event=None) -> None:
                    variable.set(custom.get().strip())
                    on_change()
                    close_popup()

                custom.bind("<Return>", save_custom)
            surface.bind("<MouseWheel>", scroll_list)
            surface.bind("<Button-1>", choose)
            surface.bind("<B1-Motion>", lambda event: choose(event)
                         if event.x >= width - 13 else None)
            window.bind("<Escape>", lambda _event: close_popup())
            window.protocol("WM_DELETE_WINDOW", close_popup)
            window.lift()
            window.focus_set()
            if editable:
                custom.focus_set()
                custom.select_range(0, END)
            return "break"

        picker.bind("<Configure>", draw)
        picker.bind("<MouseWheel>", wheel)
        picker.bind("<Button-1>", popup)
        picker.bind("<Return>", popup)
        picker.bind("<space>", popup)
        redraw_job = None

        def schedule_draw(*_args):
            nonlocal redraw_job
            if not picker.winfo_exists():
                return
            if redraw_job:
                picker.after_cancel(redraw_job)

            def refresh():
                nonlocal redraw_job
                redraw_job = None
                if picker.winfo_exists():
                    draw()

            redraw_job = picker.after_idle(refresh)

        trace_id = variable.trace_add("write", schedule_draw)

        def dispose(event):
            nonlocal redraw_job
            if event.widget is not picker:
                return
            if redraw_job:
                picker.after_cancel(redraw_job)
                redraw_job = None
            variable.trace_remove("write", trace_id)
            close = getattr(picker, "_popup_close", None)
            if close:
                close()

        picker.bind("<Destroy>", dispose, add="+")
        draw()
        return picker

    def _rounded_button(self, parent, label: str, command, *, width: int = 130,
                        primary: bool = False) -> Canvas:
        measure_font = tkfont.Font(root=self.root, family=FONT_FAMILY, size=10,
                                   weight="bold" if primary else "normal")
        width = max(width, measure_font.measure(label) + 32)
        height = max(42, measure_font.metrics("linespace") + 18)
        button = Canvas(parent, width=width, height=height, bg=parent.cget("bg"),
                        highlightthickness=0, bd=0, cursor="hand2", takefocus=True)
        button._keep_canvas_style = True

        def draw(state: str = "default") -> None:
            button.delete("all")
            actual_width = button.winfo_width() if button.winfo_width() > 1 else width
            actual_height = button.winfo_height() if button.winfo_height() > 1 else height
            fill = (COLORS["primary_hover"] if state == "hover" else COLORS["primary"])
            if not primary:
                fill = COLORS["panel"] if state == "default" else COLORS["panel_alt"]
            if state == "pressed":
                fill = COLORS["line_soft"] if not primary else COLORS["primary"]
            self._paint_rounded_card(button, 0, 0, actual_width, actual_height, 9,
                                     COLORS["primary"] if primary else COLORS["line"])
            self._paint_rounded_card(button, 1, 1, actual_width - 1, actual_height - 1, 8, fill)
            button.create_text(actual_width // 2, actual_height // 2, text=label,
                               fill="#ffffff" if primary else COLORS["text"],
                               font=(FONT_FAMILY, 10, "bold" if primary else "normal"))

        button.bind("<Configure>", lambda _event: draw())
        button.bind("<Enter>", lambda _event: draw("hover"))
        button.bind("<Leave>", lambda _event: draw())
        button.bind("<ButtonPress-1>", lambda _event: draw("pressed"))
        button.bind("<ButtonRelease-1>", lambda event: (
            draw("hover"), command() if 0 <= event.x < button.winfo_width()
            and 0 <= event.y < button.winfo_height() else None
        ))
        button.bind("<Return>", lambda _event: command())
        button.bind("<space>", lambda _event: command())
        draw()
        return button

    @staticmethod
    def _normalize_start_action_order(saved) -> list[str]:
        defaults = ["weekly_rewards", "weekly_astrite", "daily", "combat_4c_10", "combat_4c_custom", "tower"]
        if not isinstance(saved, list):
            return defaults
        ordered = []
        for key in saved:
            if key in defaults and key not in ordered:
                ordered.append(key)
        return ordered + [key for key in defaults if key not in ordered]

    def _load_start_action_order(self) -> list[str]:
        try:
            saved = json.loads(UI_CONFIG.read_text(encoding="utf-8")).get("start_action_order")
        except (OSError, ValueError, AttributeError):
            saved = None
        return self._normalize_start_action_order(saved)

    def _save_start_action_order(self) -> None:
        try:
            UI_CONFIG.write_text(json.dumps({"start_action_order": self._start_action_order},
                                            ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as exc:
            self._log(f"保存快捷任务顺序失败：{exc}")

    def _repack_start_action_cards(self) -> None:
        for card in self._start_action_cards.values():
            card.pack_forget()
        for key in self._start_action_order:
            self._start_action_cards[key].pack(fill=X, pady=(0, 6))
        next(iter(self._start_action_cards.values())).master.update_idletasks()

    def _move_start_action_card(self, key: str, pointer_y: int) -> None:
        order = self._start_action_order
        if key not in order:
            return
        index = order.index(key)
        for other_key in order:
            if other_key == key:
                continue
            other = self._start_action_cards[other_key]
            midpoint = other.winfo_rooty() + other.winfo_height() // 2
            if pointer_y < midpoint:
                target = order.index(other_key)
                if index < target:
                    target -= 1
                if target != index:
                    order.pop(index)
                    order.insert(target, key)
                    self._repack_start_action_cards()
                return
        if index != len(order) - 1:
            order.pop(index)
            order.append(key)
            self._repack_start_action_cards()

    def _activate_start_action_card(self, card: Canvas, event, command,
                                    notice_key: str, with_zone: bool) -> None:
        width = card.winfo_width()
        if not 0 <= event.x < width or not 0 <= event.y < card.winfo_height():
            return
        if width - 82 <= event.x <= width - 45 and event.y < 58:
            self._show_run_notice(notice_key)
        elif not with_zone or event.y < 65:
            command()

    def _make_start_action_card(self, parent: Frame, key: str, title: str, detail: str,
                                command, notice_key: str, with_zone: bool = False):
        title_line = tkfont.Font(root=self.root, family=FONT_FAMILY, size=11,
                                 weight="bold").metrics("linespace")
        detail_line = tkfont.Font(root=self.root, family=FONT_FAMILY, size=9).metrics("linespace")
        height = max(86, 22 + title_line + detail_line + 14) + (44 if with_zone else 0)
        card = Canvas(parent, height=height, width=360, bg=COLORS["panel"],
                      highlightthickness=0, cursor="hand2", takefocus=True)
        card._keep_canvas_style = True
        self._start_action_cards[key] = card
        picker = None
        picker_window = None
        if with_zone:
            picker = self._rounded_picker(card, self.daily_zone, DAILY_ZONE_NAMES,
                                          self._save_daily_zone)
            picker_window = card.create_window(55, 73, window=picker, anchor="nw")

        def draw(state: str = "default") -> None:
            card.delete("shape")
            width = max(180, card.winfo_width())
            if getattr(card, "_drag_started", False):
                self._paint_rounded_card(card, 1, 1, width - 2, height - 2, 14,
                                         COLORS["line_soft"])
                self._paint_rounded_card(card, 2, 2, width - 3, height - 3, 13,
                                         COLORS["panel"])
                card.create_text(width // 2, height // 2, text="松开即可放到此处",
                                 fill=COLORS["muted"], font=(FONT_FAMILY, 10), tags="shape")
                return
            self._paint_rounded_card(card, 1, 1, width - 2, height - 2, 14,
                                     COLORS["primary"] if state != "default" else COLORS["line_soft"])
            self._paint_rounded_card(card, 2, 2, width - 3, height - 3, 13,
                                     COLORS["line_soft"] if state == "pressed" else
                                     COLORS["panel"] if state == "hover" else COLORS["panel_alt"])
            for offset_y in (25, 31, 37):
                card.create_oval(19, offset_y, 22, offset_y + 3,
                                 fill=COLORS["muted"], outline="", tags="shape")
            card.create_text(51, 25, text=title, anchor="w", fill=COLORS["text"],
                             width=max(130, width - 145), font=(FONT_FAMILY, 11, "bold"), tags="shape")
            card.create_text(51, 49, text=detail, anchor="w", fill=COLORS["muted"],
                             width=max(130, width - 145), font=(FONT_FAMILY, 9), tags="shape")
            card.create_oval(width - 72, 23, width - 50, 45,
                             outline=COLORS["muted"], width=1, tags="shape")
            card.create_text(width - 61, 34, text="?", fill=COLORS["muted"],
                             font=(FONT_FAMILY, 9, "bold"), tags="shape")
            card.create_text(width - 25, 34, text="›", fill=COLORS["text"],
                             font=(FONT_FAMILY, 19), tags="shape")
            if picker_window is not None:
                card.itemconfigure(picker_window, width=max(120, width - 80))
            card.tag_lower("shape")

        card.bind("<Configure>", lambda _event: draw())
        card.bind("<Enter>", lambda _event: draw("hover"))
        card.bind("<Leave>", lambda _event: draw())
        def press(event) -> None:
            card._drag_from_handle = 8 <= event.x <= 34 and 10 <= event.y <= 56
            card._drag_started = False
            card._drag_origin = event.y_root
            card._drag_offset = (event.x_root - card.winfo_rootx(),
                                 event.y_root - card.winfo_rooty())
            card.configure(cursor="hand2")
            draw("pressed")

        def motion(event) -> None:
            if not getattr(card, "_drag_from_handle", False):
                return
            if not card._drag_started and abs(event.y_root - card._drag_origin) >= 5:
                # A floating copy preserves the pointer's position within the card,
                # while the original card becomes the destination placeholder.
                ghost = Toplevel(self.root)
                ghost.withdraw()
                ghost.overrideredirect(True)
                ghost.transient(self.root)
                ghost.attributes("-topmost", True)
                ghost.attributes("-alpha", 0.94)
                surface = Canvas(ghost, width=card.winfo_width(), height=height,
                                 bg=COLORS["panel"], highlightthickness=0, bd=0,
                                 cursor="hand2")
                surface.pack()
                # Repacking the source can change native mouse routing. The
                # floating surface must keep forwarding the same drag gesture.
                surface.bind("<B1-Motion>", motion)
                surface.bind("<ButtonRelease-1>", release)
                for item in card.find_withtag("shape"):
                    kind = card.type(item)
                    options = {name: values[-1] for name, values in card.itemconfigure(item).items()}
                    getattr(surface, "create_" + kind)(*card.coords(item), **options)
                if picker_window is not None:
                    width = card.winfo_width()
                    self._paint_rounded_card(surface, 55, 73, width - 25, 105, 9,
                                             COLORS["line"])
                    self._paint_rounded_card(surface, 56, 74, width - 26, 104, 8,
                                             COLORS["panel"])
                    surface.create_text(67, 89, text=self.daily_zone.get(), anchor="w",
                                        fill=COLORS["text"], font=(FONT_FAMILY, 10))
                    surface.create_text(width - 41, 89, text="⌄", fill=COLORS["muted"])
                    card.itemconfigure(picker_window, state="hidden")
                card._drag_ghost = ghost
                card._drag_started = True
                draw()
                offset_x, offset_y = card._drag_offset
                ghost.geometry(f"+{event.x_root - offset_x}+{event.y_root - offset_y}")
                ghost.deiconify()
            if card._drag_started:
                offset_x, offset_y = card._drag_offset
                card._drag_ghost.geometry(f"+{event.x_root - offset_x}+{event.y_root - offset_y}")
                card._drag_ghost.lift()
                top = self.start_left_canvas.winfo_rooty()
                bottom = top + self.start_left_canvas.winfo_height()
                if event.y_root < top + 30:
                    self.start_left_canvas.yview_scroll(-1, "units")
                elif event.y_root > bottom - 30:
                    self.start_left_canvas.yview_scroll(1, "units")
                self._move_start_action_card(key, event.y_root)

        def release(event) -> None:
            card.configure(cursor="hand2")
            was_handle = getattr(card, "_drag_from_handle", False)
            was_dragged = getattr(card, "_drag_started", False)
            card._drag_from_handle = False
            card._drag_started = False
            ghost = getattr(card, "_drag_ghost", None)
            if ghost is not None:
                ghost.destroy()
                card._drag_ghost = None
            if picker_window is not None:
                card.itemconfigure(picker_window, state="normal")
            draw("hover")
            if was_dragged:
                self._save_start_action_order()
            elif not was_handle:
                self._activate_start_action_card(card, event, command, notice_key, with_zone)

        card.bind("<ButtonPress-1>", press)
        card.bind("<B1-Motion>", motion)
        card.bind("<ButtonRelease-1>", release)
        card.bind("<Return>", lambda _event: command())
        card.bind("<space>", lambda _event: command())
        draw()
        return picker

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

    def _draw_nav_button(self, index: int, hovered: bool = False) -> None:
        button, title = self._nav_buttons[index]
        selected = index == getattr(self, "_selected_top_tab", 0)
        background = COLORS["panel_alt"] if hovered and not selected else COLORS["app_bg"]
        button.configure(bg=background)
        button.delete("all")
        width = int(button.cget("width"))
        nav_height = max(int(button.cget("height")), button.winfo_height())
        button.create_text(width // 2, nav_height // 2 - 2, text=title,
                           fill=COLORS["primary"] if selected else COLORS["text"],
                           font=(FONT_FAMILY, 11, "bold" if selected else "normal"))
        if selected:
            button.create_line(8, nav_height - 3, width - 8, nav_height - 3,
                               fill=COLORS["primary"], width=2)

    def _select_top_tab(self, index: int) -> None:
        self._close_rounded_picker()
        previous = getattr(self, '_visible_top_tab', None)
        if previous == index:
            return
        self._selected_top_tab = index
        # Keep layout allocated: unmapping/remapping a long axis makes Tk lay out
        # and repaint every card again. Only raise the cached page and update the
        # two navigation labels whose state actually changed.
        self._tab_panels[index].tkraise()
        self._visible_top_tab = index
        changed = range(len(self._nav_buttons)) if previous is None else (previous, index)
        for position in changed:
            self._draw_nav_button(position)
        if index == 0 and getattr(self, '_preview_deferred', False):
            self.root.after_idle(lambda: self._resize_preview_canvas(None))

    def _polish_widgets(self, widget) -> None:
        for child in widget.winfo_children():
            klass = child.winfo_class()
            if klass == "Frame":
                current_bg = child.cget("bg")
                if current_bg not in (COLORS["app_bg"], COLORS["panel"], COLORS["panel_alt"]):
                    child.configure(bg=COLORS["panel"])
            elif klass == "Label":
                parent_bg = child.master.cget("bg") if hasattr(child.master, "cget") else COLORS["panel"]
                foreground = child.cget('fg')
                child.configure(bg=parent_bg, fg=COLORS['muted'] if foreground == '#5f6b7a'
                                else COLORS['text'] if foreground in ('SystemButtonText', 'black') else foreground)
                if child.cget('wraplength'):
                    child.pack_configure(fill=X) if child.winfo_manager() == 'pack' else None
                    child.bind('<Configure>', lambda event, label=child:
                               label.configure(wraplength=max(100, event.width-8)), add='+')
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
                if getattr(child, '_rounded_shell', None) is not None:
                    continue
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
                    highlightthickness=0,
                    activestyle="none",
                )
            elif klass == "Text":
                child.configure(
                    bg=COLORS["panel"],
                    fg=COLORS["text"],
                    insertbackground=COLORS["text"],
                    relief="flat",
                    bd=0,
                    highlightthickness=0,
                    padx=10,
                    pady=8,
                )
            elif klass == "Checkbutton":
                parent_bg = child.master.cget("bg") if hasattr(child.master, "cget") else COLORS["panel"]
                child.configure(bg=parent_bg, fg=COLORS["text"], activebackground=parent_bg, activeforeground=COLORS["text"], selectcolor=COLORS["panel"])
            elif klass == "Canvas":
                if getattr(child, '_is_rounded_button', False) or getattr(child, '_is_rounded_entry', False):
                    child.configure(bg=child.master.cget('bg'))
                if (
                    child not in (getattr(self, "preview_canvas", None), getattr(self, "theme_banner", None))
                    and not getattr(child, "_keep_canvas_style", False)
                ):
                    child.configure(bg=COLORS["panel"], highlightthickness=0)
            self._polish_widgets(child)

    def _build_start_tab(self) -> None:
        self.start_tab.columnconfigure(0, weight=3, minsize=310, uniform="start_columns")
        self.start_tab.columnconfigure(1, weight=2, minsize=280, uniform="start_columns")
        self.start_tab.rowconfigure(0, weight=1)

        left_shell = Frame(self.start_tab, bg=COLORS["panel"])
        left_shell.grid(row=0, column=0, sticky="nsew", padx=(0, 18))
        left_shell.columnconfigure(0, weight=1)
        left_shell.rowconfigure(0, weight=1)
        self.start_left_canvas = Canvas(left_shell, highlightthickness=0, bg=COLORS["panel"])
        self.start_left_scrollbar = Canvas(left_shell, width=7, bg=COLORS["panel"],
                                           highlightthickness=0, cursor="sb_v_double_arrow")
        self.start_left_canvas.configure(yscrollcommand=self._update_start_scrollbar)
        self.start_left_canvas.grid(row=0, column=0, sticky="nsew")
        self.start_left_scrollbar.grid(row=0, column=1, sticky="ns", padx=(5, 0))
        self._start_scroll_range = (0.0, 1.0)
        self.start_left_scrollbar.bind("<Configure>", lambda _event: self._draw_start_scrollbar())
        self.start_left_scrollbar.bind("<Button-1>", self._drag_start_scrollbar)
        self.start_left_scrollbar.bind("<B1-Motion>", self._drag_start_scrollbar)
        left = Frame(self.start_left_canvas, bg=COLORS["panel"], padx=4, pady=4)
        left_window = self.start_left_canvas.create_window((0, 0), window=left, anchor="nw")
        left.bind("<Configure>", lambda _event: self.start_left_canvas.configure(scrollregion=self.start_left_canvas.bbox("all")))
        self.start_left_canvas.bind(
            "<Configure>",
            lambda event: self.start_left_canvas.itemconfigure(left_window, width=max(1, event.width)),
        )

        right = Frame(self.start_tab, bg=COLORS["panel"])
        right.grid(row=0, column=1, sticky="nsew")

        self.task_list = Listbox(self.start_tab, height=1, activestyle="none", font=(FONT_FAMILY, 10))
        self.task_list.bind("<<ListboxSelect>>", lambda _event: self._show_selected_task())

        Label(left, text="快捷任务", font=(FONT_FAMILY, 14, "bold"), bg=COLORS["panel"]).pack(anchor="w", pady=(2, 2))
        Label(
            left, text="点击任务直接运行；按住左侧三点拖动排序。",
            fg=COLORS["muted"], bg=COLORS["panel"],
        ).pack(anchor="w", pady=(0, 10))

        action_list = Frame(left, bg=COLORS["panel"])
        action_list.pack(fill=X)
        self._start_action_cards = {}
        self._start_action_order = self._load_start_action_order()
        self._make_start_action_card(action_list, "weekly_rewards", "周常拿满奖励", "完成周常并领取可用奖励",
                                     lambda: self._start_enabled_real(15), "weekly")
        self._make_start_action_card(action_list, "weekly_astrite", "周常拿满星声", "完成本周星声目标",
                                     lambda: self._start_enabled_real(13), "weekly")
        self._make_start_action_card(
            action_list, "daily", "一键日常（2轮双倍）", "先选择无音区，再运行两轮挑战",
            self._start_daily_routine, "daily", with_zone=True,
        )
        self._make_start_action_card(action_list, "combat_4c_10", "4C刷取（10次）", "固定 10 轮战斗与吸收",
                                     lambda: self._start_named_task_real("4C刷取", 10), "combat_4c")
        self._make_start_action_card(action_list, "combat_4c_custom", "4C刷取（自定义次数）", "运行前填写本次循环次数",
                                     self._start_custom_4c, "combat_4c")
        self._make_start_action_card(action_list, "tower", "深塔挑战", "靠近光球后开战，挑战成功后停止",
                                     self._start_tower_challenge, "tower")
        self._repack_start_action_cards()
        Label(left, text="提示：将鼠标放在无音区或键位上滚动滚轮，可快速切换选项。",
              fg=COLORS["muted"], bg=COLORS["panel"],
              wraplength=430, justify=LEFT).pack(anchor="w", pady=(1, 4))
        self._rounded_button(left, f"停止当前任务（{STOP_HOTKEY_LABEL}）", self._stop).pack(fill=X, pady=(3, 11))

        Label(left, text="桌宠", font=(FONT_FAMILY, 13, "bold"), bg=COLORS["panel"]).pack(anchor="w", pady=(13, 0))
        pet_shell, pet_box = self._rounded_panel(left, padding=12)
        pet_shell.pack(fill=X, pady=(8, 4))
        pet_box.configure(padx=14)
        self._rounded_button(pet_box, "显示 / 隐藏", self._toggle_desktop_pet, width=110).pack(side=RIGHT)
        Label(pet_box, text=self.pet_name, font=(FONT_FAMILY, 11, "bold"),
              bg=COLORS["panel_alt"]).pack(side=LEFT)
        Label(
            left,
            text=f"提示：右键{self.pet_name}可直接执行一键操作",
            fg=COLORS["muted"],
            bg=COLORS["panel"],
            wraplength=420,
            justify=LEFT,
        ).pack(anchor="w", pady=(0, 10))

        Label(left, text="任务设置", font=(FONT_FAMILY, 13, "bold"), bg=COLORS["panel"]).pack(anchor="w", pady=(12, 0))
        settings_shell, quick_settings = self._rounded_panel(left, padding=12)
        settings_shell.pack(fill=X, pady=(8, 10))
        quick_settings.configure(padx=14)
        key_row = Frame(quick_settings, bg=COLORS["panel_alt"])
        key_row.pack(fill=X, pady=(0, 8))
        key_row.columnconfigure(0, weight=1)
        key_row.columnconfigure(1, weight=1)
        skill_field = Frame(key_row, bg=COLORS["panel_alt"])
        skill_field.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        ultimate_field = Frame(key_row, bg=COLORS["panel_alt"])
        ultimate_field.grid(row=0, column=1, sticky="ew", padx=(8, 0))
        Label(skill_field, text="4C 技能键位", bg=COLORS["panel_alt"], anchor="w").pack(fill=X)
        combat_key_picker = self._rounded_picker(
            skill_field, self.combat_skill_key,
            ("E", "Q", "R", "T", "鼠标侧键1", "鼠标侧键2"),
            self._autosave_combat_settings, editable=True)
        combat_key_picker.pack(fill=X, pady=(3, 0))
        Label(ultimate_field, text="4C 大招键位", bg=COLORS["panel_alt"], anchor="w").pack(fill=X)
        ultimate_key_picker = self._rounded_picker(
            ultimate_field, self.combat_ultimate_key,
            ("R", "E", "Q", "T", "鼠标侧键1", "鼠标侧键2"),
            self._autosave_combat_settings, editable=True)
        ultimate_key_picker.pack(fill=X, pady=(3, 0))
        Label(quick_settings, text="角色位和战斗动作请在“战斗排轴”页设置。",
              fg=COLORS["muted"], bg=COLORS["panel_alt"], wraplength=420,
              justify=LEFT).pack(anchor="w", pady=(1, 5))
        Checkbutton(
            quick_settings, text="任务正常完成后自动关机", variable=self.auto_shutdown_enabled,
            command=self._apply_auto_shutdown_setting, bg=COLORS["panel_alt"],
            activebackground=COLORS["panel_alt"],
        ).pack(anchor="w", pady=(0, 5))
        Label(
            quick_settings,
            text="更改后自动保存；手动停止、执行失败和预演不会关机。",
            fg=COLORS["muted"], bg=COLORS["panel_alt"],
            wraplength=420, justify=LEFT,
        ).pack(anchor="w")

        self.start_left_canvas.bind("<MouseWheel>", lambda event: self._scroll_start_left(event), add="+")
        self._bind_start_left_mousewheel(left)

        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)
        preview_shell, preview_card = self._rounded_panel(right)
        preview_shell.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        Label(preview_card, text="实时截图", font=(FONT_FAMILY, 12, "bold"),
              bg=COLORS["panel_alt"]).pack(anchor="w", pady=(0, 9))
        self.preview_canvas = Canvas(preview_card, width=300, height=169,
                                     bg=COLORS["panel"], highlightthickness=0)
        self.preview_canvas.pack(anchor="center")
        self.preview_canvas.bind("<Configure>", self._resize_preview_canvas)
        preview_card.bind("<Configure>", self._resize_preview_canvas)

        log_shell, log_card = self._rounded_panel(right)
        log_shell.grid(row=1, column=0, sticky="nsew")
        Label(log_card, text="运行状态", font=(FONT_FAMILY, 12, "bold"),
              bg=COLORS["panel_alt"]).pack(anchor="w", pady=(0, 9))
        Label(log_card, textvariable=self.status, fg=COLORS["primary"],
              bg=COLORS["panel_alt"], anchor="w").pack(fill=X, pady=(0, 8))
        self.detail = Text(log_card, height=8, wrap="word", font=(FONT_FAMILY, 10), relief="flat", bd=0)
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
        self._ui_button(container, text="知道了", command=window.destroy).pack(anchor="e", pady=(12, 0))
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

    def _rotation_current_preset(self) -> dict:
        return next(preset for preset in self.rotation_store["presets"]
                    if preset["id"] == self._rotation_editing_id)

    def _rotation_edit_status(self, message: str) -> str:
        worker = getattr(self, 'worker', None)
        if worker is not None and worker.is_alive():
            message += " 当前任务使用启动时的轴，此修改在下次启动生效。"
        return message

    def _rotation_preset_names(self) -> list[str]:
        return [preset["name"] for preset in self.rotation_store["presets"]]

    def _rotation_schedule_time(self, slot: int) -> None:
        if self._rotation_refreshing_times:
            return
        previous = self._rotation_time_jobs.pop(slot, None)
        if previous:
            self.root.after_cancel(previous)
        preset_id = self._rotation_editing_id
        self._rotation_time_jobs[slot] = self.root.after(
            500, lambda: self._rotation_commit_time(slot, preset_id))

    def _rotation_commit_time(self, slot: int, preset_id: str | None = None) -> bool:
        if preset_id and preset_id != self._rotation_editing_id:
            return False
        pending = self._rotation_time_jobs.pop(slot, None)
        if pending:
            self.root.after_cancel(pending)
        if self._rotation_refreshing_times:
            return False
        text = self._rotation_time_fields[slot].get().strip()
        try:
            # Empty strings and a lone decimal point are valid editing drafts.
            proposal = json.loads(json.dumps(self.rotation_store, ensure_ascii=False))
            preset = next(p for p in proposal["presets"] if p["id"] == self._rotation_editing_id)
            preset["slot_times"][str(slot)] = float(text)
            checked = validate_store(proposal)
            save_store(COMBAT_PRESETS_CONFIG, checked)
        except (ValueError, OSError) as exc:
            message = "请输入 0.2～120 秒，正在输入的内容已保留。" if isinstance(exc, ValueError) else str(exc)
            self.rotation_status.set(f"{SLOT_NAMES[slot]}驻场时间未保存：{message}")
            return False
        self.rotation_store = checked
        self.rotation_status.set(self._rotation_edit_status(f"{SLOT_NAMES[slot]}驻场 {float(text):g} 秒，已自动保存。"))
        return True

    def _rotation_cancel_time_jobs(self, event) -> None:
        if event.widget is not self.rotation_tab:
            return
        for job in self._rotation_time_jobs.values():
            self.root.after_cancel(job)
        self._rotation_time_jobs.clear()

    def _rotation_save(self) -> bool:
        try:
            proposal = json.loads(json.dumps(self.rotation_store, ensure_ascii=False))
            preset = next(item for item in proposal["presets"]
                          if item["id"] == self._rotation_editing_id)
            preset["slot_times"] = {str(slot): float(variable.get())
                                    for slot, variable in self._rotation_time_fields.items()}
            checked = validate_store(proposal)
            save_store(COMBAT_PRESETS_CONFIG, checked)
        except (ValueError, OSError, StopIteration) as exc:
            messagebox.showerror("战斗排轴未保存", str(exc), parent=self.root)
            return False
        self.rotation_store = checked
        self.rotation_status.set(self._rotation_edit_status("已保存；各模式使用下方分配的预设。"))
        return True

    def _rotation_switch(self) -> None:
        selected = self.rotation_choice.get()
        current = self._rotation_current_preset()
        if selected == current["name"]:
            return
        if not self._rotation_save():
            self.rotation_choice.set(current["name"])
            return
        preset = next((p for p in self.rotation_store["presets"] if p["name"] == selected), None)
        if preset is None:
            return
        self.rotation_store["active"] = preset["id"]
        save_store(COMBAT_PRESETS_CONFIG, self.rotation_store)
        self._rotation_editing_id = preset["id"]
        self._rotation_rebuild_cards()

    def _rotation_seed_window(self, title: str, prompt: str):
        self._close_rounded_picker()
        dialog = Toplevel(self.root)
        dialog.withdraw()
        dialog.title(title)
        dialog.transient(self.root)
        dialog.configure(bg=COLORS["app_bg"])
        shell, body = self._rounded_panel(dialog, padding=18, color=COLORS["panel"],
                                          outer_color=COLORS["app_bg"])
        shell.pack(fill=BOTH, expand=True, padx=14, pady=14)
        hint = Label(body, text=prompt, bg=COLORS["panel"], fg=COLORS["muted"],
                     wraplength=650, justify=LEFT, anchor="w")
        body.columnconfigure(0, weight=1)
        body.rowconfigure(1, weight=1)
        hint.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        hint.bind("<Configure>", lambda e: hint.configure(wraplength=max(160, e.width-4)))
        text_shell, text_body = self._rounded_panel(body, padding=10)
        text_shell.grid(row=1, column=0, sticky="nsew")
        scrollbar = self._thin_scrollbar(text_body, orient="vertical")
        text = Text(text_body, height=4, width=52, wrap="char", font=(MONO_FONT, 10),
                    bg=COLORS["panel_alt"], fg=COLORS["text"], insertbackground=COLORS["text"],
                    relief="flat", bd=0, highlightthickness=0, yscrollcommand=scrollbar.set)
        scrollbar.configure(command=text.yview)
        scrollbar.pack(side=RIGHT, fill="y")
        text.pack(side=LEFT, fill=BOTH, expand=True, padx=4, pady=4)
        def select_all(_event):
            text.tag_add("sel", "1.0", "end-1c")
            return "break"
        text.bind("<Control-a>", select_all)
        def close(_event=None):
            self._close_rounded_picker()
            dialog.destroy()
        dialog.bind("<Escape>", close)
        dialog.protocol("WM_DELETE_WINDOW", close)
        dialog.minsize(520, 440)
        controls = Frame(body, bg=COLORS["panel"])
        controls.grid(row=2, column=0, sticky="ew")
        def show_centered():
            if not dialog.winfo_exists():
                return
            width = min(760, max(520, self.root.winfo_width()-40))
            height = 520
            left, top = self.root.winfo_vrootx(), self.root.winfo_vrooty()
            right, bottom = left+self.root.winfo_vrootwidth(), top+self.root.winfo_vrootheight()
            # geometry() positions the decorated window; use the owner's frame
            # origin rather than its client origin to avoid a title-bar offset.
            x = self.root.winfo_x() + (self.root.winfo_width()-width)//2
            y = self.root.winfo_y() + (self.root.winfo_height()-height)//2
            x = max(left, min(x, right-width))
            y = max(top, min(y, bottom-height-32))
            dialog.geometry(f"{width}x{height}+{x}+{y}")
            dialog.deiconify()
            dialog.lift()
            text.focus_set()
        dialog.after_idle(show_centered)
        return dialog, controls, text

    def _rotation_export_seed(self):
        if not self._rotation_save():
            return None
        seed = export_seed(self._rotation_current_preset())
        shared = decode_seed(seed)
        dialog, body, text = self._rotation_seed_window(
            "生成战斗轴种子",
            "种子包含当前预设的角色顺序、驻场时间及全部模块参数。复制给对方后，可在支持种子的版本中导入；无需联网。",
        )
        text.insert("1.0", seed)
        text.configure(state="disabled")
        status = StringVar(value=f"种子标识：{shared['share_id']}")
        status_label = Label(body, textvariable=status, bg=COLORS["panel"], fg=COLORS["muted"],
                             wraplength=650, justify=LEFT, anchor="w")
        status_label.pack(fill=X, pady=10)
        status_label.bind("<Configure>", lambda e: status_label.configure(wraplength=max(160, e.width-4)))
        footer = Frame(body, bg=COLORS["panel"])
        footer.pack(fill=X)
        def copy():
            try:
                self.root.clipboard_clear()
                self.root.clipboard_append(seed)
            except TclError:
                status.set("复制失败，请在种子框中选中文字后手动复制。")
                return
            status.set("已复制完整种子，可以发送给对方。")
        self._ui_button(footer, text="关闭", command=dialog.destroy).pack(side=RIGHT)
        self._ui_button(footer, text="复制种子", command=copy, style="Primary.TButton").pack(side=RIGHT, padx=8)
        return dialog

    def _rotation_import_seed(self):
        dialog, body, text = self._rotation_seed_window(
            "导入战斗轴种子",
            "粘贴种子即可直接导入，也可先预览。保留原轴名字并添加“（导入）”，重复导入加编号；键位沿用你的任务设置。",
        )
        status = StringVar(value="等待粘贴种子。")
        summary = Label(body, textvariable=status, bg=COLORS["panel"], fg=COLORS["muted"],
                        wraplength=650, justify=LEFT, anchor="w")
        summary.pack(fill=X, pady=10)
        summary.bind("<Configure>", lambda e: summary.configure(wraplength=max(160, e.width-4)))
        mode_row = Frame(body, bg=COLORS["panel"])
        mode_row.pack(fill=X, pady=(0, 10))
        Label(mode_row, text="导入后用于", bg=COLORS["panel"], fg=COLORS["text"]).pack(side=LEFT, padx=(0, 8))
        choices = {"仅新增预设": (), "4C 刷取": ("combat_4c",), "一键日常": ("daily",),
                   "4C 与日常": ("combat_4c", "daily"), "深塔挑战": ("tower",),
                   "所有战斗模式": tuple(COMBAT_MODES)}
        mode = StringVar(value="仅新增预设")
        self._rounded_picker(mode_row, mode, list(choices), lambda: None).pack(fill=X, expand=True)
        footer = Frame(body, bg=COLORS["panel"])
        footer.pack(fill=X)

        def preview():
            try:
                seed = text.get("1.0", "end-1c")
                preset = decode_seed(seed)
            except ValueError as exc:
                status.set(str(exc))
                return
            order = " → ".join(SLOT_NAMES[n] for n in preset["slot_order"])
            columns = "；".join(f"{SLOT_NAMES[n]} {preset['slot_times'][str(n)]:g}秒 / "
                                f"{sum(m['slot'] == n for m in preset['modules'])}个模块" for n in preset["slot_order"])
            status.set(f"{preset['name']}\n角色顺序：{order}\n{columns}")
            accept.configure(state="normal")

        def apply():
            seed = text.get("1.0", "end-1c")
            try:
                decode_seed(seed)
            except ValueError as exc:
                status.set(f"导入失败：{exc}")
                return
            if not self._rotation_save():
                return
            try:
                checked, preset_id = import_seed(self.rotation_store, seed, modes=choices[mode.get()])
                save_store(COMBAT_PRESETS_CONFIG, checked)
            except (ValueError, OSError) as exc:
                status.set(f"导入失败：{exc}")
                return
            self._close_rounded_picker()
            self.rotation_store = checked
            self._rotation_editing_id = preset_id
            preset = self._rotation_current_preset()
            self.rotation_choice.set(preset["name"])
            self._rotation_refresh_picker()
            self._rotation_rebuild_cards()
            self.rotation_status.set(f"已导入：{preset['name']}。" +
                                     ("请在模式选择中指定使用此预设。" if not choices[mode.get()] else f"已用于{mode.get()}。"))
            dialog.destroy()

        accept = self._ui_button(footer, text="导入预设", command=apply, style="Primary.TButton")
        accept.configure(state="disabled")
        accept.pack(side=RIGHT)
        self._ui_button(footer, text="预览种子", command=preview).pack(side=RIGHT, padx=8)
        self._ui_button(footer, text="取消", command=dialog.destroy).pack(side=LEFT)
        def changed(_event):
            if not text.edit_modified():
                return
            text.edit_modified(False)
            accept.configure(state="normal" if text.get("1.0", "end-1c").strip() else "disabled")
            status.set("种子内容已更新，可直接导入，也可点击预览查看内容。")
        text.edit_modified(False)
        text.bind("<<Modified>>", changed)
        text.focus_set()
        return dialog

    def _rotation_new(self) -> None:
        if not self._rotation_save():
            return
        if len(self.rotation_store["presets"]) >= 30:
            messagebox.showinfo("预设数量已满", "最多可以保存 30 个战斗预设。", parent=self.root)
            return
        name = self._ask_text("新建战斗排轴", "输入新预设名称：", parent=self.root)
        if not name:
            return
        name = name.strip()
        if not name or len(name) > 40 or name in self._rotation_preset_names():
            messagebox.showerror("名称不可用", "请输入不超过40字的独立名称。", parent=self.root)
            return
        previous_store = json.loads(json.dumps(self.rotation_store, ensure_ascii=False))
        modules = json.loads(json.dumps(self._rotation_current_preset()["modules"]))
        for item in modules:
            item["id"] = secrets.token_hex(6)
        preset = {"id": secrets.token_hex(6), "name": name, "modules": modules,
                  "slot_order": list(self._rotation_current_preset()["slot_order"]),
                  "slot_times": dict(self._rotation_current_preset()["slot_times"])}
        self.rotation_store["presets"].append(preset)
        self.rotation_store["active"] = preset["id"]
        self._rotation_editing_id = preset["id"]
        if not self._rotation_save_new_structure():
            self.rotation_store = previous_store
            self._rotation_editing_id = previous_store["active"]
            return
        self.rotation_choice.set(name)
        self._rotation_refresh_picker()
        self._rotation_rebuild_cards()

    def _rotation_save_new_structure(self) -> bool:
        try:
            self.rotation_store = validate_store(self.rotation_store)
            save_store(COMBAT_PRESETS_CONFIG, self.rotation_store)
        except (ValueError, OSError) as exc:
            messagebox.showerror("保存失败", str(exc), parent=self.root)
            return False
        return True

    def _rotation_rename(self) -> None:
        if not self._rotation_save():
            return
        preset = self._rotation_current_preset()
        name = self._ask_text("重命名战斗排轴", "输入预设名称：",
                                      initialvalue=preset["name"], parent=self.root)
        if not name:
            return
        name = name.strip()
        if not name or len(name) > 40 or name in (p["name"] for p in self.rotation_store["presets"] if p is not preset):
            messagebox.showerror("名称不可用", "请输入不超过40字的独立名称。", parent=self.root)
            return
        preset["name"] = name
        self._rotation_save_new_structure()
        self.rotation_choice.set(name)
        self._rotation_refresh_picker()

    def _rotation_delete(self) -> None:
        if len(self.rotation_store["presets"]) <= 1:
            messagebox.showinfo("保留预设", "至少需要保留一个战斗预设。", parent=self.root)
            return
        removed_id = self._rotation_editing_id
        self.rotation_store["presets"] = [p for p in self.rotation_store["presets"]
                                          if p["id"] != removed_id]
        preset = self.rotation_store["presets"][0]
        self._rotation_editing_id = preset["id"]
        self.rotation_store["active"] = preset["id"]
        for mode, assigned in self.rotation_store["modes"].items():
            if assigned == removed_id:
                self.rotation_store["modes"][mode] = preset["id"]
        if self._rotation_save_new_structure():
            self.rotation_choice.set(preset["name"])
            self._rotation_refresh_picker()
            self._rotation_rebuild_cards()

    def _rotation_refresh_picker(self) -> None:
        # Rebuild the themed picker when the available preset names change.
        self.rotation_picker.destroy()
        self.rotation_picker = self._rounded_picker(self.rotation_picker_parent,
                                                   self.rotation_choice,
                                                   self._rotation_preset_names(),
                                                   self._rotation_switch)
        self.rotation_picker.pack(side=LEFT, fill=X, expand=True, padx=(0, 8))
        self._rotation_refresh_modes()

    def _rotation_refresh_modes(self) -> None:
        if not hasattr(self, "rotation_modes_parent"):
            return
        for child in self.rotation_modes_parent.winfo_children():
            child.destroy()
        self.rotation_mode_choices = {}
        for column, (mode, title) in enumerate(COMBAT_MODES.items()):
            box = Frame(self.rotation_modes_parent, bg=COLORS["panel_alt"])
            box.grid(row=0, column=column, sticky="ew", padx=(0, 8) if column == 0 else (8, 0))
            self.rotation_modes_parent.columnconfigure(column, weight=1, uniform="rotation_modes")
            heading = Label(box, text=title + "使用的预设", bg=COLORS["panel_alt"],
                            fg=COLORS["text"], wraplength=240, justify=LEFT, anchor="w")
            heading.pack(fill=X, pady=(0, 4))
            heading.bind("<Configure>", lambda e, w=heading: w.configure(wraplength=max(80, e.width-4)))
            selected = next(p["name"] for p in self.rotation_store["presets"]
                            if p["id"] == self.rotation_store["modes"][mode])
            variable = StringVar(value=selected)
            self.rotation_mode_choices[mode] = variable
            self._rounded_picker(box, variable, self._rotation_preset_names(),
                                 lambda selected_mode=mode: self._rotation_assign_mode(selected_mode)).pack(fill=X)

    def _rotation_assign_mode(self, mode: str) -> None:
        if not self._rotation_save():
            self._rotation_refresh_modes()
            return
        preset = next(p for p in self.rotation_store["presets"]
                      if p["name"] == self.rotation_mode_choices[mode].get())
        previous = self.rotation_store["modes"][mode]
        self.rotation_store["modes"][mode] = preset["id"]
        if not self._rotation_save_new_structure():
            self.rotation_store["modes"][mode] = previous
            self._rotation_refresh_modes()
            return
        self.rotation_status.set(f"{COMBAT_MODES[mode]}已选用：{preset['name']}。")

    def _rotation_add(self, slot: int = 1) -> None:
        if not self._rotation_save():
            return
        kind = next(key for key, spec in ACTION_SPECS.items()
                    if spec[0] == self._rotation_add_choices[slot].get())
        modules = self._rotation_current_preset()["modules"]
        if len(modules) >= 100:
            messagebox.showinfo("模块数量已满", "每个预设最多添加 100 个模块。", parent=self.root)
            return
        if kind == "idle_attack" and any(m["kind"] == kind and m["slot"] == slot for m in modules):
            messagebox.showinfo("空闲普攻已存在", "每列只需一个空闲普攻模块。", parent=self.root)
            return
        modules.append(new_module(kind, slot))
        self._rotation_save_new_structure()
        self._rotation_rebuild_cards()

    def _rotation_remove(self, module_id: str) -> None:
        if not self._rotation_save():
            return
        preset = self._rotation_current_preset()
        if len(preset["modules"]) <= 1:
            messagebox.showinfo("保留模块", "一个预设至少需要一个模块。", parent=self.root)
            return
        preset["modules"] = [m for m in preset["modules"] if m["id"] != module_id]
        self._rotation_save_new_structure()
        self._rotation_rebuild_cards()

    def _rotation_edit(self, module_id: str) -> None:
        if not self._rotation_save():
            return
        item = next(m for m in self._rotation_current_preset()["modules"] if m["id"] == module_id)
        dialog = Toplevel(self.root)
        dialog.title("修改模块 · " + ACTION_SPECS[item["kind"]][0])
        dialog.transient(self.root)
        dialog.configure(bg=COLORS["panel"])
        body = Frame(dialog, bg=COLORS["panel"], padx=20, pady=16)
        body.pack(fill=BOTH, expand=True)
        value = StringVar(value=str(item["value"]))
        interval = StringVar(value=str(item["interval"]))
        slot = StringVar(value=SLOT_NAMES[item["slot"]])
        kind = item["kind"]
        caption = {"idle_attack": "每多少下普攻穿插一次重击", "attack_count": "普攻次数",
                   "jump_attack": "跳跃后普攻次数", "attack_seconds": "普攻秒数",
                   "heavy_count": "重击次数", "wait": "等待秒数", "approach": "向前移动秒数"}.get(kind, "执行次数")
        Label(body, text=ACTION_SPECS[kind][1], fg=COLORS["muted"], bg=COLORS["panel"],
              wraplength=380, justify=LEFT).pack(anchor="w", pady=(0, 12))
        Label(body, text="角色位", bg=COLORS["panel"], fg=COLORS["text"]).pack(anchor="w")
        self._rounded_picker(body, slot, list(SLOT_NAMES.values()), lambda: None).pack(fill=X, pady=(4, 10))
        for title, variable in ([] if kind in {"skill", "ultimate", "echo"} else [(caption, value)]) + ([("循环间隔（秒）", interval)]
                                                    if kind in {"skill", "ultimate", "echo", "approach"} else []):
            Label(body, text=title, bg=COLORS["panel"], fg=COLORS["text"],
                  wraplength=380, justify=LEFT).pack(anchor="w")
            self._rounded_entry(body, textvariable=variable, font=(FONT_FAMILY, 11), bg=COLORS["panel_alt"],
                  fg=COLORS["text"], insertbackground=COLORS["text"], relief="flat",
                  highlightthickness=1, highlightbackground=COLORS["line_soft"]).pack(fill=X, ipady=7, pady=(4, 12))

        def apply():
            try:
                for number in SLOT_NAMES:
                    self._rotation_commit_time(number)
                proposal = json.loads(json.dumps(self.rotation_store, ensure_ascii=False))
                target = next((m for p in proposal["presets"] for m in p["modules"] if m["id"] == module_id), None)
                if target is None:
                    raise ValueError("该模块已经被移除，请关闭后重新选择。")
                target.update(value=1 if kind in {"skill", "ultimate", "echo"} else float(value.get()), interval=float(interval.get()),
                              slot=next(n for n, name in SLOT_NAMES.items() if name == slot.get()))
                checked = validate_store(proposal)
                save_store(COMBAT_PRESETS_CONFIG, checked)
            except (ValueError, OSError) as exc:
                messagebox.showerror("参数不可用", str(exc), parent=dialog)
                return
            self.rotation_store = checked
            dialog.destroy()
            self._rotation_rebuild_cards()
            self.rotation_status.set("模块已保存。")

        footer = Frame(body, bg=COLORS["panel"])
        footer.pack(fill=X)
        self._rounded_button(footer, "移除", lambda: (dialog.destroy(), self._rotation_remove(module_id)), width=80).pack(side=LEFT)
        self._rounded_button(footer, "保存", apply, width=80, primary=True).pack(side=RIGHT)
        self._rounded_button(footer, "取消", dialog.destroy, width=80).pack(side=RIGHT, padx=8)
        dialog.update_idletasks()
        width, height = max(440, dialog.winfo_reqwidth()), max(300, dialog.winfo_reqheight())
        dialog.minsize(width, height)
        dialog.geometry(f"{width}x{height}+{self.root.winfo_rootx()+60}+{self.root.winfo_rooty()+60}")
        dialog.bind("<Escape>", lambda _event: dialog.destroy())

    def _rotation_rebuild_cards(self) -> None:
        for column in self._rotation_columns.values():
            for child in column["list"].winfo_children():
                child.destroy()
        self._rotation_cards = {}
        preset = self._rotation_current_preset()
        self._rotation_repack_columns()
        if getattr(self, "_rotation_time_preset_id", None) != preset["id"]:
            self._rotation_refreshing_times = True
            try:
                for slot, variable in self._rotation_time_fields.items():
                    variable.set(str(preset.get("slot_times", {}).get(str(slot), 5)))
                self._rotation_time_preset_id = preset["id"]
            finally:
                self._rotation_refreshing_times = False
        for item in preset["modules"]:
            self._rotation_make_card(item)

    def _rotation_drop(self, module_id, slot, index):
        if not self._rotation_save():
            return
        modules = self._rotation_current_preset()["modules"]
        item = next(m for m in modules if m["id"] == module_id)
        if item["kind"] == "idle_attack" and any(m["id"] != module_id and m["slot"] == slot
                                                  and m["kind"] == "idle_attack" for m in modules):
            self.rotation_status.set("该列已有空闲普攻，拖动未保存。")
            return
        modules.remove(item)
        item["slot"] = slot
        targets = [m for m in modules if m["slot"] == slot]
        if index < len(targets):
            modules.insert(modules.index(targets[index]), item)
        else:
            modules.append(item)
        self._rotation_save_new_structure()
        self._rotation_rebuild_cards()

    def _rotation_make_card(self, item: dict) -> None:
        slot, module_id = item["slot"], item["id"]
        column = self._rotation_columns[slot]
        card = Canvas(column["list"], height=90, bg=COLORS["panel"], bd=0, highlightthickness=0)
        card._keep_canvas_style = True
        card._drag_ghost = None
        card.pack(fill=X, pady=(0, 8))
        self._rotation_cards[module_id] = card
        title_font = tkfont.Font(root=self.root, family=FONT_FAMILY, size=11, weight="bold")
        detail_font = tkfont.Font(root=self.root, family=FONT_FAMILY, size=9)
        title = ACTION_SPECS[item["kind"]][0]
        kind, value = item["kind"], item["value"]
        detail = {"idle_attack": f"空闲普攻；每 {value:g} 下重击一次", "attack_count": f"普攻 {value:g} 次",
                  "jump_attack": f"跳跃后普攻 {value:g} 次", "heavy_count": f"长按重击 {value:g} 次",
                  "attack_seconds": f"普攻 {value:g} 秒", "wait": f"等待 {value:g} 秒",
                  "approach": f"前进 {value:g} 秒"}.get(kind, f"每 {item['interval']:g} 秒循环触发")

        def paint(target, width, height, hover=False, placeholder=False):
            target.delete("all")
            self._paint_rounded_card(target, 1, 1, width-2, height-2, 14,
                                     COLORS["primary"] if hover else COLORS["line_soft"])
            self._paint_rounded_card(target, 2, 2, width-3, height-3, 13, COLORS["panel_alt"])
            if placeholder:
                target.create_text(width/2, height/2, text="拖动中", fill=COLORS["muted"])
                return
            for y in (25, 31, 37):
                target.create_oval(17, y, 20, y+3, fill=COLORS["muted"], outline="")
            target.create_text(36, 16, text=title, anchor="nw", width=max(60, width-102),
                               font=title_font, fill=COLORS["text"], tags="title")
            title_bottom = target.bbox("title")[3]
            target.create_text(36, title_bottom+4, text=detail, anchor="nw", width=max(60, width-82),
                               font=detail_font, fill=COLORS["muted"], tags="detail")
            target.create_text(width-17, 31, text="›", font=(FONT_FAMILY, 20), fill=COLORS["text"])
            target.create_text(width-46, 31, text="×", font=(FONT_FAMILY, 15),
                               fill=COLORS["muted"], tags="remove")

        def draw(hover=False):
            width = max(180, card.winfo_width())
            height = int(card.cget("height"))
            paint(card, width, height, hover, getattr(card, "_drag_started", False))
            if not getattr(card, "_drag_started", False):
                needed = max(84, card.bbox("detail")[3]+16)
                if needed != height:
                    card.configure(height=needed)
                    paint(card, width, needed, hover)

        def over_remove(event):
            return card.winfo_width()-60 <= event.x < card.winfo_width()-30 and 12 <= event.y <= 50

        def press(event):
            card._press_pending = True
            card._remove_armed = over_remove(event)
            card._edit_armed = (not card._remove_armed and 30 <= event.x < card.winfo_width()
                                and 0 <= event.y < card.winfo_height())
            card._drag_handle = event.x < 30
            card._drag_started = False
            card._drag_origin = (event.x_root, event.y_root)
            card._drag_offset = (event.x, event.y)
            card._drop_target = None

        def motion(event):
            if not getattr(card, "_press_pending", False):
                return
            distance = max(abs(event.x_root-card._drag_origin[0]), abs(event.y_root-card._drag_origin[1]))
            if distance >= 5:
                card._edit_armed = False
                card._remove_armed = False
            if not getattr(card, "_drag_handle", False):
                return
            if not card._drag_started and distance < 5:
                return
            if not card._drag_started:
                ghost = Toplevel(self.root)
                ghost.withdraw()
                ghost.overrideredirect(True)
                ghost.attributes("-topmost", True)
                ghost.attributes("-alpha", 0.93)
                try:
                    ghost.attributes("-disabled", True)
                except TclError:
                    pass
                width, height = card.winfo_width(), card.winfo_height()
                preview = Canvas(ghost, width=width, height=height, bg=COLORS["panel"], highlightthickness=0)
                preview.pack()
                paint(preview, width, height, True)
                card._drag_ghost = ghost
                card._drag_started = True
                card._drop_marker = Frame(self.rotation_tab, bg=COLORS["primary"], height=3)
                card._drag_bindings = [(seq, self.root.bind(seq, callback, add="+")) for seq, callback in
                                       (("<B1-Motion>", motion), ("<ButtonRelease-1>", release), ("<Escape>", release))]
                draw()
            ox, oy = card._drag_offset
            card._drag_ghost.geometry(f"+{event.x_root-ox}+{event.y_root-oy}")
            card._drag_ghost.deiconify()
            target_slot = min(self._rotation_columns, key=lambda n: abs(event.x_root -
                               (self._rotation_columns[n]["canvas"].winfo_rootx()+self._rotation_columns[n]["canvas"].winfo_width()/2)))
            target = self._rotation_columns[target_slot]
            canvas = target["canvas"]
            top = canvas.winfo_rooty()
            if event.y_root < top+25:
                canvas.yview_scroll(-1, "units")
            elif event.y_root > top+canvas.winfo_height()-25:
                canvas.yview_scroll(1, "units")
            candidates = [m for m in self._rotation_current_preset()["modules"]
                          if m["slot"] == target_slot and m["id"] != module_id]
            index = len(candidates)
            marker_y = top
            for i, other in enumerate(candidates):
                other_card = self._rotation_cards[other["id"]]
                marker_y = other_card.winfo_rooty()+other_card.winfo_height()+4
                if event.y_root < other_card.winfo_rooty()+other_card.winfo_height()/2:
                    index, marker_y = i, other_card.winfo_rooty()-4
                    break
            card._drop_target = (target_slot, index)
            marker_y = min(max(marker_y, top), top+canvas.winfo_height()-3)
            card._drop_marker.place(x=canvas.winfo_rootx()-self.rotation_tab.winfo_rootx(),
                                    y=marker_y-self.rotation_tab.winfo_rooty(), width=canvas.winfo_width())
            return "break"

        def release(event):
            dragged = getattr(card, "_drag_started", False)
            # Dropdowns close on mouse-down. Their trailing mouse-up can land
            # on a newly exposed card, which must not be treated as a click.
            edit_click = getattr(card, "_press_pending", False) and getattr(card, "_edit_armed", False)
            remove_click = getattr(card, "_press_pending", False) and getattr(card, "_remove_armed", False)
            card._press_pending = False
            card._edit_armed = False
            card._remove_armed = False
            target = getattr(card, "_drop_target", None)
            if card._drag_ghost:
                card._drag_ghost.destroy()
                card._drag_ghost = None
            if hasattr(card, "_drop_marker"):
                card._drop_marker.destroy()
            for seq, binding in getattr(card, "_drag_bindings", []):
                self.root.unbind(seq, binding)
            card._drag_bindings = []
            card._drag_started = False
            card._drag_handle = False
            draw()
            if dragged and target and getattr(event, "keysym", "") != "Escape":
                self._rotation_drop(module_id, *target)
            elif remove_click and not dragged and over_remove(event) and getattr(event, "keysym", "") != "Escape":
                self._rotation_remove(module_id)
            elif (edit_click and not dragged and getattr(event, "keysym", "") != "Escape"
                  and 30 <= event.x < card.winfo_width() and 0 <= event.y < card.winfo_height()):
                self._rotation_edit(module_id)
            return "break"

        card.bind("<Configure>", lambda _event: draw())
        card.bind("<Enter>", lambda _event: draw(True))
        card.bind("<Leave>", lambda _event: draw())
        card._paint_preview = paint
        card.bind("<Motion>", lambda event: card.configure(cursor="hand2" if event.x < 30 or over_remove(event) else "arrow"))
        card.bind("<ButtonPress-1>", press)
        card.bind("<B1-Motion>", motion)
        card.bind("<ButtonRelease-1>", release)
        card.bind("<MouseWheel>", lambda event: (column["canvas"].yview_scroll(-3 if event.delta > 0 else 3, "units"), "break")[-1])
        draw()

    def _rotation_repack_columns(self) -> None:
        order = self._rotation_current_preset().get("slot_order", [1, 2, 3])
        for index, slot in enumerate(order):
            self._rotation_columns[slot]["shell"].grid(
                row=0, column=index, sticky="nsew", padx=(0, 8) if index < 2 else 0)

    def _rotation_drop_column(self, slot: int, index: int) -> None:
        if not self._rotation_save():
            return
        preset = self._rotation_current_preset()
        previous = list(preset["slot_order"])
        order = [number for number in previous if number != slot]
        order.insert(max(0, min(2, index)), slot)
        preset["slot_order"] = order
        if not self._rotation_save_new_structure():
            self._rotation_current_preset()["slot_order"] = previous
            return
        self._rotation_repack_columns()
        self.rotation_status.set(self._rotation_edit_status("角色顺序已保存：" + " → ".join(SLOT_NAMES[n] for n in order) + "。"))

    def _rotation_column_ghost(self, slot: int):
        column = self._rotation_columns[slot]
        shell, header = column["shell"], column["header"]
        ghost = Toplevel(self.root)
        ghost.withdraw()
        ghost.overrideredirect(True)
        ghost.attributes("-topmost", True)
        ghost.attributes("-alpha", 0.93)
        try:
            ghost.attributes("-disabled", True)
        except TclError:
            pass
        width, height = shell.winfo_width(), shell.winfo_height()
        preview = Canvas(ghost, width=width, height=height, bg=COLORS["panel"], highlightthickness=0)
        preview.pack()
        self._paint_rounded_card(preview, 1, 1, width-2, height-2, 14, COLORS["primary"])
        self._paint_rounded_card(preview, 2, 2, width-3, height-3, 13, COLORS["panel"])
        x, y = shell.winfo_rootx(), shell.winfo_rooty()
        heading = Canvas(preview, bg=COLORS["panel"], highlightthickness=0)
        heading.place(x=header.winfo_rootx()-x, y=header.winfo_rooty()-y,
                      width=header.winfo_width(), height=header.winfo_height())
        header._paint_preview(heading, header.winfo_width())
        timing = self._rotation_time_entries[slot].master
        preview.create_text(12, timing.winfo_rooty()-y+timing.winfo_height()/2, anchor="w",
                            text="驻场秒数  " + self._rotation_time_fields[slot].get(),
                            fill=COLORS["muted"], font=(FONT_FAMILY, 10))
        addition = column["addition"]
        preview.create_text(12, addition.winfo_rooty()-y+addition.winfo_height()/2, anchor="w",
                            text=self._rotation_add_choices[slot].get() + "    ＋",
                            fill=COLORS["text"], font=(FONT_FAMILY, 10))
        canvas = column["canvas"]
        listing = Canvas(preview, bg=COLORS["panel"], highlightthickness=0)
        listing.place(x=canvas.winfo_rootx()-x, y=canvas.winfo_rooty()-y,
                      width=canvas.winfo_width(), height=canvas.winfo_height())
        for item in self._rotation_current_preset()["modules"]:
            if item["slot"] != slot:
                continue
            card = self._rotation_cards[item["id"]]
            top = card.winfo_rooty()-canvas.winfo_rooty()
            if top >= canvas.winfo_height() or top+card.winfo_height() <= 0:
                continue
            child = Canvas(listing, bg=COLORS["panel"], highlightthickness=0)
            child.place(x=0, y=top, width=card.winfo_width(), height=card.winfo_height())
            card._paint_preview(child, card.winfo_width(), card.winfo_height())
        return ghost

    def _rotation_make_column_header(self, parent, slot: int):
        title_font = tkfont.Font(root=self.root, family=FONT_FAMILY, size=12, weight="bold")
        header = Canvas(parent, height=title_font.metrics("linespace")+14,
                        bg=COLORS["panel"], highlightthickness=0, bd=0)
        header._keep_canvas_style = True
        header._drag_ghost = None
        header.pack(fill=X)

        def paint(target, width):
            target.delete("all")
            center = (title_font.metrics("linespace")+14)/2
            for offset in (-6, 0, 6):
                target.create_oval(10, center+offset-1, 13, center+offset+2,
                                   fill=COLORS["muted"], outline="")
            target.create_text(27, center, text=SLOT_NAMES[slot], anchor="w",
                               font=title_font, fill=COLORS["text"])

        def press(event):
            header._armed = event.x < 25
            header._origin = (event.x_root, event.y_root)
            shell = self._rotation_columns[slot]["shell"]
            header._offset = (event.x_root-shell.winfo_rootx(), event.y_root-shell.winfo_rooty())
            header._target = None

        def motion(event):
            if not getattr(header, "_armed", False):
                return
            distance = max(abs(event.x_root-header._origin[0]), abs(event.y_root-header._origin[1]))
            if header._drag_ghost is None and distance < 5:
                return
            if header._drag_ghost is None:
                self._close_rounded_picker()
                header._drag_ghost = self._rotation_column_ghost(slot)
                header._marker = Frame(self._rotation_columns_parent, bg=COLORS["primary"], width=3)
                header._bindings = [(seq, self.root.bind(seq, callback, add="+")) for seq, callback in
                                    (("<B1-Motion>", motion), ("<ButtonRelease-1>", release), ("<Escape>", release))]
            ox, oy = header._offset
            header._drag_ghost.geometry(f"+{event.x_root-ox}+{event.y_root-oy}")
            header._drag_ghost.deiconify()
            nearest = min(self._rotation_columns, key=lambda n: abs(event.x_root -
                          (self._rotation_columns[n]["shell"].winfo_rootx() +
                           self._rotation_columns[n]["shell"].winfo_width()/2)))
            order = self._rotation_current_preset()["slot_order"]
            header._target = order.index(nearest)
            target = self._rotation_columns[nearest]["shell"]
            edge = target.winfo_x() + (target.winfo_width()-3 if header._target > order.index(slot) else 0)
            header._marker.place(x=edge, y=0, height=target.winfo_height())
            return "break"

        def release(event, cancel=False):
            dragged, target = header._drag_ghost is not None, getattr(header, "_target", None)
            header._armed = False
            if header._drag_ghost is not None:
                header._drag_ghost.destroy()
                header._drag_ghost = None
            if hasattr(header, "_marker"):
                header._marker.destroy()
            for seq, binding in getattr(header, "_bindings", []):
                self.root.unbind(seq, binding)
            header._bindings = []
            if dragged and target is not None and not cancel and getattr(event, "keysym", "") != "Escape":
                self._rotation_drop_column(slot, target)
            return "break"

        header._paint_preview = paint
        header.bind("<Configure>", lambda e: paint(header, e.width))
        header.bind("<Motion>", lambda e: header.configure(cursor="hand2" if e.x < 25 else "arrow"))
        header.bind("<ButtonPress-1>", press)
        header.bind("<B1-Motion>", motion)
        header.bind("<ButtonRelease-1>", release)
        header.bind("<Destroy>", lambda e: release(e, cancel=True))
        return header

    def _build_rotation_tab(self) -> None:
        Label(self.rotation_tab, text="战斗排轴", font=(FONT_FAMILY, 15, "bold"),
              bg=COLORS["panel"], fg=COLORS["text"]).pack(anchor="w")
        help_text = Label(self.rotation_tab, text="角色卡从左到右循环，空列跳过；开战先切到首个角色。离场继续计时，技能、大招与声骸到间隔按模块顺序触发。",
                          bg=COLORS["panel"], fg=COLORS["muted"], wraplength=700, justify=LEFT, anchor="w")
        help_text.pack(anchor="w", fill=X, pady=(4, 10))
        help_text.bind("<Configure>", lambda e: help_text.configure(wraplength=max(180, e.width-4)))
        self._rotation_editing_id = self.rotation_store["active"]
        self.rotation_choice.set(self._rotation_current_preset()["name"])
        self.rotation_status = StringVar(value="拖动角色标题前的三点调整整列顺序；模块三点排序，×快速删除，›修改参数。滚轮浏览，驻场时间自动保存。")
        toolbar = Frame(self.rotation_tab, bg=COLORS["panel"])
        toolbar.pack(fill=X, pady=(0, 8))
        self.rotation_picker_parent = Frame(toolbar, bg=COLORS["panel"])
        self.rotation_picker_parent.pack(side=LEFT, fill=X, expand=True)
        self.rotation_picker = self._rounded_picker(self.rotation_picker_parent, self.rotation_choice,
                                                   self._rotation_preset_names(), self._rotation_switch)
        self.rotation_picker.pack(side=LEFT, fill=X, expand=True, padx=(0, 8))
        for name, callback in (("新建", self._rotation_new), ("重命名", self._rotation_rename),
                               ("删除", self._rotation_delete), ("保存", self._rotation_save)):
            self._rounded_button(toolbar, name, callback, width=68, primary=name == "保存").pack(side=LEFT, padx=(0, 6))
        self._ui_button(toolbar, text="生成种子", command=self._rotation_export_seed).pack(side=LEFT)
        self._ui_button(toolbar, text="导入种子", command=self._rotation_import_seed).pack(side=LEFT)
        self._reserve_row_controls(toolbar, self.rotation_picker_parent)
        modes_shell, modes_body = self._rounded_panel(self.rotation_tab, padding=10)
        modes_shell.pack(fill=X, pady=(0, 8))
        self.rotation_modes_parent = Frame(modes_body, bg=COLORS["panel_alt"])
        self.rotation_modes_parent.pack(fill=X)
        self._rotation_refresh_modes()
        status = Label(self.rotation_tab, textvariable=self.rotation_status, bg=COLORS["panel"], fg=COLORS["muted"],
                       justify=LEFT, wraplength=700, anchor="w")
        status.pack(anchor="w", fill=X, pady=(0, 8))
        status.bind("<Configure>", lambda e: status.configure(wraplength=max(180, e.width-4)))
        columns = Frame(self.rotation_tab, bg=COLORS["panel"])
        self._rotation_columns_parent = columns
        columns.pack(fill=BOTH, expand=True)
        columns.rowconfigure(0, weight=1)
        self._rotation_columns = {}
        self._rotation_time_fields = {}
        self._rotation_time_entries = {}
        self._rotation_time_jobs = {}
        self._rotation_refreshing_times = False
        self._rotation_time_preset_id = None
        self.rotation_tab.bind("<Destroy>", self._rotation_cancel_time_jobs, add="+")
        self._rotation_add_choices = {}
        for slot, title in SLOT_NAMES.items():
            shell, outer = self._rounded_panel(columns, padding=6, color=COLORS["panel"])
            shell.grid(row=0, column=slot-1, sticky="nsew", padx=(0, 8) if slot < 3 else 0)
            columns.columnconfigure(slot-1, weight=1, uniform="rotation_column")
            header = self._rotation_make_column_header(outer, slot)
            timing = Frame(outer, bg=COLORS["panel"])
            timing.pack(fill=X, pady=(5, 8))
            Label(timing, text="驻场秒数", bg=COLORS["panel"], fg=COLORS["muted"]).pack(side=LEFT, padx=(0, 6))
            variable = StringVar(value="5")
            self._rotation_time_fields[slot] = variable
            entry = self._rounded_entry(timing, textvariable=variable, width=5, font=(FONT_FAMILY, 10), relief="flat",
                          bg=COLORS["panel_alt"], fg=COLORS["text"], insertbackground=COLORS["text"],
                          highlightthickness=1, highlightbackground=COLORS["line_soft"])
            entry.pack(side=LEFT, fill=X, expand=True, ipady=5)
            self._rotation_time_entries[slot] = entry
            def focus_time(event):
                self._close_rounded_picker()
                # Closing a native popup can leave Windows with no active window.
                # This is a direct click on the field, so restore its keyboard focus.
                event.widget.focus_force()

            def select_time(event):
                event.widget.selection_range(0, END)
                event.widget.icursor(END)
                return "break"

            entry.bind("<Button-1>", focus_time)
            entry.bind("<Control-a>", select_time)
            variable.trace_add("write", lambda *_args, n=slot: self._rotation_schedule_time(n))
            entry.bind("<Return>", lambda _e, n=slot: self._rotation_commit_time(n))
            entry.bind("<FocusOut>", lambda _e, n=slot: self._rotation_commit_time(n))
            addition = Frame(outer, bg=COLORS["panel"])
            addition.pack(fill=X, pady=(0, 8))
            choice = StringVar(value=ACTION_SPECS["attack_count"][0])
            self._rotation_add_choices[slot] = choice
            self._rounded_button(addition, "＋", lambda n=slot: self._rotation_add(n), width=38, primary=True).pack(side=RIGHT, padx=(6, 0))
            self._rounded_picker(addition, choice, [spec[0] for spec in ACTION_SPECS.values()], lambda: None).pack(fill=X, expand=True)
            list_shell = Frame(outer, bg=COLORS["panel"])
            list_shell.pack(fill=BOTH, expand=True)
            content, canvas = self._create_scrollable_tab(list_shell, padding=0, modern=True)
            self._rotation_columns[slot] = {"shell": shell, "header": header, "addition": addition,
                                            "list": content, "canvas": canvas, "scrollbar": canvas._scrollbar}
            self._bind_mousewheel_tree(list_shell, canvas)
        columns.rowconfigure(0, weight=1)
        self._rotation_rebuild_cards()
        if hasattr(self, 'rotation_scroll_canvas'):
            self._bind_mousewheel_tree(self.rotation_tab, self.rotation_scroll_canvas)

    def _build_template_tab(self) -> None:
        Label(self.template_tab, text="制作识别模板", font=("Microsoft YaHei UI", 13, "bold")).pack(anchor="w")
        template_help = Label(
            self.template_tab,
            text="让游戏停在目标界面，点击“制作新模板”，在截图上框住按钮或图标。保存后任务就可以自动找图点击。",
            fg="#5f6b7a",
            justify=LEFT,
        )
        template_help.pack(anchor="w", fill=X, pady=(2, 10))
        template_help.bind("<Configure>", lambda event: template_help.configure(wraplength=max(160, event.width - 8)))

        top = Frame(self.template_tab)
        top.pack(fill=X, pady=(0, 10))
        self._ui_button(top, text="制作新模板", style="Primary.TButton", command=self._make_template).pack(side=LEFT)
        self._ui_button(top, text="刷新模板列表", command=self._refresh_templates).pack(side=LEFT, padx=8)
        self._ui_button(top, text="删除当前模板组", command=self._delete_selected_template).pack(side=LEFT)
        self._ui_button(top, text="测试选中任务识别", command=self._preview_selected).pack(side=LEFT, padx=8)

        self._wrap_button_row(top)

        group_row = Frame(self.template_tab)
        group_row.pack(fill=X, pady=(0, 8))
        Label(group_row, text="当前模板组", width=12, anchor="w").pack(side=LEFT)
        self.template_group_combo = self._rounded_picker(group_row, self.template_group, [], self._on_template_group_selected)
        self.template_group_combo.pack(side=LEFT, fill=X, expand=True, padx=(0, 8))
        self._ui_button(group_row, text="新建模板组", command=self._create_template_group).pack(side=LEFT, padx=(0, 8))
        self._ui_button(group_row, text="绑定到选中任务", command=self._assign_selected_task_group).pack(side=LEFT)
        self._reserve_row_controls(group_row, self.template_group_combo)

        Label(self.template_tab, text="当前已有模板", font=("Microsoft YaHei UI", 11, "bold")).pack(anchor="w")
        list_shell, list_body = self._rounded_panel(self.template_tab, color=COLORS['panel'])
        list_shell.pack(fill=BOTH, expand=True, pady=6)
        self.template_list = Listbox(list_body, height=14, font=(FONT_FAMILY, 10),
                                     relief='flat', bd=0, highlightthickness=0)
        list_scrollbar = self._thin_scrollbar(list_body, command=self.template_list.yview)
        self.template_list.configure(yscrollcommand=list_scrollbar.set)
        self.template_list.pack(side=LEFT, fill=BOTH, expand=True)
        list_scrollbar.pack(side=RIGHT, fill='y')

        Label(
            self.template_tab,
            text="提示：选择模板组会同步切换普通启动任务；选择幻梦游园后不会再执行群声。4C请使用专用按钮。",
            fg="#5f6b7a",
        ).pack(anchor="w", pady=(6, 0))

    def _build_probability_tab(self) -> None:
        Label(self.probability_tab, text="抽取概率计算", font=(FONT_FAMILY, 15, "bold"),
              bg=COLORS["panel"], fg=COLORS["text"]).pack(anchor="w")
        intro = Label(self.probability_tab,
                      text="填写资源、水位和目标；星声与抽数自动换算。角色池计入 50% 与大保底，武器池 5 星视为 UP。",
                      fg=COLORS["muted"], bg=COLORS["panel"], justify=LEFT)
        intro.pack(anchor="w", fill=X, pady=(4, 10))
        intro.bind("<Configure>", lambda event: intro.configure(wraplength=max(180, event.width - 8)))

        def section(title: str):
            shell, body = self._rounded_panel(self.probability_tab, padding=16)
            shell.pack(fill=X, pady=(0, 10))
            Label(body, text=title, font=(FONT_FAMILY, 12, "bold"),
                  bg=COLORS["panel_alt"], fg=COLORS["text"]).pack(anchor="w", pady=(0, 9))
            fields = Frame(body, bg=COLORS["panel_alt"])
            fields.pack(fill=X)
            fields.columnconfigure(0, weight=1)
            fields.columnconfigure(1, weight=1)
            return body, fields

        def field(parent, title: str, variable: StringVar, hint: str, row: int, column: int):
            box = Frame(parent, bg=COLORS["panel_alt"])
            box.grid(row=row, column=column, sticky="nsew", padx=(0, 16), pady=(0, 10))
            Label(box, text=title, bg=COLORS["panel_alt"], fg=COLORS["text"],
                  font=(FONT_FAMILY, 10, "bold")).pack(anchor="w")
            self._rounded_entry(box, textvariable=variable, font=(FONT_FAMILY, 11),
                  bg=COLORS["panel"], fg=COLORS["text"], relief="flat", bd=1).pack(fill=X, pady=(5, 3))
            hint_label = Label(box, text=hint, bg=COLORS["panel_alt"], fg=COLORS["muted"],
                               justify=LEFT)
            hint_label.pack(anchor="w", fill=X)
            box.bind("<Configure>", lambda event, label=hint_label:
                     label.configure(wraplength=max(100, event.width - 8)))

        _body, fields = section("抽取资源")
        field(fields, "星声数量", self.prob_astrite, "按 160 星声折算为 1 抽", 0, 0)
        field(fields, "抽数", self.prob_pulls, "可直接填写；与星声数量自动同步", 0, 1)

        character_body, fields = section("角色池")
        field(fields, "角色水位", self.prob_character_pity, "距离上次 5 星已抽的次数，0–79", 0, 0)
        field(fields, "目标角色数", self.prob_character_target, "希望获得的 UP 角色数", 0, 1)
        Checkbutton(character_body, text="现在拥有角色大保底", variable=self.prob_character_guaranteed,
                    bg=COLORS["panel_alt"], fg=COLORS["text"], selectcolor=COLORS["panel"],
                    activebackground=COLORS["panel_alt"]).pack(anchor="w")

        _body, fields = section("武器池")
        field(fields, "武器水位", self.prob_weapon_pity, "距离上次 5 星已抽的次数，0–79", 0, 0)
        field(fields, "目标武器数", self.prob_weapon_target, "希望获得的 UP 武器数", 0, 1)

        self._rounded_button(self.probability_tab, "计算概率", self._calculate_probability,
                             primary=True).pack(anchor="w", pady=(2, 12))
        result_shell, result = self._rounded_panel(self.probability_tab, padding=18)
        result_shell.pack(fill=X, pady=(0, 12))
        Label(result, text="计算结果", font=(FONT_FAMILY, 12, "bold"),
              bg=COLORS["panel_alt"], fg=COLORS["text"]).pack(anchor="w")
        result_label = Label(result, textvariable=self.prob_result, justify=LEFT, anchor="w",
                             bg=COLORS["panel_alt"], fg=COLORS["text"])
        result_label.pack(anchor="w", fill=X, pady=(8, 0))
        result.bind("<Configure>", lambda event:
                    result_label.configure(wraplength=max(180, event.width - 10)))
        note = Label(self.probability_tab,
                     text="同时设置角色与武器目标时，先计算角色目标，再用剩余抽数计算武器目标。",
                     fg=COLORS["muted"], bg=COLORS["panel"], justify=LEFT)
        note.pack(anchor="w", fill=X)
        note.bind("<Configure>", lambda event: note.configure(wraplength=max(180, event.width - 8)))

    def _build_settings_tab(self) -> None:
        Label(self.settings_tab, text="高级设置", font=("Microsoft YaHei UI", 13, "bold")).pack(anchor="w")
        Label(self.settings_tab, text="普通使用 PC 客户端模式即可。只有使用模拟器时才需要切换到 ADB。", fg="#5f6b7a").pack(anchor="w", pady=(2, 12))

        theme_box = self._card_body(self.settings_tab)
        theme_box.pack(fill=X, pady=(0, 14))
        Label(theme_box, text="程序主题", font=(FONT_FAMILY, 11, "bold"), bg=COLORS["panel_alt"]).pack(anchor="w")
        Label(theme_box, textvariable=self.theme_status, fg=COLORS["muted"], bg=COLORS["panel_alt"]).pack(anchor="w", pady=(3, 10))
        theme_actions = Frame(theme_box, bg=COLORS["panel_alt"])
        theme_actions.pack(fill=X)
        self._ui_button(theme_actions, text="使用原版简约主题", command=lambda: self._select_theme("simple")).pack(side=LEFT)
        self._ui_button(theme_actions, text="使用达妮娅主题", command=lambda: self._select_theme("daniya")).pack(side=LEFT, padx=(10, 0))
        self._ui_button(theme_actions, text="使用爱弥斯主题", command=lambda: self._select_theme("aemeath")).pack(side=LEFT, padx=(10, 0))
        self._ui_button(theme_actions, text="使用景燃主题", command=lambda: self._select_theme("jingran")).pack(side=LEFT, padx=(10, 0))
        self._ui_button(theme_actions, text="使用卡提希娅主题", command=lambda: self._select_theme("cartethyia")).pack(side=LEFT, padx=(10, 0))
        self._wrap_button_row(theme_actions)
        theme_hint = Label(
            theme_box,
            text="选择角色主题时会切换到同名桌宠；之后仍可单独改选桌宠。切换主题后会自动重启程序。",
            fg=COLORS["muted"],
            bg=COLORS["panel_alt"],
            justify=LEFT,
        )
        theme_hint.pack(anchor="w", fill=X, pady=(10, 0))
        theme_hint.bind("<Configure>", lambda event: theme_hint.configure(wraplength=max(160, event.width - 8)))

        pet_select_box = self._card_body(self.settings_tab)
        pet_select_box.pack(fill=X, pady=(0, 14))
        Label(pet_select_box, text="桌宠角色", font=(FONT_FAMILY, 11, "bold"), bg=COLORS["panel_alt"]).pack(anchor="w")
        Label(pet_select_box, textvariable=self.pet_status, fg=COLORS["muted"], bg=COLORS["panel_alt"]).pack(anchor="w", pady=(3, 10))
        pet_actions = Frame(pet_select_box, bg=COLORS["panel_alt"])
        pet_actions.pack(fill=X)
        self._ui_button(pet_actions, text="使用达妮娅", command=lambda: self._select_pet("daniya")).pack(side=LEFT)
        self._ui_button(pet_actions, text="使用爱弥斯", command=lambda: self._select_pet("aemeath")).pack(side=LEFT, padx=(10, 0))
        self._ui_button(pet_actions, text="使用景燃", command=lambda: self._select_pet("jingran")).pack(side=LEFT, padx=(10, 0))
        self._ui_button(pet_actions, text="使用卡提希娅", command=lambda: self._select_pet("cartethyia")).pack(side=LEFT, padx=(10, 0))
        self._wrap_button_row(pet_actions)
        pet_hint = Label(
            pet_select_box,
            text="选择桌宠不会改变程序主题；四款桌宠使用相同功能、右键菜单和排版。",
            fg=COLORS["muted"],
            bg=COLORS["panel_alt"],
            justify=LEFT,
        )
        pet_hint.pack(anchor="w", fill=X, pady=(10, 0))
        pet_hint.bind("<Configure>", lambda event: pet_hint.configure(wraplength=max(160, event.width - 8)))
        pet_size_row = Frame(pet_select_box, bg=COLORS["panel_alt"])
        pet_size_row.pack(fill=X, pady=(12, 0))
        Label(pet_size_row, text="桌宠大小", width=12, anchor="w", bg=COLORS["panel_alt"]).pack(side=LEFT)
        pet_size_picker = self._rounded_picker(pet_size_row, self.pet_size,
                                               ("70%", "85%", "100%", "115%", "130%", "150%"), self._apply_pet_size)
        pet_size_picker.configure(width=150)
        pet_size_picker.pack(side=LEFT, padx=(0, 10))
        Label(
            pet_select_box,
            text="选择后立即生效，下次启动会保持当前大小",
            fg=COLORS["muted"],
            bg=COLORS["panel_alt"],
        ).pack(anchor="w", pady=(4, 0))
        pet_behavior_row = Frame(pet_select_box, bg=COLORS["panel_alt"])
        pet_behavior_row.pack(fill=X, pady=(10, 0))
        behavior_state = "normal" if self.pet_supports_look_controls else "disabled"
        Checkbutton(
            pet_behavior_row,
            text="盯鼠标",
            variable=self.pet_look_enabled,
            command=self._apply_pet_look_setting,
            state=behavior_state,
            bg=COLORS["panel_alt"],
        ).pack(side=LEFT)
        Checkbutton(
            pet_behavior_row,
            text="定时跳跃（每45至90秒尝试一次）",
            variable=self.pet_auto_jump_enabled,
            command=self._apply_pet_auto_jump_setting,
            state=behavior_state,
            bg=COLORS["panel_alt"],
        ).pack(side=LEFT, padx=(16, 0))
        Label(
            pet_select_box,
            text="仅景燃与卡提希娅可用，设置自动保存",
            fg=COLORS["muted"],
            bg=COLORS["panel_alt"],
        ).pack(anchor="w", pady=(4, 0))

        agent_box = self._card_body(self.settings_tab)
        agent_box.pack(fill=X, pady=(0, 14))
        Label(
            agent_box,
            text="桌宠 Agent（本地模型 / API）",
            font=(FONT_FAMILY, 11, "bold"),
            bg=COLORS["panel_alt"],
        ).pack(anchor="w")
        Checkbutton(
            agent_box,
            text="启用桌宠 Agent",
            variable=self.cartethyia_agent_enabled,
            command=lambda: self._save_cartethyia_agent_settings(announce=False),
            bg=COLORS["panel_alt"],
            activebackground=COLORS["panel_alt"],
        ).pack(anchor="w", pady=(8, 4))
        Label(agent_box, text="启用 Agent 后停止随机自言自语，只回复聊天和任务消息；关闭后恢复主动发言。聊天记录保存在本机。",
              bg=COLORS["panel_alt"], fg=COLORS["muted"], wraplength=700, justify="left").pack(anchor="w")
        provider_row = Frame(agent_box, bg=COLORS["panel_alt"])
        provider_row.pack(fill=X, pady=3)
        Label(provider_row, text="接入方式", width=12, anchor="w", bg=COLORS["panel_alt"]).pack(side=LEFT)
        provider_picker = self._rounded_picker(provider_row, self.agent_provider,
            ("Ollama 本地", "DeepSeek API", "OpenAI 兼容 API", "SillyTavern 酒馆"), self._change_agent_provider)
        provider_picker.pack(side=LEFT, fill=X, expand=True)
        endpoint_row = Frame(agent_box, bg=COLORS["panel_alt"])
        endpoint_row.pack(fill=X, pady=3)
        Label(endpoint_row, text="服务地址", width=12, anchor="w", bg=COLORS["panel_alt"]).pack(side=LEFT)
        self._rounded_entry(endpoint_row, textvariable=self.cartethyia_agent_endpoint, width=42).pack(side=LEFT, fill=X, expand=True)
        Label(agent_box, text="API 填服务商 Base URL（通常以 /v1 结尾）", fg=COLORS["muted"], bg=COLORS["panel_alt"]).pack(anchor="w")
        key_row = Frame(agent_box, bg=COLORS["panel_alt"])
        key_row.pack(fill=X, pady=3)
        Label(key_row, text="API Key", width=12, anchor="w", bg=COLORS["panel_alt"]).pack(side=LEFT)
        self._rounded_entry(key_row, textvariable=self.agent_api_key, show="*", width=42).pack(side=LEFT, fill=X, expand=True)
        Label(agent_box, text="可留空；仅本次运行有效，重启后需重新填写", fg=COLORS["muted"], bg=COLORS["panel_alt"]).pack(anchor="w")
        bridge_row = Frame(agent_box, bg=COLORS["panel_alt"])
        bridge_row.pack(fill=X, pady=3)
        Label(bridge_row, text="酒馆桥接密钥", width=12, anchor="w", bg=COLORS["panel_alt"]).pack(side=LEFT)
        self._rounded_entry(bridge_row, textvariable=self.agent_bridge_token, width=42, state="readonly").pack(side=LEFT, fill=X, expand=True)
        Label(agent_box, text=f"复制到酒馆 wwbs 扩展；本机端口 {SILLYTAVERN_BRIDGE_PORT}", fg=COLORS["muted"], bg=COLORS["panel_alt"]).pack(anchor="w")
        model_row = Frame(agent_box, bg=COLORS["panel_alt"])
        model_row.pack(fill=X, pady=3)
        Label(model_row, text="模型名称", width=12, anchor="w", bg=COLORS["panel_alt"]).pack(side=LEFT)
        self.agent_model_picker = self._rounded_picker(model_row, self.cartethyia_agent_model, [], lambda: None, editable=True)
        self.agent_model_picker.pack(side=LEFT, fill=X, expand=True, padx=(0, 10))
        self._ui_button(model_row, text="获取服务模型", command=self._fetch_agent_models).pack(side=LEFT)
        self._reserve_row_controls(model_row, self.agent_model_picker)
        discovery_row = Frame(agent_box, bg=COLORS["panel_alt"])
        discovery_row.pack(fill=X, pady=3)
        Label(discovery_row, text="本机模型", width=12, anchor="w", bg=COLORS["panel_alt"]).pack(side=LEFT)
        self.agent_discovery_picker = self._rounded_picker(discovery_row, self.agent_discovered_choice, [], self._use_discovered_model)
        self.agent_discovery_picker.pack(side=LEFT, fill=X, expand=True, padx=(0, 10))
        self._ui_button(discovery_row, text="重新检测", command=self._scan_local_models).pack(side=LEFT)
        self._reserve_row_controls(discovery_row, self.agent_discovery_picker)
        self.agent_discovery_status = StringVar(value="等待检测本机模型")
        Label(agent_box, textvariable=self.agent_discovery_status, bg=COLORS["panel_alt"], fg=COLORS["muted"], wraplength=900).pack(anchor="w")
        agent_actions = Frame(agent_box, bg=COLORS["panel_alt"])
        agent_actions.pack(fill=X, pady=(9, 3))
        self._ui_button(agent_actions, text="保存 Agent 设置", command=self._save_cartethyia_agent_settings).pack(side=LEFT)
        self._ui_button(agent_actions, text="测试连接", command=self._test_cartethyia_agent).pack(side=LEFT, padx=(10, 0))
        self._wrap_button_row(agent_actions)
        Label(
            agent_box,
            textvariable=self.cartethyia_agent_status,
            fg=COLORS["muted"],
            bg=COLORS["panel_alt"],
        ).pack(anchor="w", pady=(7, 0))
        Label(
            agent_box,
            text="四位共享连接设置。酒馆模式使用当前打开的角色卡、世界书和会话上下文；请先在酒馆选中与桌宠相同的角色。远程 API 可能收费。",
            fg=COLORS["muted"],
            bg=COLORS["panel_alt"],
            wraplength=980,
            justify=LEFT,
        ).pack(anchor="w", pady=(5, 0))

        mode_row = Frame(self.settings_tab)
        mode_row.pack(fill=X, pady=5)
        Label(mode_row, text="操作目标", width=12, anchor="w").pack(side=LEFT)
        ttk.Radiobutton(mode_row, text="PC 客户端窗口", variable=self.target_mode, value="client", command=self._update_mode_label).pack(side=LEFT, padx=6)
        ttk.Radiobutton(mode_row, text="模拟器 / ADB", variable=self.target_mode, value="adb", command=self._update_mode_label).pack(side=LEFT, padx=6)

        client_row = Frame(self.settings_tab)
        client_row.pack(fill=X, pady=5)
        Label(client_row, text="窗口标题", width=12, anchor="w").pack(side=LEFT)
        self._rounded_entry(client_row, textvariable=self.window_title, width=24).pack(side=LEFT, padx=6)
        Label(self.settings_tab, text="“自动”同时识别国服与国际服 Steam 端；标题包含这些字就会被识别。",
              fg=COLORS["muted"], bg=COLORS["panel"], justify=LEFT,
              wraplength=520).pack(anchor="w", fill=X)

        size_row = Frame(self.settings_tab)
        size_row.pack(fill=X, pady=5)
        Label(size_row, text="模板基准", width=12, anchor="w").pack(side=LEFT)
        self._rounded_entry(size_row, textvariable=self.expected_resolution, width=24).pack(side=LEFT, padx=6)
        Label(self.settings_tab, text="模板按这个分辨率制作，窗口可等比例缩小，例如 1536x864",
              fg=COLORS["muted"], bg=COLORS["panel"], justify=LEFT,
              wraplength=520).pack(anchor="w", fill=X)

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
        if "--admin-restarted" not in arguments:
            arguments.append("--admin-restarted")
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
        log_shell, log_body = self._rounded_panel(self.log_tab, color=COLORS['panel'])
        log_shell.pack(fill=BOTH, expand=True, pady=8)
        log_scrollbar = self._thin_scrollbar(log_body, orient="vertical")
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
        self._ui_button(self.log_tab, text="清空日志", command=lambda: self.log_text.delete("1.0", END)).pack(anchor="e")

    def _show_startup_notice_once(self) -> None:
        if getattr(self, '_startup_notice_handled', False):
            return
        self._startup_notice_handled = True
        try:
            record = json.loads(UPDATE_NOTICE_CONFIG.read_text(encoding='utf-8'))
            seen = record.get('seen_versions', []) if isinstance(record, dict) else []
            if not isinstance(seen, list):
                seen = []
        except (OSError, ValueError):
            seen = []
        if APP_VERSION in seen:
            return
        seen = [version for version in seen if isinstance(version, str)]
        seen.append(APP_VERSION)
        try:
            UPDATE_NOTICE_CONFIG.write_text(json.dumps({'seen_versions': seen}, ensure_ascii=False), encoding='utf-8')
        except OSError as exc:
            self._log(f'无法保存首次公告状态：{exc}')
        worker = getattr(self, 'worker', None)
        if (worker is not None and worker.is_alive()) or getattr(self, '_preflight_running', False):
            self._log('任务已启动，跳过自动公告；可通过“更新公告”手动查看。')
            return
        self._show_update_notice()

    def _show_update_notice(self) -> None:
        messagebox.showinfo(
            f"wwbs {APP_VERSION} 更新公告",
            UPDATE_HISTORY[0][1],
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
                    "chat": self._open_cartethyia_chat,
                    "chat_history": self._show_pet_chat_history,
                    "run_rewards": lambda: self._start_enabled_real(15, require_confirmation=False),
                    "run_astrite": lambda: self._start_enabled_real(13, require_confirmation=False),
                    "run_daily": lambda: self._start_daily_routine(require_confirmation=False),
                    "run_4c_10": lambda: self._start_named_task_real("4C刷取", 10, require_confirmation=False),
                    "run_4c_custom": self._start_custom_4c,
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
                allow_generated_speech=lambda: not self.cartethyia_agent_enabled.get(),
                bubble_palette=self.pet_definition["bubble_palette"],
                look_spritesheet=self.pet_definition.get("look_spritesheet"),
                alpha_cutoff=self.pet_definition.get("alpha_cutoff"),
                look_enabled=(
                    bool(self.pet_look_enabled.get())
                    if self.pet_supports_look_controls
                    else False
                ),
                auto_jump_enabled=(
                    bool(self.pet_auto_jump_enabled.get())
                    if self.pet_supports_look_controls
                    else None
                ),
                forward_jump_enabled=self.pet_supports_look_controls,
                visible=self.pet_visible,
                on_visibility_changed=self._save_pet_visibility,
                on_look_enabled_changed=self._save_pet_look_from_menu,
                on_auto_jump_enabled_changed=self._save_pet_auto_jump_from_menu,
                speak_on_interact=self.pet_id == "jingran",
                chatter_delay_range=(12000, 24000) if self.pet_id == "jingran" else None,
            )
            self.log_queue.put(f"{self.pet_name}已启动：拖动移动，双击互动，右键执行功能或运行诊断。")
            welcome_factory = self.pet_definition.get("welcome_dialogue")
            if callable(welcome_factory) and not self.cartethyia_agent_enabled.get():
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
                                ("warning", "当前截图未显示首领名字与血条，可能处于大招或镜头动画；单张截图不能判断战斗结束。")
                            )
                    elif self._task_with_action(diagnostic_tasks, "daily_routine") is not None:
                        required = [
                            "activity_full.png", "battle_task_text.png", "reward_prompt.png",
                            "guide_battle_tab.png", "guide_tacet_section.png", "guide_material_title.png",
                        ]
                        missing = [name for name in required if not (TEMPLATES_DIR / "daily" / name).exists()]
                        if not (TEMPLATES_DIR / DIAGNOSTIC_START_TEMPLATE).exists():
                            missing.append("../" + DIAGNOSTIC_START_TEMPLATE)
                        if missing:
                            findings.append(("error", f"日常与衔接周常模板不完整：{', '.join(missing)}。"))
                        else:
                            findings.append(("ok", "日常与衔接周常模板齐全；日常从大世界开始，运行中无需匹配周常起始界面。"))
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
        self.sillytavern_bridge.stop()
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

        self._ui_button(
            container,
            text="打开 B 站视频",
            command=lambda: self._open_external_link(ABOUT_BILIBILI_URL),
        ).pack(fill=X, pady=(0, 10))
        self._ui_button(
            container,
            text="打开 GitHub",
            command=lambda: self._open_external_link(ABOUT_GITHUB_URL),
        ).pack(fill=X)
        self._ui_button(container, text="关闭", command=window.destroy).pack(anchor="e", pady=(20, 0))

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

        text_shell, text_frame = self._rounded_panel(container, color=COLORS['panel'])
        text_shell.pack(fill=BOTH, expand=True)
        scrollbar = self._thin_scrollbar(text_frame, orient="vertical")
        history_text = Text(text_frame, wrap="word", font=(FONT_FAMILY, 10), yscrollcommand=scrollbar.set)
        scrollbar.config(command=history_text.yview)
        scrollbar.pack(side=RIGHT, fill="y")
        history_text.pack(side=LEFT, fill=BOTH, expand=True)
        for version, notice in UPDATE_HISTORY:
            history_text.insert(END, f"{version}\n{notice}\n\n")
        history_text.configure(state="disabled")
        self._ui_button(container, text="关闭", command=window.destroy).pack(anchor="e", pady=(10, 0))

    @staticmethod
    def _version_tuple(value: str) -> tuple[int, ...]:
        match = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", value or "")
        if not match:
            return (0, 0, 0, 0, 0)
        version = tuple(int(number or 0) for number in match.groups())
        prerelease = re.search(r"(alpha|beta|rc)[ .-]*(\d*)", value, re.I)
        stage = {"alpha": 0, "beta": 1, "rc": 2}[prerelease[1].lower()] if prerelease else 3
        return (*version, stage, int(prerelease[2] or 0) if prerelease else 0)

    def _check_for_updates(self) -> None:
        if getattr(self, "_update_installing", False):
            messagebox.showinfo("更新中", "正在下载并准备安装更新，请稍候。", parent=self.root)
            return
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
            messagebox.showinfo("检查更新", f"暂未发现比 wwbs {APP_VERSION} 更新的正式版本。", parent=self.root)
            return
        notes = str(release.get("body", "")).strip() or "该版本没有填写更新说明。"
        prompt = f"发现新版本：{tag}\n\n{notes}\n\n是否下载并安装？"
        if not messagebox.askyesno("发现新版本", prompt, parent=self.root):
            return
        if not getattr(sys, "frozen", False):
            messagebox.showinfo("开发模式", "源码运行模式可以检查更新，但请使用打包版 wwbs.exe 执行自动替换。", parent=self.root)
            return
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("任务运行中", "请先结束当前任务，再安装更新。", parent=self.root)
            return
        self._update_installing = True
        self.status.set(f"正在下载 {tag}...")
        threading.Thread(target=self._download_and_install_update, args=(tag, asset), daemon=True).start()

    def _show_update_error(self, error_text: str) -> None:
        self._update_installing = False
        self.status.set("更新未完成，原程序继续运行")
        messagebox.showerror("更新未完成", error_text, parent=self.root)

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

            staged = prepare_update(zip_path, work_dir / "extract", asset.get("size", 0), asset.get("digest") or "")
            target_dir = Path(sys.executable).resolve().parent
            script_path = work_dir / "update.ps1"
            script = install_script(staged, target_dir, work_dir, os.getpid())
            script_path.write_text(script, encoding="utf-8-sig")
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

    def _start_enabled_real(self, max_cycles: int | None = None, require_confirmation: bool = False) -> None:
        if require_confirmation:
            target = "PC 客户端窗口" if self.target_mode.get() == "client" else "模拟器 / ADB"
            if not messagebox.askyesno("确认开始", f"程序将操作 {target}。请确认游戏已打开并停在正确界面。"):
                return
        else:
            self._log("任务直接启动，不显示开始确认。")
        self.max_cycles = max_cycles
        self.dry_run.set(False)
        if not self._ensure_admin_for_real_run():
            return
        self._preflight_enabled_run()

    def _start_named_task_real(
        self,
        task_name: str,
        cycles: int | None = None,
        require_confirmation: bool = False,
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

    def _start_tower_challenge(self) -> None:
        if self.target_mode.get() != "client":
            messagebox.showerror("模式不支持", "深塔挑战目前只支持 PC 客户端窗口。", parent=self.root)
            return
        task = WeeklyTask(name="深塔挑战", enabled=True, weekday="any", template_group="tower",
                          description="从塔内光球前开始，按分配的排轴战斗至挑战成功，保持结算界面。",
                          steps=[Step(action="tower_challenge", label="靠近光球并挑战", timeout=1200)])
        self.max_cycles = None
        self.dry_run.set(False)
        if self._ensure_admin_for_real_run():
            self._start_worker([task])

    def _start_daily_routine(self, require_confirmation: bool = False) -> None:
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
            self._log(f"一键日常直接启动，目标为“{selected}”。")
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
        if getattr(self, "_update_installing", False):
            messagebox.showinfo("正在更新", "更新准备期间不能启动自动任务。", parent=self.root)
            return
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("提示", "任务正在运行中。")
            return
        if not self._ensure_admin_for_real_run():
            return
        if hasattr(self, "rotation_store") and not self._rotation_save():
            return
        if hasattr(self, "rotation_store"):
            self._rotation_run_store = validate_store(self.rotation_store)
            kinds = {"tower_challenge": "tower", "daily_routine": "daily", "combat_4c": "combat_4c"}
            modes = {kinds[step.action] for task in tasks for step in task.steps if step.action in kinds}
            for mode in modes:
                selected = next(p for p in self._rotation_run_store['presets']
                                if p['id'] == self._rotation_run_store['modes'][mode])
                order = [n for n in selected['slot_order'] if any(m['slot'] == n for m in selected['modules'])]
                route = ' → '.join(f"{SLOT_NAMES[n]} {selected['slot_times'][str(n)]:g}秒" for n in order)
                self._log(f"本次{COMBAT_MODES[mode]}战斗轴：{selected['name']}，运行顺序：{route}（启动时快照）。")
        self._last_started_tasks = list(tasks)
        self._last_task_started_at = time.monotonic()
        self._manual_stop_requested = False
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
            rotation_snapshot = getattr(self, "_rotation_run_store", self.rotation_store)
            runner = TaskRunner(
                controller,
                self._log,
                self.dry_run.get(),
                self.stop_event,
                self.max_cycles,
                self.combat_skill_key.get(),
                self.combat_ultimate_key.get(),
                self.daily_zone.get(),
                False,
                notice=lambda message: self.root.after(
                    0,
                    lambda text=message: messagebox.showinfo("提示", text, parent=self.root),
                ),
                rotation_presets={mode: active_modules(rotation_snapshot, mode) for mode in COMBAT_MODES},
                rotation_times={mode: next(p["slot_times"] for p in rotation_snapshot["presets"]
                                           if p["id"] == rotation_snapshot["modes"][mode])
                                for mode in COMBAT_MODES},
                rotation_orders={mode: next(p["slot_order"] for p in rotation_snapshot["presets"]
                                            if p["id"] == rotation_snapshot["modes"][mode])
                                 for mode in COMBAT_MODES},
            )
            for task in tasks:
                runner.run_task(task)
                if runner.weekly_rewards_pending:
                    break
            self._log("执行结束。")
            if runner.weekly_rewards_pending:
                self.root.after(0, lambda: self._pet_feedback("review", "周常已达上限，宝箱请再检查一下；本次不会自动关机。", 6500))
            elif self._manual_stop_requested:
                self._log("任务由用户手动停止，不会触发自动关机。")
            else:
                self.root.after(0, self._handle_successful_task_completion)
        except Exception as exc:
            error_text = str(exc)
            self._log(f"执行失败: {error_text}")
            self.root.after(0, lambda text=error_text: self._handle_task_failure(text))
        finally:
            self.max_cycles = None
            self.root.after(0, lambda: self._set_pet_working(False))

    def _handle_successful_task_completion(self) -> None:
        self._pet_feedback("review", self._event_line("task_complete"))
        if any(any(step.action == "tower_challenge" for step in task.steps)
               for task in getattr(self, "_last_started_tasks", [])):
            self._log("深塔挑战完成，保持结算界面，不再操作。")
            return
        if (
            not self.auto_shutdown_enabled.get()
            or self.dry_run.get()
            or self._manual_stop_requested
        ):
            return
        self._log("任务正常完成，已请求 Windows 在30秒后自动关机。")
        self._pet_feedback("review", "任务已经完成。电脑将在30秒后自动关机。", 9000)
        try:
            subprocess.Popen(
                [
                    "shutdown.exe",
                    "/s",
                    "/t",
                    "30",
                    "/c",
                    "wwbs 自动任务已完成，电脑将在30秒后关机。",
                ],
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except OSError as exc:
            self._log(f"自动关机请求失败: {exc}")
            self._pet_feedback("failed", f"任务已经完成，但自动关机请求失败：{exc}", 7200)

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
                self.root.after(0, lambda: TemplateCropper(self.root, target, group_dir, self._after_template_saved, ui=self))
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
        self._manual_stop_requested = True
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
            self.template_group_combo.set_choices([self._template_group_name(group) for group in groups])
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
        return any(step.action in {"combat_4c", "tower_challenge"} for step in task.steps)

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
                "4C请使用10次或自定义次数按钮。"
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
        return DEFAULT_GROUP_KEY if group == DEFAULT_GROUP_NAME else "tower" if group == "深塔挑战" else group

    @staticmethod
    def _template_group_name(group: str) -> str:
        return DEFAULT_GROUP_NAME if group == DEFAULT_GROUP_KEY else "深塔挑战" if group == "tower" else group

    @classmethod
    def _template_group_dir(cls, group: str) -> Path:
        group_key = cls._template_group_key(group)
        return TEMPLATES_DIR if group_key == DEFAULT_GROUP_KEY else TEMPLATES_DIR / group_key

    def _create_template_group(self) -> None:
        name = self._ask_text("新建模板组", "输入模板组名称，例如 周本任务2", parent=self.root)
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
        if getattr(self, '_selected_top_tab', 0) != 0:
            self._preview_deferred = True
            return
        self._preview_deferred = False
        canvas_width, canvas_height = self._preview_canvas_size()
        render_key = (str(image_path), image_path.stat().st_mtime_ns, canvas_width, canvas_height, title)
        if getattr(self, '_preview_render_key', None) == render_key:
            return
        with Image.open(image_path) as source:
            image = source.convert("RGB")
        current_width = self.preview_canvas.winfo_width()
        current_height = self.preview_canvas.winfo_height()
        if abs(current_width - canvas_width) > 2 or abs(current_height - canvas_height) > 2:
            self.preview_canvas.configure(width=canvas_width, height=canvas_height)
        scale = min(canvas_width / image.width, canvas_height / image.height)
        preview_size = (max(1, int(image.width * scale)), max(1, int(image.height * scale)))
        preview = image.resize(preview_size, Image.Resampling.BILINEAR)
        self.preview_photo = ImageTk.PhotoImage(preview)
        self._preview_render_key = render_key
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
        if getattr(self, '_selected_top_tab', 0) != 0:
            self._preview_deferred = True
            return
        self._preview_deferred = False
        width, height = self._preview_canvas_size()
        if abs(self.preview_canvas.winfo_width() - width) > 2 or abs(self.preview_canvas.winfo_height() - height) > 2:
            self.preview_canvas.configure(width=width, height=height)
        if self.preview_source and self.preview_source.exists():
            self._show_preview(self.preview_source, self.preview_title)
        else:
            self.preview_canvas.delete("all")
            self.preview_canvas.create_text(
                width // 2, height // 2,
                text="暂无截图\n运行任务后显示游戏画面",
                fill=COLORS["muted"], font=(FONT_FAMILY, 10), justify="center",
            )

    def _preview_canvas_size(self) -> tuple[int, int]:
        parent_width = max(180, self.preview_canvas.master.winfo_width() - 28)
        available_height = min(PREVIEW_MAX_HEIGHT, max(PREVIEW_MIN_HEIGHT, int(self.root.winfo_height() * 0.29)))
        target_width = min(parent_width, int(available_height * PREVIEW_ASPECT))
        target_height = max(1, int(target_width / PREVIEW_ASPECT))
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
            return f"{label}持续战斗，击败后寻找并吸收金色目标，再点击重新挑战；支持10次或自定义次数循环"
        if step.action == "tower_challenge":
            return f"{label}靠近光球，开始挑战后按深塔排轴战斗；出现挑战成功即停止并保留结算页面"
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
        lines = []
        # Bound each UI batch so a busy task cannot monopolize navigation input.
        for _ in range(60):
            try:
                line = self.log_queue.get_nowait()
            except queue.Empty:
                break
            if "鼠标没有移动成功" in line:
                self._notify_mouse_move_failure()
            lines.append(line)
        if lines:
            self.detail.insert(END, "\n" + "\n".join(lines))
            self.detail.see(END)
            if hasattr(self, "log_text"):
                self.log_text.insert(END, "\n".join(lines) + "\n")
                self.log_text.see(END)
            self.status.set(lines[-1])
        self.root.after(16 if not self.log_queue.empty() else 120, self._drain_logs)


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
    root.after(0, signal_update_ready)
    root.mainloop()


if __name__ == "__main__":
    main()
