"""Native radio title/icon evidence, including already-claimed reward pages."""
from pathlib import Path

from PIL import Image

from image_matcher import TemplateMatcher


class DailyRadioVision:
    def __init__(self, templates):
        self.matcher = TemplateMatcher(Path(templates))

    def find(self, path, name, box, threshold=.86):
        with Image.open(path) as source:
            width, height = source.size
        if abs(width/height-16/9) > .04:
            return None
        region = tuple(round(value*(width if i % 2 == 0 else height)) for i, value in enumerate(box))
        try:
            return self.matcher.find_fast(path, name, threshold=threshold, scale=width/1600, region=region)
        except (OSError, RuntimeError):
            return None

    def page(self, path):
        return self.find(path, 'radio_title_native.png', (.045, .025, .16, .105)) is not None

    def rewards_icon(self, path):
        return self.page(path) and self.find(path, 'radio_rewards_tab_native.png', (.018, .12, .065, .23), .80) is not None

    def close(self, path):
        return self.find(path, 'radio_close_native.png', (.92, .015, .98, .105), .84) if self.page(path) else None
