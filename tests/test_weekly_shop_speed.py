from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

import numpy as np
from PIL import Image

from tasks.models import Step
from tasks.weekly_runtime_150 import SessionMatcher, WeeklyRuntime, ShopNotClosed
from tasks.weekly_matcher_150 import MatchResult


ROOT = Path(__file__).resolve().parents[1]
SHOP = ROOT/'tests/fixtures/weekly-shop-reported.png'


class WeeklyShopTests(unittest.TestCase):
    def runner(self):
        runner = WeeklyRuntime(Mock(), Mock(), dry_run=False)
        runner._sleep_interruptible = Mock()
        return runner

    def test_reported_modal_has_verified_close_not_dimmed_background_exit(self):
        runner = self.runner()
        close = runner._shop_close(SHOP)
        self.assertIsNotNone(close)
        self.assertTrue(1260 < close.center[0] < 1370)
        self.assertTrue(25 < close.center[1] < 90)
        # Reproduce the old false match on the dimmed exit behind the shop.
        behind = runner.matcher.find(SHOP, 'menu96.png', .82, [1, .9, .8])
        self.assertGreater(behind.center[0], 1450)
        self.assertNotEqual(close.center, behind.center)

    def test_shop_recognition_scales_and_does_not_match_main_board(self):
        runner = self.runner()
        with tempfile.TemporaryDirectory() as folder, Image.open(SHOP) as source:
            for width in (1280, 1920):
                target = Path(folder)/f'{width}.png'
                source.resize((width, round(width*9/16)), Image.Resampling.LANCZOS).save(target)
                self.assertIsNotNone(runner._shop_close(target), width)
        self.assertIsNone(runner._shop_close(ROOT/'tests/fixtures/weekly-speed-x5-photo.png'))

    def test_shop_closes_before_menu97_search_and_waits_for_two_absent_frames(self):
        runner = self.runner()
        close = MatchResult(1260, 30, 110, 40, .99)
        runner._expected_template = 'menu97.png'
        runner._shop_close = Mock(side_effect=[close, close, None, None])
        events = []
        runner.controller.screencap.side_effect = lambda *_a, **_k: events.append('capture')
        runner.controller.tap.side_effect = lambda *point: events.append(point)
        runner._capture_for_matching(SHOP)
        self.assertEqual(events, ['capture', close.center, 'capture', 'capture', 'capture'])
        self.assertEqual(runner._shop_close.call_count, 4)

    def test_ignored_shop_close_never_falls_through_to_background_button(self):
        runner = self.runner()
        close = MatchResult(1260, 30, 110, 40, .99)
        runner._expected_template = 'menu96.png'
        runner._shop_close = Mock(return_value=close)
        now = [0.]
        runner._sleep_interruptible = lambda seconds: now.__setitem__(0, now[0]+seconds)
        with patch('tasks.weekly_runtime_150.time.monotonic', side_effect=lambda: now[0]):
            with self.assertRaises(ShopNotClosed):
                runner._capture_for_matching(SHOP)
        self.assertEqual(runner.controller.tap.call_count, 3)
        self.assertTrue(all(call.args == close.center for call in runner.controller.tap.call_args_list))

    def test_stop_during_shop_recovery_never_sends_another_click(self):
        runner = self.runner()
        runner._expected_template = 'menu97.png'
        runner._shop_close = Mock(return_value=MatchResult(1260, 30, 110, 40, .99))
        runner.controller.tap.side_effect = lambda *_: runner.stop_event.set()
        with self.assertRaisesRegex(RuntimeError, '停止'):
            runner._capture_for_matching(SHOP)
        runner.controller.tap.assert_called_once()

    def test_reported_menu97_wait_closes_shop_then_retries_real_menu96(self):
        runner = self.runner()
        runner.controller.screenshot_to_screen = lambda x,y: (x,y)
        close = MatchResult(1260,30,110,40,.99)
        state, clicks = ['shop'], []
        def tap(x,y):
            clicks.append((x,y))
            if (x,y) == close.center:
                state[0] = 'park'
            elif (x,y) == (1517,62) and state[0] == 'park':
                state[0] = 'exit'
        runner.controller.tap.side_effect = tap
        runner.controller.screencap.side_effect = lambda path, **_: Image.new('RGB',(1600,900)).save(path)
        runner._shop_close = Mock(side_effect=lambda _: close if state[0] == 'shop' else None)
        def find(_path, name, *_args):
            if name == 'menu96.png' and state[0] == 'park':
                return MatchResult(1500,40,34,44,.99)
            if name == 'menu97.png' and state[0] == 'exit':
                return MatchResult(1400,600,80,80,.99)
            raise RuntimeError('not on this page')
        runner.matcher.find = Mock(side_effect=find)
        runner._random_click_point = lambda match, *_: match.center
        with tempfile.TemporaryDirectory() as folder, patch('tasks.weekly_150.APP_DIR', Path(folder)):
            result = runner._wait_for_cycle_template(Step(action='tap_image',template='menu97.png',timeout=.01),
                                                     Step(action='tap_image',template='menu96.png',timeout=.01))
        self.assertEqual(result, (1440,640,.99))
        self.assertEqual(clicks, [close.center, (1517,62)])
        self.assertEqual(state[0], 'exit')


class WeeklyScaleTests(unittest.TestCase):
    def test_every_find_uses_one_measured_scale_even_on_misses_and_resize_relocks(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'screen.png'
            with Image.open(SHOP) as source:
                source.save(path)
            matcher = SessionMatcher(ROOT/'templates/weekly150', Mock())
            found = MatchResult(1, 2, 30, 20, .99)
            with patch('tasks.weekly_runtime_150._match_single_scale_gray', return_value=found) as match:
                matcher.find(path, 'menu95.png', .82, [1,.97,1.03,.94,1.06])
                self.assertEqual(match.call_count, 1)
                shape = match.call_args.args[1].shape
                matcher.find(path, 'menu95.png', .82, [.5,.8,1.2])
                self.assertEqual(match.call_count, 2)
                self.assertEqual(match.call_args.args[1].shape, shape)
                self.assertEqual(matcher.current_scale, 1600/1920)
                match.return_value = MatchResult(1,2,30,20,.2)
                with self.assertRaises(RuntimeError):
                    matcher.find(path, 'menu95.png', .82, [1,.9,1.1])
                self.assertEqual(match.call_count, 3)
                with Image.open(SHOP) as source:
                    source.resize((1280,720)).save(path)
                match.return_value = found
                matcher.find(path, 'menu95.png', .82)
                self.assertEqual(match.call_count, 4)
                self.assertEqual(matcher.current_scale, 1280/1920)
                self.assertNotEqual(match.call_args.args[1].shape, shape)
                self.assertEqual(matcher.log.call_count, 2)

    def test_scaled_template_is_reused_without_stale_screenshots(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'screen.png'
            Image.new('RGB',(1600,900),'black').save(path)
            matcher = SessionMatcher(ROOT/'templates/weekly150', Mock())
            seen = []
            def found(screen, _template):
                seen.append(float(np.mean(screen)))
                return MatchResult(1,2,30,20,.99)
            with patch('tasks.weekly_runtime_150._scaled_template_gray', wraps=__import__(
                    'tasks.weekly_runtime_150', fromlist=['_scaled_template_gray'])._scaled_template_gray) as scale:
                with patch('tasks.weekly_runtime_150._match_single_scale_gray', side_effect=found):
                    matcher.find(path, 'menu95.png')
                    time.sleep(.002)
                    Image.new('RGB',(1600,900),'white').save(path)
                    matcher.find(path, 'menu95.png')
                self.assertEqual(scale.call_count, 1)
            self.assertEqual(seen, [0., 1.])
