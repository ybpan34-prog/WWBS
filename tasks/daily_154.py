"""Daily navigation restored from WWBS v1.5.4 (75c3eecb).

The adapter keeps the runner's current combat and reward-collection methods.
Only the reproduced pale-card false positive retains the text validation fix.
"""
from pathlib import Path
import time

import numpy as np
from PIL import Image

from image_matcher import TemplateMatcher
from tasks.models import Step
from tasks.runner import TaskRunner
from tasks.other import OtherTask
from tasks.weekly_rewards import WeeklyRewardsVision

APP_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = APP_DIR/'templates'

WEEKLY_TEMPLATE_THRESHOLD = 0.5

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


class Daily154Navigation:
    def __init__(self, runner):
        object.__setattr__(self, '_runner', runner)

    def __getattribute__(self, name):
        runner = object.__getattribute__(self, '_runner')
        if name not in ('_runner', '_run_daily_battle') and name in runner.__dict__:
            return getattr(runner, name)
        return object.__getattribute__(self, name)

    def _run_daily_battle(self, step, skill_key, ultimate_key, cycle_index):
        # Old navigation predates the current scheduler's restart marker.
        self._runner._daily_restart_pending = cycle_index > 1
        return self._runner._run_daily_battle(step, skill_key, ultimate_key, cycle_index)

    def __getattr__(self, name):
        return getattr(self._runner, name)

    def __setattr__(self, name, value):
        setattr(self._runner, name, value)

    def _capture_size(self, screenshot: Path | None = None) -> tuple[Path, int, int]:
        target = screenshot or (APP_DIR / "_runtime_screenshot.png")
        self._capture_for_matching(target)
        with Image.open(target) as captured:
            width, height = captured.size
        return target, width, height

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

    def _dismiss_reward_overlay_safely(self) -> None:
        # Both the stamina exchange success and item reward overlays explicitly
        # allow a blank-area click. Bottom-left is outside every item card.
        self._tap_ratio(0.13, 0.86, 0.18)

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

    _guide_tacet_section_selected = staticmethod(OtherTask._guide_tacet_section_selected)

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

    def _start_weekly_travel_from_selected_page(self) -> None:
        """Enter Dream Park from an already selected unfinished weekly page."""
        self._tap_ratio(0.247, 0.505, 0.8)
        self.template_root = TEMPLATES_DIR
        self.matcher.templates_dir = TEMPLATES_DIR
        self._wait_for_daily_template("menu1.png", timeout=12.0, threshold=WEEKLY_TEMPLATE_THRESHOLD)
        self._ensure_weekly_skill_selected()
        self.log("    小漂泊者界面准备完成，接续周常拿满奖励（15轮）。")
        self._run_default_weekly_from_daily()

    def _tap_ratio(self, x_ratio: float, y_ratio: float, pause: float = 1.0) -> None:
        _screenshot, width, height = self._capture_size()
        self.controller.tap(round(width * x_ratio), round(height * y_ratio))
        self._sleep_interruptible(pause)

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

    def _wait_for_daily_success(self, cycle_index: int) -> None:
        match = self._wait_for_daily_template(
            "challenge_success.png",
            timeout=15.0,
            threshold=0.64,
            region_ratio=(0.31, 0.20, 0.69, 0.43),
        )
        self.log(f"    第{cycle_index}轮挑战成功，相似度 {match.score:.3f}。")

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

    def _wait_for_weekly_skill_dialog(self, timeout: float = 5.0) -> None:
        screenshot = APP_DIR / "_runtime_screenshot.png"
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and not self.stop_event.is_set():
            self._capture_for_matching(screenshot)
            if self._weekly_skill_dialog_present(screenshot):
                return
            self._sleep_interruptible(0.12)
        raise RuntimeError("点击祝福技能槽后未出现四技能选择界面，已停止以避免误点。")

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

    @staticmethod
    def _weekly_skill_equipped(screenshot: Path) -> bool:
        """Any known weekly slot without the explicit plus sign is equipped."""
        return not TaskRunner._weekly_skill_slot_empty(screenshot)

    @staticmethod
    def _weekly_travel_page_present(screenshot: Path) -> bool:
        """Require the selected tab's text, not a pale training-target card."""
        return WeeklyRewardsVision(TEMPLATES_DIR / "weekly").weekly_page(screenshot)

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

