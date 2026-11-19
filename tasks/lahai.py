"""WWBS task for the currently available Lahai Blocks score challenges."""
from functools import lru_cache
from pathlib import Path
from time import monotonic

import numpy as np
from PIL import Image

from tasks.lahai_reader import read_score_board, scan_tray
from tasks.lahai_solver import apply_move, plan

NAME = "拉海洛方块·逆转"
SHAPE = (1920, 1080)
TEMPLATES = Path(__file__).resolve().parent.parent / 'templates' / 'lahai'


@lru_cache(maxsize=32)
def _anchor(name):
    path, = TEMPLATES.glob(f'lahai_{name}_*.png')
    _, x, y = path.stem.rsplit('_', 3)[-3:]
    with Image.open(path) as source:
        ref = np.asarray(source.convert('L'), dtype=np.float32)
    ref -= ref.mean()
    return int(x), int(y), ref, np.linalg.norm(ref)


def visible(gray, name, threshold=.85):
    x, y, ref, norm = _anchor(name)
    h, w = ref.shape
    def matches(dx, dy):
        crop = gray[y+dy:y+dy+h, x+dx:x+dx+w].astype(np.float32)
        if crop.shape != ref.shape:
            return False
        crop -= crop.mean()
        denom = norm * np.linalg.norm(crop)
        return bool(denom and np.sum(ref * crop) / denom >= threshold)

    if matches(0, 0):
        return True
    for distance in range(1, 7):
        for dy in range(-min(distance, 4), min(distance, 4) + 1):
            dx = distance - abs(dy)
            if matches(dx, dy) or (dx and matches(-dx, dy)):
                return True
    return False


def first_difficulty(gray):
    if not visible(gray, 'challenge_start', .90):
        return None
    if visible(gray, 'first_easy', .93):
        return '简单'
    if visible(gray, 'first_hard', .93):
        return '困难'
    return None


def diagnose_activity(path):
    with Image.open(path) as image:
        if image.size != SHAPE:
            return 'error', '拉海洛方块需要 1920×1080 游戏截图。'
        gray = np.asarray(image.convert('L'))
    if difficulty := first_difficulty(gray):
        return 'ok', f'已识别「回转的深空·{difficulty}」和「开始挑战」。'
    if visible(gray, 'score_icon'):
        return 'ok', '已识别拉海洛方块积分棋盘。'
    if visible(gray, 'levels_title') or visible(gray, 'event_title'):
        return 'info', '已识别拉海洛方块活动界面，暂未确认首组可启动状态。'
    return 'warning', '未识别到拉海洛方块活动界面，请查看诊断截图。'


def run_lahai(runner):
    controller = runner.controller
    if not callable(getattr(controller, 'drag_rotating', None)):
        raise RuntimeError('拉海洛方块需要鸣潮 PC 客户端。')
    screenshot = Path(runner.template_root).parent.parent / '_runtime_screenshot.png'
    stop = runner.stop_event

    def capture():
        runner._capture_for_matching(screenshot)
        with Image.open(screenshot) as image:
            if image.size != SHAPE:
                raise RuntimeError('拉海洛方块需要将游戏窗口设为 1920×1080。')
            return np.asarray(image.convert('RGB')), np.asarray(image.convert('L'))

    def wait_for(predicate, seconds=7):
        deadline = monotonic() + seconds
        while not stop.is_set() and monotonic() < deadline:
            result = predicate(*capture())
            if result is not None:
                return result
            stop.wait(.15)
        return None

    def reward(gray):
        return visible(gray, 'reward_title') and visible(gray, 'reward_continue')

    def screen(rgb, gray):
        if reward(gray):
            return 'reward'
        if visible(gray, 'challenge_success'):
            return 'success'
        if visible(gray, 'score_icon'):
            try:
                board = read_score_board(rgb)
                if any(board.pieces):
                    return rgb, board
            except ValueError:
                pass
        return None

    def click(x, y):
        if not stop.is_set():
            controller.tap(x, y, precise=True)

    played = 0
    for _ in range(12):
        if stop.is_set():
            return
        rgb, gray = capture()
        if visible(gray, 'first_complete') and visible(gray, 'levels_title'):
            runner.log('回转的深空已完成。后续磁带尚未适配。')
            return
        if runner.dry_run:
            runner.log('预演：只截图，不发送方块输入。')
            return
        if reward(gray):
            click(960, 954)
            stop.wait(.7)
            continue
        if visible(gray, 'event_title') and visible(gray, 'event_enter'):
            click(1674, 990)
        elif visible(gray, 'first_card') and visible(gray, 'first_in_progress'):
            click(380, 370)
        elif difficulty := first_difficulty(gray):
            if difficulty == '简单' and easy_complete(rgb):
                click(225, 300)
            else:
                click(1590, 990)
        elif visible(gray, 'tutorial_second') or visible(gray, 'corrupted_tutorial', .9):
            if visible(gray, 'tutorial_confirm', .88):
                click(960, 986)
            else:
                click(1850, 242)
        elif visible(gray, 'tutorial_first'):
            click(1413, 870)
        elif visible(gray, 'guide_select'):
            stop.wait(.7)
        elif visible(gray, 'score_icon') or visible(gray, 'challenge_success'):
            if played >= 2:
                raise RuntimeError('已完成两次挑战，未能确认返回选关。')
            outcome = _play(runner, wait_for, screen)
            if stop.is_set():
                return
            played += 1
            runner.log(f'挑战成功，已核对 {outcome} 次落子。')
            wait_for(lambda _, g: True if reward(g) or visible(g, 'levels_title')
                     or visible(g, 'first_hard', .93) else None, 7)
            continue
        else:
            if played:
                raise RuntimeError('已经通关，但未识别到活动结算或选关页。')
            raise RuntimeError('请先打开拉海洛方块活动页、回转的深空详情或积分棋盘。')
        stop.wait(.55)
    if not stop.is_set():
        raise RuntimeError('活动页面没有按预期切换，已停止。')


def _play(runner, wait_for, screen):
    state = wait_for(screen)
    for step in range(120):
        if runner.stop_event.is_set():
            return step
        if isinstance(state, str):
            return step
        if state is None:
            raise RuntimeError('未能确认积分棋盘或新一批方块。')
        rgb, board = state
        path = plan(8, 8, board.occupied, 0, board.pieces, rotate=True, permanent=board.permanent)
        if not path:
            raise RuntimeError('当前没有可用落点。')
        move = path[0]
        expected, _, cleared, _ = apply_move(8, 8, board.occupied, 0, move, permanent=board.permanent)
        x1, y1, x2, y2 = board.slots[move.slot]
        piece, (cx, cy) = scan_tray(rgb[y1:y2, x1:x2])
        w = 1 + max(c for _, c in piece.cells)
        h = 1 + max(r for r, _ in piece.cells)
        r, c = min(piece.cells, key=lambda pos: (pos[0]+.5-h/2)**2 + (pos[1]+.5-w/2)**2)
        source = round(x1+cx+(c+.5-w/2)*36), round(y1+cy+(r+.5-h/2)*36)
        for _ in range(move.turns):
            piece = piece.rotate()
        w = 1 + max(c for _, c in piece.cells)
        h = 1 + max(r for r, _ in piece.cells)
        target = round(559+(move.col+(w-1)/2)*114), round(140+(move.row+(h-1)/2)*114)
        runner.controller.drag_rotating(source, target, move.turns)
        runner.stop_event.wait(.42)

        def settled(frame, gray):
            current = screen(frame, gray)
            if isinstance(current, str):
                return current
            if current is None:
                return None
            _, after = current
            old_count = sum(p is not None for p in board.pieces)
            new_count = sum(p is not None for p in after.pieces)
            expected_count = old_count - 1 if old_count > 1 else len(board.slots)
            if after.occupied == expected and new_count == expected_count and (
                    old_count == 1 or after.pieces[move.slot] is None):
                return current
            return None

        state = wait_for(settled)
        if isinstance(state, str):
            return step + 1
        if state is None and not runner.stop_event.is_set():
            raise RuntimeError(f'第 {step+1} 次落子无法核对，已停止。')
        if state:
            runner.log(f'第 {step+1} 次落子已核对，消除 {cleared} 条线。')
    raise RuntimeError('达到方块任务步数上限。')


def easy_complete(rgb):
    patch = rgb[184:227, 353:398].astype(np.int16)
    return np.mean((patch[:, :, 1] > patch[:, :, 0] + 22)
                   & (patch[:, :, 1] > patch[:, :, 2] + 22)) > .06
