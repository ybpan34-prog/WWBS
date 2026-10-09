import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np
from PIL import Image

import app
from image_matcher import MatchResult


class NewTacetZoneTests(unittest.TestCase):
    def test_thin_button_sliver_is_not_clickable_but_whole_button_is(self):
        with tempfile.TemporaryDirectory() as directory:
            screen = Path(directory) / 'screen.png'
            image = Image.new('RGB', (1600, 900), (190, 205, 215))
            from PIL import ImageDraw
            draw = ImageDraw.Draw(image)
            draw.rectangle((1338, 602, 1528, 609), fill=(20, 22, 24))
            image.save(screen)
            self.assertFalse(app.TaskRunner._daily_row_button_ready(screen, 606))
            draw.rectangle((1338, 588, 1528, 627), fill=(20, 22, 24))
            image.save(screen)
            self.assertTrue(app.TaskRunner._daily_row_button_ready(screen, 606))

    def test_title_without_complete_button_is_kept_for_small_scroll(self):
        source = Path(__file__).parent / 'fixtures' / 'daily-new-tacet-rows.png'
        with tempfile.TemporaryDirectory() as directory, Image.open(source) as row:
            frame = Image.new('RGB', (1920, 1080), (190, 205, 215))
            frame.paste(row.crop((0, 0, 1694, 80)), (0, 170))
            screen = Path(directory) / 'screen.png'
            frame.save(screen)
            runner = app.TaskRunner(Mock(), Mock())
            runner.matcher.templates_dir = app.TEMPLATES_DIR / 'daily'
            runner._fast_scales = Mock(return_value=[1.])
            result = runner._find_new_daily_zone(screen, 'zone_chenxin_yu.png')
            self.assertIsNotNone(result)
            self.assertIsNone(result[1])

    def test_new_reader_matches_visible_raw_and_normalized_rows_without_fixed_x(self):
        fixture = Path(__file__).parent / 'fixtures' / 'daily-new-tacet-rows.png'
        with tempfile.TemporaryDirectory() as directory, Image.open(fixture) as source:
            screen = Path(directory) / 'screen.png'
            for template, bounds in (('zone_chenxin_yu.png', (0, 0, 1694, 230)),
                                     ('zone_jinxin_yu.png', (0, 240, 1694, 460))):
                for reference in (1., 24/37):
                    row = source.crop(bounds)
                    row = row.resize((round(row.width*reference), round(row.height*reference)), Image.Resampling.LANCZOS)
                    x, y = (0, 170) if reference == 1 else (650, 250)
                    base = Image.new('RGB', (1920, 1080), (25, 30, 35))
                    base.paste(row, (x, y))
                    for window_scale in (.833333, 1.):
                        frame = base.resize((round(1920*window_scale), round(1080*window_scale)), Image.Resampling.BILINEAR)
                        frame.save(screen)
                        runner = app.TaskRunner(Mock(), Mock())
                        runner.matcher.templates_dir = app.TEMPLATES_DIR / 'daily'
                        runner._fast_scales = Mock(return_value=[window_scale])
                        with self.subTest(template=template, reference=reference, window=window_scale):
                            result = runner._find_new_daily_zone(screen, template)
                            self.assertIsNotNone(result)
                            bx, by = result[1].center
                            self.assertGreater(bx, (x+1340*reference)*window_scale)
                            self.assertLess(bx, (x+1694*reference)*window_scale)
                            self.assertGreater(by, y*window_scale)
                            self.assertLess(by, (y+row.height)*window_scale)

    def test_visible_wrong_location_is_not_clicked(self):
        with tempfile.TemporaryDirectory() as directory, Image.open(Path(__file__).parent / 'fixtures' / 'daily-new-tacet-rows.png') as source:
            screen = Path(directory) / 'screen.png'
            for wrong, bounds in (('zone_jinxin_yu.png', (0, 0, 1694, 230)),
                                  ('zone_chenxin_yu.png', (0, 240, 1694, 460))):
                canvas = Image.new('RGB', (1920, 1080), (25, 30, 35))
                canvas.paste(source.crop(bounds), (0, 170))
                canvas.save(screen)
                runner = app.TaskRunner(Mock(), Mock())
                runner.matcher.templates_dir = app.TEMPLATES_DIR / 'daily'
                runner._fast_scales = Mock(return_value=[1.])
                self.assertIsNone(runner._find_new_daily_zone(screen, wrong))

    def test_direct_challenge_variant_is_matched_on_the_same_row(self):
        with tempfile.TemporaryDirectory() as directory:
            screen = Path(directory) / 'screen.png'
            canvas = Image.new('RGB', (1600, 900), (25, 30, 35))
            with Image.open(Path(__file__).parent / 'fixtures' / 'direct-challenge-real-button.png') as real:
                canvas.paste(real, (1374, 309))
            canvas.save(screen)
            runner = app.TaskRunner(Mock(), Mock())
            runner.matcher.templates_dir = app.TEMPLATES_DIR / 'daily'
            runner._fast_scales = Mock(return_value=[1600/1920])
            original = runner._find_daily_template
            def lookup(name, **kwargs):
                if name == 'zone_chenxin_yu.png':
                    return MatchResult(745, 281, 68, 24, .98)
                return original(name, **kwargs)
            with patch.object(runner, '_find_daily_template', side_effect=lookup):
                result = runner._find_new_daily_zone(screen, 'zone_chenxin_yu.png')
            self.assertIsNotNone(result)
            self.assertLess(abs(result[1].center[1]-325), 8)

    def test_new_zones_are_first_in_selector(self):
        self.assertIn("沉心域无音区", app.DAILY_ZONE_NAMES)
        self.assertIn("烬心域无音区", app.DAILY_ZONE_NAMES)
        self.assertEqual(app.DAILY_ZONE_NAMES[:2], ("沉心域无音区", "烬心域无音区"))
        self.assertEqual(len(set(app.DAILY_ZONE_TEMPLATES.values())), len(app.DAILY_ZONE_NAMES))

    def test_real_rows_match_their_own_name_and_button_at_multiple_resolutions(self):
        fixture = Path(__file__).parent / "fixtures" / "daily-new-tacet-rows.png"
        with tempfile.TemporaryDirectory() as directory, Image.open(fixture) as source:
            screen = Path(directory) / "screen.png"
            for name, bounds in (("沉心域无音区", (0, 0, 1694, 230)),
                                 ("烬心域无音区", (0, 240, 1694, 460))):
                row = source.crop(bounds)
                # The supplied crop has 37px glyphs; existing 1080p references
                # have 24px glyphs. Normalize the whole real row, not the template.
                row = row.resize((round(row.width*24/37), round(row.height*24/37)), Image.Resampling.LANCZOS)
                canvas = Image.new("RGB", (1920, 1080), (25, 30, 35))
                canvas.paste(row, (650, 250))
                for scale in (1.0, 2/3, 4/3):
                    with self.subTest(name=name, scale=scale):
                        image = canvas.resize((round(1920*scale), round(1080*scale)), Image.Resampling.BILINEAR)
                        image.save(screen)
                        runner = app.TaskRunner(Mock(), Mock())
                        runner.matcher.templates_dir = app.TEMPLATES_DIR / "daily"
                        template = app.DAILY_ZONE_TEMPLATES[name]
                        match = runner._find_daily_template(template, threshold=.85, scales=[scale],
                                                            template_crop=(0, 0, 82, 29), screenshot=screen)
                        self.assertIsNotNone(match)
                        row_y = match.center[1] + round(app.DAILY_ZONE_BUTTON_Y_OFFSETS[template]*scale)
                        self.assertTrue(runner._daily_row_button_ready(screen, row_y))
                        x = round(image.width*.895)
                        self.assertLess(np.asarray(image)[row_y, x].max(), 75)

    def test_similar_new_location_names_do_not_match_each_other(self):
        fixture = Path(__file__).parent / "fixtures" / "daily-new-tacet-rows.png"
        with tempfile.TemporaryDirectory() as directory, Image.open(fixture) as source:
            for actual, wrong, bounds in (("沉心域无音区", "烬心域无音区", (0, 0, 1694, 230)),
                                         ("烬心域无音区", "沉心域无音区", (0, 240, 1694, 460))):
                row = source.crop(bounds)
                row = row.resize((round(row.width*24/37), round(row.height*24/37)), Image.Resampling.LANCZOS)
                canvas = Image.new("RGB", (1920, 1080), (25, 30, 35))
                canvas.paste(row, (650, 250))
                screen = Path(directory) / "screen.png"
                canvas.save(screen)
                runner = app.TaskRunner(Mock(), Mock())
                runner.matcher.templates_dir = app.TEMPLATES_DIR / "daily"
                match = runner._find_daily_template(app.DAILY_ZONE_TEMPLATES[wrong], threshold=.85,
                                                    scales=[1], template_crop=(0, 0, 82, 29), screenshot=screen)
                self.assertIsNone(match, f"{actual} must not match {wrong}")


if __name__ == "__main__":
    unittest.main()
