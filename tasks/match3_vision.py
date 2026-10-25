"""Read the supplied 7×8 board, rejecting overlays and unrecognised tiles."""
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image

from tasks.match3_solver import Tile, ROWS, COLS


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


@dataclass(frozen=True)
class BoardFrame:
    tiles: tuple
    centers: tuple
    confidence: float

    @property
    def signature(self):
        return self.tiles


def read_board(path):
    with Image.open(path) as source:
        image = source.convert('RGB')
    width, height = image.size
    if abs(width/height-16/9) > .04:
        return None
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
        return None
    refs = references()
    tiles, centers, scores = [], [], []
    for row in range(ROWS):
        values, points = [], []
        for col in range(COLS):
            x, y = 773+102.85*col, 163+102.5*row
            candidates = []
            for ox, oy in ((0, 0), (-2, 0), (2, 0), (0, -2), (0, 2)):
                crop = normal.crop((round(x-34+ox), round(y-34+oy), round(x+34+ox), round(y+34+oy)))
                data = np.asarray(crop)
                if (data.max(axis=2) > 155).mean() < .18:
                    continue
                vector = feature(crop)
                ncc = (refs@vector)/len(vector)
                candidates.append(ncc)
            if not candidates:
                return None
            scores_by_type = np.max(candidates, axis=0)
            index = int(np.argmax(scores_by_type))
            # Small gold markers distinguish bomb/cross. Only commit their
            # identity when the supplied special sprite wins clearly.
            if index in (5, 6) and scores_by_type[index]-scores_by_type[2 if index == 5 else 0] < .035:
                index = 2 if index == 5 else 0
            score = float(scores_by_type[index])
            other_colors = [scores_by_type[i] for i in range(len(TILES)) if TILES[i].color != TILES[index].color]
            if score < .74 or score-max(other_colors) < .09:
                return None
            values.append(TILES[index])
            points.append((round(x*width/1600), round(y*height/900)))
            scores.append(score)
        tiles.append(tuple(values))
        centers.append(tuple(points))
    return BoardFrame(tuple(tiles), tuple(centers), min(scores))
