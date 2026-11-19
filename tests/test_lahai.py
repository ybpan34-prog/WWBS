import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock

import numpy as np
from PIL import Image

from app import App
from tasks.lahai import run_lahai
from tasks.lahai_solver import Move, apply_move


class LahaiTests(unittest.TestCase):
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
        from tasks.lahai import _anchor
        canvas = np.zeros((1080, 1920), dtype=np.uint8)
        for name in ('first_complete', 'levels_title'):
            x, y, ref, _ = _anchor(name)
            h, w = ref.shape
            canvas[y:y+h, x:x+w] = (ref - ref.min()).astype(np.uint8)
        runner = Mock()
        runner.stop_event = threading.Event()
        with tempfile.TemporaryDirectory() as directory:
            runner.template_root = Path(directory) / 'templates' / 'lahai'
            runner._capture_for_matching.side_effect = lambda path: Image.fromarray(canvas).save(path)
            run_lahai(runner)
        runner.controller.tap.assert_not_called()
        runner.controller.drag_rotating.assert_not_called()
