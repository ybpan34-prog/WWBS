"""Keep the 1.5.4 route, adding explicit confirmation around its transitions."""
from pathlib import Path
import time

import numpy as np
from PIL import Image

from tasks.daily_154 import (Daily154Navigation, DAILY_ZONE_BUTTON_Y_OFFSETS)
from tasks.daily_checks import DailyStepChecks
from tasks.daily_radio import DailyRadioVision
from tasks.daily_team import team_start_target
from tasks.weekly_rewards import WeeklyRewardsVision
from tasks.terminal_navigation import terminal_target
from tasks.tacet_navigation import tacet_card_list_present
from tasks.combat_4c_entrance import EntranceFrame
from windows_ocr import WindowsOcr


ROOT = Path(__file__).resolve().parent.parent
APP_DIR = ROOT


class VerifiedDailyNavigation(Daily154Navigation):
    def __init__(self, runner):
        super().__init__(runner)
        object.__setattr__(self, '_checks', DailyStepChecks(runner))
        object.__setattr__(self, '_ocr', None)
        object.__setattr__(self, '_ocr_unavailable', False)

    def _run_daily_routine(self, step):
        try:
            return super()._run_daily_routine(step)
        finally:
            if self._ocr is not None:
                self._ocr.close()

    def _terminal(self, path):
        return terminal_target(path, ROOT/'templates/daily', '索拉指南') is not None

    def _panel(self, path, label='索拉指南'):
        return self._runner._terminal_destination_ready(path, label)

    def _battle(self, path):
        return self._runner._overworld_hud_ready(path) and self._runner._daily_combat_visible(path)

    def _world(self, path):
        if not self._runner._overworld_hud_ready(path):
            return False
        # Team portraits and the pale action buttons can satisfy the coarse HUD
        # brightness checks, regardless of which characters occupy the slots.
        if team_start_target(path) is not None:
            return False
        # Radio weapon art/menu icons can satisfy the coarse HUD brightness
        # check. A known open menu must not acknowledge "returned to world".
        if self._panel(path, '先约电台') or self._panel(path) or self._terminal(path):
            return False
        return (not self._runner._daily_combat_visible(path)
                and self._runner._read_daily_settlement(path) is None)

    def _normal(self, path):
        return (self._world(path) or self._battle(path) or self._panel(path) or self._panel(path, '先约电台')
                or self._terminal(path) or self._runner._read_daily_settlement(path) is not None)

    def _tap(self, point):
        if self.stop_event.is_set():
            return False
        self.controller.tap(*point)
        return True

    def _ratio_point(self, path, x, y):
        with Image.open(path) as image:
            return round(image.width*x), round(image.height*y)

    def _match(self, path, template, threshold=.8):
        match = self._find_daily_template(template, threshold=threshold, screenshot=path)
        if match is not None and template == 'one_click_claim.png':
            with Image.open(path) as image:
                patch = np.asarray(image.crop((match.x, match.y, match.x+match.width, match.y+match.height)).convert('RGB'), dtype=np.int16)
            gold = (patch[:, :, 0] > 150) & (patch[:, :, 1] > 120) & (patch[:, :, 0]-patch[:, :, 2] > 25)
            if float(gold.mean()) < .015:
                return None  # Disabled grey claim buttons are not pending rewards.
        return match

    def _open_menu(self):
        def action(path):
            if not self._world(path) or self.stop_event.is_set():
                return False
            self.controller.press_key('ESC', 70)
            return True
        return self._checks.transition('打开终端菜单', self._terminal, action)

    def _enter(self, label):
        def action(path):
            point = terminal_target(path, ROOT/'templates/daily', label)
            return self._tap(point) if point is not None else False
        return self._checks.transition('进入'+label, lambda p: self._panel(p, label), action)

    def _open_terminal_destination(self, label, x_ratio=None, y_ratio=None, *, require_transition=False):
        if self._open_menu():
            return self._enter(label)
        return False

    def _close_page(self):
        def action(path):
            if not (self._panel(path) or self._panel(path, '先约电台')):
                return False
            match = self._match(path, 'guide_close.png', .87)
            if match is None:
                match = DailyRadioVision(ROOT/'templates/daily').close(path)
            return self._tap(match.center) if match else False
        return self._checks.transition('退出页面并返回终端／大世界',
                                       lambda p: self._terminal(p) or self._world(p), action)

    def _start_target(self, path):
        target = team_start_target(path)
        if target is not None:
            return target
        if self._world(path) or self._battle(path) or self._runner._read_daily_settlement(path) is not None:
            return None
        with Image.open(path) as source:
            image = source.convert('RGB')
        width, height = image.size
        left, top = round(width*.55), round(height*.72)
        cropped = image.crop((left, top, round(width*.99), round(height*.99)))
        if not self._ocr_unavailable:
            try:
                if self._ocr is None:
                    object.__setattr__(self, '_ocr', WindowsOcr())
                crop_path = ROOT/'_daily_start_check.png'
                cropped.save(crop_path)
                lines = self._ocr.recognize(crop_path, cancelled=self.stop_event.is_set, timeout=2)
                box = EntranceFrame(cropped, lines).find('开启挑战', '开始挑战')
                if box:
                    return box.center[0]+left, box.center[1]+top
            except (OSError, RuntimeError):
                object.__setattr__(self, '_ocr_unavailable', True)
                if self._ocr is not None:
                    self._ocr.close()
                    object.__setattr__(self, '_ocr', None)
        # A fallback is restricted to the known post-zone-selection step and
        # requires a distinct, text-bearing pale button, not an arbitrary point.
        if tacet_card_list_present(path) or self._terminal(path):
            return None
        rgb = np.asarray(image)
        x1, x2, y1, y2 = round(width*.72), round(width*.98), round(height*.83), round(height*.97)
        area = rgb[y1:y2, x1:x2]
        pale = (area.min(axis=2) > 155) & (area.max(axis=2)-area.min(axis=2) < 100)
        rows = np.flatnonzero(pale.mean(axis=1) > .55)
        if not len(rows):
            return None
        groups = np.split(rows, np.flatnonzero(np.diff(rows) > 2)+1)
        for group in groups:
            if not height*.028 <= len(group) <= height*.10:
                continue
            columns = np.flatnonzero(pale[group[0]:group[-1]+1].mean(axis=0) > .55)
            if not len(columns) or columns[-1]-columns[0] < width*.12:
                continue
            button = area[group[0]:group[-1]+1, columns[0]:columns[-1]+1]
            ink = float((button.max(axis=2) < 110).mean())
            if .01 < ink < .25:
                return x1+int((columns[0]+columns[-1])//2), y1+int((group[0]+group[-1])//2)
        return None

    def _enter_zone(self, zone_template):
        def source_action(path):
            if not self._runner._guide_tacet_section_selected(path, self._ratio_point(path, 0, .73)[1]):
                return False
            if zone_template in ('zone_chenxin_yu.png', 'zone_jinxin_yu.png'):
                found = self._find_new_daily_zone(path, zone_template)
                return self._tap(found[1].center) if found and found[1] is not None else False
            with Image.open(path) as image:
                width, height = image.size
            numbered = zone_template in ('zone_huangshi_gaodi_1.png', 'zone_huangshi_gaodi_2.png')
            title = self._find_daily_template(zone_template, threshold=.97 if numbered else .9, screenshot=path,
                template_crop=(6, 18, 304 if numbered else 190, 64), scales=[self._fast_scales()[0]],
                region=(round(width*.34), round(height*.12), round(width*.98), round(height*.92)))
            if title is not None and self._daily_row_button_ready(path, title.center[1]):
                return self._tap((round(width*.895), title.center[1]))
            return False
        return self._checks.transition('进入所选无音区的队伍页面',
            lambda p: self._battle(p) or self._start_target(p) is not None, source_action, timeout=35)

    def _tap_ratio(self, x_ratio, y_ratio, pause=1.):
        if abs(x_ratio-.86) < .005 and abs(y_ratio-.92) < .005:
            return self._checks.transition('开启挑战并进入战斗', self._battle,
                lambda p: self._tap(point) if (point := self._start_target(p)) is not None else False,
                timeout=60)
        if abs(x_ratio-.957) < .005 and abs(y_ratio-.058) < .005:
            return self._close_page()
        if abs(x_ratio-.744) < .005 and abs(y_ratio-.257) < .005:
            self._open_menu()
            return self._enter('先约电台')
        if abs(x_ratio-.515) < .005 and abs(y_ratio-.671) < .005:
            self._open_menu()
            return self._enter('索拉指南')
        if abs(x_ratio-.039) < .005 and abs(y_ratio-.174) < .012:
            return self._checks.transition('打开活跃行迹',
                lambda p: self._match(p, 'activity_title.png', .82) is not None and self._daily_activity_page_present(p),
                lambda p: self._tap(self._ratio_point(p, x_ratio, y_ratio)) if self._panel(p) else False)
        if abs(x_ratio-.945) < .005 and abs(y_ratio-.868) < .005:
            result = self._checks.transition('活跃度里程碑领取后的页面',
                lambda p: self._match(p, 'activity_title.png', .82) is not None and not self._yellow_claim_rows(p),
                lambda p: self._tap(self._ratio_point(p, x_ratio, y_ratio))
                    if self._match(p, 'activity_title.png', .82) is not None else False,
                require_action=True, recovery=lambda p: self._tap(self._ratio_point(p, .13, .86)))
            return result
        return super()._tap_ratio(x_ratio, y_ratio, pause)

    def _collect_daily_activity_rewards(self):
        if not self._open_terminal_destination('索拉指南') or self.stop_event.is_set():
            return
        if not self._tap_ratio(.039, .174) or self.stop_event.is_set():
            return
        path = self._checks.screenshot
        for _ in range(36):
            if self.stop_event.is_set():
                return
            self._capture_for_matching(path)
            rows = self._yellow_claim_rows(path)
            if not rows:
                self._sleep_interruptible(.2)
                self._capture_for_matching(path)
                if not self._yellow_claim_rows(path) and self._match(path, 'activity_title.png', .82):
                    break
                continue
            count, row_y = len(rows), rows[0]
            def action(screen):
                fresh = self._yellow_claim_rows(screen)
                return self._tap((self._ratio_point(screen, .88, 0)[0], fresh[0])) if fresh else False
            def claimed(screen):
                fresh = self._yellow_claim_rows(screen)
                return self._match(screen, 'activity_title.png', .82) is not None and (
                    len(fresh) < count or all(abs(y-row_y) > 25 for y in fresh))
            self._checks.transition('领取当前黄色任务奖励', claimed, action, require_action=True,
                recovery=lambda p: self._tap(self._ratio_point(p, .13, .86)) if not self._normal(p) else False)
        else:
            raise RuntimeError('已逐项复核36次，任务奖励尚未清空；未提前推进。')
        if self.stop_event.is_set():
            return
        self.log('    已复核上方任务奖励，领取100里程碑；不按显示数字拦截。')
        self._tap_ratio(.945, .868)
        if self.stop_event.is_set():
            return
        self._dismiss_reward_overlay_safely()
        self._close_page()

    def _click_daily_template(self, template_name, label, *, timeout=10., threshold=.72, region_ratio=None):
        def source_action(path):
            match = self._match(path, template_name, threshold)
            return self._tap(match.center) if match is not None else False
        if template_name == 'guide_battle_tab.png':
            destination = lambda p: self._guide_material_page_present(p) or (
                self._runner._guide_tacet_section_selected(p, self._ratio_point(p, 0, .73)[1]) and tacet_card_list_present(p))
        elif template_name == 'restart_challenge.png':
            self._runner._daily_restart_pending = True
            def recover(path):
                prompt = self._match(path, 'insufficient_continue.png', .82)
                return self._tap(prompt.center) if prompt is not None else False
            return self._checks.transition('重开后进入下一轮战斗', self._battle, source_action,
                                           timeout=60, recovery=recover)
        elif template_name == 'exit_instance.png':
            def recover(path):
                return self._tap(self._ratio_point(path, .657, .628)) if self._daily_exit_confirmation_present(path) else False
            return self._checks.transition('退出副本并回到大世界', self._world, source_action,
                                           timeout=45, recovery=recover)
        else:
            # Claim buttons can become disabled without disappearing. Confirm
            # the return to the same known page; callers recheck remaining claims.
            destination = lambda p: self._match(p, template_name, threshold) is None and self._normal(p)
        return self._checks.transition(label, destination, source_action, timeout=max(12, timeout),
            recovery=lambda p: self._tap(self._ratio_point(p, .13, .86))
                if template_name == 'one_click_claim.png' and not self._normal(p) else False)

    def _click_optional_daily_template(self, template_name, label, *, timeout=3., threshold=.72):
        missing = 0
        deadline = time.monotonic()+timeout
        while time.monotonic() < deadline and not self.stop_event.is_set():
            self._capture_for_matching(self._checks.screenshot)
            if self._match(self._checks.screenshot, template_name, threshold) is not None:
                self._click_daily_template(template_name, label, timeout=timeout, threshold=threshold)
                return True
            missing = missing+1 if self._normal(self._checks.screenshot) else 0
            if missing >= 2:
                self.log(f'    已复核「{label}」当前无可领取／确认按钮，继续。')
                return False
            self._sleep_interruptible(.2)
        if self.stop_event.is_set():
            return False
        raise RuntimeError(f'未确认「{label}」是否可领取，已等待并复核，保留当前页面。')

    def _dismiss_reward_overlay_safely(self):
        return self._checks.transition('奖励提示关闭并返回原页面', self._normal,
            lambda p: self._tap(self._ratio_point(p, .13, .86)))

    def _wait_for_daily_success(self, cycle_index):
        return self._checks.transition(f'第{cycle_index}轮挑战成功结算',
                                      lambda p: self._runner._read_daily_settlement(p) is not None, timeout=25)

    def _wait_daily_battlepass_tab(self, tab):
        # Reuse its existing selected-icon + page-title confirmation.
        return self._runner._wait_daily_battlepass_tab(tab)

    def _continue_daily_into_weekly_travel(self):
        self.log('    电台领取结束，返回索拉指南复核周常完成情况。')
        if self.stop_event.is_set() or not self._open_terminal_destination('索拉指南'):
            return
        self._continue_daily_from_open_guide_page()

    def _continue_daily_from_open_guide_page(self):
        state = ['']
        def classify(screen):
            if not self._panel(screen):
                state[0] = ''
                return False
            current = ('completed' if self._weekly_completion_confirmed(screen) else
                       'pending' if self._weekly_travel_page_present(screen) else '')
            stable = bool(current) and state[0] == current
            state[0] = current
            return stable
        # Reopen the activity entry if the guide remembered its material page.
        # Only an explicit completed check, never an unknown page, skips weekly.
        def select_progress(screen):
            if not state[0] and self._panel(screen):
                return self._tap(self._ratio_point(screen, .039, .174))
            return False
        if not self._checks.transition('周常完成状态', classify, select_progress):
            return
        if self.stop_event.is_set():
            return
        if state[0] == 'completed':
            self.log('    已复核周度游历完成勾，本周周常已完成。')
            self._close_page()
        else:
            self.log('    已复核周度游历仍未完成，接入1.5.0周常流程。')
            self._start_weekly_travel_from_selected_page()

    def _start_weekly_travel_from_selected_page(self):
        from tasks.weekly_150 import continue_from_daily
        return continue_from_daily(self._runner)

    def _weekly_completion_confirmed(self, screen):
        # A light patch on a material card is not a completion check.
        return self._weekly_travel_completed(screen) and WeeklyRewardsVision(ROOT/'templates/weekly').matches(
            screen, 'weekly_tab.png', (540, 105, 745, 195), threshold=.78)


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
                    self._enter_zone(zone_template)
                    self._sleep_interruptible(.15)
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
                self._sleep_interruptible(0.32)
                self.log(
                    f"    精确找到“{self.daily_zone_name}”（第{page_index + 1}屏，相似度 {found.score:.3f}），"
                    "点击同一行的直接挑战/前往。"
                )
                self._enter_zone(zone_template)
                self._sleep_interruptible(.15)
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
