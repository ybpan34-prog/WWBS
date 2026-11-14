"""Keep the 1.5.4 route, adding explicit confirmation around its transitions."""
from pathlib import Path
import time

import numpy as np
from PIL import Image

from combat_vision import enemy_health_bar_present
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
        if callable(getattr(type(self.controller), 'tap_team_guarded', None)):
            try:
                self.controller.tap_team_guarded(*point)
            except RuntimeError as error:
                self.log(f'    点击前复核未通过，重新定位：{error}')
                return False
            return not self.stop_event.is_set()
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
        # The third character's portrait/name ends above this bottom strip.
        left, top = round(width*.76), round(height*.86)
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
        x1, x2, y1, y2 = round(width*.76), round(width*.98), round(height*.86), round(height*.97)
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

    def _tap_start(self, path):
        point = self._start_target(path)
        if point is None:
            return False
        with Image.open(path) as source:
            width, height = source.size
        if not (width*.78 <= point[0] <= width*.98 and height*.86 <= point[1] <= height*.97):
            return False
        if self.stop_event.is_set():
            return False
        if callable(getattr(type(self.controller), 'tap_precise', None)):
            try:
                self.controller.tap_precise(*point)
            except RuntimeError as error:
                self.log(f'    开启挑战点击未确认，重新截图定位：{error}')
                return False
            return not self.stop_event.is_set()
        return self._tap(point)

    def _locate_zone_row(self, path, template, width, height):
        if template in DAILY_ZONE_BUTTON_Y_OFFSETS:
            result = self._find_new_daily_zone(path, template)
            if result is None:
                return None, None
            title, button = result
            point = button.center if button and height*.20 < button.center[1] < height*.88 else None
            return title, point

        numbered = template in ('zone_huangshi_gaodi_1.png', 'zone_huangshi_gaodi_2.png')
        threshold = .97 if numbered else .88
        if template == 'zone_luori_diyu.png':
            # The recorded title scores about .82 even when the full row is visible.
            threshold = .80
        base = self._fast_scales()[0]
        title = self._find_daily_template(template, threshold=threshold, screenshot=path,
            template_crop=(6, 18, 304 if numbered else 201, 58),
            scales=[base, base*.97, base*1.03],
            region=(round(width*.36), round(height*.16), round(width*.71), round(height*.92)))
        if title is None:
            return None, None
        y = title.center[1]
        # The button is commonly lower than the title, within the same card.
        # Restrict both the search and the accepted click to that card's span.
        top = max(round(height*.19), y-round(height*.022))
        bottom = min(round(height*.885), y+round(height*.080))
        if bottom-top < round(height*.024):
            return title, None
        for name, scale in (('zone_direct_challenge.png', base), ('zone_go_native.png', base*1600/1920)):
            button = self._find_daily_template(name, threshold=.78 if template == 'zone_luori_diyu.png' else .80, screenshot=path,
                scales=[scale, scale*.94, scale*1.06],
                region=(round(width*.79), top, round(width*.97), bottom))
            if button and self._runner._daily_row_button_ready(
                    path, button.center[1], center_x=button.center[0], matched_label=True):
                return title, button.center
        return title, None

    def _enter_zone(self, zone_template):
        def source_action(path):
            if team_start_target(path) is not None or not tacet_card_list_present(path):
                return False
            if not self._runner._guide_tacet_section_selected(path, self._ratio_point(path, 0, .73)[1]):
                return False
            with Image.open(path) as image:
                width, height = image.size
            _title, point = self._locate_zone_row(path, zone_template, width, height)
            return point is not None and self._tap(point)
        return self._checks.transition('进入所选无音区的队伍页面',
            lambda p: self._restart_battle_visible(p) or self._start_target(p) is not None,
            source_action, timeout=35, capture=lambda path: self._capture_for_matching(path, loading=True))

    def _tap_ratio(self, x_ratio, y_ratio, pause=1.):
        if abs(x_ratio-.86) < .005 and abs(y_ratio-.92) < .005:
            ready = self._checks.transition('开启挑战并进入战斗', self._restart_battle_visible,
                self._tap_start,
                timeout=90, capture=lambda path: self._capture_for_matching(path, loading=True))
            self._runner._daily_entry_ready = ready
            return ready
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
            self._runner._daily_restart_confirmed = False
            self._runner._daily_restart_ready = False
            self._runner._click_daily_settlement_action('restart', wait_for_disappearance=False)
            path = self._checks.screenshot
            deadline = time.monotonic()+60
            next_confirm = 0.
            next_restart = time.monotonic()+1.8
            restarts = 1
            while time.monotonic() < deadline and not self.stop_event.is_set():
                self._capture_for_matching(path)
                if self.stop_event.is_set():
                    return False
                prompt = self._match(path, 'insufficient_continue.png', .82)
                if prompt is not None:
                    if time.monotonic() >= next_confirm and self._tap(prompt.center):
                        self.log('    已确认体力不足继续挑战，等待战斗画面。')
                        next_confirm = time.monotonic()+1.2
                else:
                    settled = self._runner._read_daily_settlement(path)
                    if settled is None and self._restart_battle_visible(path):
                        self._runner._daily_restart_confirmed = True
                        self._runner._daily_restart_ready = True
                        return True
                    if settled is not None and restarts < 3 and time.monotonic() >= next_restart:
                        if self._tap(settled.restart.center):
                            restarts += 1
                            next_restart = time.monotonic()+1.8
                self._sleep_interruptible(.12)
            if self.stop_event.is_set():
                return False
            raise RuntimeError('重开后未确认下一轮战斗画面。')
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

    def _restart_battle_visible(self, path):
        if self._battle(path):
            return True
        if not self._runner._overworld_hud_ready(path):
            return False
        with Image.open(path) as image:
            return enemy_health_bar_present(image)

    def _click_optional_daily_template(self, template_name, label, *, timeout=3., threshold=.72):
        if self.stop_event.is_set():
            return False
        if template_name == 'insufficient_continue.png' and getattr(self._runner, '_daily_restart_confirmed', False):
            self._runner._daily_restart_confirmed = False
            self.log('    已确认进入第二轮，立即接续战斗。')
            return False
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
        previous_panel = None
        search_direction = -1
        reversed_search = False
        stationary = 0
        partial_attempts = 0
        for _ in range(40):
            if self.stop_event.is_set():
                return False
            _path, width, height = self._capture_size(screenshot)
            title, point = self._locate_zone_row(screenshot, zone_template, width, height)
            if point is not None:
                self.log(f"    已定位「{self.daily_zone_name}」同行按钮，复核后点击。")
                if not self._enter_zone(zone_template):
                    return False
                self.log("    队伍界面点击“开启挑战”，不修改队伍。")
                return self._tap_ratio(.86, .92, 5.0)

            with Image.open(screenshot) as image:
                panel = image.crop((round(width*.37), round(height*.19),
                                    round(width*.96), round(height*.88))).convert('L')
                sample = np.asarray(panel.resize((64, 48)), dtype=np.int16)
            stationary = stationary+1 if previous_panel is not None and np.abs(sample-previous_panel).mean() < 1.5 else 0
            previous_panel = sample
            if title is not None:
                partial_attempts += 1
                if partial_attempts > 6 or stationary >= 2:
                    raise RuntimeError(f'已找到「{self.daily_zone_name}」，但同一行的挑战按钮无法确认。')
                # Move the card toward the middle. At the middle, a missing
                # button is not evidence that scrolling would make it appear.
                row_y = title.center[1]/height
                if .34 <= row_y <= .66:
                    self._sleep_interruptible(.35)
                    continue
                scroll = 120 if row_y < .34 else -120
            else:
                if stationary >= 2:
                    if reversed_search:
                        break
                    search_direction = 1
                    reversed_search = True
                    stationary = 0
                scroll = 120*search_direction
            x, y = round(width*.91), round(height*.60)
            if hasattr(self.controller, 'screenshot_to_client'):
                x, y = self.controller.screenshot_to_client(x, y)
            self.controller.wheel_at(x, y, scroll)
            self._sleep_interruptible(.40)
        if self.stop_event.is_set():
            return False
        raise RuntimeError(f'无音清剿列表中未确认「{self.daily_zone_name}」的挑战入口。')
