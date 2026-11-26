"""Score-mode 8x8 board reader, calibrated against the live first challenge."""
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

from .lahai_solver import Piece, normalize

# Color samples are from tile interiors, away from the tile glyph.
PALETTE = np.array([(234, 93, 55), (255, 200, 99), (94, 94, 234),
                    (65, 170, 184), (223, 58, 105), (142, 60, 240)], dtype=np.int16)
SLOTS = ((1584, 375, 1765, 555), (1584, 600, 1765, 780))
HARD_SLOTS = tuple((1584, y, 1765, y + 177) for y in (262, 487, 712))
FOUR_SLOTS = tuple((1584, y, 1765, y + 177) for y in (150, 375, 600, 825))
PITCH = 36


@dataclass(frozen=True)
class Board:
    occupied: int
    pieces: tuple[Piece | None, ...]
    permanent: int = 0
    slots: tuple = SLOTS
    medals: int = 0
    bombs: int = 0
    secondary_medals: int = 0
    dual_mode: bool = False
    medal_mode: bool = False
    faults: int = 0
    triple_mode: bool = False
    severe_faults: int = 0
    final_mode: bool = False


@lru_cache(maxsize=8)
def _icon_reference(size, kind):
    directory = Path(__file__).resolve().parents[1] / 'templates/lahai'
    name = kind + ('_tray' if size == 18 else '')
    with Image.open(next(directory.glob(f'lahai_{name}_1920*.png'))) as image:
        patch = np.asarray(image.convert('L'), dtype=np.float32)
    patch -= patch.mean()
    return patch / np.linalg.norm(patch)


def _has_icon(rgb, x, y, size, kind):
    reference = _icon_reference(size, kind)
    side = size // 2
    threshold = .60 if size == 18 and kind in ('snow_medal', 'void_medal') else (
        .76 if kind.endswith('_severe') else .85 if kind.endswith('_fault') else .72)
    for dy in (0, -1, 1, -2, 2):
        for dx in (0, -1, 1, -2, 2):
            patch = rgb[y+dy-side:y+dy+side, x+dx-side:x+dx+side]
            if patch.shape[:2] != (size, size):
                continue
            gray = np.asarray(Image.fromarray(patch).convert('L'), dtype=np.float32)
            gray -= gray.mean()
            norm = np.linalg.norm(gray)
            if norm and np.sum(gray*reference)/norm >= threshold:
                return True
    return False


def scan_tray(rgb, medal_mode=False, bomb_mode=False, dual_mode=False, triple_mode=False,
              final_mode=False):
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
    marks = {}
    kinds = ('snow_medal', 'void_medal') if dual_mode else ('sun_medal',) if medal_mode else ()
    if triple_mode:
        kinds += ('fire_medal', 'spiral_medal')
    if final_mode:
        kinds += ('leaf_medal',)
    if bomb_mode:
        kinds = ('bomb',) + kinds
    for r in range(rows):
        for c in range(cols):
            top, left = y + r * PITCH + 5, x + c * PITCH + 5
            region = tile_mask[top:top+24, left:left+24]
            coverage = region.mean()
            if coverage >= .30:
                marks[r, c] = next((kind for kind in kinds if
                                   _has_icon(rgb, x+c*PITCH+18, y+r*PITCH+17, 18, kind)), None)
            if coverage >= .68 or marks.get((r, c)):
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
    medals = tuple(cell for cell in cells if marks.get(cell) in (
        'snow_medal', 'sun_medal', 'fire_medal', 'spiral_medal', 'leaf_medal'))
    bombs = tuple(cell for cell in cells if marks.get(cell) == 'bomb')
    secondary = tuple(cell for cell in cells if marks.get(cell) == 'void_medal')
    return Piece(normalize(tuple(cells)), medals, bombs, secondary), (x + width / 2, y + height / 2)


def pieces_from_tray(rgb, medal_mode=False, bomb_mode=False, dual_mode=False, triple_mode=False,
                     final_mode=False):
    sample = scan_tray(rgb, medal_mode, bomb_mode, dual_mode, triple_mode, final_mode)
    return sample[0] if sample else None


def read_score_board(frame, medal_mode=False, slots=None, *, bomb_mode=False, dual_mode=False,
                     triple_mode=False, final_mode=False):
    h, w = frame.shape[:2]
    if abs(w * 9 - h * 16) > 16:
        raise ValueError('Only the 16:9 score board is calibrated')
    if (w, h) != (1920, 1080):
        frame = np.asarray(Image.fromarray(frame).resize((1920, 1080), Image.Resampling.BILINEAR))
    rgb = frame[:, :, :3]
    occupied = permanent = medals = bombs = secondary = faults = severe = 0
    for r in range(8):
        for c in range(8):
            x, y = 540 + c * 114, 130 + r * 114
            sample = np.median(rgb[y-6:y+6, x-6:x+6], axis=(0, 1))
            bit = 1 << (r * 8 + c)
            if sample[0] < 52 and sample[1] < 52 and sample[2] < 105:
                continue
            bomb = bomb_mode and _has_icon(rgb, x+22, y+3, 58, 'bomb')
            red, green, blue = rgb[y-28:y-10, x-20:x-2].mean(axis=(0, 1))
            pink_fault = bomb_mode and red > 233 and 105 < green < 170 and blue > 175
            orange_fault = triple_mode and red > 244 and 170 < green < 195 and 65 < blue < 92
            if pink_fault or orange_fault:
                faults |= bit
            triple_medal = triple_mode and any(
                _has_icon(rgb, x+22, y+3, 58, kind) for kind in ('fire_medal', 'spiral_medal'))
            triple_fault = triple_mode and (
                (orange_fault and _has_icon(rgb, x+22, y+3, 58, 'fire_fault'))
                or (pink_fault and _has_icon(rgb, x+22, y+3, 58, 'spiral_fault'))
                or (green > 213 and red > 244 and _has_icon(rgb, x+22, y+3, 58, 'sun_fault')))
            if triple_fault:
                faults |= bit
            if triple_fault or triple_medal:
                medals |= bit
            snow = dual_mode and _has_icon(rgb, x+22, y+3, 58, 'snow_medal')
            void = dual_mode and _has_icon(rgb, x+22, y+3, 58, 'void_medal')
            leaf_fault = final_mode and green > 185 and _has_icon(rgb, x+22, y+3, 58, 'leaf_fault')
            leaf = leaf_fault or (final_mode and _has_icon(rgb, x+22, y+3, 58, 'leaf_medal'))
            if leaf_fault:
                faults |= bit
            if final_mode:
                severe_leaf = green > 170 and red < 130 and (
                    _has_icon(rgb, x-13, y-23, 28, 'leaf_severe')
                    or _has_icon(rgb, x-13, y-23, 28, 'leaf_bomb_severe'))
                severe_snow = red < 130 and blue > 200 and _has_icon(
                    rgb, x-13, y-23, 28, 'snow_severe')
                severe_void = red > 180 and blue > 200 and _has_icon(
                    rgb, x-13, y-23, 28, 'void_severe')
                if severe_snow or severe_void or severe_leaf:
                    severe |= bit
                    faults |= bit
                    snow = snow or severe_snow
                    void = void or severe_void
                leaf = leaf or (severe_leaf and not bomb)
            if dual_mode:
                snow_fault = green > 130 and _has_icon(rgb, x+22, y+3, 58, 'snow_fault')
                void_fault = red > 180 and _has_icon(rgb, x+22, y+3, 58, 'void_fault')
                if snow_fault or void_fault:
                    faults |= bit
                    snow = snow or snow_fault
                    void = void or void_fault
            if sample.min() >= 75 and sample.max() <= 165 and np.ptp(sample) < 20:
                permanent |= bit
                occupied |= bit
            elif (bomb or snow or void or leaf or faults & bit or triple_medal
                  or np.min(np.max(np.abs(PALETTE - sample), axis=1)) <= 48):
                occupied |= bit
                if snow or leaf or (medal_mode and not dual_mode and _has_icon(rgb, x+19, y+7, 58, 'sun_medal')):
                    medals |= bit
                if void:
                    secondary |= bit
                if bomb:
                    bombs |= bit
            else:
                raise ValueError(f'Unrecognized grid cell at row {r+1}, column {c+1}')
    if slots is None:
        first_four = rgb[160:175, 1600:1620]
        first_three = rgb[273:285, 1600:1620]
        if first_four.mean() < 33 and first_four[:, :, 2].mean() < 55:
            slots = FOUR_SLOTS
        else:
            slots = HARD_SLOTS if permanent or (
                first_three.mean() < 33 and first_three[:, :, 2].mean() < 55) else SLOTS
    pieces = tuple(pieces_from_tray(rgb[y1:y2, x1:x2], medal_mode, bomb_mode, dual_mode,
                                   triple_mode, final_mode)
                   for x1, y1, x2, y2 in slots)
    return Board(occupied, pieces, permanent, slots, medals, bombs, secondary, dual_mode, medal_mode,
                 faults, triple_mode, severe, final_mode)
