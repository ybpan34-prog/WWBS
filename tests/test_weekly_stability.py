import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np
from PIL import Image

import app
from image_matcher import MatchResult, TemplateMatcher
from weekly_clicks import WeeklyTarget, weekly_template_crop


class WeeklyStabilityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.now = 0.
        self.runner = app.TaskRunner(Mock(spec=['tap']), Mock(), dry_run=False)
        self.runner._weekly_monitoring = True
        self.runner._check_weekly_cap = Mock()
        self.runner._fast_scales = lambda: [1.]
        self.runner._sleep_interruptible = lambda duration: self.advance(duration)
        self.runner.matcher = TemplateMatcher(self.root)
        pattern = np.random.default_rng(42).integers(70, 220, (32, 64, 3), dtype=np.uint8)
        Image.fromarray(pattern).save(self.root/'a.png')
        Image.fromarray(pattern[:, ::-1]).save(self.root/'b.png')
        self.page = Image.new('RGB', (220, 160), (70, 80, 90))
        self.page.paste(Image.fromarray(pattern), (60, 60))
        self.capture = Mock(side_effect=self.write_page)
        self.runner._capture_for_matching = self.capture
        self.frame_patch = patch.object(app, 'APP_DIR', self.root)
        self.clock_patch = patch.object(app.time, 'monotonic', side_effect=lambda: self.now)
        self.wall_patch = patch.object(app.time, 'time', side_effect=lambda: self.now)
        self.frame_patch.start()
        self.clock_patch.start()
        self.wall_patch.start()

    def tearDown(self):
        self.wall_patch.stop()
        self.clock_patch.stop()
        self.frame_patch.stop()
        self.tmp.cleanup()

    def advance(self, duration):
        self.now += duration

    def write_page(self, path):
        self.advance(.03)
        self.page.save(path)

    def find(self, name='a.png'):
        return self.runner._find_image(app.Step(action='tap_image', template=name), single_attempt=True)

    def arm_previous(self):
        point = self.find()
        self.runner._click_cycle_template(app.Step(action='tap_image', template='a.png'), *point[:2])

    def test_two_fresh_frames_are_required_before_the_first_click(self):
        self.find()
        self.assertEqual(self.capture.call_count, 2)
        self.assertGreaterEqual(self.now, app.WEEKLY_STABLE_INTERVAL)
        self.runner.controller.tap.assert_not_called()

    def test_a_target_that_moves_between_frames_is_not_clicked(self):
        self.runner.matcher.find = Mock(side_effect=[MatchResult(60, 60, 64, 32, .99),
                                                    MatchResult(85, 60, 64, 32, .99)])
        with self.assertRaises(RuntimeError):
            self.find()
        self.assertIsNone(self.runner._weekly_observed_target)
        self.runner.controller.tap.assert_not_called()

    def test_unchanged_previous_page_blocks_search_and_click_of_next_step(self):
        self.arm_previous()
        matcher = Mock(wraps=self.runner.matcher)
        self.runner.matcher = matcher
        with self.assertRaisesRegex(RuntimeError, '上一点击未确认'):
            self.find('b.png')
        matcher.find.assert_not_called()
        self.runner.controller.tap.assert_called_once()
        self.assertLess(self.now-self.runner._weekly_click_at, 4.5)

    def test_hover_colour_alone_does_not_acknowledge_a_click(self):
        self.arm_previous()
        pending = self.runner._weekly_pending_click
        pixels = np.asarray(self.page).astype(np.int16)
        left, top, right, bottom = pending.box
        pixels[top:bottom, left:right] = np.minimum(255, pixels[top:bottom, left:right]+35)
        changed = Image.fromarray(pixels.astype(np.uint8))
        path = self.root/'hover.png'
        changed.save(path)
        matcher = Mock()
        matcher.find_fast.return_value = MatchResult(60, 60, 64, 32, .99)
        self.assertFalse(pending.click_responded(path, matcher))

    def test_weak_stock_match_is_not_mistaken_for_click_response(self):
        self.arm_previous()
        matcher = Mock()
        matcher.find_fast.side_effect = RuntimeError('stock score below strict threshold')
        path = self.root/'still.png'
        self.page.save(path)
        self.assertFalse(self.runner._weekly_pending_click.click_responded(path, matcher))

    def test_avatar_or_background_animation_without_button_change_is_not_response(self):
        self.arm_previous()
        changed = Image.new('RGB', self.page.size, (150, 160, 180))
        with Image.open(self.root/'a.png') as button:
            changed.paste(button, (60, 60))
        path = self.root/'animated.png'
        changed.save(path)
        self.assertFalse(self.runner._weekly_pending_click.click_responded(path, self.runner.matcher))

    def test_modal_dimming_the_old_button_and_surroundings_is_a_response(self):
        self.arm_previous()
        path = self.root/'modal.png'
        Image.fromarray((np.asarray(self.page)//2).astype(np.uint8)).save(path)
        self.assertTrue(self.runner._weekly_pending_click.click_responded(path, self.runner.matcher))

    def test_final_unacknowledged_click_is_retried_only_twice_then_reports_failure(self):
        self.arm_previous()
        with self.assertRaisesRegex(RuntimeError, '最终模板'):
            self.runner._verify_final_cycle_click(app.Step(action='tap_image', template='a.png'))
        self.assertEqual(self.runner.controller.tap.call_count, 3)
        self.assertTrue(self.runner.stop_event.is_set())

    def test_loading_waits_for_response_then_uses_a_new_stable_target(self):
        self.arm_previous()
        old = self.page.copy()
        changed = Image.new('RGB', self.page.size, (115, 125, 135))
        with Image.open(self.root/'b.png') as target:
            changed.paste(target, (130, 90))
        pages = iter([old, old, changed, changed, changed])
        def capture(path):
            self.advance(.03)
            next(pages).save(path)
        self.runner._capture_for_matching = Mock(side_effect=capture)
        x, y, _score = self.find('b.png')
        self.assertTrue(130 <= x < 194 and 90 <= y < 122)
        self.assertIsNone(self.runner._weekly_pending_click)
        self.runner.controller.tap.assert_called_once()

    def test_recovery_can_reidentify_previous_button_after_ignored_click(self):
        self.arm_previous()
        with self.assertRaises(RuntimeError):
            self.find('b.png')
        point = self.find('a.png')
        self.runner._click_cycle_template(app.Step(action='tap_image', template='a.png'), *point[:2], recovery=True)
        self.assertEqual(self.runner.controller.tap.call_count, 2)

    def test_darkened_transition_button_is_rejected_even_with_a_high_shape_score(self):
        pixels = np.asarray(self.page).copy()
        pixels[60:92, 60:124] //= 3
        self.page = Image.fromarray(pixels)
        self.runner.matcher.find = Mock(return_value=MatchResult(60, 60, 64, 32, .99))
        with self.assertRaisesRegex(RuntimeError, '颜色'):
            self.find()
        self.runner.controller.tap.assert_not_called()

    def test_stop_during_response_does_not_send_another_click(self):
        self.arm_previous()
        self.runner._capture_for_matching = Mock(side_effect=lambda _: self.runner.stop_event.set())
        with self.assertRaisesRegex(RuntimeError, '已停止'):
            self.find('b.png')
        self.assertEqual(self.runner.controller.tap.call_count, 1)


class WeeklyCharacterCompatibilityTests(unittest.TestCase):
    def test_button_text_matches_after_all_non_text_character_pixels_change(self):
        matcher = TemplateMatcher(app.TEMPLATES_DIR)
        with tempfile.TemporaryDirectory() as directory:
            screen = Path(directory)/'screen.png'
            for name in ('menu1.png', 'menu3.png', 'menu5.png', 'menu7.png', 'menu9.png', 'menu92.png'):
                crop = weekly_template_crop(name, app.TEMPLATES_DIR)
                with Image.open(app.TEMPLATES_DIR/name) as source:
                    text = source.crop(crop)
                    for colour in ((40, 100, 190), (190, 70, 130)):
                        # Two different avatar/decorative areas, with identical UI text.
                        variant = Image.new('RGB', source.size, colour)
                        variant.paste(text, crop[:2])
                        frame = Image.new('RGB', (800, 500), (80, 90, 100))
                        frame.paste(variant, (150, 140))
                        frame.save(screen)
                        result = matcher.find_fast(screen, name, threshold=.84, template_crop=crop)
                        self.assertEqual((result.x, result.y), (150+crop[0], 140+crop[1]))
                        observed = WeeklyTarget.read(screen, name, result, app.TEMPLATES_DIR, crop)
                        self.assertLess(observed.colour_error, 1)
                        self.assertAlmostEqual(observed.scale, 1)


class WeeklyWholeChainTests(unittest.TestCase):
    def test_real_template_chain_runs_in_order_for_two_avatar_variants_and_a_missed_click(self):
        names = ['menu1.png', 'menu2.png', 'menu3.png', 'menu4.png', 'menu5.png', 'menu6.png',
                 'menu7.png', 'menu8.png', 'menu9.png', 'menu91.png', 'menu92.png', 'menu93.png',
                 'menu94.png', 'menu95.png', 'menu96.png', 'menu97.png', 'menu98.png', 'menu99.png']
        for avatar in ((45, 100, 180), (190, 80, 130)):
            with self.subTest(avatar=avatar), tempfile.TemporaryDirectory() as directory:
                runner = app.TaskRunner(Mock(spec=['tap']), Mock(), dry_run=False)
                runner._weekly_monitoring = True
                runner._check_weekly_cap = Mock()
                runner._fast_scales = lambda: [1.]
                state = {'index': 0, 'remaining': 0, 'next': None, 'now': 0., 'ignored': False}
                taps = []
                pages, boxes = [], []
                for index, name in enumerate(names):
                    with Image.open(app.TEMPLATES_DIR/name) as source:
                        crop = weekly_template_crop(name, app.TEMPLATES_DIR)
                        picture = source.copy()
                        if crop:
                            picture = Image.new('RGB', source.size, avatar)
                            picture.paste(source.crop(crop), crop[:2])
                        x, y = 230+(index%3)*15, 210+(index%2)*7
                        frame = Image.new('RGB', (960, 540), (50+index*8, 70+index*6, 80+index*5))
                        frame.paste(picture, (x, y))
                        pages.append(frame)
                        bounds = crop or (0, 0, source.width, source.height)
                        boxes.append((x+bounds[0], y+bounds[1], x+bounds[2], y+bounds[3]))
                def capture(path):
                    state['now'] += .03
                    if state['next'] is not None:
                        if state['remaining']:
                            state['remaining'] -= 1
                        else:
                            state['index'], state['next'] = state['next'], None
                    pages[state['index']].save(path)
                def tap(x, y):
                    index = state['index']
                    left, top, right, bottom = boxes[index]
                    self.assertTrue(left <= x < right and top <= y < bottom, (names[index], x, y))
                    taps.append(names[index])
                    if index == 1 and not state['ignored']:
                        state['ignored'] = True
                        return  # Simulate an early confirmation click being ignored.
                    state['next'] = min(index+1, len(names)-1)
                    state['remaining'] = 3  # The old page stays visible during processing.
                runner.controller.tap.side_effect = tap
                runner._capture_for_matching = capture
                runner._sleep_interruptible = lambda seconds: state.__setitem__('now', state['now']+seconds)
                with patch.object(app, 'APP_DIR', Path(directory)), \
                        patch.object(app.time, 'monotonic', side_effect=lambda: state['now']), \
                        patch.object(app.time, 'time', side_effect=lambda: state['now']):
                    runner._run_step(app.Step(action='tap_image', template='menu1.png', offset_x=80, timeout=8))
                    runner._run_image_cycle(app.Step(action='tap_image_cycle', templates=names[1:], seconds=.08))
                self.assertEqual(taps, ['menu1.png', 'menu2.png', *names[1:]])
                self.assertFalse(runner.stop_event.is_set())


if __name__ == '__main__':
    unittest.main()
