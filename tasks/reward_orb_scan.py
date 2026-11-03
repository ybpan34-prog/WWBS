"""Remember the strongest orb direction and confirm a camera lap visually."""
from dataclasses import dataclass

import numpy as np
from PIL import Image

from image_matcher import _match_single_scale_gray


REWARD_SEARCH_SECONDS = 180
ORB_SCAN_STEP = 450
ORB_DIRECT_CONFIDENCE = .8


class RewardCamera:
    def __init__(self):
        self.previous_turn = None
        self.scan_sign = 1

    def follow(self, direction, x, y, width, height):
        horizontal = direction in ('left', 'right')
        sign = -1 if direction in ('left', 'up') else 1
        coordinate, size = (x, width) if horizontal else (y, height)
        distance = min(1., abs(2 * coordinate / size - 1))
        minimum, maximum = (100, 480) if horizontal else (70, 240)
        step = round(minimum + (maximum - minimum) * distance)
        if self.previous_turn is not None:
            previous_direction, previous_distance, previous_step = self.previous_turn
            if direction == previous_direction and distance >= previous_distance - .025:
                step = min(maximum, max(step, previous_step + 50))
            elif (direction, previous_direction) in (
                ('left', 'right'), ('right', 'left'), ('up', 'down'), ('down', 'up'),
            ):
                step = min(step, max(minimum, previous_step // 2))
        self.previous_turn = (direction, distance, step)
        if horizontal:
            self.scan_sign = sign
            return sign * step, 0
        return 0, sign * step

    def sweep(self, misses):
        self.previous_turn = None
        return self.scan_sign * min(600, ORB_SCAN_STEP // 2 + 75 * misses)


@dataclass
class OrbDirection:
    turn: int
    confidence: float


class OrbDirectionSweep:
    def __init__(self):
        self.turn = 0
        self.best = None
        self.anchors = []
        self.samples = 0
        self.away_frames = 0
        self.departed = False
        self.complete = False

    @staticmethod
    def _scene(image):
        width, height = image.size
        crop = image.crop((round(width*.24), round(height*.15), round(width*.82), round(height*.42)))
        return np.asarray(crop.convert('L').resize((216,72), Image.Resampling.BILINEAR), dtype=np.float64)/255

    def observe(self, image, target_x, confidence):
        if target_x is not None and confidence > .45 and (self.best is None or confidence > self.best.confidence):
            self.best = OrbDirection(self.turn, confidence)
        scene = self._scene(image)
        self.samples += 1
        if self.samples == 1:
            # Two separated scenery patches exclude portraits, minimap, player
            # and bottom HUD; using both reduces repeated-wall false returns.
            for x in (36,128):
                options = [(scene[y:y+28,x:x+40].copy(),x,y) for y in (8,24,40)]
                anchor = max(options,key=lambda item: item[0].std())
                if anchor[0].std() >= .03:
                    self.anchors.append(anchor)
            return
        if len(self.anchors) != 2:
            return
        matches = [_match_single_scale_gray(scene, patch) for patch,_x,_y in self.anchors]
        if any(match.score < .65 for match in matches):
            self.away_frames += 1
            self.departed = self.departed or self.away_frames >= 2
            return
        self.away_frames = 0
        offsets = [match.x-x for match,(_patch,x,_y) in zip(matches,self.anchors)]
        # A right turn moves scenery left. Wait until both anchors have returned
        # AND passed their initial horizontal position, rather than stopping
        # just before a full circle when they reappear at the right edge.
        self.complete = (self.departed and self.samples >= 5
            and all(match.score >= .82 and abs(match.y-y) <= 5
                    for match,(_patch,_x,y) in zip(matches,self.anchors))
            and abs(offsets[0]-offsets[1]) <= 8 and max(offsets) <= 2)

    def advance(self, delta):
        self.turn += delta

    def return_delta(self):
        return self.best.turn-self.turn if self.best is not None else 0


def orb_confidence(value):
    try:
        number = float(str(value).rstrip('%'))
        if number > 1:
            number /= 100
        return number if .45 <= number <= .95 else .45
    except (ValueError, TypeError):
        return .45
