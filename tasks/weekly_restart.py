"""Recognize the actual restart button and the next round's entry page."""
from pathlib import Path

import numpy as np
from PIL import Image

from image_matcher import TemplateMatcher
from tasks.weekly_board import board_ready


def _button(path, name, region, threshold=.93):
    matcher = TemplateMatcher(Path(__file__).resolve().parents[1]/'templates/weekly150')
    with Image.open(path) as image:
        width, height = image.size
    box = tuple(round(value*(width if i % 2 == 0 else height)) for i, value in enumerate(region))
    match = matcher.find_fast(path, name, threshold, scale=width/1920, region=box)
    # Match the caption independently; pale button borders alone are ambiguous.
    crops = {'menu99.png': (.27, .32, .73, .74), 'menu4.png': (.43, .25, .66, .75),
             'menu2.png': (.31, .20, .69, .81)}
    with Image.open(matcher.templates_dir/name) as image:
        crop = tuple(round(value*(image.width if i % 2 == 0 else image.height))
                     for i, value in enumerate(crops[name]))
    matcher.find_fast(path, name, .9, scale=width/1920,
                      region=(match.x, match.y, match.x+match.width, match.y+match.height), template_crop=crop)
    return match


def restart_match(path):
    match = _button(path, 'menu99.png', (.20, .78, .47, .97))
    with Image.open(path) as image:
        width, height = image.size
    home = TemplateMatcher(Path(__file__).resolve().parents[1]/'templates/weekly')
    home.find_fast(path, 'return_home.png', .88, scale=width/1920,
                   region=(round(width*.56), round(height*.80), round(width*.79), round(height*.97)))
    return match


def round_entry(path):
    if board_ready(path):
        return 'menu3.png'
    for name, region in (('menu2.png', (.25, .30, .75, .78)),
                         ('menu4.png', (.25, .30, .92, .95))):
        try:
            _button(path, name, region)
            return name
        except RuntimeError:
            pass
    return None


def skip_match(path):
    return _button(path, 'menu4.png', (0., 0., 1., 1.), threshold=.88)


def thumbnail(path):
    with Image.open(path) as image:
        return np.asarray(image.convert('RGB').resize((120, 68)), dtype=np.int16)
