"""Conservative weekly page recognition; coordinates refer to the client area."""
from pathlib import Path
from PIL import Image
import numpy as np
from image_matcher import TemplateMatcher


class WeeklyLimitReached(Exception):
    """The weekly loop ended intentionally, not because a menu image timed out."""


class WeeklyRewardsVision:
    CHEST_X = (710, 924, 1138, 1352, 1564, 1778)

    def __init__(self, templates: Path):
        self.matcher = TemplateMatcher(templates)

    def matches(self, screenshot: Path, name: str, region: tuple[int, int, int, int], threshold: float = 0.88) -> bool:
        with Image.open(screenshot) as image:
            width, height = image.size
        if abs(width / height - 16 / 9) > 0.04:
            return False
        scale = width / 1920
        try:
            self.matcher.find_fast(screenshot, name, threshold=threshold, scale=scale,
                                   region=tuple(round(p * scale) for p in region))
            return True
        except (RuntimeError, FileNotFoundError):
            return False

    def cap_page(self, screenshot: Path) -> str | None:
        if self.matches(screenshot, "cap_result.png", (1380, 580, 1640, 680)) and self.matches(
                screenshot, "return_home.png", (1170, 865, 1390, 975)):
            return "result"
        if self.matches(screenshot, "cap_home.png", (90, 170, 350, 270)) and self.matches(
                screenshot, "park_title.png", (110, 35, 455, 140)):
            return "home"
        return None

    def weekly_page(self, screenshot: Path) -> bool:
        return self.matches(screenshot, "weekly_tab.png", (540, 105, 745, 195))

    def all_claimed(self, screenshot: Path) -> bool:
        return self.weekly_page(screenshot) and all(self.matches(
            screenshot, "claimed.png", (x - 38, 928, x + 38, 991)) for x in self.CHEST_X)

    def rightmost_claimable(self, screenshot: Path) -> tuple[int, int] | None:
        # Enable only with a verified glowing-chest reference; never infer a
        # reward from an absolute 5000/6000 coordinate or click a claimed check.
        if not (self.matcher.templates_dir / "claimable.png").is_file() or not self.weekly_page(screenshot):
            return None
        with Image.open(screenshot) as image:
            scale = image.width / 1920
            pixels = np.asarray(image.convert("RGB"), dtype=np.float32)
        for x in reversed(self.CHEST_X):
            region = (x - 48, 912, x + 48, 1005)
            hint = pixels[round(909 * scale):round(937 * scale), round((x + 20) * scale):round((x + 46) * scale)]
            body = pixels[round(944 * scale):round(980 * scale), round((x - 28) * scale):round((x + 28) * scale)]
            if not hint.size or not body.size:
                continue
            red = (hint[..., 0] > 150) & (hint[..., 0] > hint[..., 1] * 1.25) & (hint[..., 0] > hint[..., 2] * 1.15)
            gold = (body[..., 0] > 170) & (body[..., 1] > 160) & (body[..., 1] > body[..., 2] * 1.12)
            if red.mean() < 0.05 or gold.mean() < 0.12:
                continue
            if not self.matches(screenshot, "claimed.png", region) and self.matches(screenshot, "claimable.png", region, threshold=0.82):
                return round(x * scale), round(960 * scale)
        return None

    def claimed_at(self, screenshot: Path, target: tuple[int, int]) -> bool:
        with Image.open(screenshot) as image:
            x = round(target[0] * 1920 / image.width)
        return self.matches(screenshot, "claimed.png", (x - 38, 928, x + 38, 991))
