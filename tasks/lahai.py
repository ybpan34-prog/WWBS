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


def activity_page(gray):
    if visible(gray, 'reward_title') and visible(gray, 'reward_continue'):
        return 'reward'
    if visible(gray, 'challenge_success'):
        return 'board'
    if visible(gray, 'corrupted_tutorial', .9) or visible(gray, 'tutorial_second'):
        return 'tutorial_end'
    if visible(gray, 'tutorial_first'):
        return 'tutorial_first'
    if visible(gray, 'guide_select'):
        return 'guide'
    if visible(gray, 'score_icon'):
        return 'board'
    if difficulty := first_difficulty(gray):
        return difficulty
    if visible(gray, 'event_title') and visible(gray, 'event_enter'):
        return 'overview'
    if visible(gray, 'levels_title') and visible(gray, 'first_card'):
        if visible(gray, 'first_complete'):
            return 'complete'
        if visible(gray, 'first_in_progress'):
            return 'levels'
    return None


def run_lahai(runner):
    controller = runner.controller
    if not callable(getattr(controller, 'drag_rotating', None)):
        raise RuntimeError('拉海洛方块需要鸣潮 PC 客户端。')
    screenshot = Path(runner.template_root).parent.parent / '_runtime_screenshot.png'
    stop = runner.stop_event

    def capture():
        if runner._capture_for_matching(screenshot, loading=True) is False:
            return None
        with Image.open(screenshot) as image:
            if image.size != SHAPE:
                raise RuntimeError('拉海洛方块需要将游戏窗口设为 1920×1080。')
            return np.asarray(image.convert('RGB')), np.asarray(image.convert('L'))

    def wait_for(predicate, seconds=7):
        deadline = monotonic() + seconds
        while not stop.is_set() and monotonic() < deadline:
            captured = capture()
            result = predicate(*captured) if captured else None
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

    def known_page(rgb, gray):
        page = activity_page(gray)
        return (rgb, gray, page) if page else None

    played = 0
    last_page, repeats = None, 0
    for _ in range(24):
        if stop.is_set():
            return
        state = wait_for(known_page, 12)
        if stop.is_set():
            return
        if state is None:
            raise RuntimeError('等待活动画面超时。请停在拉海洛方块活动页、首组详情或积分棋盘后重试。')
        rgb, gray, page = state
        repeats = repeats + 1 if page == last_page else 0
        last_page = page
        if repeats >= 3:
            raise RuntimeError('活动画面未切换，已停止重复点击。')
        if page == 'complete':
            runner.log('回转的深空已完成。后续磁带尚未适配。')
            return
        if runner.dry_run:
            runner.log('预演：只截图，不发送方块输入。')
            return
        if page == 'reward':
            click(960, 954)
            stop.wait(.7)
            continue
        if page == 'overview':
            click(1674, 990)
        elif page == 'levels':
            click(380, 370)
        elif page in ('简单', '困难'):
            if page == '简单' and easy_complete(rgb):
                click(225, 300)
            else:
                click(1590, 990)
        elif page == 'tutorial_end':
            if visible(gray, 'tutorial_confirm', .88):
                click(960, 986)
            else:
                click(1850, 242)
        elif page == 'tutorial_first':
            click(1413, 870)
        elif page == 'guide':
            stop.wait(.7)
        elif page == 'board':
            if played >= 2:
                raise RuntimeError('已完成两次挑战，未能确认返回选关。')
            outcome = _play(runner, wait_for, screen)
            if stop.is_set():
                return
            played += 1
            runner.log(f'挑战成功，已核对 {outcome} 次落子。')
            wait_for(lambda _, g: True if activity_page(g) in
                     ('reward', 'levels', 'complete', '简单', '困难') else None, 12)
            continue
        stop.wait(.55)
    if not stop.is_set():
        raise RuntimeError('活动页面没有按预期切换，已停止。')


def _play(runner, wait_for, screen):
    state = wait_for(screen)
    consecutive_retries = 0
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

        state = wait_for(settled, 5)
        if isinstance(state, str):
            return step + 1
        if state is None and not runner.stop_event.is_set():
            stable = None

            def recovered(frame, gray):
                nonlocal stable
                current = screen(frame, gray)
                if isinstance(current, str):
                    return current
                if current is None:
                    stable = None
                    return None
                _, after = current
                if after.permanent != board.permanent or after.slots != board.slots:
                    stable = None
                    return None
                old_count = sum(p is not None for p in board.pieces)
                # Accept a different landing only if the tray shows that the move
                # was consumed and the board is stable. Otherwise retry unchanged.
                consumed = (after.occupied != board.occupied and
                            ((old_count == 1 and all(after.pieces))
                             or (old_count > 1 and all(
                                 p == (None if i == move.slot else board.pieces[i])
                                 for i, p in enumerate(after.pieces)))))
                if after != board and not consumed:
                    stable = None
                    return None
                if stable == after:
                    return current
                stable = after
                return None

            state = wait_for(recovered, 5)
            if isinstance(state, str):
                return step + 1
            if runner.stop_event.is_set():
                return step
            if state is None:
                raise RuntimeError(f'第 {step+1} 次落子后棋盘或候选区一直未稳定，已停止输入。')
            if state[1] == board:
                consecutive_retries += 1
                if consecutive_retries > 2:
                    raise RuntimeError('连续拖动未生效，已停止，当前棋局已保留。')
                runner.log('方块未落下，棋盘保持原样，重新尝试。')
            else:
                consecutive_retries = 0
                runner.log('落点与预计不同，已按稳定的新棋盘重新规划。')
            continue
        if state:
            consecutive_retries = 0
            runner.log(f'第 {step+1} 次落子已核对，消除 {cleared} 条线。')
    raise RuntimeError('达到方块任务步数上限。')


def easy_complete(rgb):
    patch = rgb[184:227, 353:398].astype(np.int16)
    return np.mean((patch[:, :, 1] > patch[:, :, 0] + 22)
                   & (patch[:, :, 1] > patch[:, :, 2] + 22)) > .06
