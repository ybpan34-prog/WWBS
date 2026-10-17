"""幻梦游园模板循环与周常收尾流程。"""

import re
import time
from dataclasses import replace
from pathlib import Path

import numpy as np
from PIL import Image

from tasks.models import Step
from tasks.weekly_rewards import WeeklyLimitReached, WeeklyRewardsVision


APP_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = APP_DIR / "templates"
DEFAULT_GROUP_NAME = "幻梦游园"
WEEKLY_TEMPLATE_THRESHOLD = 0.5
CYCLE_PROBE_ATTEMPTS = 2
CYCLE_PROBE_INTERVAL = 0.15
WEEKLY_CLICK_INTERVAL = 0.30
WEEKLY_RESPONSE_TIMEOUT = 4.0
CYCLE_FINAL_MAX_RETRIES = 2


class DreamlandTask:
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
        return not DreamlandTask._weekly_skill_slot_empty(screenshot)

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

    def _click_cycle_template(self, step: Step, x: int, y: int, recovery: bool = False):
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
        if (self._weekly_monitoring and self._weekly_observed_target is not None
                and self._weekly_observed_target.template == step.template):
            self._weekly_pending_click = self._weekly_observed_target
            self._weekly_click_at = time.monotonic()
        return result

    def _wait_weekly_click_response(self) -> bool:
        pending = self._weekly_pending_click
        if pending is None:
            return True
        remaining = self._weekly_click_at + WEEKLY_CLICK_INTERVAL - time.monotonic()
        if remaining > 0:
            self._sleep_interruptible(remaining)
        deadline = self._weekly_click_at + WEEKLY_RESPONSE_TIMEOUT
        screenshot = APP_DIR / '_runtime_screenshot.png'
        while not self.stop_event.is_set():
            self._capture_for_matching(screenshot)
            self._check_weekly_cap(screenshot)
            if self.stop_event.is_set():
                raise RuntimeError('周常已停止。')
            if pending.click_responded(screenshot, self.matcher):
                self._weekly_pending_click = None
                self.log(f"    已确认 {pending.template} 点击后画面有响应，再识别下一步。")
                return True
            if time.monotonic() >= deadline:
                self.log(f"    {pending.template} 点击后画面未确认变化，暂停推进，仅允许重新识别上一按钮。")
                return False
            self._sleep_interruptible(CYCLE_PROBE_INTERVAL)
        raise RuntimeError('周常已停止。')

    def _verify_final_cycle_click(self, final_step: Step) -> None:
        probe = replace(final_step, timeout=min(max(final_step.timeout, 0.5), 1.0))
        self.log(f"    最终轮验证：确认 {final_step.template} 已响应点击。")
        for retry_index in range(CYCLE_FINAL_MAX_RETRIES + 1):
            if self._weekly_monitoring:
                if self._weekly_pending_click is not None and self._wait_weekly_click_response():
                    self.log(f"    最终轮验证通过：{final_step.template} 点击后画面已响应。")
                    return
            try:
                x, y, score = self._find_image(probe)
            except WeeklyLimitReached:
                raise
            except Exception:
                if self._weekly_monitoring and self._weekly_pending_click is not None:
                    if self._wait_weekly_click_response():
                        self.log('    最终轮验证通过：点击响应已确认。')
                        return
                    self.stop_event.set()
                    raise RuntimeError(f'最终点击 {final_step.template} 未确认响应，已停止，不将遮罩或过渡帧当作完成。')
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
