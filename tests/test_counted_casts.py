import json
from pathlib import Path
import tempfile
import threading
import tkinter as tk
import unittest
from unittest.mock import Mock, patch

import app
from combat_rotation import RotationClock, default_store, new_module, validate_store
from combat_seed import decode_seed, export_seed


class CountedCastTests(unittest.TestCase):
    def test_counts_run_once_per_visit_in_order_and_looping_casts_still_repeat(self):
        modules = [new_module(k) for k in ('skill_count', 'execute', 'ultimate_count', 'skill')]
        modules[0]['value'] = 3
        clock = RotationClock(modules, 0, slot_times={'1': 20})
        actions = [clock.next_action(tick*.05) for tick in range(400)]
        actions = [a for a in actions if a and a['kind'] != 'select_slot']
        self.assertEqual([a['kind'] for a in actions[:5]], ['skill', 'skill', 'skill', 'execute', 'ultimate'])
        for module, count in zip(modules, (3, 1, 1, 4)):
            self.assertEqual(sum(a['module']['id'] == module['id'] for a in actions), count)
        self.assertEqual(clock.next_action(20)['kind'], 'select_slot')
        self.assertEqual(clock.next_action(20.05)['module']['id'], modules[0]['id'])

    def test_pending_casts_do_not_skip_next_wait_and_deadline_discards_remaining(self):
        cast, wait = new_module('ultimate_count'), new_module('wait')
        cast['value'] = 20
        clock = RotationClock([cast, wait, new_module('execute', 2)], 0, slot_times={'1': 1, '2': 1})
        clock.next_action(0)
        self.assertEqual(clock.next_action(.1)['kind'], 'ultimate')
        self.assertFalse(clock.has_following_wait(.1))
        self.assertEqual(clock.next_action(1)['module']['slot'], 2)
        self.assertEqual(clock.next_action(1.1)['kind'], 'execute')

    def test_f_press_pauses_idle_and_respects_stop_and_settlement(self):
        for stopped, finished in ((False, False), (True, False), (False, True)):
            with self.subTest(stopped=stopped, finished=finished):
                runner = app.TaskRunner(Mock(), Mock())
                runner._rotation_slot = 1
                runner._rotation_battle_finished = finished
                runner._rotation_idle_worker = Mock()
                if stopped:
                    runner.stop_event.set()
                module = new_module('execute')
                clock = RotationClock([module], 0)
                with patch('tasks.combat_4c.time.monotonic', return_value=.1):
                    runner._run_rotation_action({'kind': 'execute', 'module': module}, clock,
                        'E', 'R', threading.Event(), threading.Lock())
                if stopped or finished:
                    runner.controller.press_key.assert_not_called()
                else:
                    runner._rotation_idle_worker.pause.assert_called_once()
                    runner.controller.press_key.assert_called_once_with('F', 65)

    def test_finite_modules_use_configured_bindings_exactly_once(self):
        modules = [new_module(k) for k in ('skill_count', 'ultimate_count')]
        runner = app.TaskRunner(Mock(), Mock())
        runner._rotation_slot = 1
        runner._sleep_interruptible = Mock()
        clock = RotationClock(modules, 0, slot_times={'1': 10})
        with patch('tasks.combat_4c.time.monotonic', return_value=.1):
            for tick in range(100):
                runner._run_rotation_action(clock.next_action(tick*.05), clock, 'T', 'Y',
                                            threading.Event(), threading.Lock())
        self.assertEqual([call.args for call in runner.controller.press_binding.call_args_list], [('T', 65), ('Y', 120)])

    def test_validation_save_and_new_seed_round_trip(self):
        preset = default_store()['presets'][0]
        preset['modules'] = [new_module(k) for k in ('execute', 'skill_count', 'ultimate_count')]
        preset['modules'][1]['value'] = 3
        seed = export_seed(preset)
        self.assertIn('】WWBS5.', seed)
        restored = decode_seed(seed)
        self.assertEqual([{k:m[k] for k in ('kind','value','slot','interval')} for m in restored['modules']],
                         [{k:m[k] for k in ('kind','value','slot','interval')} for m in preset['modules']])
        for bad in (0, 1.5, 21):
            store = default_store()
            store['presets'][0]['modules'] = [dict(new_module('skill_count'), value=bad)]
            with self.assertRaises(ValueError):
                validate_store(store)

    def test_editor_exposes_cast_count_and_saves_without_changing_loop_modules(self):
        root = tk.Tk()
        try:
            ui = app.App.__new__(app.App)
            ui.root = root
            ui.rotation_store = default_store()
            item = new_module('skill_count')
            ui.rotation_store['presets'][0]['modules'] = [item, new_module('skill')]
            ui.rotation_choice = tk.StringVar()
            ui.rotation_tab = tk.Frame(root)
            ui._build_rotation_tab()
            ui._rotation_save = Mock(return_value=True)
            ui._rotation_commit_time = Mock()
            entries = []
            original = ui._rounded_entry
            def entry(*args, **kwargs):
                entries.append(kwargs['textvariable'])
                return original(*args, **kwargs)
            ui._rounded_entry = entry
            commands = {}
            original_button = ui._rounded_button
            def button(parent, label, command, **kwargs):
                commands[label] = command
                return original_button(parent, label, command, **kwargs)
            ui._rounded_button = button
            with tempfile.TemporaryDirectory() as directory, patch.object(app, 'COMBAT_PRESETS_CONFIG', Path(directory)/'axis.json'):
                ui._rotation_edit(item['id'])
                self.assertEqual(len(entries), 1)
                entries[0].set('3')
                commands['保存']()
                saved = json.loads(app.COMBAT_PRESETS_CONFIG.read_text(encoding='utf-8'))
                self.assertEqual(saved['presets'][0]['modules'][0]['value'], 3)
                self.assertEqual(saved['presets'][0]['modules'][1]['interval'], 5)
        finally:
            root.destroy()
