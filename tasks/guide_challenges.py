"""Guide navigation for material domains and the opt-in story dialog task."""
import ctypes
from functools import lru_cache
from pathlib import Path
import time

import numpy as np
from PIL import Image

from combat_vision import enemy_health_bar_present
from image_matcher import _match_single_scale_gray
from tasks.combat_4c_entrance import EntranceFrame
from tasks.daily_checks import DailyStepChecks
from tasks.daily_team import team_start_target
from tasks.models import TaskNeedsReview
from windows_ocr import WindowsOcr


APP_DIR = Path(__file__).resolve().parent.parent
SCREENSHOT = APP_DIR / "_runtime_screenshot.png"


def _icon_edges(image):
    return np.hypot(*np.gradient(np.asarray(image, dtype=np.float64)))


@lru_cache(maxsize=12)
def _forgery_icon_edges(side):
    path = APP_DIR/'templates/daily/guide_forgery_icon.png'
    with Image.open(path) as source:
        return _icon_edges(source.convert('L').resize((side, side), Image.Resampling.LANCZOS))


def forgery_category(screenshot):
    """Find the crossed-tools glyph in the sidebar, including when its colors invert."""
    with Image.open(screenshot) as source:
        width, height = source.size
        left, top = round(width*.10), round(height*.14)
        region = source.crop((left, top, round(width*.15), round(height*.94))).convert('L')
        scene = _icon_edges(region)
        native_side = 61*width/1920
        for factor in (1., .97, 1.03):
            side = max(8, round(native_side*factor))
            if side >= min(scene.shape):
                continue
            icon = _match_single_scale_gray(scene, _forgery_icon_edges(side))
            if icon.score < .78:
                continue
            x, y = left+icon.center[0], top+icon.center[1]
            # The active card has a pale fill. Read its interior away from the
            # glyph and labels so a bright label on an inactive card can't pass.
            pad = round(height*.016)
            background = np.asarray(source.crop(
                (round(width*.267), y-pad, round(width*.315), y+pad)).convert('L'))
            selected = background.size > 0 and float((background > 150).mean()) >= .75
            return (x, y), selected
    return None


class GuideFrames:
    def __init__(self, runner, ocr):
        self.runner = runner
        self.ocr = ocr
        self.stamp = None
        self.frame = None

    def read(self, path):
        stamp = path.stat().st_mtime_ns
        if self.stamp != stamp:
            with Image.open(path) as source:
                image = source.copy()
            lines = self.ocr.recognize(path, cancelled=self.runner.stop_event.is_set)
            self.frame = EntranceFrame(image, lines)
            self.stamp = stamp
        return self.frame

    def tap(self, point):
        if point is None or self.runner.stop_event.is_set():
            return False
        self.runner.controller.tap(*point)
        return True


def _skip_target(frame, pending):
    if pending and frame.find('是否跳过', '确认跳过', '跳过后', region=(.20,.25,.80,.67)):
        button = frame.find('确认', '确定', '跳过', region=(.49,.52,.79,.78))
        return ('confirm', button.center) if button else (None, None)
    button = frame.find('跳过', region=(.015,.018,.20,.15))
    return ('skip', button.center) if button else (None, None)


def run_story_skip(runner):
    if runner.dry_run:
        return
    controller = runner.controller
    foreground = lambda: ctypes.windll.user32.GetForegroundWindow() == controller.hwnd
    ocr = WindowsOcr()
    frames = GuideFrames(runner, ocr)
    pending_until = next_click = 0.
    previous = None
    runner.log('    剧情跳过已开启。切回鸣潮后开始识别，关闭开关或按停止键可结束。')
    try:
        while not runner.stop_event.is_set():
            if not foreground():
                previous = None
                runner._sleep_interruptible(.5)
                continue
            controller.screencap(SCREENSHOT, bring_to_front=False, tolerate_blank=True)
            now = time.monotonic()
            target = _skip_target(frames.read(SCREENSHOT), now < pending_until)
            if (target[1] is not None and target == previous and now >= next_click
                    and foreground() and frames.tap(target[1])):
                pending_until = now+6 if target[0] == 'skip' else 0.
                next_click = now+.6
                previous = None
            else:
                previous = target
            runner._sleep_interruptible(.35)
    finally:
        ocr.close()


class ForgeryChallenge(GuideFrames):
    def __init__(self, runner, ocr, target):
        super().__init__(runner, ocr)
        self.target = target
        self.checks = DailyStepChecks(runner, SCREENSHOT)

    def guide(self, path):
        return self.read(path).find('索拉指南', '活跃行迹', '素材获取', region=(.01,.01,.36,.23))

    def challenge_prompt(self, path):
        if self.runner._overworld_hud_ready(path):
            return self.read(path).find('开启挑战', '开始挑战', region=(.47,.27,.90,.77))
        return None

    def battle(self, path):
        if not self.runner._overworld_hud_ready(path):
            return False
        with Image.open(path) as image:
            return enemy_health_bar_present(image)

    def loaded(self, path):
        runner = self.runner
        return (runner._overworld_hud_ready(path)
                and team_start_target(path) is None
                and runner.controller.active_character_slot(path) is not None)

    def detail_button(self, path):
        frame = self.read(path)
        if frame.find(self.target, region=(.30,.03,.98,.31)):
            return frame.find('开启挑战', '开始挑战', '前往挑战', '进入副本',
                              region=(.72,.75,.985,.99))
        return None

    def select_row(self, path):
        frame = self.read(path)
        title = frame.find(self.target, region=(.34,.13,.76,.93))
        if title is not None:
            height = frame.image.height
            row = title.center[1] / height
            button = frame.find('直接挑战', '前往', '传送',
                                region=(.75, max(.15,row-.035), .985, min(.91,row+.15)))
            if button is not None:
                return self.tap(button.center)
        x, y = round(frame.image.width*.90), round(frame.image.height*.62)
        controller = self.runner.controller
        x, y = controller.screenshot_to_client(x, y)
        controller.wheel_at(x, y, 120 if title is not None and row < .30 else -120 if title else -480)
        return True

    def enter(self):
        runner = self.runner
        runner._capture_for_matching(SCREENSHOT)
        if not runner._guide_material_page_present(SCREENSHOT):
            if not self.guide(SCREENSHOT):
                runner._open_terminal_destination('索拉指南')
            runner._click_daily_template('guide_battle_tab.png', '索拉指南战斗标签', threshold=.78,
                                         region_ratio=(.01,.10,.10,.88))
        def category(path):
            if runner._guide_material_page_present(path):
                return forgery_category(path)
            return None

        def open_category(path):
            state = category(path)
            return self.tap(state[0]) if state and not state[1] else False

        def selected(path):
            state = category(path)
            return bool(state and state[1])

        if not self.checks.transition('打开凝素领域列表', selected, open_category, timeout=16):
            return False
        deadline, next_click = time.monotonic()+45, 0.
        for _ in range(35):
            if runner.stop_event.is_set() or time.monotonic() >= deadline:
                return False
            runner._capture_for_matching(SCREENSHOT)
            team = team_start_target(SCREENSHOT)
            if team is not None:
                break
            if self.battle(SCREENSHOT) or self.challenge_prompt(SCREENSHOT):
                return True
            if time.monotonic() >= next_click:
                button = self.detail_button(SCREENSHOT)
                if button is not None:
                    self.tap(button.center)
                    next_click = time.monotonic()+1.5
                elif selected(SCREENSHOT):
                    self.select_row(SCREENSHOT)
                    next_click = time.monotonic()+.45
            runner._sleep_interruptible(.20)
        else:
            raise RuntimeError(f'未能确认凝素领域「{self.target}」的入口。')
        def start_team(path):
            target = team_start_target(path)
            return self.tap(target) if target is not None else False
        return self.checks.transition('进入凝素领域', self.loaded, start_team,
                                      require_action=True, timeout=60)

    def start_combat(self, *, approach):
        def interact(path):
            if self.read(path).find('体力不足', '结晶波片不足', region=(.20,.22,.80,.72)):
                raise TaskNeedsReview('凝素领域体力不足，已停止刷取。')
            if self.challenge_prompt(path):
                self.runner.controller.press_key('F', 100)
                return True
            return False
        def walk(path):
            if approach and self.loaded(path):
                self.runner.controller.press_keys(('W',), 350)
                return True
            return False
        return self.checks.transition('凝素领域战斗出现', self.battle, interact, timeout=35, recovery=walk)

    def claim_button(self, path):
        with Image.open(path) as image:
            width, height = image.size
        if self.runner._find_daily_template('reward_dialog_title.png', threshold=.83,
                screenshot=path, scales=[width/1920],
                region=(round(width*.21), round(height*.26), round(width*.40), round(height*.42))) is None:
            return None
        return self.read(path).find('单倍领取', '领取奖励', region=(.24,.53,.77,.75))

    def claim(self, cycle):
        button = self.claim_button(SCREENSHOT)
        if button is None or not self.tap(button.center):
            raise RuntimeError('未确认凝素领域的单倍领取按钮。')
        state = self.runner._wait_daily_claim_state(8)
        if state == 'refill':
            raise TaskNeedsReview('凝素领域体力不足，已停止刷取。')
        if state != 'success':
            raise RuntimeError('凝素领域未确认领取成功，请检查当前体力及结算页面。')
        self.runner.log(f'    凝素领域第{cycle}轮已领取奖励。')

    def run(self, step):
        if not self.enter():
            if not self.runner.stop_event.is_set():
                raise RuntimeError(f'等待凝素领域「{self.target}」入口超时。')
            return
        cycles = max(1, int(self.runner.max_cycles or 1))
        for cycle in range(1, cycles+1):
            if not self.start_combat(approach=True):
                return
            while not self.runner.stop_event.is_set():
                self.runner._run_tower_battle(step, SCREENSHOT, mode='forgery', end_check=self.battle_ended)
                if self.runner.stop_event.is_set():
                    return
                if self.runner._collect_daily_reward(cycle, claim_dialog=self.claim_button,
                                                     claim_reward=self.claim):
                    break
            if self.runner.stop_event.is_set():
                return
            self.runner._wait_for_daily_success(cycle)
            if cycle < cycles:
                self.runner._click_daily_settlement_action('restart')
                self.runner._daily_restart_pending = False

    def battle_ended(self, path):
        return self.runner._daily_battle_end_present(path, combat_visible=self.battle(path))


def run_forgery_challenge(runner, step):
    if runner.dry_run:
        return
    ocr = WindowsOcr()
    try:
        ForgeryChallenge(runner, ocr, step.text).run(step)
    finally:
        ocr.close()
        runner.controller.release_keys()
