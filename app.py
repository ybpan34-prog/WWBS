import json
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tkinter import BOTH, END, LEFT, RIGHT, TOP, X, BooleanVar, Button, Canvas, Checkbutton, Entry, Frame, Label, Listbox, StringVar, Text, Tk, Toplevel, filedialog, messagebox, simpledialog, ttk

from PIL import Image, ImageDraw, ImageTk

from image_matcher import TemplateMatcher
from windows_client import ClientWindowController


APP_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG = APP_DIR / "weekly_tasks.json"
TEMPLATES_DIR = APP_DIR / "templates"
DEFAULT_GROUP_KEY = "default"
DEFAULT_GROUP_NAME = "幻梦游园"
APP_ICON = APP_DIR / "wwbs.ico"
APP_VERSION = "1.3.1"
UPDATE_API_URL = "https://api.github.com/repos/ybpan34-prog/WWBS/releases/latest"
UPDATE_ASSET_NAME = "wwbs-exe.zip"
UPDATE_NOTICE = """v1.3.1 更新内容
1. 新增抽取概率计算，可以分别填写角色水位和武器水位。
2. 新增“现在是否拥有大保底”选项，角色概率可按当前保底状态计算。
3. 优化小概率显示，不再把极低概率显示成 0.00%。
4. 保留原有自动周历、模板识别和循环点击功能。

使用前请确认
1. 请以管理员身份运行。
2. 请将游戏窗口调整为 1920*1080p 或等比例缩放。
3. 请先完成周本的新手教程，并将速度调整至 MAX。"""
UPDATE_HISTORY = [
    ("v1.3.1", UPDATE_NOTICE.split("\n使用前请确认", 1)[0]),
]
LOCAL_TZ = timezone(timedelta(hours=8))
PREVIEW_ASPECT = 16 / 9
PREVIEW_MAX_HEIGHT = 520
PREVIEW_MIN_HEIGHT = 320
START_CONTENT_SIDE_PADDING = 28
ACTION_PANEL_WIDTH = 360
FONT_FAMILY = "Microsoft YaHei UI"
MONO_FONT = "Consolas"
COLORS = {
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
    def __init__(self, controller, log, dry_run: bool = True, stop_event: threading.Event | None = None, max_cycles: int | None = None):
        self.controller = controller
        self.log = log
        self.dry_run = dry_run
        self.stop_event = stop_event or threading.Event()
        self.max_cycles = max_cycles
        self.matcher = TemplateMatcher(TEMPLATES_DIR)
        self.template_root = TEMPLATES_DIR
        self.debug_matches = False

    def run_task(self, task: WeeklyTask) -> None:
        group_dir = TEMPLATES_DIR / task.template_group if task.template_group != "default" else TEMPLATES_DIR
        if not group_dir.exists():
            raise FileNotFoundError(f"模板组不存在: {task.template_group}")
        self.template_root = group_dir
        self.matcher.templates_dir = group_dir
        self.log(f"使用模板组: {task.template_group}")
        self.log(f"开始任务: {task.name}")
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
            time.sleep(step.seconds)
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
            time.sleep(step.seconds)
        elif step.action == "tap_image_cycle":
            self._run_image_cycle(step)
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

    def _run_image_cycle(self, step: Step) -> None:
        templates = step.templates or self._numbered_templates("menu", 2, 99)
        if not templates:
            raise RuntimeError("循环模板列表为空。")
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
                x, y, score = self._wait_for_cycle_template(current)
                self.log(f"    找到 {template_name}: ({x}, {y}) 相似度 {score:.3f}")
                if self.dry_run:
                    self.log("    干运行：已识别位置，但不点击。")
                else:
                    self.log(f"    正在点击识别坐标: ({x}, {y})")
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
                self._sleep_interruptible(step.seconds)
            if not step.loop:
                return
            round_index += 1

    def _wait_for_cycle_template(self, step: Step) -> tuple[int, int, float]:
        misses = 0
        while not self.stop_event.is_set():
            try:
                return self._find_image(step)
            except Exception as exc:
                misses += 1
                if misses >= 5:
                    self.stop_event.set()
                    raise RuntimeError(f"连续 5 次未找到 {step.template}，已自动停止。最后错误: {exc}")
                self.log(f"    等待 {step.template} 出现: {exc}")
                self._sleep_interruptible(0.15)
        raise RuntimeError("循环任务已停止。")

    def _sleep_interruptible(self, seconds: float) -> None:
        deadline = time.time() + seconds
        while time.time() < deadline:
            if self.stop_event.is_set():
                return
            time.sleep(min(0.1, deadline - time.time()))

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
                center_x, center_y = match.center
                image_x = center_x + step.offset_x
                image_y = center_y + step.offset_y
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

    def _fast_scales(self) -> list[float]:
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
        self.root.title(f"wwbs {APP_VERSION}")
        if APP_ICON.exists():
            self.root.iconbitmap(str(APP_ICON))
        self.root.geometry("1280x1210")
        self.root.minsize(1100, 760)
        self.config_path = StringVar(value=str(DEFAULT_CONFIG))
        self.target_mode = StringVar(value="client")
        self.window_title = StringVar(value="鸣潮")
        self.expected_resolution = StringVar(value="1920x1080")
        self.adb_path = StringVar(value="adb")
        self.device_id = StringVar(value="")
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

        self._build_ui()
        self._load_config(silent=True)
        self._refresh_templates()
        self._drain_logs()
        self.root.after(300, self._show_update_notice)

    def _build_ui(self) -> None:
        self._setup_style()
        self.root.configure(bg=COLORS["app_bg"])

        header = Frame(self.root, padx=24, pady=18, bg=COLORS["app_bg"])
        header.pack(side=TOP, fill=X)
        Label(header, text="wwbs", font=(FONT_FAMILY, 22, "bold"), fg=COLORS["text"], bg=COLORS["app_bg"]).pack(side=LEFT)
        Button(header, text="检查更新", command=self._check_for_updates).pack(side=RIGHT, padx=(0, 8))
        Button(header, text="更新公告", command=self._show_update_history).pack(side=RIGHT, padx=(0, 14))
        Label(header, textvariable=self.status, font=(FONT_FAMILY, 10), fg=COLORS["muted"], bg=COLORS["app_bg"]).pack(side=RIGHT)

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
        self.settings_tab = Frame(self.tabs, padx=20, pady=18, bg=COLORS["panel"])
        self.log_tab = Frame(self.tabs, padx=20, pady=18, bg=COLORS["panel"])
        self.tabs.add(self.start_tab, text="开始")
        self.tabs.add(self.template_tab, text="模板")
        self.tabs.add(self.probability_tab, text="概率")
        self.tabs.add(self.settings_tab, text="设置")
        self.tabs.add(self.log_tab, text="日志")

        self._build_start_tab()
        self._build_template_tab()
        self._build_probability_tab()
        self._build_settings_tab()
        self._build_log_tab()
        self._polish_widgets(self.root)

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
        style.map("TNotebook.Tab", background=[("selected", COLORS["panel"]), ("active", "#ffffff")], foreground=[("selected", COLORS["text"]), ("active", COLORS["text"])])
        style.configure("Primary.TButton", padding=(18, 11), font=(FONT_FAMILY, 11, "bold"), background=COLORS["primary"], foreground="#ffffff", borderwidth=0, focusthickness=0)
        style.map("Primary.TButton", background=[("active", COLORS["primary_hover"]), ("pressed", "#0066cc")], foreground=[("disabled", "#f2f2f7"), ("!disabled", "#ffffff")])
        style.configure("TButton", padding=(12, 7), font=(FONT_FAMILY, 10), background="#ffffff", foreground=COLORS["text"], bordercolor=COLORS["line"], lightcolor="#ffffff", darkcolor=COLORS["line"], focusthickness=0)
        style.map("TButton", background=[("active", COLORS["panel_alt"]), ("pressed", "#f2f2f7")])
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
                    bg="#ffffff",
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
                    bg="#ffffff",
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
                    bg="#ffffff",
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
                    bg="#ffffff",
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
                child.configure(bg=parent_bg, fg=COLORS["text"], activebackground=parent_bg, activeforeground=COLORS["text"], selectcolor="#ffffff")
            elif klass == "Canvas":
                if child is not getattr(self, "preview_canvas", None):
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
        action_box.columnconfigure(0, weight=1, uniform="actions")
        ttk.Button(action_box, text="检测游戏窗口", style="Primary.TButton", command=self._check_target).grid(row=0, column=0, sticky="ew", pady=(0, 10))
        ttk.Button(action_box, text="拿满奖励（15轮）", style="Primary.TButton", command=lambda: self._start_enabled_real(15)).grid(row=1, column=0, sticky="ew", pady=(0, 10))
        ttk.Button(action_box, text="拿满星声（13轮）", style="Primary.TButton", command=lambda: self._start_enabled_real(13)).grid(row=2, column=0, sticky="ew", pady=(0, 10))
        Button(action_box, text="停止当前任务", command=self._stop).grid(row=3, column=0, sticky="ew")

        Label(right, text="游戏窗口预览", font=("Microsoft YaHei UI", 12, "bold")).pack(anchor="w", pady=(12, 4))
        self.preview_canvas = Canvas(right, width=900, height=506, bg=COLORS["preview"], highlightthickness=1, highlightbackground=COLORS["line_soft"])
        self.preview_canvas.pack(anchor="w", pady=(0, 8))
        self.preview_canvas.create_text(
            210,
            120,
            text="点击“检测游戏窗口”后显示画面",
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
        self.template_group_combo.bind("<<ComboboxSelected>>", lambda _event: self._refresh_templates())
        Button(group_row, text="新建模板组", command=self._create_template_group).pack(side=LEFT, padx=(0, 8))
        Button(group_row, text="绑定到选中任务", command=self._assign_selected_task_group).pack(side=LEFT)

        Label(self.template_tab, text="当前已有模板", font=("Microsoft YaHei UI", 11, "bold")).pack(anchor="w")
        self.template_list = Listbox(self.template_tab, height=14, font=(FONT_FAMILY, 10))
        self.template_list.pack(fill=BOTH, expand=True, pady=6)

        Label(
            self.template_tab,
            text="提示：每个模板组是一套完整步骤图片，例如 menu1 到 menu99。切换任务时会自动切换对应模板组。",
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

        mode_row = Frame(self.settings_tab)
        mode_row.pack(fill=X, pady=5)
        Label(mode_row, text="操作目标", width=12, anchor="w").pack(side=LEFT)
        ttk.Radiobutton(mode_row, text="PC 客户端窗口", variable=self.target_mode, value="client", command=self._update_mode_label).pack(side=LEFT, padx=6)
        ttk.Radiobutton(mode_row, text="模拟器 / ADB", variable=self.target_mode, value="adb", command=self._update_mode_label).pack(side=LEFT, padx=6)

        client_row = Frame(self.settings_tab)
        client_row.pack(fill=X, pady=5)
        Label(client_row, text="窗口标题", width=12, anchor="w").pack(side=LEFT)
        Entry(client_row, textvariable=self.window_title, width=24).pack(side=LEFT, padx=6)
        Label(client_row, text="标题包含这些字就会被识别", fg="#697386").pack(side=LEFT)

        size_row = Frame(self.settings_tab)
        size_row.pack(fill=X, pady=5)
        Label(size_row, text="模板基准", width=12, anchor="w").pack(side=LEFT)
        Entry(size_row, textvariable=self.expected_resolution, width=24).pack(side=LEFT, padx=6)
        Label(size_row, text="模板按这个分辨率制作，窗口可等比例缩小，例如 1536x864", fg="#697386").pack(side=LEFT)

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

    def _build_log_tab(self) -> None:
        Label(self.log_tab, text="运行日志", font=("Microsoft YaHei UI", 13, "bold")).pack(anchor="w")
        self.log_text = Text(self.log_tab, wrap="word", font=(MONO_FONT, 10), relief="solid", bd=1)
        self.log_text.pack(fill=BOTH, expand=True, pady=8)
        Button(self.log_tab, text="清空日志", command=lambda: self.log_text.delete("1.0", END)).pack(anchor="e")

    def _show_update_notice(self) -> None:
        messagebox.showinfo(f"wwbs {APP_VERSION} 更新公告", UPDATE_NOTICE, parent=self.root)

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
        tasks = [task for task in self.tasks if task.enabled]
        if not tasks:
            messagebox.showinfo("提示", "没有需要执行的启用任务。")
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

    def _start_enabled_real(self, max_cycles: int | None = None) -> None:
        target = "PC 客户端窗口" if self.target_mode.get() == "client" else "模拟器 / ADB"
        if not messagebox.askyesno("确认开始", f"程序将操作 {target}。请确认游戏已打开并停在正确界面。"):
            return
        self.max_cycles = max_cycles
        self.dry_run.set(False)
        self._run_enabled()

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
        self.stop_event.clear()
        self.worker = threading.Thread(target=self._run_tasks, args=(tasks,), daemon=True)
        self.worker.start()

    def _run_tasks(self, tasks: list[WeeklyTask]) -> None:
        target = "PC 客户端窗口" if self.target_mode.get() == "client" else "模拟器 / ADB"
        self._log("预演模式：会识别模板，但不会点击。" if self.dry_run.get() else f"真实执行模式：将操作 {target}。")
        try:
            controller = self._make_controller()
            if hasattr(controller, "connect"):
                self._log(controller.connect())
            runner = TaskRunner(controller, self._log, self.dry_run.get(), self.stop_event, self.max_cycles)
            for task in tasks:
                runner.run_task(task)
            self._log("执行结束。")
        except Exception as exc:
            self._log(f"执行失败: {exc}")
        finally:
            self.max_cycles = None

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
        def work() -> None:
            try:
                if self.target_mode.get() == "adb":
                    output = AdbClient(self.adb_path.get(), self.device_id.get()).devices()
                    connected = [line for line in output.splitlines()[1:] if line.strip().endswith("device")]
                    self.device_status.set(f"已连接 {len(connected)} 台设备" if connected else "未发现可用设备")
                    self._log("ADB 设备列表:\n" + output)
                    if connected:
                        preview = APP_DIR / "_target_preview.png"
                        AdbClient(self.adb_path.get(), self.device_id.get()).screencap(preview)
                        self.root.after(0, lambda: self._show_preview(preview, "模拟器画面"))
                else:
                    controller = ClientWindowController(self.window_title.get(), self._parse_resolution())
                    message = controller.connect()
                    preview = APP_DIR / "_target_preview.png"
                    controller.screencap(preview)
                    self.device_status.set("已找到 PC 窗口")
                    self._log(message)
                    self.root.after(0, lambda: self._show_preview(preview, "PC 客户端画面"))
            except Exception as exc:
                self.device_status.set("检测失败")
                self._log(f"检测失败: {exc}")

        threading.Thread(target=work, daemon=True).start()

    def _screenshot(self) -> None:
        def work() -> None:
            try:
                target = APP_DIR / f"screenshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
                controller = self._make_controller()
                if hasattr(controller, "connect"):
                    self._log(controller.connect())
                controller.screencap(target)
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
                controller.screencap(target)
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

    def _drain_logs(self) -> None:
        while True:
            try:
                line = self.log_queue.get_nowait()
            except queue.Empty:
                break
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
    root = Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
