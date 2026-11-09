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


def crystal_dismiss_point(path):
    matcher = TemplateMatcher(Path(__file__).resolve().parents[1]/'templates/weekly150')
    try:
        with Image.open(path) as image:
            width, height = image.size
    except OSError:
        return None
    for name, box in (
        ('crystal_detail_title.png', (.40, .24, .51, .32)),
        ('crystal_detail_icon.png', (.40, .30, .51, .45)),
    ):
        region = tuple(round(value * (width if i % 2 == 0 else height))
                       for i, value in enumerate(box))
        try:
            matcher.find_fast(path, name, .88, scale=width/1920, region=region)
        except (OSError, RuntimeError):
            return None
    return round(width*.77), round(height*.76)
