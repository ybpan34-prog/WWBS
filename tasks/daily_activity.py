"""Read the yellow current activity counter without matching its background."""
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image


def _yellow_digits(image: Image.Image) -> np.ndarray:
    rgb = np.asarray(image.convert('RGB')).astype(np.int16)
    red, green, blue = rgb[:, :, 0], rgb[:, :, 1], rgb[:, :, 2]
    return (red > 155) & (green > 130) & (blue < green*.85) & (red > blue+35)


def _digits(mask: np.ndarray, minimum_height: float, maximum_height: float):
    # Column projection joins the thin yellow decoration to the first "1".
    # Separate connected ink regions so that horizontal rules cannot widen it.
    parts = []
    seen = np.zeros(mask.shape,dtype=bool)
    rows,columns = mask.shape
    for y,x in zip(*np.nonzero(mask)):
        if seen[y,x]:
            continue
        pending = [(int(y),int(x))]
        seen[y,x] = True
        points = []
        while pending:
            yy,xx = pending.pop()
            points.append((yy,xx))
            for ny,nx in ((yy-1,xx),(yy+1,xx),(yy,xx-1),(yy,xx+1)):
                if 0 <= ny < rows and 0 <= nx < columns and mask[ny,nx] and not seen[ny,nx]:
                    seen[ny,nx] = True
                    pending.append((ny,nx))
        top,bottom = min(point[0] for point in points),max(point[0] for point in points)+1
        left,right = min(point[1] for point in points),max(point[1] for point in points)+1
        height, width = bottom-top, right-left
        if minimum_height <= height <= maximum_height and .25 <= width/height <= 1.1:
            ink = np.zeros((height,width),dtype=bool)
            for yy,xx in points:
                ink[yy-top,xx-left] = True
            parts.append((left,top,right,bottom,ink))
    return sorted(parts,key=lambda part:part[0])


def _normalized(mask: np.ndarray) -> np.ndarray:
    return np.asarray(Image.fromarray(mask.astype(np.uint8)*255).resize(
        (24, 36), Image.Resampling.BILINEAR)) > 100


@lru_cache(maxsize=8)
def _reference_digits(template: str, modified_ns: int):
    with Image.open(template) as image:
        parts = _digits(_yellow_digits(image), 10, image.height)
    if len(parts) != 3:
        raise ValueError('活跃度100模板没有完整的三个数字。')
    return tuple(_normalized(part[4]) for part in parts)


def activity_counter_full(screenshot: Path, template: Path) -> bool:
    with Image.open(screenshot) as image:
        width, height = image.size
        # Milestone labels (including another "100") are outside this region.
        if width < 512 and height < 256 and width/height < 1.5:
            # Also support a cropped counter supplied for diagnostics.
            region = image.copy()
            parts = _digits(_yellow_digits(region),height*.12,height*.50)
        else:
            region = image.crop((round(width*.15), round(height*.77),
                                 round(width*.29), round(height*.94)))
            parts = _digits(_yellow_digits(region), height*.020, height*.052)
    try:
        reference = _reference_digits(str(template), template.stat().st_mtime_ns)
    except (OSError, ValueError):
        return False
    for index in range(max(0, len(parts)-2)):
        candidate = parts[index:index+3]
        heights = [part[3]-part[1] for part in candidate]
        if max(heights)-min(heights) > max(3, height*.005):
            continue
        if max(part[1] for part in candidate)-min(part[1] for part in candidate) > max(3, height*.005):
            continue
        if any(not 0 < following[0]-current[2] < max(heights)*.65
               for current, following in zip(candidate, candidate[1:])):
            continue
        # Only three or more aligned digits can reach 100. The leading digit
        # must be nonzero; middle digits need not look like the old "100".
        if any(not .18 <= float(part[4].mean()) <= .85 for part in candidate):
            continue
        actual = _normalized(candidate[0][4])
        def similarity(expected):
            overlap = np.logical_and(actual, expected).sum()
            union = np.logical_or(actual, expected).sum()
            return overlap/union if union else 0.
        # A zero has one tall central hole. 6/8/9 may overlap a zero template
        # strongly but their middle strokes interrupt that hole.
        center = actual[:,actual.shape[1]//2-1:actual.shape[1]//2+2].any(axis=1)
        empty = np.flatnonzero(~center)
        gaps = np.split(empty,np.flatnonzero(np.diff(empty)>1)+1)
        zero_hole = max((len(gap) for gap in gaps),default=0) >= actual.shape[0]*.45
        if similarity(reference[1]) >= .65 and zero_hole:
            continue  # Reject 000 and other zero-padded values below 100.
        aspect = (candidate[0][2]-candidate[0][0])/heights[0]
        if aspect <= .55 and similarity(reference[0]) < .60:
            continue
        return True
    return False
