"""Closed-loop match-three shortcut, leaving every result screen untouched."""
from pathlib import Path
import re
import time

from PIL import Image

from tasks.match3_solver import evaluate, ranked_moves, runs
from tasks.match3_vision import read_board, success_present, shared_board, known_change
from tasks.models import TaskNeedsReview
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
        self.last_read_reason = ''

    def status(self, force=False):
        if self.result or self.ocr_disabled or (not force and time.monotonic()-self.last_status_at < 4):
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

    def stable_board(self, timeout=18, previous=None, unchanged_after=None):
        deadline = time.monotonic()+timeout
        candidate = None
        stable_at = 0.
        success_frames = 0
        unknown_cells = None
        while time.monotonic() < deadline and not self.runner.stop_event.is_set():
            self.runner._capture_for_matching(self.path)
            if self.runner.stop_event.is_set():
                return None
            if success_present(self.path):
                success_frames += 1
                candidate = None
                if success_frames >= 2:
                    self.result = 'success'
                    return None
                self.runner._sleep_interruptible(.18)
                continue
            success_frames = 0
            details = {}
            frame = read_board(self.path, diagnostics=details)
            if frame is None:
                reason = details.get('reason', '棋盘仍未稳定。')
                if reason != self.last_read_reason:
                    self.last_read_reason = reason
                    self.runner.log('    棋盘复核：'+reason)
                candidate = None
                self.status()
                if self.result or self.remaining == 0:
                    return None
            elif not runs(frame.tiles):
                current_unknown = tuple(details.get('unknown', ()))
                if current_unknown and current_unknown != unknown_cells:
                    self.runner.log(f'    {len(current_unknown)}格暂未识别，作为占位格；继续从已知格计算合法交换。')
                unknown_cells = current_unknown
                # Settling pieces may look individually valid for one frame.
                # Two identical reads at least .35s apart must also have no
                # uncleared ordinary match before the next action.
                shared = shared_board(candidate, frame) if candidate is not None else None
                if shared is not None:
                    candidate = shared
                    if time.monotonic()-stable_at >= .35:
                        if previous is None or known_change(previous, shared.tiles):
                            return shared
                        if unchanged_after is not None and time.monotonic()-stable_at >= unchanged_after:
                            return shared
                else:
                    candidate, stable_at = frame, time.monotonic()
            else:
                candidate = None  # A pending elimination breaks stability.
            self.runner._sleep_interruptible(.18)
        return None

    def await_move_result(self, before, deadline):
        waiting_logged = False
        while time.monotonic() < deadline and not self.runner.stop_event.is_set():
            frame = self.stable_board(timeout=min(18, max(.1, deadline-time.monotonic())),
                                      previous=before, unchanged_after=2.)
            if frame is not None:
                return frame
            self.status(force=True)
            if self.result or self.remaining == 0 or self.runner.stop_event.is_set():
                return None
            if not waiting_logged:
                self.runner.log('    拖动后暂未读到稳定画面，继续重读；本次尚未计作有效操作。')
                waiting_logged = True
            self.runner._sleep_interruptible(.2)
        return None

    def run(self, timeout=1200):
        runner = self.runner
        runner.log('    无音消除：请先关闭规则／引导，打开7行8列棋盘；每步拖动后等待稳定并重新识别。')
        try:
            frame = self.stable_board()
            if frame is None:
                if runner.stop_event.is_set():
                    return
                if self.result == 'success':
                    return self.finish('已识别挑战成功，保留结算界面。', completed=True)
                return self.finish('未确认完整稳定棋盘；'+self.last_read_reason+' 请检查画面后重新启动。')
            self.status(force=True)
            budget = min(20, self.remaining) if self.remaining is not None else 20
            expected_remaining = self.remaining
            deadline = time.monotonic()+timeout
            attempts = confirmed = 0
            failed_moves = {}
            while confirmed < budget and time.monotonic() < deadline and not runner.stop_event.is_set():
                if self.result or self.remaining == 0:
                    break
                if frame is None:
                    frame = self.stable_board(timeout=min(18, max(.1, deadline-time.monotonic())))
                    if frame is None:
                        self.status()
                        runner._sleep_interruptible(.2)
                        continue
                moves = ranked_moves(frame.tiles)
                if not moves:
                    return self.finish('已知格中暂时没有可确认的合法交换，保留当前画面；未知格不会被盲目拖动。')
                move = next((item for item in moves if failed_moves.get((item.start, item.end), 0) < 2), None)
                if move is None:
                    failed_moves.clear()
                    move = moves[0]
                if runner.dry_run:
                    runner.log(f'    预演：建议第{move.start[0]+1}行第{move.start[1]+1}列 → '
                               f'第{move.end[0]+1}行第{move.end[1]+1}列，已知可消除{move.cleared}枚；未拖动。')
                    return self.finish('预演完成，未操作棋盘。', completed=True)
                # Re-read immediately before input. A skill or cascade can
                # change the board while planning/reading the score.
                runner._capture_for_matching(self.path)
                latest = read_board(self.path)
                shared = shared_board(frame, latest) if latest is not None else None
                refreshed_move = evaluate(shared.tiles, move.start, move.end) if shared is not None else None
                if refreshed_move is None:
                    frame = self.stable_board()
                    failed_moves.clear()
                    continue
                frame, move = shared, refreshed_move
                if runner.stop_event.is_set():
                    return
                a, b = frame.centers[move.start[0]][move.start[1]], frame.centers[move.end[0]][move.end[1]]
                runner.log(f'    第{confirmed+1}步（第{attempts+1}次尝试）：({move.start[0]+1},{move.start[1]+1}) → '
                           f'({move.end[0]+1},{move.end[1]+1})；已知消除{move.cleared}枚'
                           + ('，优先生成特殊棋子。' if move.creates else '。'))
                key = move.start, move.end
                retry = failed_moves.get(key, 0)
                # Reverse the same logical swap and slow the retry slightly;
                # an ignored drag must not consume the game's move budget.
                runner.controller.swipe(*(b if retry else a), *(a if retry else b), 420 if retry else 240)
                attempts += 1
                runner._sleep_interruptible(.5)
                before = frame.signature
                frame = self.await_move_result(before, deadline)
                if frame is None:
                    self.status(force=True)
                    if self.result or self.remaining == 0 or runner.stop_event.is_set():
                        break
                    continue
                if known_change(before, frame.tiles):
                    confirmed += 1
                    if expected_remaining is not None:
                        expected_remaining = max(0, expected_remaining-1)
                    failed_moves.clear()
                    self.status()
                    runner.log(f'    已复核第{confirmed}次有效棋盘变化，继续计算。')
                else:
                    self.status(force=True)
                    if (expected_remaining is not None and self.remaining is not None
                            and self.remaining < expected_remaining):
                        confirmed += expected_remaining-self.remaining
                        expected_remaining = self.remaining
                        failed_moves.clear()
                        runner.log('    棋盘外观未变，但已确认剩余回合减少；按实际回合继续。')
                    elif not self.result and self.remaining != 0 and not runner.stop_event.is_set():
                        failed_moves[key] = retry+1
                        runner.log('    棋盘未变化，本次拖动可能未生效；不计作有效步数，重新定位后重试或换一步。')
            if runner.stop_event.is_set():
                return
            self.status(force=True)
            if self.result == 'success':
                return self.finish('已识别挑战成功，保留结算界面。', completed=True)
            if self.result == 'failure' or self.remaining == 0:
                return self.finish('本局回合已结束，保留结算界面，可手动重开。')
            return self.finish('已达到本次步数或时间上限，停止输入并保留当前页面；未判定为通关。')
        finally:
            if self.ocr is not None:
                self.ocr.close()

    def finish(self, message, *, completed=False):
        if self.runner.stop_event.is_set():
            return
        self.runner.log('    '+message)
        if not completed:
            raise TaskNeedsReview('无音消除：'+message)
        self.runner.warning('无音消除：'+message)


class Match3Task:
    def _run_match3_puzzle(self, step):
        Match3Session(self).run(max(30., min(float(step.timeout), 1800.)))
