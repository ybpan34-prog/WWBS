import ast
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from tasks.runner import TaskRunner
from tasks.weekly_150 import TaskRunner as OriginalRunner, original_task, from_host
from tasks.daily_verified import VerifiedDailyNavigation
from tasks.match3_solver import Tile, UNKNOWN, ranked_moves, evaluate


ROOT = Path(__file__).resolve().parents[1]


def structure(value):
    if isinstance(value, ast.AST):
        return {'node': type(value).__name__, **{k: structure(v) for k, v in ast.iter_fields(value)}}
    if isinstance(value, list):
        return [structure(v) for v in value]
    return value


class Weekly150RestoreTests(unittest.TestCase):
    def test_original_weekly_methods_matcher_templates_and_steps_match_release(self):
        provenance = json.loads((ROOT/'tests/fixtures/weekly150-provenance.json').read_text(encoding='utf-8'))
        module = ast.parse((ROOT/'tasks/weekly_150.py').read_text(encoding='utf-8'))
        cls = next(n for n in module.body if isinstance(n, ast.ClassDef))
        for node in cls.body:
            if isinstance(node, ast.FunctionDef):
                self.assertEqual(hashlib.sha256(json.dumps(structure(node), sort_keys=True).encode()).hexdigest(),
                                 provenance['methods'][node.name], node.name)
        # Git's Windows checkout can translate LF to CRLF. Verify the original
        # text while allowing that encoding-only checkout transformation.
        self.assertEqual(hashlib.sha256((ROOT/'tasks/weekly_matcher_150.py').read_text(encoding='utf-8').encode()).hexdigest(),
                         provenance['matcher_text_sha256'])
        for name, digest in provenance['templates'].items():
            self.assertEqual(hashlib.sha256((ROOT/'templates/weekly150'/name).read_bytes()).hexdigest(), digest, name)
        from dataclasses import asdict
        actual = asdict(original_task())
        for key, value in provenance['task'].items():
            if key == 'steps':
                for index, step in enumerate(value):
                    for field, expected in step.items():
                        self.assertEqual(actual[key][index][field], expected)
            else:
                self.assertEqual(actual[key], value)

    def test_standalone_routes_to_original_runner_and_ignores_newer_saved_steps(self):
        host = TaskRunner(Mock(), Mock(), dry_run=False, max_cycles=13)
        task = original_task()
        task.steps[0].threshold = .5
        with patch.object(OriginalRunner, 'run_task') as run:
            host.run_task(task)
        self.assertEqual(run.call_args.args[0].steps[0].threshold, .82)
        isolated = from_host(host)
        self.assertEqual(isolated.max_cycles, 13)
        self.assertIs(isolated.stop_event, host.stop_event)
        self.assertEqual(type(isolated).__bases__, (object,))
        self.assertNotIsInstance(isolated.matcher, type(host.matcher))

    def test_other_tasks_keep_current_dispatch(self):
        task = original_task()
        task.name, task.template_group = '一键日常', 'daily'
        host = TaskRunner(Mock(), Mock())
        host._run_task_impl = Mock()
        with patch('tasks.weekly_150.run_weekly') as weekly:
            host.run_task(task)
        host._run_task_impl.assert_called_once_with(task)
        weekly.assert_not_called()

    def test_original_sequential_menu_chain_obeys_selected_round_count(self):
        runner = OriginalRunner(Mock(), Mock(), dry_run=False, max_cycles=2)
        runner._sleep_click_interval = Mock()
        runner._find_image = Mock(return_value=(10, 20, .95))
        runner._verify_final_cycle_click = Mock()
        runner._run_image_cycle(original_task().steps[1])
        self.assertEqual([call.args[0].template for call in runner._find_image.call_args_list],
                         original_task().steps[1].templates*2)
        self.assertEqual(runner.controller.tap.call_count, 34)
        self.assertTrue(runner.stop_event.is_set())


class DailyWeeklyReturnTests(unittest.TestCase):
    def navigation(self, states):
        host = TaskRunner(Mock(), Mock(), dry_run=False)
        host._capture_for_matching = Mock()
        host._sleep_interruptible = Mock()
        host._panel = Mock(return_value=True)
        host._weekly_travel_page_present = Mock(side_effect=[s == 'pending' for s in states])
        host._weekly_completion_confirmed = Mock(side_effect=[s == 'completed' for s in states])
        host._tap = Mock(return_value=True)
        host._ratio_point = Mock(return_value=(62, 160))
        host._close_page = Mock()
        host._start_weekly_travel_from_selected_page = Mock()
        host._open_terminal_destination = Mock(return_value=True)
        return VerifiedDailyNavigation(host), host

    def test_radio_finished_reopens_guide_and_stable_pending_starts_old_weekly(self):
        nav, host = self.navigation(['pending']*3)
        nav._continue_daily_into_weekly_travel()
        host._open_terminal_destination.assert_called_once_with('索拉指南')
        host._start_weekly_travel_from_selected_page.assert_called_once()
        host._tap.assert_not_called()

    def test_unknown_page_is_retried_not_assumed_complete(self):
        nav, host = self.navigation(['unknown', 'pending', 'pending', 'pending'])
        nav._continue_daily_into_weekly_travel()
        host._tap.assert_called_once()
        host._close_page.assert_not_called()
        host._start_weekly_travel_from_selected_page.assert_called_once()

    def test_completed_check_requires_stable_frames_and_does_not_start(self):
        nav, host = self.navigation(['completed']*3)
        nav._continue_daily_into_weekly_travel()
        self.assertEqual(host._capture_for_matching.call_count, 3)
        host._close_page.assert_called_once()
        host._start_weekly_travel_from_selected_page.assert_not_called()

    def test_manual_stop_does_not_open_guide_or_start_weekly(self):
        nav, host = self.navigation([])
        host.stop_event.set()
        nav._continue_daily_into_weekly_travel()
        host._open_terminal_destination.assert_not_called()
        host._start_weekly_travel_from_selected_page.assert_not_called()


class BottomFirstPuzzleTests(unittest.TestCase):
    def test_lower_three_outranks_upper_five_special(self):
        board = [[UNKNOWN for _ in range(8)] for _ in range(7)]
        for row, color, length in ((0, 1, 5), (5, 2, 3)):
            for col in range(length):
                board[row][col] = Tile(color)
            board[row][1], board[row+1][1] = Tile(4), Tile(color)
        upper, lower = evaluate(board, (0, 1), (1, 1)), evaluate(board, (5, 1), (6, 1))
        self.assertGreater(upper.value, lower.value)
        moves = ranked_moves(board)
        self.assertGreater(moves[0].depth, upper.depth)
        self.assertLess(moves.index(lower), moves.index(upper))

    def test_actual_elimination_depth_does_not_follow_drag_endpoint(self):
        board = [[UNKNOWN for _ in range(8)] for _ in range(7)]
        for col in (0, 2):
            board[4][col] = Tile(2)
        board[4][1], board[5][1] = Tile(4), Tile(2)
        move = evaluate(board, (4, 1), (5, 1))
        self.assertEqual(move.depth, (4, 4))

    def test_unknown_and_target_cells_still_cannot_be_swapped(self):
        board = [[UNKNOWN for _ in range(8)] for _ in range(7)]
        board[6][1] = Tile(6, 'target', 3)
        self.assertEqual(ranked_moves(board), [])
