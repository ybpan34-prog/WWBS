"""Closed-loop match-three shortcut, leaving every result screen untouched."""
from pathlib import Path
import re
import time

from PIL import Image

from tasks.match3_solver import ranked_moves, runs
from tasks.match3_vision import read_board
from windows_ocr import WindowsOcr


ROOT = Path(__file__).resolve().parent.parent


def status_from_lines(lines):
    text = ''.join(str(word.get('text', '')) for line in lines for word in line.get('words', []))
    text = re.sub(r'\s+', '', text)
    # Only explicit result text can announce success/failure. A covered or
    # absent board is never treated as a completed puzzle.
    if any(value in text for value in ('挑战成功', '挑战完成', '挑战达成', '通关成功')):
        return 'success', None
    if any(value in text for value in ('挑战失败', '挑战未达成', '挑战未完成', '回合耗尽')):
        return 'failure', 0
    match = re.search(r'剩余回合(?:数)?[:：]?(\d{1,2})[/／]\d{1,2}', text)
    return 'playing', int(match[1]) if match else None


class Match3Session:
    def __init__(self, runner):
        self.runner = runner
        self.path = ROOT/'_runtime_screenshot.png'
        self.ocr = None
        self.ocr_disabled = False
        self.last_status_at = -100.
        self.remaining = None
        self.result = None

    def status(self, force=False):
        if self.ocr_disabled or (not force and time.monotonic()-self.last_status_at < 4):
            return
        self.last_status_at = time.monotonic()
        try:
            if self.ocr is None:
                self.ocr = WindowsOcr()
            # Upscale small counters for the local recognizer, no screenshot is
            # sent to a server. Full frame is needed for a result overlay.
            with Image.open(self.path) as source:
                image = source.convert('RGB')
            target = ROOT/'_match3_status.png'
            image.resize((1600, 900)).save(target)
            lines = self.ocr.recognize(target, cancelled=self.runner.stop_event.is_set, timeout=3)
            state, turns = status_from_lines(lines)
            if state != 'playing':
                self.result = state
            if turns is not None:
                self.remaining = turns
        except (OSError, RuntimeError):
            self.ocr_disabled = True
            if self.ocr is not None:
                self.ocr.close()
                self.ocr = None
            self.runner.log('    无法读取回合文字，仍按完整棋盘复核；最多交换20步，结算页面不操作。')

    def stable_board(self, timeout=18, previous=None):
        deadline = time.monotonic()+timeout
        candidate = None
        stable_at = 0.
        while time.monotonic() < deadline and not self.runner.stop_event.is_set():
            self.runner._capture_for_matching(self.path)
            if self.runner.stop_event.is_set():
                return None
            frame = read_board(self.path)
            if frame is None:
                candidate = None
                self.status()
                if self.result or self.remaining == 0:
                    return None
            elif not runs(frame.tiles):
                # Settling pieces may look individually valid for one frame.
                # Two identical reads at least .35s apart must also have no
                # uncleared ordinary match before the next action.
                if candidate is not None and candidate.signature == frame.signature:
                    if time.monotonic()-stable_at >= .35:
                        if previous is None or previous != frame.signature:
                            return frame
                else:
                    candidate, stable_at = frame, time.monotonic()
            self.runner._sleep_interruptible(.18)
        return None

    def run(self, timeout=1200):
        runner = self.runner
        runner.log('    无音消除：请先关闭规则／引导，打开7行8列棋盘；每步拖动后等待稳定并重新识别。')
        try:
            frame = self.stable_board()
            if frame is None:
                return self.finish('未确认完整稳定棋盘，请关闭规则、引导或其他遮挡后再启动。')
            self.status(force=True)
            budget = min(20, self.remaining) if self.remaining is not None else 20
            deadline = time.monotonic()+timeout
            attempts = confirmed = 0
            while frame is not None and attempts < budget and time.monotonic() < deadline and not runner.stop_event.is_set():
                if self.result or self.remaining == 0:
                    break
                moves = ranked_moves(frame.tiles)
                if not moves:
                    return self.finish('当前稳定棋盘没有确认可消除的交换，已停留原页面，请检查是否需要重排。')
                move = moves[0]
                if runner.dry_run:
                    runner.log(f'    预演：建议第{move.start[0]+1}行第{move.start[1]+1}列 → '
                               f'第{move.end[0]+1}行第{move.end[1]+1}列，已知可消除{move.cleared}枚；未拖动。')
                    return self.finish('预演完成，未操作棋盘。')
                # Re-read immediately before input. A skill or cascade can
                # change the board while planning/reading the score.
                runner._capture_for_matching(self.path)
                latest = read_board(self.path)
                if latest is None or latest.signature != frame.signature:
                    frame = self.stable_board()
                    continue
                if runner.stop_event.is_set():
                    return
                a, b = frame.centers[move.start[0]][move.start[1]], frame.centers[move.end[0]][move.end[1]]
                runner.log(f'    第{attempts+1}步：({move.start[0]+1},{move.start[1]+1}) → '
                           f'({move.end[0]+1},{move.end[1]+1})；已知消除{move.cleared}枚'
                           + ('，优先生成特殊棋子。' if move.creates else '。'))
                runner.controller.swipe(*a, *b, 240)
                attempts += 1
                runner._sleep_interruptible(.5)
                before = frame.signature
                frame = self.stable_board(previous=before)
                if frame is None:
                    # Do not burn the next turn or blindly retry an unchanged
                    # drag. The real number of remaining turns is authoritative.
                    self.status(force=True)
                    if self.result or self.remaining == 0 or runner.stop_event.is_set():
                        break
                    return self.finish('拖动后未确认新的稳定棋盘，已停止输入，请检查游戏画面后重跑。')
                confirmed += 1
                self.status()
                runner.log(f'    已复核第{confirmed}次棋盘变化，继续计算。')
            if runner.stop_event.is_set():
                return
            self.status(force=True)
            if self.result == 'success':
                return self.finish('已识别挑战成功，保留结算界面。')
            if self.result == 'failure' or self.remaining == 0:
                return self.finish('本局回合已结束，保留结算界面，可手动重开。')
            return self.finish('已达到本次步数或时间上限，停止输入并保留当前页面；未判定为通关。')
        finally:
            if self.ocr is not None:
                self.ocr.close()

    def finish(self, message):
        self.runner.log('    '+message)
        self.runner.warning('无音消除：'+message)


class Match3Task:
    def _run_match3_puzzle(self, step):
        Match3Session(self).run(max(30., min(float(step.timeout), 1800.)))
