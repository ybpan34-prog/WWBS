"""Locate terminal entries from their icons and captions, never fixed ratios."""
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image

from image_matcher import _match_single_scale_gray


@lru_cache(maxsize=4)
def _reference(path):
    with Image.open(path) as image:
        return np.asarray(image.convert('L'), dtype=np.float64)/255


def terminal_target(screenshot: Path, templates: Path, label: str):
    names = {'索拉指南':'terminal_guide_entry.png', '先约电台':'terminal_radio_entry.png'}
    if label not in names:
        raise ValueError('不支持的终端入口：'+label)
    with Image.open(screenshot) as image:
        width, height = image.size
        if abs(width/height-16/9) > .05:
            return None
        # The supplied diagnostic is a 424px-wide game preview. Compare at that
        # native detail rather than inventing pixels in an enlarged reference.
        small = image.convert('L').resize((424, 239), Image.Resampling.BILINEAR)
    pixels = np.asarray(small, dtype=np.float64)/255
    left, top = 170, 22
    region = pixels[top:211, left:412]
    matches = {}
    for name in names.values():
        match = _match_single_scale_gray(region, _reference(str(templates/name)))
        if match.score < .87:
            return None
        matches[name] = match
    guide, radio = (matches[names[key]] for key in ('索拉指南', '先约电台'))
    # Two different menu entries must coexist in the terminal grid. An isolated
    # book/camera icon elsewhere is not evidence that the terminal is open.
    if not (50 <= radio.x-guide.x <= 165 and 65 <= guide.y-radio.y <= 170):
        return None
    target = matches[names[label]]
    # Click the icon itself; the space between its icon and caption is not a button.
    return (round((left+target.x+target.width/2)*width/424),
            round((top+target.y+11)*height/239))
