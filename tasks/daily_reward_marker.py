"""Locate the reward chest marker, independently of bright scenery."""
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image

from image_matcher import _fast_fft_length, _match_single_scale_gray, _window_sum


@lru_cache(maxsize=1)
def _templates():
    directory = Path(__file__).resolve().parents[1]/'templates/daily'
    return tuple(Image.open(directory/f'reward_marker_{i}.png').convert('L') for i in (1, 2, 3, 4, 5))


def reward_marker_location(screenshot, near=None):
    with Image.open(screenshot) as source:
        width, height = source.size
        # Exclude minimap, party portraits and the bottom skill bar. Markers
        # can be below the old white-core search band, including the 6m sample.
        bounds = (round(width*.005), round(height*.12), round(width*.995), round(height*.88))
        image = source.convert('L')
    reduction = min(1., 960/width)
    if near is not None:
        x, y = near
        left, top, right, bottom = bounds
        local = (max(left, x-round(width*.10)), max(top, y-round(height*.12)),
                 min(right, x+round(width*.10)), min(bottom, y+round(height*.12)))
        if local[0] < local[2] and local[1] < local[3]:
            match = _find_marker_in_region(image, local, width, reduction)
            if match[0] is not None:
                return match
    return _find_marker_in_region(image, bounds, width, reduction)


def _find_marker_in_region(image, bounds, width, reduction):
    left, top, _, _ = bounds
    region = image.crop(bounds)
    region = region.resize((round(region.width*reduction), round(region.height*reduction)), Image.Resampling.LANCZOS)
    scene = np.asarray(region, dtype=np.float64)/255
    best = None
    scene_transforms = {}
    sides = dict.fromkeys(max(12, round(37*width/1600*reduction*f))
                          for f in (.8, .9, .97, 1.05, 1.15, 1.3))
    for side in sides:
        if side >= min(scene.shape):
            continue
        shape = tuple(_fast_fft_length(n+side-1) for n in scene.shape)
        if shape not in scene_transforms:
            scene_transforms[shape] = np.fft.rfft2(scene, s=shape, axes=(0, 1))
        transform = scene_transforms[shape]
        local_sum = _window_sum(scene, side, side)
        norm = np.sqrt(np.maximum(_window_sum(scene*scene, side, side)-local_sum**2/side**2, 0))
        for kernel, template_norm in _marker_kernels(side, shape):
            corr = np.fft.irfft2(transform*kernel, s=shape, axes=(0, 1))
            corr = corr[side-1:scene.shape[0], side-1:scene.shape[1]]
            scores = np.divide(corr, norm*template_norm, out=np.full_like(corr, -1.),
                               where=norm >= template_norm*.08)
            y, x = np.unravel_index(np.argmax(scores), scores.shape)
            score = min(1., float(scores[y, x]))
            if best is None or score > best[0]:
                best = score, x, y, side
    if best is None or best[0] < .82:
        return None, None, 0.
    score, x, y, side = best
    return left+round((x+side/2)/reduction), top+round((y+side/2)/reduction), score


@lru_cache(maxsize=6)
def _marker_kernels(side, shape):
    result = []
    for template in _templates():
        patch = np.asarray(template.resize((side, side), Image.Resampling.LANCZOS), dtype=np.float64)/255
        patch -= patch.mean()
        result.append((np.fft.rfft2(patch[::-1, ::-1], s=shape, axes=(0, 1)), np.linalg.norm(patch)))
    return result


@lru_cache(maxsize=1)
def _arrow_templates():
    directory = Path(__file__).resolve().parents[1]/'templates/daily'
    left = _arrow_mask(directory/'reward_arrow_left.png')
    left_low = _arrow_mask(directory/'reward_arrow_left_low.png')
    left_tilted = _arrow_mask(directory/'reward_arrow_left_tilted.png')
    down_right = _arrow_mask(directory/'reward_arrow_down_right.png')
    down_right_steep = _arrow_mask(directory/'reward_arrow_down_right_steep.png')
    down_right_steep_small = _arrow_mask(directory/'reward_arrow_down_right_steep_1600.png')
    return {
        'left': ((left, 1600), (left_low, 1920), (left_tilted, 1920)),
        'right': ((left.transpose(Image.Transpose.ROTATE_180), 1600),
                  (left_low.transpose(Image.Transpose.FLIP_LEFT_RIGHT), 1920),
                  (left_tilted.transpose(Image.Transpose.FLIP_LEFT_RIGHT), 1920)),
        'up': ((left.transpose(Image.Transpose.ROTATE_270), 1600),),
        'down': ((left.transpose(Image.Transpose.ROTATE_90), 1600),),
        'down_right': ((down_right, 1600), (down_right_steep, 1920), (down_right_steep_small, 1600)),
        'down_left': ((down_right.transpose(Image.Transpose.FLIP_LEFT_RIGHT), 1600),
                      (down_right_steep.transpose(Image.Transpose.FLIP_LEFT_RIGHT), 1920),
                      (down_right_steep_small.transpose(Image.Transpose.FLIP_LEFT_RIGHT), 1600)),
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
             'down_right': (x+side*.08, y+side*.35, x+side*1.55, y+side*1.55),
             'down_left': (x-side*1.55, y+side*.35, x-side*.08, y+side*1.55)}
    best = (0., None)
    possible_arrow = False
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
                if direction.startswith('down_') and abs(left+match.center[0]-x) < side*.15:
                    continue
                # A corner glyph on either side of the ring must turn horizontally.
                if direction == 'down' and abs(left+match.center[0]-x) >= side*.49:
                    continue
                if match.score >= threshold and match.score > best[0]:
                    best = (match.score, direction)
                elif match.score >= threshold - .06:
                    possible_arrow = True
    direction = best[1]
    if direction:
        return direction.removeprefix('down_')
    return 'uncertain' if possible_arrow else None
