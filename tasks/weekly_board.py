"""Confirm the unobstructed park board, rather than a button behind a modal."""
from pathlib import Path

import numpy as np
from PIL import Image

from image_matcher import TemplateMatcher


def board_ready(path):
    with Image.open(path) as image:
        width, height = image.size
    matcher = TemplateMatcher(Path(__file__).resolve().parents[1]/'templates/weekly150')
    try:
        title = matcher.find_fast(path, 'board_title.png', .9, scale=width/1920,
                                  region=(0, 0, round(width*.25), round(height*.16)))
        with Image.open(path) as image:
            pixels = np.asarray(image.convert('RGB').crop((title.x, title.y,
                                title.x+title.width, title.y+title.height)), dtype=np.int16)
        # Normalized correlation also matches dimmed text behind an overlay.
        gold = (pixels[:, :, 0] > 195) & (pixels[:, :, 1] > 115) & (pixels[:, :, 2] < 180)
        return float(gold.mean()) > .25
    except (OSError, RuntimeError):
        return False
