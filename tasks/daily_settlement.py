"""Daily settlement requires its success caption and both distinct actions."""
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from image_matcher import MatchResult, TemplateMatcher


@dataclass
class DailySettlement:
    title: MatchResult
    exit: MatchResult
    restart: MatchResult
    scale: float


class DailySettlementVision:
    def __init__(self, templates: Path):
        self.matcher = TemplateMatcher(templates)
        self.scale = None

    def read(self, screenshot, scales=()):
        try:
            with Image.open(screenshot) as image:
                width, height = image.size
        except OSError:
            return None
        base = min(width/1920, height/1080)
        candidates = [self.scale, *scales, base]
        candidates += [base*ratio for ratio in (1.03, .97, 1.125, .875, 1.25, .75, 1.375, 1.5)]
        tested = set()
        for scale in candidates:
            if scale is None or round(scale, 3) in tested:
                continue
            tested.add(round(scale, 3))
            try:
                title = self.matcher.find_fast(screenshot, 'challenge_success.png', .84, scale,
                    region=(round(width*.15), round(height*.08), round(width*.85), round(height*.43)),
                    template_crop=(55, 17, 320, 82), max_width=1000)
                exit_button = self.matcher.find_fast(screenshot, 'exit_instance.png', .84, scale,
                    region=(0, round(height*.52), round(width*.57), round(height*.96)),
                    template_crop=(85, 24, 237, 61), max_width=800)
                restart = self.matcher.find_fast(screenshot, 'restart_challenge.png', .84, scale,
                    region=(round(width*.43), round(height*.52), width, round(height*.96)),
                    template_crop=(80, 24, 238, 61), max_width=800)
            except (OSError, RuntimeError, ValueError):
                continue
            if (abs(exit_button.center[1]-restart.center[1]) <= height*.025
                    and restart.center[0]-exit_button.center[0] > width*.15
                    and min(exit_button.center[1], restart.center[1])-title.center[1] > height*.25):
                self.scale = scale
                return DailySettlement(title, exit_button, restart, scale)
        return None
