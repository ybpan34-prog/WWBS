"""Read the active party slot from the two inactive numeric portrait badges."""
from pathlib import Path
from functools import lru_cache

import numpy as np
from PIL import Image

from image_matcher import TemplateMatcher, _match_single_scale_gray


def enemy_health_bar_present(image: Image.Image) -> bool:
    """Find a thin red floating health bar inside the scene, excluding HUD edges."""
    frame = np.asarray(image.convert('RGB'), dtype=np.int16)
    height, width = frame.shape[:2]
    scene = frame[round(height*.13):round(height*.72), round(width*.18):round(width*.82)]
    red, green, blue = (scene[:, :, index] for index in range(3))
    health = ((red > 170) & (red > green*1.8) & (red > blue*1.5)
              & (blue > red*.2) & (abs(green-blue) < 40))
    gap = max(2, round(height*.008))
    for y in range(gap, len(health)-gap):
        positions = np.flatnonzero(health[y])
        if not len(positions):
            continue
        for run in np.split(positions, np.flatnonzero(np.diff(positions) > 2)+1):
            span = run[-1]-run[0]+1
            if not width*.018 <= span <= width*.18 or len(run)/span < .85:
                continue
            # A health bar has horizontal edges; red character art and large
            # scenery patches usually continue above or below the candidate.
            if (health[y-gap, run[0]:run[-1]+1].mean() < .15
                    and health[y+gap, run[0]:run[-1]+1].mean() < .15):
                return True
    return False


@lru_cache(maxsize=48)
def _badge_template(path: Path, modified_ns: int, scale: float) -> np.ndarray:
    # The timestamp invalidates a replaced template without rereading it per frame.
    with Image.open(path) as source:
        image = source.convert('L')
        size = (max(8, round(image.width*scale)), max(8, round(image.height*scale)))
        return np.asarray(image.resize(size, Image.Resampling.BILINEAR), dtype=np.float64)/255.


def active_character_slot(screenshot: Path, matcher: TemplateMatcher) -> int | None:
    with Image.open(screenshot) as image:
        width, height = image.size
        game_height = min(height, round(width*9/16))
        titlebar = max(0, height-game_height)
        scale = game_height/1080
        inactive = []
        # Decode the frame once; convert only the three tiny portrait badge regions.
        for slot, fraction in ((1, .205), (2, .328), (3, .45)):
            y = titlebar+game_height*fraction
            region = (max(0, round(width-225*scale)), max(0, round(y-28*scale)),
                      min(width, round(width-140*scale)), min(height, round(y+28*scale)))
            crop = np.asarray(image.crop(region).convert('L'), dtype=np.float64)/255.
            path = matcher.templates_dir / f'slot_{slot}.png'
            modified_ns = path.stat().st_mtime_ns
            for candidate in (scale, scale*.97, scale*1.03):
                template = _badge_template(path, modified_ns, candidate)
                if template.shape[0] >= crop.shape[0] or template.shape[1] >= crop.shape[1]:
                    continue
                if _match_single_scale_gray(crop, template).score >= .88:
                    inactive.append(slot)
                    break
    if len(inactive) != 2:
        return None  # Hidden HUD, dead characters, or an ambiguous transition.
    return next(slot for slot in (1, 2, 3) if slot not in inactive)
