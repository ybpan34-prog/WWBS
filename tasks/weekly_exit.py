"""Match the park exit only in its own corner, away from currency controls."""
from pathlib import Path

import numpy as np
from PIL import Image

from image_matcher import TemplateMatcher
from tasks.weekly_board import board_ready


def weekly_exit_match(path):
    if not board_ready(path):
        raise RuntimeError('未确认无遮挡的棋盘，取消退出点击。')
    with Image.open(path) as image:
        width, height = image.size
    matcher = TemplateMatcher(Path(__file__).resolve().parents[1]/'templates/weekly150')
    match = matcher.find_fast(path, 'menu96.png', .95, scale=width/1920,
                             region=(round(width*.925), 0, round(width*.985), round(height*.14)))
    with Image.open(path) as image:
        pixels = np.asarray(image.convert('RGB').crop((match.x, match.y,
                            match.x+match.width, match.y+match.height)), dtype=np.int16)
    gold = (pixels[:, :, 0] > 195) & (pixels[:, :, 1] > 110) & (pixels[:, :, 2] < 175)
    if float(gold.mean()) < .3:
        raise RuntimeError('退出按钮颜色未确认，取消点击。')
    return match
