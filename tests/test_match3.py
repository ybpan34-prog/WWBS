from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from PIL import Image, ImageEnhance

import app
from tasks.match3_solver import Tile, UNKNOWN, evaluate, ranked_moves, runs, expand_specials
from tasks.match3_task import Match3Session, status_from_lines
from tasks.match3_vision import read_board
from tasks.models import TaskNeedsReview


FIXTURE = Path(__file__).parent/'fixtures/match3-board-reported.png'
EXPECTED = ['01234011', '00322312', '10202240', '32433432', '42123113', '44321013', '03342430']


class Match3Tests(unittest.TestCase):
    def test_reported_board_all_56_cells_and_scale(self):
        with tempfile.TemporaryDirectory() as directory, Image.open(FIXTURE) as image:
            for width in (1280, 1600, 1920, 2560):
                path = Path(directory)/'screen.png'
                image.resize((width, round(width*9/16)), Image.Resampling.BILINEAR).save(path)
                frame = read_board(path)
                self.assertIsNotNone(frame, width)
                self.assertEqual([''.join(str(t.color) for t in row) for row in frame.tiles], EXPECTED)
                self.assertLess(abs(frame.centers[0][0][0]-773*width/1600), 2)
                self.assertTrue(ranked_moves(frame.tiles))

    def test_dim_overlay_unrelated_page_and_unreadable_cell_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory, Image.open(FIXTURE) as image:
            path = Path(directory)/'screen.png'
            ImageEnhance.Brightness(image).enhance(.35).save(path)
            self.assertIsNone(read_board(path))
            image.paste((40, 40, 40), (740, 130, 810, 200))
            image.save(path)
            self.assertIsNone(read_board(path))
        self.assertIsNone(read_board(Path(__file__).parent/'fixtures/daily-tacet-selected-reported.png'))

    def test_solver_creates_special_and_does_not_invent_refills(self):
        board = [[UNKNOWN for _ in range(8)] for _ in range(7)]
        # Swap the lower red with the blue to make a horizontal line of four.
        for col in (0, 1, 3):
            board[2][col] = Tile(1)
        board[2][2], board[3][2] = Tile(4), Tile(1)
        move = evaluate(board, (2, 2), (3, 2))
        self.assertEqual((move.cleared, move.creates), (4, 'bomb'))
        board[2][4], board[3][4] = Tile(1), Tile(2)
        self.assertEqual(evaluate(board, (2, 2), (3, 2)).creates, 'rainbow')
        self.assertIsNone(evaluate(board, (2, 4), (3, 4)))

    def test_l_shape_cross_bomb_chain_and_double_rainbow(self):
        board = [[Tile((r+c)%5) for c in range(8)] for r in range(7)]
        board[2][2], board[2][3], board[2][4] = Tile(1), Tile(2), Tile(1)
        board[0][3], board[1][3], board[3][3] = Tile(1), Tile(1), Tile(1)
        self.assertEqual(evaluate(board, (2, 3), (3, 3)).creates, 'cross')
        board[3][3], board[3][4] = Tile(0, 'bomb'), Tile(1, 'cross')
        cleared = expand_specials(board, {(3, 3)})
        self.assertTrue({(0, 4), (3, 7), (2, 2)} <= cleared)
        board[3][3], board[3][4] = Tile(5, 'rainbow'), Tile(5, 'rainbow')
        self.assertEqual(evaluate(board, (3, 3), (3, 4)).cleared, 56)

    def test_status_requires_explicit_result_and_reads_remaining_turns(self):
        lines = lambda text: [{'words': [{'text': text}]}]
        self.assertEqual(status_from_lines(lines('剩余回合数12/20')), ('playing', 12))
        self.assertEqual(status_from_lines(lines('挑战成功')), ('success', None))
        self.assertEqual(status_from_lines(lines('效果说明')), ('playing', None))

    def test_pending_animation_and_manual_stop_never_drag(self):
        runner = app.TaskRunner(Mock(), Mock(), dry_run=False)
        runner.warning = Mock()
        session = Match3Session(runner)
        session.stable_board = Mock(return_value=None)
        session.status = Mock()
        with self.assertRaises(TaskNeedsReview):
            session.run(30)
        runner.controller.swipe.assert_not_called()
        runner.stop_event.set()
        session.run(30)
        runner.controller.swipe.assert_not_called()

    def test_changed_board_is_rechecked_before_any_drag(self):
        runner = app.TaskRunner(Mock(), Mock(), dry_run=False)
        runner._capture_for_matching = Mock()
        runner.warning = Mock()
        session = Match3Session(runner)
        session.stable_board = Mock(side_effect=[read_board(FIXTURE), None])
        session.status = Mock()
        with patch('tasks.match3_task.read_board', return_value=None):
            with self.assertRaises(TaskNeedsReview):
                session.run(30)
        runner.controller.swipe.assert_not_called()

    def test_dry_run_and_shortcut_do_not_change_the_board_or_shutdown(self):
        runner = app.TaskRunner(Mock(), Mock(), dry_run=True)
        runner.warning = Mock()
        session = Match3Session(runner)
        session.stable_board = Mock(return_value=read_board(FIXTURE))
        session.status = Mock()
        session.run(30)
        runner.controller.swipe.assert_not_called()
        ui = app.App.__new__(app.App)
        ui.dry_run = Mock()
        ui._ensure_admin_for_real_run = Mock(return_value=True)
        ui._start_worker, ui._log, ui._pet_feedback, ui._event_line = Mock(), Mock(), Mock(), Mock()
        ui._start_match3_puzzle()
        task = ui._start_worker.call_args.args[0][0]
        self.assertEqual(task.steps[0].action, 'match3_puzzle')
        self.assertTrue(app.App._is_dedicated_launcher_task(task))
        ui._last_started_tasks = [task]
        with patch('app.subprocess.Popen') as launch:
            ui._handle_successful_task_completion()
        launch.assert_not_called()

    def test_stop_after_fresh_capture_prevents_drag(self):
        runner = app.TaskRunner(Mock(), Mock(), dry_run=False, stop_event=threading.Event())
        frame = read_board(FIXTURE)
        self.assertFalse(runs(frame.tiles))
        session = Match3Session(runner)
        session.stable_board = Mock(return_value=frame)
        session.status = Mock()
        runner._capture_for_matching = Mock(side_effect=lambda _p: runner.stop_event.set())
        with patch('tasks.match3_task.read_board', return_value=frame):
            session.run(30)
        runner.controller.swipe.assert_not_called()

    def test_confirmed_move_uses_two_cell_centers_and_leaves_result_untouched(self):
        runner = app.TaskRunner(Mock(), Mock(), dry_run=False)
        runner._capture_for_matching = Mock()
        runner._sleep_interruptible = Mock()
        runner.warning = Mock()
        frame = read_board(FIXTURE)
        session = Match3Session(runner)
        session.stable_board = Mock(side_effect=[frame, None])
        calls = [0]
        def status(force=False):
            calls[0] += 1
            if calls[0] > 1:
                session.result = 'success'
        session.status = status
        with patch('tasks.match3_task.read_board', return_value=frame):
            session.run(30)
        move = ranked_moves(frame.tiles)[0]
        runner.controller.swipe.assert_called_once_with(
            *frame.centers[move.start[0]][move.start[1]], *frame.centers[move.end[0]][move.end[1]], 240)
        runner.controller.tap.assert_not_called()
        self.assertIn('挑战成功', runner.warning.call_args.args[0])
