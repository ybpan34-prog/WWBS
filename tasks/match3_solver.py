"""Deterministic evaluation of known match-three tiles; refill stays unknown."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Tile:
    color: int
    special: str = ''


UNKNOWN = Tile(-1)
ROWS, COLS = 7, 8


@dataclass(frozen=True)
class Move:
    start: tuple[int, int]
    end: tuple[int, int]
    value: float
    cleared: int
    creates: str = ''


def runs(board):
    result = []
    for vertical in (False, True):
        for line in range(COLS if vertical else ROWS):
            points = [(i, line) if vertical else (line, i) for i in range(ROWS if vertical else COLS)]
            group = []
            for point in points+[None]:
                tile = board[point[0]][point[1]] if point is not None else UNKNOWN
                if group and (tile.color < 0 or tile.special == 'rainbow'
                              or tile.color != board[group[0][0]][group[0][1]].color):
                    if len(group) >= 3:
                        result.append(set(group))
                    group = []
                if point is not None and tile.color >= 0 and tile.special != 'rainbow':
                    group.append(point)
    return result


def expand_specials(board, cleared):
    cleared = set(cleared)
    applied = set()
    while cleared-applied:
        point = next(iter(cleared-applied))
        applied.add(point)
        r, c = point
        tile = board[r][c]
        if tile.special == 'bomb':
            cleared.update((rr, cc) for rr in range(max(0, r-1), min(ROWS, r+2))
                           for cc in range(max(0, c-1), min(COLS, c+2)))
        elif tile.special == 'cross':
            cleared.update((r, cc) for cc in range(COLS))
            cleared.update((rr, c) for rr in range(ROWS))
    return cleared


def evaluate(board, start, end):
    changed = [list(row) for row in board]
    r, c = start
    rr, cc = end
    a, b = changed[r][c], changed[rr][cc]
    if a.color < 0 or b.color < 0:
        return None
    changed[r][c], changed[rr][cc] = b, a
    formed = runs(changed)
    special = ''
    if a.special == 'rainbow' or b.special == 'rainbow':
        other = b if a.special == 'rainbow' else a
        cleared = {(i, j) for i in range(ROWS) for j in range(COLS)
                   if other.special == 'rainbow' or changed[i][j].color == other.color}
        cleared.update((start, end))
    else:
        involved = [group for group in formed if start in group or end in group]
        if not involved:
            return None
        # Existing incidental runs do not make an unrelated swap legal.
        cleared = set().union(*formed)
        if any(len(group) >= 5 for group in involved):
            special = 'rainbow'
        elif any(x & y and len(x | y) >= 5 for i, x in enumerate(involved) for y in involved[i+1:]):
            special = 'cross'
        elif any(len(group) == 4 for group in involved):
            special = 'bomb'
    cleared = expand_specials(changed, cleared)
    count = len(cleared)
    value = count*10 + {'': 0, 'bomb': 28, 'cross': 60, 'rainbow': 110}[special]
    # Reward only cascades proven by the currently known pieces; never invent
    # future refill colors. This makes the chosen move reproducible.
    fallen = [[UNKNOWN for _ in range(COLS)] for _ in range(ROWS)]
    for col in range(COLS):
        remaining = [changed[row][col] for row in range(ROWS) if (row, col) not in cleared]
        for row, tile in zip(range(ROWS-len(remaining), ROWS), remaining):
            fallen[row][col] = tile
    cascades = runs(fallen)
    if cascades:
        value += len(set().union(*cascades))*7
    return Move(start, end, value, count, special)


def ranked_moves(board, excluded=()):
    if len(board) != ROWS or any(len(row) != COLS for row in board):
        raise ValueError('无音消除棋盘必须为7行8列。')
    excluded = set(excluded)
    result = []
    for row in range(ROWS):
        for col in range(COLS):
            for dr, dc in ((0, 1), (1, 0)):
                end = row+dr, col+dc
                if end[0] >= ROWS or end[1] >= COLS or ((row, col), end) in excluded:
                    continue
                move = evaluate(board, (row, col), end)
                if move is not None:
                    result.append(move)
    return sorted(result, key=lambda m: (-m.value, m.start, m.end))
