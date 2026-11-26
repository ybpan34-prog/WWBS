"""Pure placement planner for simultaneous row and column clearing."""
from dataclasses import dataclass
from functools import lru_cache

Cells = tuple[tuple[int, int], ...]


def normalize(cells: Cells) -> Cells:
    y0 = min(r for r, _ in cells)
    x0 = min(c for _, c in cells)
    return tuple(sorted((r - y0, c - x0) for r, c in cells))


@dataclass(frozen=True)
class Piece:
    cells: Cells
    medals: Cells = ()
    bombs: Cells = ()
    secondary_medals: Cells = ()

    def __post_init__(self):
        if (not self.cells or self.cells != normalize(self.cells)
                or len(set(self.cells)) != len(self.cells)
                or not set(self.medals + self.bombs + self.secondary_medals) <= set(self.cells)):
            raise ValueError('piece cells must be unique and normalized; marks must lie on cells')

    def rotate(self):
        h = 1 + max(r for r, _ in self.cells)
        return Piece(tuple(sorted((c, h - 1 - r) for r, c in self.cells)),
                     tuple(sorted((c, h - 1 - r) for r, c in self.medals)),
                     tuple(sorted((c, h - 1 - r) for r, c in self.bombs)),
                     tuple(sorted((c, h - 1 - r) for r, c in self.secondary_medals)))


@dataclass(frozen=True)
class Move:
    slot: int
    turns: int
    row: int
    col: int
    mask: int
    medal_mask: int
    bomb_mask: int = 0
    secondary_medal_mask: int = 0


@lru_cache(maxsize=16)
def lines(rows, cols):
    return (tuple(((1 << cols) - 1) << (r * cols) for r in range(rows)) +
            tuple(sum(1 << (r * cols + c) for r in range(rows)) for c in range(cols)))


@lru_cache(maxsize=128)
def options(rows, cols, piece, rotate):
    results = []
    seen = set()
    for turns in range(4 if rotate else 1):
        if piece in seen:
            break
        seen.add(piece)
        h, w = 1 + max(r for r, _ in piece.cells), 1 + max(c for _, c in piece.cells)
        shape = sum(1 << (r * cols + c) for r, c in piece.cells) if w <= cols else 0
        medals = sum(1 << (r * cols + c) for r, c in piece.medals) if w <= cols else 0
        bombs = sum(1 << (r * cols + c) for r, c in piece.bombs) if w <= cols else 0
        secondary = sum(1 << (r * cols + c) for r, c in piece.secondary_medals) if w <= cols else 0
        for r in range(rows - h + 1):
            for c in range(cols - w + 1):
                shift = r * cols + c
                results.append((turns, r, c, shape << shift, medals << shift,
                                bombs << shift, secondary << shift))
        piece = piece.rotate()
    return tuple(results)


def apply_move(rows, cols, board, medals, move, *, permanent=0):
    return resolve_move(rows, cols, board, medals, 0, move, permanent=permanent)[:4]


@lru_cache(maxsize=16)
def blast_masks(rows, cols):
    return tuple(sum(1 << (r*cols+c)
                     for r in range(max(0, y-1), min(rows, y+2))
                     for c in range(max(0, x-1), min(cols, x+2)))
                 for y in range(rows) for x in range(cols))


def resolve_move(rows, cols, board, medals, bombs, move, *, permanent=0, faults=0, severe_faults=0):
    if board & move.mask:
        raise ValueError('placement overlaps the board')
    filled, tokens = board | move.mask, medals | move.medal_mask
    cleared, count = 0, 0
    for line in lines(rows, cols):
        if filled & line == line and line & ~permanent:
            cleared |= line
            count += 1
    explosives = bombs | move.bomb_mask
    remaining = explosives
    while pending := cleared & remaining & ~faults:
        bit = pending & -pending
        remaining ^= bit
        cleared |= blast_masks(rows, cols)[bit.bit_length()-1] & ~permanent
    removed = cleared & ~faults
    return ((filled & ~removed) | permanent, tokens & ~removed, count,
            (tokens & removed).bit_count(), remaining, (faults & ~cleared) | severe_faults,
            severe_faults & ~cleared)


@lru_cache(maxsize=4096)
def board_value(rows, cols, board, medals):
    isolated = 0
    for r in range(rows):
        for c in range(cols):
            bit = 1 << (r * cols + c)
            if board & bit:
                continue
            occupied = 0
            for y, x in ((r - 1, c), (r + 1, c), (r, c - 1), (r, c + 1)):
                occupied += not (0 <= y < rows and 0 <= x < cols) or bool(board & (1 << (y * cols + x)))
            isolated += max(0, occupied - 2)
    line_value = sum((board & line).bit_count() ** 2 + 3 * (medals & line).bit_count()
                     for line in lines(rows, cols))
    return 0.07 * line_value - 0.8 * board.bit_count() - 1.4 * isolated


def plan(rows, cols, board, medals, pieces, *, medal_mode=False, rotate=False, width=20,
         permanent=0, bombs=0, secondary_medals=0, faults=0, severe_faults=0):
    """Plan across the visible batch. Returns an empty tuple if all moves overlap."""
    if not (1 <= rows <= 16 and 1 <= cols <= 16 and 0 < width <= 64):
        raise ValueError('unsupported board or search size')
    if not (0 <= board < (1 << (rows * cols)) and 0 <= medals and medals & ~board == 0
            and 0 <= permanent and permanent & ~board == 0
            and 0 <= secondary_medals and secondary_medals & ~board == 0):
        raise ValueError('invalid board or medal mask')
    moves = {i: tuple(Move(i, *args) for args in options(rows, cols, p, rotate))
             for i, p in enumerate(pieces) if p is not None}
    beam = [(0., 0., board, medals, secondary_medals, bombs, faults, severe_faults, tuple(moves), ())]
    best = ()
    while beam:
        candidates = {}
        for _, earned, grid, tokens, secondary, explosives, stuck, severe, todo, path in beam:
            for slot in todo:
                remaining = tuple(i for i in todo if i != slot)
                for move in moves[slot]:
                    if grid & move.mask:
                        continue
                    nxt, next_tokens, cleared, collected, next_bombs, next_faults, next_severe = resolve_move(
                        rows, cols, grid, tokens, explosives, move, permanent=permanent,
                        faults=stuck, severe_faults=severe)
                    secondary_with_move = secondary | move.secondary_medal_mask
                    next_secondary = secondary_with_move & nxt
                    collected += (secondary_with_move ^ next_secondary).bit_count()
                    gain = 8 * cleared + 5 * cleared ** 2 + (95 if medal_mode else 2) * collected
                    gain += 30 * ((stuck ^ next_faults).bit_count() + (severe ^ next_severe).bit_count())
                    value = earned + gain - 0.12 * move.turns
                    quick = value - 0.8 * nxt.bit_count()
                    key = (nxt, next_tokens, next_secondary, next_bombs, next_faults, next_severe, remaining)
                    prior = candidates.get(key)
                    if prior is None or value > prior[1]:
                        candidates[key] = (quick, value, *key, path + (move,))
        if not candidates:
            break
        shortlist = sorted(candidates.values(), key=lambda s: s[0], reverse=True)[:width * 4]
        beam = sorted(shortlist, key=lambda s: s[1] + board_value(rows, cols, s[2], s[3] | s[4]),
                      reverse=True)[:width]
        best = beam[0][-1]
    return best
