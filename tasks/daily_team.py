"""Recognize the team page's paired buttons without matching character art."""
from pathlib import Path

import numpy as np
from PIL import Image


def team_start_target(screenshot: Path) -> tuple[int, int] | None:
    with Image.open(screenshot) as source:
        image = np.asarray(source.convert('RGB'))
    height, width = image.shape[:2]
    left, top = round(width*.60), round(height*.86)
    area = image[top:round(height*.97), left:round(width*.97)]
    pale = (area.min(axis=2) > 195) & (np.ptp(area, axis=2) < 65)
    rows = np.flatnonzero(pale.mean(axis=1) > .40)
    if not len(rows):
        return None
    for band in np.split(rows, np.flatnonzero(np.diff(rows) > 1)+1):
        if not height*.018 <= len(band) <= height*.065:
            continue
        columns = np.flatnonzero(pale[band[0]:band[-1]+1].mean(axis=0) > .55)
        if not len(columns):
            continue
        buttons = []
        for run in np.split(columns, np.flatnonzero(np.diff(columns) > max(2, width*.024))+1):
            span = run[-1]-run[0]+1
            if not width*.075 <= span <= width*.23:
                continue
            button = area[band[0]:band[-1]+1, run[0]:run[-1]+1]
            ink = float((button.max(axis=2) < 130).mean())
            if .01 < ink < .35:
                buttons.append((left+int((run[0]+run[-1])//2),
                                top+int((band[0]+band[-1])//2), span))
        if len(buttons) == 2 and buttons[1][2] >= buttons[0][2] and buttons[1][0] > width*.80:
            return buttons[1][:2]
    return None
