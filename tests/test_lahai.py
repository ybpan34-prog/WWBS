import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock

import numpy as np
from PIL import Image

from app import App
from tasks.lahai import _anchor, _play, first_difficulty, run_lahai
from tasks.lahai_reader import Board
from tasks.lahai_solver import Piece
from tasks.lahai_solver import Move, apply_move


class LahaiTests(unittest.TestCase):
    def test_shifted_title_and_button_still_open_easy_challenge(self):
        canvas = np.zeros((1080, 1920), dtype=np.uint8)
        for name in ('first_easy', 'challenge_start'):
            x, y, ref, _ = _anchor(name)
            h, w = ref.shape
            canvas[y:y+h, x+3:x+3+w] = (ref - ref.min()).astype(np.uint8)
        self.assertEqual(first_difficulty(canvas), '简单')
        canvas[960:, :] = 0
        self.assertIsNone(first_difficulty(canvas))

    def test_release_shortcut_starts_native_task(self):
        app = Mock()
        app.target_mode.get.return_value = 'client'
        App._start_lahai_blocks(app)
        task, = app._start_worker.call_args.args[0]
        self.assertEqual((task.template_group, task.steps[0].action), ('lahai', 'lahai_blocks'))
        self.assertIn('lahai_blocks', App._normalize_start_action_order(['daily']))
        app.dry_run.set.assert_called_once_with(False)

    def test_corrupted_tile_survives_a_completed_line(self):
        move = Move(0, 0, 0, 2, 4, 0)
        self.assertEqual(apply_move(2, 3, 3, 0, move, permanent=1), (1, 0, 1, 0))

    def test_completed_task_does_not_send_any_input(self):
        canvas = np.zeros((1080, 1920), dtype=np.uint8)
        for name in ('first_complete', 'levels_title', 'first_card'):
            x, y, ref, _ = _anchor(name)
            h, w = ref.shape
            canvas[y:y+h, x:x+w] = (ref - ref.min()).astype(np.uint8)
        runner = Mock()
        runner.stop_event = threading.Event()
        with tempfile.TemporaryDirectory() as directory:
            runner.template_root = Path(directory) / 'templates' / 'lahai'
            runner._capture_for_matching.side_effect = lambda path, **_: Image.fromarray(canvas).save(path)
            run_lahai(runner)
        runner.controller.tap.assert_not_called()
        runner.controller.drag_rotating.assert_not_called()

    def test_unconfirmed_drop_replans_from_two_matching_consumed_frames(self):
        from unittest.mock import patch

        runner = Mock()
        runner.stop_event.is_set.return_value = False
        piece = Piece(((0, 0),))
        before = Board(0, (piece, piece))
        changed = Board(2, (None, piece))
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        captures = iter((
            [before], [], [changed, changed], ['success'],
        ))

        def wait_for(predicate, *_):
            for value in next(captures):
                result = predicate(frame, value)
                if result is not None:
                    return result
            return None

        def screen(rgb, value):
            return value if isinstance(value, str) else (rgb, value)

        with patch('tasks.lahai.scan_tray', return_value=(piece, (40, 40))):
            self.assertEqual(_play(runner, wait_for, screen), 2)
        self.assertEqual(runner.controller.drag_rotating.call_count, 2)
        self.assertTrue(any('重新规划' in args[0] for args, _ in runner.log.call_args_list))

    def test_loading_frame_does_not_abort_or_trigger_a_click(self):
        canvas = np.zeros((1080, 1920), dtype=np.uint8)
        for name in ('first_complete', 'levels_title', 'first_card'):
            x, y, ref, _ = _anchor(name)
            h, w = ref.shape
            canvas[y:y+h, x:x+w] = (ref - ref.min()).astype(np.uint8)
        runner = Mock()
        runner.stop_event = threading.Event()
        with tempfile.TemporaryDirectory() as directory:
            runner.template_root = Path(directory) / 'templates' / 'lahai'

            def capture(path, **_):
                index = runner._capture_for_matching.call_count
                if index == 1:
                    return False
                Image.fromarray(np.zeros_like(canvas) if index == 2 else canvas).save(path)

            runner._capture_for_matching.side_effect = capture
            run_lahai(runner)
        self.assertEqual(runner._capture_for_matching.call_count, 3)
        runner.controller.tap.assert_not_called()
