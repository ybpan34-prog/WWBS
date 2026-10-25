"""Read the supplied 7×8 board, rejecting overlays and unrecognised tiles."""
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image

from image_matcher import TemplateMatcher
from tasks.match3_solver import Tile, UNKNOWN, ROWS, COLS


ASSETS = Path(__file__).resolve().parent.parent/'templates/match3'
NAMES = ('green', 'red', 'purple', 'cat', 'blue', 'purple_bomb', 'green_cross', 'rainbow')
TILES = (Tile(0), Tile(1), Tile(2), Tile(3), Tile(4), Tile(2, 'bomb'), Tile(0, 'cross'), Tile(5, 'rainbow'))


def feature(image):
    rgb = np.asarray(image.resize((40, 40), Image.Resampling.BILINEAR).convert('RGB'), dtype=float)/255
    mean, std = rgb.mean(), rgb.std()
    return ((rgb-mean)/max(std, .08)).reshape(-1)


@lru_cache(maxsize=1)
def references():
    return np.array([feature(Image.open(ASSETS/(name+'.png'))) for name in NAMES])


@lru_cache(maxsize=1)
def rainbow_reference():
    with Image.open(ASSETS/'rainbow_native.png') as source:
        return feature(source)


def success_present(path):
    with Image.open(path) as source:
        width, height = source.size
    if abs(width/height-16/9) > .04:
        return False
    matcher = TemplateMatcher(ASSETS)
    for name, box in (('success_title_native.png', (.35, .40, .66, .62)),
                      ('exit_level_native.png', (.33, .81, .68, .97))):
        region = tuple(round(value*(width if i % 2 == 0 else height)) for i, value in enumerate(box))
        try:
            matcher.find_fast(path, name, threshold=.84, scale=width/1600, region=region)
        except (OSError, RuntimeError):
            return False
    return True


@lru_cache(maxsize=1)
def target_reference():
    with Image.open(ASSETS/'target.png') as source:
        return feature(source.crop((0, 24, 68, 68)))


def target_hearts(crop):
    rgb = np.asarray(crop.convert('RGB'), dtype=np.int16)[:24]
    gold = (rgb[:, :, 0] > 190) & (rgb[:, :, 1] > 110) & (rgb[:, :, 2] < 105)
    columns = np.flatnonzero(gold.sum(axis=0) >= 3)
    groups = np.split(columns, np.flatnonzero(np.diff(columns) > 2)+1) if len(columns) else []
    return max(1, min(3, sum(len(group) >= 4 for group in groups)))


@dataclass(frozen=True)
class BoardFrame:
    tiles: tuple
    centers: tuple
    confidence: float

    @property
    def signature(self):
        return self.tiles


def shared_board(first, second):
    """Keep mutually confirmed cells; unfamiliar sprites cannot reset a board."""
    if first.centers != second.centers:
        return None
    if first.tiles == second.tiles:
        return second
    shared, confirmed = [], 0
    for row in range(ROWS):
        values = []
        for col in range(COLS):
            a, b = first.tiles[row][col], second.tiles[row][col]
            if a.color >= 0 and b.color >= 0:
                if a != b:
                    return None
                values.append(b)
                confirmed += 1
            else:
                values.append(UNKNOWN)
        shared.append(tuple(values))
    return replace(second, tiles=tuple(shared), confidence=min(first.confidence, second.confidence)) if confirmed >= 8 else None


def known_change(before, after):
    return any(a.color >= 0 and b.color >= 0 and a != b
               for old_row, new_row in zip(before, after) for a, b in zip(old_row, new_row))


def read_board(path, diagnostics=None):
    def reject(reason):
        if diagnostics is not None:
            diagnostics['reason'] = reason
        return None
    with Image.open(path) as source:
        image = source.convert('RGB')
    width, height = image.size
    if abs(width/height-16/9) > .04:
        return reject('游戏画面比例不符，需完整的16:9客户端画面。')
    normal = image.resize((1600, 900), Image.Resampling.BILINEAR)
    rgb = np.asarray(normal, dtype=np.int16)
    rim = (rgb[:, :, 0] > 105) & (rgb[:, :, 0] > rgb[:, :, 1]*1.30) & (rgb[:, :, 2] > rgb[:, :, 1]*1.30)
    # Both long side borders and both horizontal borders must be visible.
    # The dark help/tutorial overlay dims these below the required brightness.
    left = np.flatnonzero(rim[100:825, 690:730].mean(axis=0) > .85)
    right = np.flatnonzero(rim[100:825, 1540:1580].mean(axis=0) > .85)
    upper = np.flatnonzero(rim[80:115, 735:1530].mean(axis=1) > .85)
    lower = np.flatnonzero(rim[825:862, 735:1530].mean(axis=1) > .85)
    if not all(len(band) for band in (left, right, upper, lower)):
        return reject('未找到完整棋盘边框，可能有遮挡、弹窗或画面仍在切换。')
    refs = references()
    tiles, centers, scores, unknown, obscured = [], [], [], [], []
    for row in range(ROWS):
        values, points = [], []
        for col in range(COLS):
            x, y = 773+102.85*col, 163+102.5*row
            candidates = []
            target_candidates = []
            rainbow_scores = []
            for ox, oy in ((a, b) for a in (-4, 0, 4) for b in (-4, 0, 4)):
                crop = normal.crop((round(x-34+ox), round(y-34+oy), round(x+34+ox), round(y+34+oy)))
                data = np.asarray(crop)
                if (data.max(axis=2) > 155).mean() < .18:
                    continue
                vector = feature(crop)
                ncc = (refs@vector)/len(vector)
                candidates.append(ncc)
                rainbow_scores.append(float(rainbow_reference()@vector/len(vector)))
                target_score = float(target_reference()@feature(crop.crop((0, 24, 68, 68)))/len(vector))
                target_candidates.append((target_score, crop))
            if not candidates:
                values.append(UNKNOWN)
                points.append((round(x*width/1600), round(y*height/900)))
                unknown.append((row, col))
                obscured.append((row, col))
                continue
            scores_by_type = np.max(candidates, axis=0)
            rainbow_score = max(rainbow_scores)
            if rainbow_score >= .82 and rainbow_score > float(scores_by_type[:7].max())+.08:
                values.append(Tile(5, 'rainbow'))
                points.append((round(x*width/1600), round(y*height/900)))
                scores.append(rainbow_score)
                continue
            target_score, target_crop = max(target_candidates, key=lambda item: item[0])
            if target_score >= .82 and target_score > float(scores_by_type.max())+.03:
                values.append(Tile(6, 'target', target_hearts(target_crop)))
                points.append((round(x*width/1600), round(y*height/900)))
                scores.append(target_score)
                continue
            index = int(np.argmax(scores_by_type))
            # Small gold markers distinguish bomb/cross. Only commit their
            # identity when the supplied special sprite wins clearly.
            if index in (5, 6) and scores_by_type[index]-scores_by_type[2 if index == 5 else 0] < .035:
                index = 2 if index == 5 else 0
            score = float(scores_by_type[index])
            other_colors = [scores_by_type[i] for i in range(len(TILES)) if TILES[i].color != TILES[index].color]
            if score < .74 or score-max(other_colors) < .09:
                values.append(UNKNOWN)
                unknown.append((row, col))
            else:
                values.append(TILES[index])
                scores.append(score)
            points.append((round(x*width/1600), round(y*height/900)))
        tiles.append(tuple(values))
        centers.append(tuple(points))
    if diagnostics is not None:
        diagnostics['unknown'] = unknown
    # A few unfamiliar level-specific tiles are blockers, not a reason to reject
    # the entire board. Large obscured areas still cannot authorize input.
    if len(unknown) > 40 or len(obscured) > 14:
        return reject(f'只有{ROWS*COLS-len(unknown)}格可确认，棋盘可能被大面积遮挡。')
    obscured_set = set(obscured)
    if any(sum((r, c) in obscured_set for r in range(top, top+3) for c in range(left, left+3)) >= 8
           for top in range(ROWS-2) for left in range(COLS-2)):
        return reject('棋盘有连续大片未识别区域，可能存在弹窗遮挡，等待恢复。')
    return BoardFrame(tuple(tiles), tuple(centers), min(scores) if scores else 0.)
