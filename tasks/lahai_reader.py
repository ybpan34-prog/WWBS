"""Score-mode 8x8 board reader, calibrated against the live first challenge."""
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageFilter

from .lahai_solver import Piece, normalize

# Color samples are from tile interiors, away from the tile glyph.
PALETTE = np.array([(234, 93, 55), (255, 200, 99), (94, 94, 234),
                    (65, 170, 184), (223, 58, 105), (142, 60, 240)], dtype=np.int16)
SLOTS = ((1588, 380, 1760, 548), (1588, 604, 1760, 773))
HARD_SLOTS = tuple((1584, y, 1765, y + 177) for y in (262, 487, 712))
PITCH = 36


@dataclass(frozen=True)
class Board:
    occupied: int
    pieces: tuple[Piece | None, ...]
    permanent: int = 0
    slots: tuple = SLOTS


def scan_tray(rgb):
    delta = np.abs(rgb[:, :, None, :].astype(np.int16) - PALETTE)
    tile_mask = np.any(np.max(delta, axis=-1) <= 45, axis=-1)
    mask = Image.fromarray(tile_mask.astype(np.uint8) * 255)
    tile_mask = np.asarray(mask.filter(ImageFilter.MinFilter(5)).filter(ImageFilter.MaxFilter(5))) > 0
    ys, xs = np.where(tile_mask)
    if len(xs) < 20:
        return None
    x, y = int(xs.min()), int(ys.min())
    width, height = int(xs.max()) - x + 1, int(ys.max()) - y + 1
    cols, rows = round(width / PITCH), round(height / PITCH)
    if not (1 <= rows <= 5 and 1 <= cols <= 5 and
            abs(width - cols * PITCH) <= 7 and abs(height - rows * PITCH) <= 7):
        raise ValueError('Cannot resolve the tray tile grid')
    cells = []
    for r in range(rows):
        for c in range(cols):
            top, left = y + r * PITCH + 5, x + c * PITCH + 5
            region = tile_mask[top:top+24, left:left+24]
            coverage = region.mean()
            if coverage >= 0.68:
                cells.append((r, c))
            elif coverage >= 0.12:
                raise ValueError('Partial tray tile; wait for the animation')
    if not cells:
        raise ValueError('Tray tile grid has no cells')
    todo = set(cells)
    seen = {todo.pop()}
    while True:
        adjacent = {(r+dr, c+dc) for r, c in seen
                    for dr, dc in ((-1, 0), (1, 0), (0, 1), (0, -1))} & todo
        if not adjacent:
            break
        seen |= adjacent
        todo -= adjacent
    if todo:
        raise ValueError('Tray tiles are disconnected')
    return Piece(normalize(tuple(cells))), (x + width / 2, y + height / 2)


def pieces_from_tray(rgb):
    sample = scan_tray(rgb)
    return sample[0] if sample else None


def read_score_board(frame):
    h, w = frame.shape[:2]
    if abs(w * 9 - h * 16) > 16:
        raise ValueError('Only the 16:9 score board is calibrated')
    if (w, h) != (1920, 1080):
        frame = np.asarray(Image.fromarray(frame).resize((1920, 1080), Image.Resampling.BILINEAR))
    rgb = frame[:, :, :3]
    occupied = permanent = 0
    for r in range(8):
        for c in range(8):
            x, y = 540 + c * 114, 130 + r * 114
            sample = np.median(rgb[y-6:y+6, x-6:x+6], axis=(0, 1))
            bit = 1 << (r * 8 + c)
            if sample.min() >= 75 and sample.max() <= 165 and np.ptp(sample) < 20:
                permanent |= bit
                occupied |= bit
            elif np.min(np.max(np.abs(PALETTE - sample), axis=1)) <= 48:
                occupied |= bit
            elif not (sample[0] < 52 and sample[1] < 52 and sample[2] < 105):
                raise ValueError(f'Unrecognized grid cell at row {r+1}, column {c+1}')
    slots = HARD_SLOTS if permanent else SLOTS
    pieces = tuple(pieces_from_tray(rgb[y1:y2, x1:x2]) for x1, y1, x2, y2 in slots)
    return Board(occupied, pieces, permanent, slots)
