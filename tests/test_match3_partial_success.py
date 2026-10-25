from dataclasses import replace
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import Mock, patch

import numpy as np
from PIL import Image

from tasks.match3_solver import UNKNOWN, Tile, ranked_moves
from tasks.match3_task import Match3Session
from tasks.match3_vision import read_board, success_present, shared_board, known_change
from tasks.runner import TaskRunner


FIXTURES = Path(__file__).parent/'fixtures'
SPECIAL = FIXTURES/'match3-special-reported.png'
SUCCESS = FIXTURES/'match3-success-reported.png'


class PartialBoardTests(unittest.TestCase):
    def test_real_rainbow_board_and_one_two_three_bottle_hearts_at_window_scales(self):
        with tempfile.TemporaryDirectory() as directory, Image.open(SPECIAL) as source:
            for width in (1280, 1600, 1920, 2560):
                path = Path(directory)/'screen.png'
                source.resize((width, round(width*9/16)), Image.Resampling.BILINEAR).save(path)
                details = {}
                frame = read_board(path, details)
                self.assertIsNotNone(frame, details)
                self.assertEqual(frame.tiles[3][4], Tile(5, 'rainbow'))
                self.assertEqual([frame.tiles[r][c].health for r, c in ((2, 6), (3, 6), (5, 1), (5, 6))], [3, 2, 1, 3])
                self.assertTrue(ranked_moves(frame.tiles))

    def test_unknown_level_specific_cells_do_not_block_other_confirmed_moves(self):
        with tempfile.TemporaryDirectory() as directory, Image.open(SPECIAL) as source:
            path = Path(directory)/'screen.png'
            # A future colored sprite with no corresponding template. A 3x3
            # group must be tolerated; it is not a dark modal obstruction.
            checker = (np.indices((68, 68)).sum(axis=0)//5) % 2
            pixels = np.empty((68, 68, 3), dtype=np.uint8)
            pixels[checker == 0], pixels[checker == 1] = (255, 220, 0), (0, 255, 255)
            unknown = {(r, c) for r in range(3) for c in range(3)}
            for row, col in unknown:
                x, y = round(773+102.85*col-34), round(163+102.5*row-34)
                source.paste(Image.fromarray(pixels), (x, y))
            source.save(path)
            details = {}
            frame = read_board(path, details)
            self.assertIsNotNone(frame, details)
            self.assertTrue(unknown <= set(details['unknown']))
            moves = ranked_moves(frame.tiles)
            self.assertTrue(moves)
            self.assertFalse(any(move.start in unknown or move.end in unknown for move in moves))

    def test_large_dark_cover_still_blocks_input(self):
        with tempfile.TemporaryDirectory() as directory, Image.open(SPECIAL) as source:
            source.paste('black', (732, 122, 1015, 396))
            path = Path(directory)/'screen.png'
            source.save(path)
            details = {}
            self.assertIsNone(read_board(path, details))
            self.assertIn('遮挡', details['reason'])

    def test_partial_board_stabilizes_and_produces_a_move(self):
        runner = TaskRunner(Mock(), Mock(), dry_run=False)
        original = read_board(SPECIAL)
        tiles = [list(row) for row in original.tiles]
        tiles[0][3] = UNKNOWN
        frame = replace(original, tiles=tuple(tuple(row) for row in tiles))
        now = [0.]
        runner._capture_for_matching = Mock()
        runner._sleep_interruptible = lambda sec: now.__setitem__(0, now[0]+sec)
        session = Match3Session(runner)
        def read(_path, diagnostics=None):
            diagnostics['unknown'] = [(0, 3)]
            return frame
        with patch('tasks.match3_task.time.monotonic', side_effect=lambda: now[0]), \
                patch('tasks.match3_task.success_present', return_value=False), \
                patch('tasks.match3_task.read_board', side_effect=read):
            self.assertIs(session.stable_board(), frame)
        self.assertTrue(ranked_moves(frame.tiles))
        self.assertLessEqual(runner._capture_for_matching.call_count, 4)
        runner.controller.swipe.assert_not_called()

    def test_unrelated_unknown_fluctuation_does_not_reset_wait_or_acknowledge_a_move(self):
        full = read_board(SPECIAL)
        tiles = [list(row) for row in full.tiles]
        tiles[0][3] = UNKNOWN
        partial = replace(full, tiles=tuple(tuple(row) for row in tiles))
        shared = shared_board(partial, full)
        self.assertEqual(shared.tiles[0][3], UNKNOWN)
        self.assertFalse(known_change(partial.tiles, full.tiles))
        runner = TaskRunner(Mock(), Mock(), dry_run=False)
        runner._capture_for_matching = Mock()
        now = [0.]
        runner._sleep_interruptible = lambda sec: now.__setitem__(0, now[0]+sec)
        session = Match3Session(runner)
        with patch('tasks.match3_task.time.monotonic', side_effect=lambda: now[0]), \
                patch('tasks.match3_task.success_present', return_value=False), \
                patch('tasks.match3_task.read_board', side_effect=[partial, full, partial]):
            result = session.stable_board()
        self.assertEqual(result.tiles[0][3], UNKNOWN)
        self.assertEqual(runner._capture_for_matching.call_count, 3)

    def test_a_real_known_cell_change_or_window_resize_requires_a_new_stable_board(self):
        frame = read_board(SPECIAL)
        tiles = [list(row) for row in frame.tiles]
        tiles[0][0] = Tile(1)
        changed = replace(frame, tiles=tuple(tuple(row) for row in tiles))
        self.assertIsNone(shared_board(frame, changed))
        self.assertTrue(known_change(frame.tiles, changed.tiles))
        self.assertIsNone(shared_board(frame, replace(frame, centers=())))


class PuzzleSuccessTests(unittest.TestCase):
    def test_actual_success_title_and_exit_at_resolutions_and_negative_frames(self):
        with tempfile.TemporaryDirectory() as directory, Image.open(SUCCESS) as source:
            path = Path(directory)/'screen.png'
            for width in (1280, 1600, 1920, 2560):
                source.resize((width, round(width*9/16)), Image.Resampling.BILINEAR).save(path)
                self.assertTrue(success_present(path), width)
            for box in ((610, 760, 995, 865), (640, 420, 955, 525)):
                incomplete = source.copy()
                incomplete.paste('black', box)
                incomplete.save(path)
                self.assertFalse(success_present(path))
        for name in ('match3-board-reported.png', 'match3-targets-reported.png', 'match3-special-reported.png',
                     'daily-settlement-reported.png', 'daily-radio-rewards-reported.png'):
            self.assertFalse(success_present(FIXTURES/name), name)

    def test_two_fresh_success_frames_finish_without_ocr_drag_or_exit(self):
        runner = TaskRunner(Mock(), Mock(), dry_run=False)
        runner.warning = Mock()
        now = [0.]
        runner._sleep_interruptible = lambda sec: now.__setitem__(0, now[0]+sec)
        runner._capture_for_matching = lambda path: shutil.copy2(SUCCESS, path)
        session = Match3Session(runner)
        with tempfile.TemporaryDirectory() as directory:
            session.path = Path(directory)/'screen.png'
            with patch('tasks.match3_task.time.monotonic', side_effect=lambda: now[0]), \
                    patch('tasks.match3_task.WindowsOcr') as ocr:
                session.run(30)
                self.assertEqual(session.result, 'success')
                self.assertLess(now[0], 1)
                ocr.assert_not_called()
        runner.controller.swipe.assert_not_called()
        runner.controller.tap.assert_not_called()
        self.assertIn('挑战成功', runner.warning.call_args.args[0])

    def test_a_pending_elimination_breaks_previous_stability(self):
        runner = TaskRunner(Mock(), Mock(), dry_run=False)
        frame = read_board(SPECIAL)
        pending_tiles = [list(row) for row in frame.tiles]
        pending_tiles[0][:3] = [Tile(1)]*3
        pending = replace(frame, tiles=tuple(tuple(row) for row in pending_tiles))
        now = [0.]
        runner._capture_for_matching = Mock()
        runner._sleep_interruptible = lambda sec: now.__setitem__(0, now[0]+sec)
        session = Match3Session(runner)
        with patch('tasks.match3_task.time.monotonic', side_effect=lambda: now[0]), \
                patch('tasks.match3_task.success_present', return_value=False), \
                patch('tasks.match3_task.read_board', side_effect=[frame, pending, frame, frame, frame]):
            self.assertIs(session.stable_board(), frame)
        self.assertEqual(runner._capture_for_matching.call_count, 5)
