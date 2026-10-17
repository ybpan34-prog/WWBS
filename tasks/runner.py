"""任务调度与各流程共用能力。"""

import random
import threading
import time
from pathlib import Path

from PIL import Image, ImageDraw

from tasks.combat_4c import Combat4CTask
from tasks.combat_4c_entrance import BossChallengeEntrance
from tasks.dreamland import (DEFAULT_GROUP_NAME, WEEKLY_CLICK_INTERVAL,
                             WEEKLY_TEMPLATE_THRESHOLD, DreamlandTask)
from tasks.models import Step, WeeklyTask
from tasks.other import OtherTask
from tasks.weekly_rewards import WeeklyLimitReached
from combat_rotation import active_modules, default_store
from image_matcher import TemplateMatcher


APP_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = APP_DIR / "templates"
CLICK_EDGE_MARGIN_RATIO = 0.10
CLICK_JITTER_RATIO = 0.25
CLICK_DELAY_JITTER_SECONDS = 0.20
WEEKLY_CLICK_JITTER = 0.02
WEEKLY_STABLE_INTERVAL = 0.15


class TaskRunner(Combat4CTask, DreamlandTask, OtherTask):
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
        boss_challenge: BossChallengeEntrance | None = None,
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
        self.boss_challenge = boss_challenge
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
        self._weekly_observed_target = None
        self._weekly_pending_click = None
        self._weekly_click_at = 0.

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
            self.log(f"周常阈值：{WEEKLY_TEMPLATE_THRESHOLD:.2f}，连续截图稳定后点击；每步先确认上一点击响应。")
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
                result = (self._click_cycle_template(step, x, y) if self._weekly_monitoring
                          else self.controller.tap(x, y))
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

    def _sleep_interruptible(self, seconds: float) -> None:
        deadline = time.time() + seconds
        while time.time() < deadline:
            if self.stop_event.is_set():
                return
            time.sleep(min(0.1, deadline - time.time()))

    def _sleep_click_interval(self, base_seconds: float) -> None:
        jitter = CLICK_DELAY_JITTER_SECONDS
        if self._weekly_monitoring:
            base_seconds = WEEKLY_CLICK_INTERVAL
            jitter = WEEKLY_CLICK_JITTER
        minimum = max(0.0, base_seconds - jitter)
        maximum = max(minimum, base_seconds + jitter)
        self._sleep_interruptible(random.uniform(minimum, maximum))

    def _find_image(self, step: Step, *, single_attempt: bool = False) -> tuple[int, int, float]:
        if not step.template:
            raise ValueError("tap_image 步骤需要 template 字段")
        deadline = time.time() + step.timeout
        last_error: Exception | None = None
        weekly = self._weekly_monitoring
        if (weekly and not self.dry_run and self._weekly_pending_click is not None
                and step.template != self._weekly_pending_click.template
                and not self._wait_weekly_click_response()):
            raise RuntimeError('上一点击未确认响应，不点击下一步；进入限次重新识别。')
        previous_target = None
        frames = 0
        while single_attempt or time.time() <= deadline:
            if self.stop_event.is_set():
                raise RuntimeError("已停止模板识别。")
            screenshot = APP_DIR / "_runtime_screenshot.png"
            self._capture_for_matching(screenshot)
            frames += 1
            if self._weekly_monitoring and not self.dry_run:
                self._check_weekly_cap(screenshot)
            try:
                scales = self._fast_scales()
                if self._weekly_monitoring:
                    from tasks.weekly_clicks import WeeklyTarget, weekly_template_crop
                    crop = weekly_template_crop(step.template, self.matcher.templates_dir)
                    options = {'template_crop': crop} if crop is not None else {}
                    match = self.matcher.find(screenshot, step.template, WEEKLY_TEMPLATE_THRESHOLD,
                                              scales, first_match=True, **options)
                    target = WeeklyTarget.read(screenshot, step.template, match, self.matcher.templates_dir, crop)
                    if target.colour_error > 45:
                        raise RuntimeError(f'{step.template} 颜色与模板明显不同，等待过渡或遮罩结束。')
                    stable = previous_target is not None and previous_target.stable_with(target)
                    if not stable:
                        previous_target = target
                        if single_attempt and frames >= 2:
                            raise RuntimeError(f'{step.template} 连续截图位置或画面未稳定，暂不点击。')
                        self._sleep_interruptible(WEEKLY_STABLE_INTERVAL)
                        continue
                    self._weekly_observed_target = target
                else:
                    match = self.matcher.find(screenshot, step.template, step.threshold, scales)
                offset_x = 0 if weekly and crop is not None and step.template == 'menu1.png' and step.offset_x == 80 else step.offset_x
                image_x, image_y = self._random_click_point(match, offset_x, step.offset_y,
                    jitter_ratio=.05) if weekly else self._random_click_point(match, step.offset_x, step.offset_y)
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
                previous_target = None
                self._sleep_interruptible(.15 if weekly else .6)
        raise RuntimeError(str(last_error) if last_error else f"识别超时: {step.template}")

    @staticmethod
    def _random_click_point(match, offset_x: int, offset_y: int, *, jitter_ratio=CLICK_JITTER_RATIO) -> tuple[int, int]:
        margin_x = min(max(1, int(round(match.width * CLICK_EDGE_MARGIN_RATIO))), max(1, (match.width - 1) // 2))
        margin_y = min(max(1, int(round(match.height * CLICK_EDGE_MARGIN_RATIO))), max(1, (match.height - 1) // 2))
        safe_left = match.x + margin_x
        safe_right = match.x + match.width - 1 - margin_x
        safe_top = match.y + margin_y
        safe_bottom = match.y + match.height - 1 - margin_y

        anchor_x = min(max(match.center[0] + offset_x, safe_left), safe_right)
        anchor_y = min(max(match.center[1] + offset_y, safe_top), safe_bottom)
        jitter_x = max(1, int(round(match.width * jitter_ratio)))
        jitter_y = max(1, int(round(match.height * jitter_ratio)))

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
