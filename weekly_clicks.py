"""Fresh-frame stability and click acknowledgement for the weekly template chain."""
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image
from image_matcher import _match_single_scale_gray


def weekly_template_crop(template: str, templates_dir: Path):
    name = Path(template).name
    ratios = ((.37, .40, .86, .83) if name == 'menu1.png' else
              (.35, .40, .94, .79) if name in {'menu3.png', 'menu5.png', 'menu7.png', 'menu9.png', 'menu92.png'} else None)
    if ratios is None:
        return None
    with Image.open(templates_dir/template) as source:
        width, height = source.size
    return tuple(round((width if i%2 == 0 else height)*value) for i, value in enumerate(ratios))


@dataclass
class WeeklyTarget:
    template: str
    box: tuple[int, int, int, int]
    size: tuple[int, int]
    scale: float
    pixels: np.ndarray
    context_box: tuple[int, int, int, int]
    context: np.ndarray
    context_mask: np.ndarray
    template_crop: tuple[int, int, int, int] | None = None
    colour_error: float = 0.

    @classmethod
    def read(cls, screenshot: Path, template: str, match, templates_dir: Path, template_crop=None):
        with Image.open(templates_dir/template) as source:
            template_width, template_height = source.size
            reference = np.asarray(source.crop(template_crop or (0, 0, template_width, template_height))
                                   .convert('RGB').resize((64, 32)), dtype=np.int16)
        crop_left, crop_top, crop_right, crop_bottom = template_crop or (0, 0, template_width, template_height)
        scale = match.width/(crop_right-crop_left)
        box = (match.x, match.y, match.x+match.width, match.y+match.height)
        visual_box = (round(match.x-crop_left*scale), round(match.y-crop_top*scale),
                      round(match.x+(template_width-crop_left)*scale), round(match.y+(template_height-crop_top)*scale))
        pad_x, pad_y = max(16, round(template_width*scale/2)), max(16, round(template_height*scale/2))
        with Image.open(screenshot) as source:
            size = source.size
            context_box = (max(0, visual_box[0]-pad_x), max(0, visual_box[1]-pad_y),
                           min(size[0], visual_box[2]+pad_x), min(size[1], visual_box[3]+pad_y))
            pixels = np.asarray(source.crop(box).convert('L').resize((64, 32)), dtype=np.int16)
            colour = np.asarray(source.crop(box).convert('RGB').resize((64, 32)), dtype=np.int16)
            context = np.asarray(source.crop(context_box).convert('L').resize((96, 64)), dtype=np.int16)
        mask = np.ones((64, 96), dtype=bool)
        left, top, right, bottom = context_box
        x0 = max(0, int((visual_box[0]-6-left)*96/max(1, right-left)))
        y0 = max(0, int((visual_box[1]-6-top)*64/max(1, bottom-top)))
        x1 = min(96, int(np.ceil((visual_box[2]+6-left)*96/max(1, right-left))))
        y1 = min(64, int(np.ceil((visual_box[3]+6-top)*64/max(1, bottom-top))))
        mask[y0:y1, x0:x1] = False
        colour_error = float(np.abs(colour-reference).mean())
        return cls(template, box, size, scale, pixels, context_box, context, mask, template_crop, colour_error)

    def stable_with(self, newer):
        tolerance = max(3, min(self.box[2]-self.box[0], self.box[3]-self.box[1])*.03)
        return (self.size == newer.size and self.template == newer.template
                and all(abs(a-b) <= tolerance for a, b in zip(self.box, newer.box))
                and float(np.abs(self.pixels-newer.pixels).mean()) <= 8)

    def click_responded(self, screenshot: Path, matcher) -> bool:
        with Image.open(screenshot) as source:
            if source.size != self.size:
                return True
            current = np.asarray(source.crop(self.context_box).convert('L').resize((96, 64)), dtype=np.int16)
        # Ignore the clicked button itself: hover/pressed colours are not proof
        # that the page accepted a click. Surrounding UI changes can confirm it.
        context_changed = False
        if self.context_mask.any():
            changed = np.abs(current-self.context)[self.context_mask] > 20
            context_changed = float(changed.mean()) >= .18
        margin = max(6, round(8*self.scale))
        left, top, right, bottom = self.box
        with Image.open(screenshot) as source:
            patch = source.crop(self.box).convert('L').resize((64, 32))
            patch_pixels = np.asarray(patch, dtype=np.int16)
            if float(np.abs(patch_pixels-self.pixels).mean()) <= 8:
                return False
            # Background/avatar motion alone is not acknowledgement. A modal
            # that changes surrounding UI and dims the old button is a response.
            if context_changed and float(patch_pixels.mean()) < float(self.pixels.mean())*.85:
                return True
            search = source.crop((max(0, left-margin), max(0, top-margin),
                                  min(source.width, right+margin), min(source.height, bottom+margin))).convert('L')
            size = (max(64, round(search.width*64/(right-left))),
                    max(32, round(search.height*32/(bottom-top))))
            search_pixels = np.asarray(search.resize(size), dtype=np.float64)/255.
        try:
            score = _match_single_scale_gray(search_pixels, self.pixels.astype(np.float64)/255.).score
        except RuntimeError:
            return False  # A featureless crop cannot prove that input succeeded.
        # Compare against the actual pre-click pixels, not a stricter stock
        # template threshold: a valid 0.5 match can still be weak against stock art.
        return score < .85
