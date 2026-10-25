"""Supplementary evidence for an already-open tacet-field guide page."""
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image

from image_matcher import _match_single_scale_gray


@lru_cache(maxsize=1)
def _label():
    with Image.open(Path(__file__).resolve().parent.parent/'templates/daily/guide_tacet_selected_native.png') as image:
        return image.convert('L').copy()


def selected_tacet_label(screenshot):
    with Image.open(screenshot) as image:
        width, height = image.size
        left, top = round(width*.13), round(height*.40)
        gray = np.asarray(image.crop((left, top, round(width*.35), round(height*.87))).convert('L'), dtype=np.float64)/255
        rgb = np.asarray(image.convert('RGB'))
    label = _label()
    for scale in (width/1600, width/1600*.96, width/1600*1.04, width/1600*.9, width/1600*1.1):
        patch = np.asarray(label.resize((round(label.width*scale), round(label.height*scale))), dtype=np.float64)/255
        match = _match_single_scale_gray(gray, patch)
        if match.score < .86:
            continue
        row_y = top+match.y+patch.shape[0]//2
        row = rgb[max(0, row_y-round(height*.025)):min(height, row_y+round(height*.025)),
                  round(width*.105):round(width*.34)]
        if row.size and float((row.min(axis=2) > 170).mean()) > .5:
            return row_y
    return None


def tacet_card_list_present(screenshot):
    """Require multiple right-hand cards with their separate dark action buttons."""
    with Image.open(screenshot) as image:
        pixels = np.asarray(image.convert('RGB'))
    height, width = pixels.shape[:2]
    panel = pixels[round(height*.22):round(height*.86), round(width*.37):round(width*.96)]
    pale = (panel.min(axis=2) > 145) & (panel.max(axis=2)-panel.min(axis=2) < 65)
    active = np.flatnonzero(pale.mean(axis=1) > .48)
    if not len(active):
        return False
    groups = np.split(active, np.flatnonzero(np.diff(active) > max(3, round(height*.008)))+1)
    cards = 0
    for group in groups:
        if not height*.055 <= len(group) <= height*.16:
            continue
        row_y = round(height*.22)+int((group[0]+group[-1])//2)
        button = pixels[row_y-round(height*.015):row_y+round(height*.015),
                        round(width*.84):round(width*.94)]
        if button.size and float((button.max(axis=2) < 100).mean()) > .5:
            cards += 1
    return cards >= 2
