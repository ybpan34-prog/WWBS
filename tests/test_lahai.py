import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock

import numpy as np
from PIL import Image

from app import App
from tasks.lahai import _anchor, _play, cassette_target, first_difficulty, run_lahai
from tasks.lahai_reader import Board, FOUR_SLOTS, read_score_board
from tasks.lahai_solver import Move, Piece, apply_move, resolve_move


class LahaiTests(unittest.TestCase):
    @staticmethod
    def cassette(second_status):
        canvas = np.zeros((1080, 1920), dtype=np.uint8)
        for name, point in (
            ('levels_title', None), ('first_card', None), ('first_complete', (179, 433)),
            ('stage2_card', (656, 581)), (second_status, (687, 807)),
        ):
            x, y, ref, _ = _anchor(name)
            if point:
                x, y = point
            h, w = ref.shape
            canvas[y:y+h, x:x+w] = (ref-ref.min()).astype(np.uint8)
        return canvas

    def test_completed_first_cassette_dispatches_second(self):
        stage, point = cassette_target(self.cassette('first_in_progress'))
        self.assertEqual((stage, point), (2, (891, 746)))

    def test_completed_sixth_cassette_dispatches_seventh(self):
        canvas = np.zeros((1080, 1920), dtype=np.uint8)
        for name, (x, y) in (
            ('stage6_card', (835, 581)), ('first_complete', (873, 808)),
            ('stage7_card', (1346, 205)), ('first_in_progress', (1380, 433)),
        ):
            _, _, ref, _ = _anchor(name)
            h, w = ref.shape
            canvas[y:y+h, x:x+w] = (ref-ref.min()).astype(np.uint8)
        self.assertEqual(cassette_target(canvas), (7, (1581, 371)))

    def test_five_cell_blue_piece_at_either_tray_edge(self):
        canvas = np.full((1080, 1920, 3), (24, 24, 65), dtype=np.uint8)
        for top in (375, 600):
            for tile in range(5):
                y = top + 36 * tile
                canvas[y:y+35, 1656:1691] = (94, 94, 234)
        board = read_score_board(canvas)
        self.assertEqual(tuple(piece.cells for piece in board.pieces),
                         (((0, 0), (1, 0), (2, 0), (3, 0), (4, 0)),) * 2)

    def test_four_slot_layout_reads_last_piece_and_pink_fault(self):
        canvas = np.full((1080, 1920, 3), (24, 24, 65), dtype=np.uint8)
        canvas[100:155, 510:570] = (245, 143, 208)
        for left, top, _, _ in FOUR_SLOTS:
            canvas[top:top+177, left:left+181] = (25, 26, 45)
            canvas[top+50:top+85, left+50:left+85] = (94, 94, 234)
        board = read_score_board(canvas, bomb_mode=True)
        self.assertEqual(board.slots, FOUR_SLOTS)
        self.assertEqual(tuple(piece.cells for piece in board.pieces), (((0, 0),),) * 4)
        self.assertEqual(board.faults, 1)

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

    def test_blast_chains_without_removing_corrupted_tiles(self):
        move = Move(0, 0, 0, 3, 1 << 3, 0)
        permanent = 1 << 8
        bombs = (1 << 1) | (1 << 5)
        occupied = 7 | bombs | permanent | (1 << 9) | (1 << 15)
        self.assertEqual(resolve_move(4, 4, occupied, 0, bombs, move, permanent=permanent),
                         (permanent | (1 << 15), 0, 1, 0, 0, 0, 0))

    def test_faulted_bomb_unlocks_without_exploding_on_first_clear(self):
        move = Move(0, 0, 0, 2, 4, 0)
        self.assertEqual(resolve_move(3, 3, 11, 2, 2, move, faults=2),
                         (10, 2, 1, 0, 2, 0, 0))

    def test_severe_fault_requires_two_clears_before_it_can_be_removed(self):
        move = Move(0, 0, 0, 2, 4, 0)
        self.assertEqual(resolve_move(3, 3, 11, 2, 2, move, faults=2, severe_faults=2),
                         (10, 2, 1, 0, 2, 2, 0))
        self.assertEqual(resolve_move(3, 3, 11, 2, 2, move, faults=2),
                         (10, 2, 1, 0, 2, 0, 0))
        self.assertEqual(resolve_move(3, 3, 11, 2, 2, move), (0, 0, 1, 1, 0, 0, 0))

    def test_secondary_medals_survive_rotation_and_drive_planning(self):
        from tasks.lahai_solver import plan

        piece = Piece(((0, 0), (1, 0), (1, 1)), secondary_medals=((1, 1),))
        self.assertEqual(piece.rotate().secondary_medals, ((1, 0),))
        single = Piece(((0, 0),))
        moves = plan(3, 3, 0b011000011, 0, (single,), medal_mode=True,
                     secondary_medals=1 << 6)
        self.assertEqual((moves[0].row, moves[0].col), (2, 2))

    def test_completed_task_does_not_send_any_input(self):
        canvas = self.cassette('first_complete')
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
        canvas = self.cassette('first_complete')
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
