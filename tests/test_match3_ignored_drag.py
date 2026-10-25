from dataclasses import replace
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from tasks.match3_solver import Tile, ranked_moves
from tasks.match3_task import Match3Session
from tasks.match3_vision import read_board
from tasks.runner import TaskRunner


FIXTURE = Path(__file__).parent/'fixtures/match3-board-reported.png'


class IgnoredDragTests(unittest.TestCase):
    def session(self):
        runner = TaskRunner(Mock(), Mock(), dry_run=False)
        runner.warning = Mock()
        runner._capture_for_matching = Mock()
        now = [0.]
        runner._sleep_interruptible = lambda seconds: now.__setitem__(0, now[0]+seconds)
        session = Match3Session(runner)
        session.status = Mock()
        return session, runner, now, read_board(FIXTURE)

    @staticmethod
    def changed(frame, col=0):
        tiles = [list(row) for row in frame.tiles]
        tiles[0][col] = Tile((tiles[0][col].color+1) % 5)
        return replace(frame, tiles=tuple(tuple(row) for row in tiles))

    def test_missed_drag_retries_then_continues_to_success(self):
        session, runner, now, frame = self.session()
        changed = self.changed(frame)
        session.stable_board = Mock(side_effect=[frame, frame, changed])
        def status(force=False):
            if runner.controller.swipe.call_count >= 2:
                session.result = 'success'
        session.status = status
        with patch('tasks.match3_task.time.monotonic', side_effect=lambda: now[0]), \
                patch('tasks.match3_task.read_board', return_value=frame):
            session.run(30)
        calls = runner.controller.swipe.call_args_list
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0].args[-1], 240)
        self.assertEqual(calls[1].args[-1], 420)
        self.assertEqual(calls[1].args[:4], calls[0].args[2:4]+calls[0].args[:2])
        self.assertEqual(session.result, 'success')

    def test_two_ignored_swaps_choose_another_legal_move_without_stopping(self):
        session, runner, now, frame = self.session()
        session.stable_board = Mock(return_value=frame)
        runner.controller.swipe.side_effect = lambda *_args: runner.stop_event.set() if runner.controller.swipe.call_count == 3 else None
        with patch('tasks.match3_task.time.monotonic', side_effect=lambda: now[0]), \
                patch('tasks.match3_task.read_board', return_value=frame):
            session.run(30)
        calls = runner.controller.swipe.call_args_list
        self.assertEqual(len(calls), 3)
        first = frozenset((calls[0].args[:2], calls[0].args[2:4]))
        third = frozenset((calls[2].args[:2], calls[2].args[2:4]))
        self.assertNotEqual(first, third)

    def test_ignored_attempts_do_not_consume_the_twenty_move_budget(self):
        session, runner, now, frame = self.session()
        session.stable_board = Mock(return_value=frame)
        runner.controller.swipe.side_effect = lambda *_args: runner.stop_event.set() if runner.controller.swipe.call_count == 23 else None
        with patch('tasks.match3_task.time.monotonic', side_effect=lambda: now[0]), \
                patch('tasks.match3_task.read_board', return_value=frame):
            session.run(120)
        self.assertEqual(runner.controller.swipe.call_count, 23)
        self.assertFalse(any('已复核第' in str(call.args[0]) for call in runner.log.call_args_list))

    def test_more_than_twenty_confirmed_moves_continue_until_real_success(self):
        session, runner, now, frame = self.session()
        current = [frame]
        session.remaining = 40
        session.stable_board = Mock(side_effect=lambda **_kwargs: current[0])
        runner.controller.swipe.side_effect = lambda *_args: current.__setitem__(0, self.changed(current[0]))
        def status(force=False):
            if runner.controller.swipe.call_count == 23:
                session.result = 'success'
        session.status = status
        with patch('tasks.match3_task.time.monotonic', side_effect=lambda: now[0]), \
                patch('tasks.match3_task.read_board', side_effect=lambda _path: current[0]):
            session.run(120)
        self.assertEqual(runner.controller.swipe.call_count, 23)
        self.assertEqual(session.result, 'success')

    def test_only_one_legal_option_keeps_retrying_instead_of_stopping(self):
        session, runner, now, frame = self.session()
        only_move = ranked_moves(frame.tiles)[0]
        session.stable_board = Mock(return_value=frame)
        runner.controller.swipe.side_effect = lambda *_args: runner.stop_event.set() if runner.controller.swipe.call_count == 5 else None
        with patch('tasks.match3_task.time.monotonic', side_effect=lambda: now[0]), \
                patch('tasks.match3_task.read_board', return_value=frame), \
                patch('tasks.match3_task.ranked_moves', return_value=[only_move]):
            session.run(30)
        self.assertEqual(runner.controller.swipe.call_count, 5)
        self.assertEqual([call.args[-1] for call in runner.controller.swipe.call_args_list], [240, 420, 240, 420, 240])

    def test_temporary_unreadable_result_recovers_and_retries(self):
        session, runner, now, frame = self.session()
        session.stable_board = Mock(side_effect=[frame, None, frame, self.changed(frame)])
        def status(force=False):
            if runner.controller.swipe.call_count >= 2:
                session.result = 'success'
        session.status = status
        with patch('tasks.match3_task.time.monotonic', side_effect=lambda: now[0]), \
                patch('tasks.match3_task.read_board', return_value=frame):
            session.run(30)
        self.assertEqual(runner.controller.swipe.call_count, 2)
        self.assertEqual(session.result, 'success')

    def test_stop_during_recovery_never_sends_another_drag(self):
        session, runner, now, frame = self.session()
        calls = [0]
        def stable(**_kwargs):
            calls[0] += 1
            if calls[0] == 1:
                return frame
            runner.stop_event.set()
            return None
        session.stable_board = Mock(side_effect=stable)
        with patch('tasks.match3_task.time.monotonic', side_effect=lambda: now[0]), \
                patch('tasks.match3_task.read_board', return_value=frame):
            session.run(30)
        runner.controller.swipe.assert_called_once()

    def test_stable_unchanged_board_is_returned_quickly_for_retry(self):
        session, runner, now, frame = self.session()
        with patch('tasks.match3_task.time.monotonic', side_effect=lambda: now[0]), \
                patch('tasks.match3_task.success_present', return_value=False), \
                patch('tasks.match3_task.read_board', return_value=frame):
            result = session.stable_board(previous=frame.tiles, unchanged_after=2.)
        self.assertIs(result, frame)
        self.assertGreaterEqual(now[0], 2.)
        self.assertLess(now[0], 3.)

    def test_stale_turn_count_does_not_acknowledge_a_later_ignored_drag(self):
        session, runner, now, frame = self.session()
        second = self.changed(frame)
        third = self.changed(second, 1)
        session.remaining = 20
        session.stable_board = Mock(side_effect=[frame, second, third, third])
        def status(force=False):
            if runner.controller.swipe.call_count >= 3:
                session.remaining = 18
        session.status = status
        runner.controller.swipe.side_effect = lambda *_args: runner.stop_event.set() if runner.controller.swipe.call_count == 4 else None
        with patch('tasks.match3_task.time.monotonic', side_effect=lambda: now[0]), \
                patch('tasks.match3_task.read_board', side_effect=[frame, second, third, third]):
            session.run(30)
        messages = [call.args[0] for call in runner.log.call_args_list]
        self.assertEqual(sum('有效棋盘变化' in message for message in messages), 2)
        self.assertFalse(any('已确认剩余回合减少' in message for message in messages))
        self.assertTrue(any('拖动可能未生效' in message for message in messages))

    def test_success_during_result_wait_does_not_retry_or_click_exit(self):
        session, runner, now, frame = self.session()
        session.stable_board = Mock(side_effect=[frame, None])
        def status(force=False):
            if runner.controller.swipe.call_count:
                session.result = 'success'
        session.status = status
        with patch('tasks.match3_task.time.monotonic', side_effect=lambda: now[0]), \
                patch('tasks.match3_task.read_board', return_value=frame):
            session.run(30)
        runner.controller.swipe.assert_called_once()
        runner.controller.tap.assert_not_called()
        self.assertEqual(session.result, 'success')
