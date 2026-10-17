"""一键日常、深塔挑战与视觉导航流程。"""

import threading
import time
from pathlib import Path

import numpy as np
from PIL import Image

from combat_rotation import BattleMonitor, IdleAttackWorker, RotationClock, SLOT_NAMES
from image_matcher import TemplateMatcher
from tasks.models import Step
from tasks.reward_orb_scan import ORB_DIRECT_CONFIDENCE, ORB_SCAN_STEP, OrbDirectionSweep
from tasks.weekly_rewards import WeeklyRewardsVision


APP_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = APP_DIR / "templates"
DAILY_REWARD_ORB_MIN_CONFIDENCE = 0.45

# “一键日常”无音区使用精确名称匹配。相似名称必须各自对应独立模板，
# 避免滑动列表时误点相邻条目；新增紧凑标题模板的按钮位置会略低。
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
DAILY_ZONE_BUTTON_Y_OFFSETS = {"zone_chenxin_yu.png": 37, "zone_jinxin_yu.png": 37}


class OtherTask:
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
                if getattr(self, '_daily_activity_confirmed_full', False):
                    self.log('    已确认当前活跃度达到100，跳过无音区战斗，直接领取任务与宝箱奖励。')
                    self._collect_daily_activity_rewards(already_open=True)
                    if self.stop_event.is_set():
                        return
                    self._collect_daily_battlepass_rewards()
                    if self.stop_event.is_set():
                        return
                    self._continue_daily_into_weekly_travel()
                    return
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
        if self._weekly_monitoring and template_crop is None:
            from tasks.weekly_clicks import weekly_template_crop
            template_crop = weekly_template_crop(template_name, self.matcher.templates_dir)
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
        """Confirm the activity page and a counter at or above the daily target."""
        screenshot = APP_DIR / "_runtime_screenshot.png"
        deadline = time.monotonic() + timeout
        confirmations = 0
        last_state: tuple[bool, bool] | None = None
        self._daily_activity_confirmed_full = False
        while time.monotonic() < deadline and not self.stop_event.is_set():
            self._capture_for_matching(screenshot)
            if not self._sola_guide_page_ready(screenshot):
                confirmations = 0
                self._sleep_interruptible(0.15)
                continue
            page = self._daily_activity_page_present(screenshot)
            full = page and self._daily_activity_score_full(screenshot)
            state = (page, full)
            confirmations = confirmations + 1 if state == last_state else 1
            last_state = state
            if confirmations >= 2:
                self._daily_activity_confirmed_full = bool(full)
                return page and not full
            self._sleep_interruptible(0.15)
        raise RuntimeError("进入索拉指南后未能确认当前页面，已停止以避免误打无音区。")

    def _open_daily_tacet_field(self, zone_template: str) -> bool:
        self.log("    打开索拉指南 → 素材获取 → 无音清剿。")
        self._open_terminal_destination("索拉指南", 0.515, 0.671)
        if not self._daily_activity_still_pending():
            screenshot = APP_DIR / "_runtime_screenshot.png"
            if getattr(self, '_daily_activity_confirmed_full', False):
                self.log('    当前活跃度已达到100（包含150等更高分数），无需再刷无音区。')
                return False
            if self._weekly_travel_page_present(screenshot):
                self.log("    索拉指南自动进入周度游历，今日日常已完成。")
                return False
            # The guide may reopen on its previously selected material page.
            # That page is not evidence that the daily activity is complete.
            self.log("    索拉指南未停留在活跃度页，尝试切回左侧活跃度入口。")
            self._tap_ratio(0.04, 0.18, 0.45)
            if not self._daily_activity_still_pending():
                if getattr(self, '_daily_activity_confirmed_full', False):
                    self.log('    已确认活跃度达到100，转入奖励领取。')
                    return False
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
        sweep = None
        approaching = False
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
                scan_image = captured.copy()
            if self.stop_event.is_set():
                break
            if prompt is not None:
                self.controller.release_keys()
                self.controller.press_key("F", 100)
                self.log(f"    第{cycle_index}轮：识别到“领取奖励”，已按 F。")
                self._sleep_interruptible(0.2)
                self._claim_daily_double_reward(cycle_index)
                return True
            valid = target_x is not None and density > DAILY_REWARD_ORB_MIN_CONFIDENCE
            stalled = self._daily_reward_movement_stalled(previous_forward_confidence, density)
            if valid and density > ORB_DIRECT_CONFIDENCE:
                approaching, sweep = True, None
                self.log(f"    光球置信度 {density:.2f} 超过0.80，直接前往。")
            elif not valid or stalled:
                approaching = False
            if not approaching:
                if sweep is None:
                    sweep = OrbDirectionSweep()
                    self.log("    开始水平转满一圈，记录各方向光球置信度；超过0.80时直接前往。")
                sweep.observe(scan_image, target_x, density)
                previous_forward_confidence = None
                if sweep.complete:
                    if sweep.best is not None:
                        self.log(f"    已转满一圈，选择最高置信度 {sweep.best.confidence:.2f} 的方向。")
                        self._turn_daily_reward_camera(sweep.return_delta())
                        approaching = True
                    else:
                        self.log("    已转满一圈，未找到有效光球，重新扫描。")
                    sweep = None
                    continue  # Fresh screenshot at the selected direction before moving.
                self.controller.move_mouse_relative(ORB_SCAN_STEP, 0)
                sweep.advance(ORB_SCAN_STEP)
            else:
                offset = target_x - width * 0.5
                if abs(offset) > width * 0.05:
                    self.controller.move_mouse_relative(int(max(-300, min(300, offset * 0.40))), 0)
                self.controller.press_keys(("W",), 500)
                self.log(f"    已定位白色奖励光球（核心密度 {density:.2f}），正在靠近。")
                previous_forward_confidence = density
            self._sleep_interruptible(0.22)
        raise RuntimeError("奖励阶段未找到“领取奖励”提示，已停止以避免误操作。")

    def _turn_daily_reward_camera(self, delta: int) -> None:
        while delta and not self.stop_event.is_set():
            step = max(-ORB_SCAN_STEP, min(ORB_SCAN_STEP, delta))
            self.controller.move_mouse_relative(step, 0)
            delta -= step
            self._sleep_interruptible(.12)

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
        from tasks.daily_activity import activity_counter_full
        return activity_counter_full(screenshot, TEMPLATES_DIR/'daily'/'activity_full.png')

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

    def _collect_daily_activity_rewards(self, *, already_open: bool = False) -> None:
        self.log(
            '    直接领取当前活跃行迹页面的奖励。'
            if already_open
            else "    返回大世界后，经终端进入索拉指南领取活跃度奖励；只点击黄色“领取”，不点击“前往”。"
        )
        if not already_open:
            self._open_terminal_destination("索拉指南", 0.515, 0.671, require_transition=True)
        # The guide can remember a different category. Select activity explicitly
        # and wait for its title rather than treating an unpainted frame as empty.
        if not already_open:
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

        if self.stop_event.is_set():
            return
        # A completed daily route earns enough activity. Claim the final chest
        # after the task rewards, regardless of the rendered counter (100/120/
        # 140/160 or a missed digit); it must not block a successful route.
        self.log("    上方任务奖励已领取，直接领取100宝箱；不再按活跃度数字拦截，其余里程碑奖励由游戏一并领取。")
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
