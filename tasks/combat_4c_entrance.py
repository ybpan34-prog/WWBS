"""Verified entrance for the separate Warsong shortcut, based on PR #18."""
from dataclasses import dataclass
from pathlib import Path
import re
import time

import numpy as np
from PIL import Image

from boss_rain import boss_bar_present
from windows_ocr import WindowsOcr


BOSS_AVATARS = {
    '定序诸理之律': 'warsong_dingxu_zhuli.png',
    '失坠困智之庭': 'warsong_shizhui_kunzhi.png',
    '虚妄诞生之神': 'warsong_xuwang_dansheng.png',
}


def normalized(text):
    return re.sub(r'[^\w]', '', str(text)).lower()


@dataclass(frozen=True)
class TextBox:
    text: str
    x: float
    y: float
    width: float
    height: float

    @property
    def center(self):
        return round(self.x+self.width/2), round(self.y+self.height/2)


@dataclass
class EntranceFrame:
    image: object
    lines: list
    battle: bool = False

    def find(self, *texts, region=(0,0,1,1)):
        width, height = self.image.size
        for line in self.lines:
            chars, owners = '', []
            for word in line.get('words', []):
                value = normalized(word.get('text', ''))
                chars += value
                owners.extend([word]*len(value))
            for text in texts:
                token = normalized(text)
                matches = list(re.finditer(re.escape(token),chars)) if token else []
                if not matches:
                    continue
                for match in matches:
                    words = owners[match.start():match.end()]
                    left, top = min(w['x'] for w in words), min(w['y'] for w in words)
                    right = max(w['x']+w['width'] for w in words)
                    bottom = max(w['y']+w['height'] for w in words)
                    # The complete label must be visible, including its margin.
                    if (max(4,width*region[0]) <= left < right <= min(width-4,width*region[2])
                            and max(4,height*region[1]) <= top < bottom <= min(height-4,height*region[3])):
                        return TextBox(text,left,top,right-left,bottom-top)
        return None


class BossChallengeEntrance:
    LEVELS = ('80','90')
    DEFAULT_LEVEL = '80'
    DEFAULT_TARGET = next(iter(BOSS_AVATARS))
    POLL = .20
    RETRY_DELAY = 2.0
    MAX_CLICKS = 3
    STEP_TIMEOUT = 15.0

    def __init__(self, target=None, level=None, *, ocr_factory=WindowsOcr):
        self.target = target if isinstance(target,str) and target in BOSS_AVATARS else self.DEFAULT_TARGET
        self.level = level if isinstance(level,str) and level in self.LEVELS else self.DEFAULT_LEVEL
        self.ocr_factory = ocr_factory
        self.ocr = None
        self.screenshot = Path(__file__).resolve().parent.parent/'_warsong_screenshot.png'

    def _capture(self, runner):
        try:
            runner.controller.screencap(self.screenshot, bring_to_front=True, tolerate_blank=True)
        except TypeError:
            runner._capture_for_matching(self.screenshot)
        with Image.open(self.screenshot) as source:
            image = source.convert('RGB')
        width, height = image.size
        battle = runner._overworld_hud_ready(self.screenshot) and boss_bar_present(
            image.crop((0,0,width,round(height*.11))), image.size)
        if battle or self.ocr is None or np.asarray(image.resize((80,45))).std() < 6:
            lines = []
        else:
            lines = self.ocr.recognize(self.screenshot, cancelled=runner.stop_event.is_set)
        return EntranceFrame(image,lines,bool(battle))

    def _transition(self, runner, label, source, action, destination, *, timeout=None):
        """Retry only while the old page is still verified; never advance on a timer."""
        deadline = time.monotonic()+(self.STEP_TIMEOUT if timeout is None else timeout)
        attempts, source_frames, ready_frames = 0, 0, 0
        previous_source = None
        last_click = float('-inf')
        while time.monotonic() < deadline:
            if runner.stop_event.is_set():
                raise InterruptedError('战歌重奏已停止。')
            frame = self._capture(runner)
            ready = destination(frame)
            ready_frames = ready_frames+1 if ready else 0
            if ready_frames >= 2:
                runner.log(f'    战歌重奏：已确认{label}。')
                return frame
            current = source(frame) if not ready else None
            # Text anchors must remain in place in two fresh screenshots.
            anchor = current.center if isinstance(current,TextBox) else current
            stable = (current and previous_source is not None and
                      (anchor == previous_source or (isinstance(anchor,tuple) and
                       isinstance(previous_source,tuple) and
                       max(abs(a-b) for a,b in zip(anchor,previous_source)) <= 4)))
            source_frames = source_frames+1 if stable else int(bool(current))
            previous_source = anchor if current else None
            if (source_frames >= 2 and attempts < self.MAX_CLICKS and
                    time.monotonic()-last_click >= self.RETRY_DELAY):
                if runner.stop_event.is_set():
                    raise InterruptedError('战歌重奏已停止。')
                action(frame,current)
                attempts += 1
                last_click = time.monotonic()
                source_frames = 0
                runner.log(f'    战歌重奏：{label}，等待页面确认（点击 {attempts}/{self.MAX_CLICKS}）。')
            runner._sleep_interruptible(self.POLL)
        raise RuntimeError(f'战歌重奏「{label}」未能确认，已停止；请检查当前游戏页面后重试。')

    @staticmethod
    def _guide(frame):
        return frame.find('活跃行迹','索拉指南','素材获取','讨伐强敌',region=(0,.01,.40,.18))

    @staticmethod
    def _category(frame):
        return frame.find('战歌重奏',region=(.08,.16,.37,.86))

    @staticmethod
    def _single(frame):
        return frame.find('单人挑战',region=(.62,.78,.98,.98))

    @staticmethod
    def _start(frame):
        return frame.find('开启挑战',region=(.60,.78,.98,.98))

    def _row_button(self, frame, runner):
        if not self._guide(frame) or not self._category(frame):
            return None
        width,height = frame.image.size
        target = frame.find(self.target,region=(.35,.24,.79,.86))
        if target is None:
            # Retain the contributor's native avatar templates as a text fallback.
            target = runner._find_daily_template(
                BOSS_AVATARS[self.target],threshold=.82,
                region=(round(width*.37),round(height*.24),round(width*.49),round(height*.86)),
                screenshot=self.screenshot)
        if target is None:
            return None
        y = target.center[1]/height
        return frame.find('直接挑战','前往',region=(.73,max(.24,y-.07),.98,min(.87,y+.07)))

    def _level_row(self, frame):
        if not self._single(frame):
            return None
        return frame.find('推荐等级'+self.level,'等级'+self.level,
                          region=(.02,.22,.30,.82))

    def _selected_level(self, frame):
        row = self._level_row(frame)
        if row is None:
            return False
        # A difficulty summary in the details panel is an explicit confirmation.
        if frame.find('推荐等级'+self.level,'等级'+self.level,
                      region=(.31,.16,.96,.78)):
            return True
        # Selected list rows use a pale plate; unselected rows are dark. Require
        # its background on BOTH sides of the text, not bright glyphs alone.
        return self._selection_plate(frame,row)

    @staticmethod
    def _selection_plate(frame, row):
        width,height = frame.image.size
        y1,y2 = max(0,round(row.y)), min(height,round(row.y+row.height))
        pixels = np.asarray(frame.image)
        pads = (pixels[y1:y2,max(0,round(row.x-width*.025)):max(0,round(row.x-width*.006))],
                pixels[y1:y2,min(width,round(row.x+row.width+width*.006)):
                       min(width,round(row.x+row.width+width*.025))])
        return all(pad.size and float((pad.min(axis=2)>155).mean()) > .65 for pad in pads)

    def _warsong_list(self, frame, runner):
        category = self._category(frame)
        if not category or not self._guide(frame):
            return False
        if self._selection_plate(frame,category):
            return True
        if frame.find('战歌重奏',region=(.36,.16,.97,.86)):
            return True
        for name in BOSS_AVATARS:
            if frame.find(name,region=(.35,.24,.79,.86)):
                return True
        return bool(self._row_button(frame,runner))

    def _tap(self, runner, _frame, box):
        runner.controller.tap(*box.center)

    def _find_row(self, runner):
        # Search a bounded list. A clipped row is scrolled fully into view before
        # its button can qualify; never click at an inferred fixed X coordinate.
        for attempt in range(9):
            frame = self._capture(runner)
            if self._row_button(frame,runner):
                return
            if runner.stop_event.is_set():
                raise InterruptedError('战歌重奏已停止。')
            if not self._guide(frame) or not self._category(frame):
                raise RuntimeError('战歌重奏列表尚未确认，已停止搜索首领。')
            direction = -1 if attempt < 3 else 1
            runner._swipe_ratio(.69,.48 if direction < 0 else .73,
                                .69,.76 if direction < 0 else .40,380,.30)
        raise RuntimeError(f'未找到完整可点击的「{self.target}」条目，已停止战歌重奏。')

    def wait_for_battle(self, runner, timeout=60):
        self._transition(runner,'进入战斗',lambda _frame:None,lambda *_args:None,
                         lambda frame:frame.battle,timeout=timeout)

    def enter(self, runner):
        if runner.dry_run:
            runner.log(f'    干运行：战歌重奏 {self.target}，等级 {self.level}；不操作游戏。')
            return True
        try:
            self.ocr = self.ocr_factory()
            self._transition(runner,'打开索拉指南',
                lambda frame:runner._overworld_hud_ready(self.screenshot) and not frame.battle,
                lambda *_args:runner.controller.press_key('F2',70),self._guide)
            self._transition(runner,'讨伐强敌页面',self._guide,
                lambda frame,_box:runner.controller.tap(round(frame.image.width*.0385),
                                                       round(frame.image.height*.296)),self._category)
            self._transition(runner,'战歌重奏分类',self._category,
                lambda frame,box:self._tap(runner,frame,box),
                lambda frame:self._warsong_list(frame,runner),timeout=8)
            self._find_row(runner)
            self._transition(runner,'首领挑战页面',lambda frame:self._row_button(frame,runner),
                             lambda frame,box:self._tap(runner,frame,box),self._single)
            self._transition(runner,f'推荐等级{self.level}',self._level_row,
                             lambda frame,box:self._tap(runner,frame,box),self._selected_level)
            self._transition(runner,'队伍与开启挑战页面',
                             lambda frame:self._single(frame) if self._selected_level(frame) else None,
                             lambda frame,box:self._tap(runner,frame,box),self._start)
            self._transition(runner,'进入战斗',self._start,
                             lambda frame,box:self._tap(runner,frame,box),
                             lambda frame:frame.battle,timeout=60)
            return True
        except InterruptedError:
            return False
        finally:
            if self.ocr is not None:
                self.ocr.close()
                self.ocr = None
