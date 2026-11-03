"""Recognize the stage-goal overlay before considering background controls."""
from pathlib import Path

import numpy as np
from PIL import Image

from image_matcher import TemplateMatcher


def stage_goal_confirm(path):
    matcher = TemplateMatcher(Path(__file__).resolve().parents[1]/'templates/weekly150')
    with Image.open(path) as image:
        width, height = image.size
    try:
        matcher.find_fast(path, 'stage_goal_title.png', .88, scale=width/1920,
                          region=(round(width*.32), round(height*.24), round(width*.69), round(height*.46)))
        button = matcher.find_fast(path, 'stage_goal_confirm.png', .88, scale=width/1920,
                          region=(round(width*.36), round(height*.55), round(width*.65), round(height*.79)))
        with Image.open(path) as image:
            x, y = button.center
            area = np.asarray(image.convert('RGB').crop((x-round(width*.07), y-round(height*.025),
                                                        x+round(width*.07), y+round(height*.025))), dtype=np.int16)
        orange = (area[:, :, 0] > 200) & (area[:, :, 1] > 115) & (area[:, :, 1] < 210) & (area[:, :, 2] < 145)
        return button.center if orange.mean() > .5 else None
    except (OSError, RuntimeError):
        return None
