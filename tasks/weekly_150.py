"""Weekly execution copied from v1.5.0, commit 638a505716ac72c7778a1959a522b8b71632968a.

Only module imports, template storage location and the host entry adapters differ.
This runner does not inherit any newer task runner or weekly recognition code.
"""
import random
import re
import threading
import time
from dataclasses import replace
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from tasks.weekly_matcher_150 import TemplateMatcher
from tasks.models import Step, WeeklyTask

APP_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = APP_DIR/'templates'/'weekly150'
DEFAULT_GROUP_NAME = '幻梦游园'
CLICK_EDGE_MARGIN_RATIO = 0.10
CLICK_JITTER_RATIO = 0.25
CLICK_DELAY_JITTER_SECONDS = 0.20
CYCLE_MAX_MISSES = 5
CYCLE_FALLBACK_MISS_COUNTS = (2, 4)
CYCLE_FINAL_MAX_RETRIES = 2


class TaskRunner:
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


    def _capture_size(self, screenshot: Path | None = None) -> tuple[Path, int, int]:
        target = screenshot or (APP_DIR / "_runtime_screenshot.png")
        self._capture_for_matching(target)
        with Image.open(target) as captured:
            width, height = captured.size
        return target, width, height


    def _tap_ratio(self, x_ratio: float, y_ratio: float, pause: float = 1.0) -> None:
        _screenshot, width, height = self._capture_size()
        self.controller.tap(round(width * x_ratio), round(height * y_ratio))
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


ORIGINAL_TASK = {'name': '幻梦游园', 'enabled': True, 'weekday': 'any', 'description': '原版周本流程：先识别并点击 menu1，再依次循环 menu2 到 menu99；普通启动按钮按所选15轮或13轮执行。', 'template_group': 'default', 'steps': [{'action': 'tap_image', 'label': '先识别并点击 menu1', 'template': 'menu1.png', 'templates': [], 'loop': False, 'skip_missing': True, 'threshold': 0.82, 'timeout': 8, 'offset_x': 80, 'offset_y': 0, 'x': None, 'y': None, 'x2': None, 'y2': None, 'duration_ms': 300, 'seconds': 0.15, 'text': ''}, {'action': 'tap_image_cycle', 'label': '循环识别 menu2 到 menu99', 'template': '', 'templates': ['menu2.png', 'menu3.png', 'menu4.png', 'menu5.png', 'menu6.png', 'menu7.png', 'menu8.png', 'menu9.png', 'menu91.png', 'menu92.png', 'menu93.png', 'menu94.png', 'menu95.png', 'menu96.png', 'menu97.png', 'menu98.png', 'menu99.png'], 'loop': True, 'skip_missing': True, 'threshold': 0.82, 'timeout': 1, 'offset_x': 0, 'offset_y': 0, 'x': None, 'y': None, 'x2': None, 'y2': None, 'duration_ms': 300, 'seconds': 0.15, 'text': ''}]}


def original_task():
    return WeeklyTask(**{**ORIGINAL_TASK, 'steps': [Step(**step) for step in ORIGINAL_TASK['steps']]})


def from_host(host):
    runner = TaskRunner(host.controller, host.log, dry_run=host.dry_run,
                        stop_event=host.stop_event, max_cycles=host.max_cycles, notice=host.notice)
    runner.debug_matches = host.debug_matches
    return runner


def run_weekly(host):
    return from_host(host).run_task(original_task())


def continue_from_daily(host):
    return from_host(host)._start_weekly_travel_from_selected_page()
