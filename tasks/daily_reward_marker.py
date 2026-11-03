"""Locate the reward chest marker, independently of bright scenery."""
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image

from image_matcher import _match_single_scale_gray


@lru_cache(maxsize=1)
def _templates():
    directory = Path(__file__).resolve().parents[1]/'templates/daily'
    return tuple(Image.open(directory/f'reward_marker_{i}.png').convert('L') for i in (1, 2, 3, 4, 5))


def reward_marker_location(screenshot):
    with Image.open(screenshot) as source:
        width, height = source.size
        # Exclude minimap, party portraits and the bottom skill bar. Markers
        # can be below the old white-core search band, including the 6m sample.
        left, top = round(width*.005), round(height*.12)
        region = source.convert('L').crop((left, top, round(width*.995), round(height*.88)))
    reduction = min(1., 960/width)
    region = region.resize((round(region.width*reduction), round(region.height*reduction)), Image.Resampling.LANCZOS)
    scene = np.asarray(region, dtype=np.float64)/255
    best = None
    for template in _templates():
        sizes = set()
        for factor in (.8, .9, .97, 1.05, 1.15, 1.3):
            side = max(12, round(37*width/1600*reduction*factor))
            if side in sizes or side >= min(scene.shape):
                continue
            sizes.add(side)
            patch = np.asarray(template.resize((side, side), Image.Resampling.LANCZOS), dtype=np.float64)/255
            match = _match_single_scale_gray(scene, patch)
            if best is None or match.score > best.score:
                best = match
    if best is None or best.score < .82:
        return None, None, 0.
    return (left+round((best.x+best.width/2)/reduction),
            top+round((best.y+best.height/2)/reduction), best.score)


@lru_cache(maxsize=1)
def _arrow_templates():
    directory = Path(__file__).resolve().parents[1]/'templates/daily'
    left = _arrow_mask(directory/'reward_arrow_left.png')
    left_low = _arrow_mask(directory/'reward_arrow_left_low.png')
    down_right = _arrow_mask(directory/'reward_arrow_down_right.png')
    return {
        'left': ((left, 1600), (left_low, 1920)),
        'right': ((left.transpose(Image.Transpose.ROTATE_180), 1600),
                  (left_low.transpose(Image.Transpose.FLIP_LEFT_RIGHT), 1920)),
        'up': ((left.transpose(Image.Transpose.ROTATE_270), 1600),),
        'down': ((left.transpose(Image.Transpose.ROTATE_90), 1600),),
        'down_right': ((down_right, 1600),),
        'down_left': ((down_right.transpose(Image.Transpose.FLIP_LEFT_RIGHT), 1600),),
    }


def _arrow_mask(path):
    with Image.open(path) as image:
        rgb = np.asarray(image.convert('RGB'))
    white = ((rgb.min(axis=2) > 210) & (np.ptp(rgb, axis=2) < 70)).astype('uint8')*255
    return Image.fromarray(white)


def reward_marker_direction(screenshot, x, y):
    with Image.open(screenshot) as image:
        width, height = image.size
        rgb = np.asarray(image.convert('RGB'))
    side = 37*width/1600
    boxes = {'left': (x-side*1.7, y-side*.65, x-side*.52, y+side*.65),
             'right': (x+side*.52, y-side*.65, x+side*1.7, y+side*.65),
             'up': (x-side*.65, y-side*1.7, x+side*.65, y-side*.52),
             'down': (x-side*.65, y+side*.52, x+side*.65, y+side*1.7),
             'down_right': (x+side*.49, y+side*.35, x+side*1.55, y+side*1.55),
             'down_left': (x-side*1.55, y+side*.35, x-side*.49, y+side*1.55)}
    best = (0., None)
    for direction, box in boxes.items():
        left, top, right, bottom = (round(value) for value in box)
        left, top = max(0, left), max(0, top)
        region = rgb[top:max(0, bottom), left:max(0, right)]
        if not region.size:
            continue
        scene = ((region.min(axis=2) > 210) & (np.ptp(region, axis=2) < 70)).astype(np.float64)
        threshold = .80 if direction.startswith('down_') else .82
        for template, reference_width in _arrow_templates()[direction]:
            for factor in (.75, .9, 1., 1.1, 1.25, 1.5):
                size = (max(4, round(template.width*width/reference_width*factor)),
                        max(4, round(template.height*width/reference_width*factor)))
                if size[0] >= scene.shape[1] or size[1] >= scene.shape[0]:
                    continue
                patch = np.asarray(template.resize(size, Image.Resampling.NEAREST), dtype=np.float64)/255
                match = _match_single_scale_gray(scene, patch)
                # A corner glyph on either side of the ring must turn horizontally.
                if direction == 'down' and abs(left+match.center[0]-x) >= side*.49:
                    continue
                if match.score >= threshold and match.score > best[0]:
                    best = (match.score, direction)
    direction = best[1]
    return direction.removeprefix('down_') if direction else None
