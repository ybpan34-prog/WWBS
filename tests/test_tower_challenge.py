import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from PIL import Image

import app
from combat_rotation import default_store, load_store, new_module, validate_store


FIXTURES = Path(__file__).parent / "fixtures"


class TowerVisionTests(unittest.TestCase):
    def test_provided_start_and_success_frames_at_multiple_resolutions(self):
        runner = app.TaskRunner(Mock(), Mock())
        with tempfile.TemporaryDirectory() as directory:
            screen = Path(directory) / 'screen.png'
            for label in ('scene', 'prompt', 'result'):
                with Image.open(FIXTURES / f'tower-{label}.png') as source:
                    for scale in (.75, 1., 1.25):
                        source.resize((round(1920*scale), round(1080*scale)), Image.Resampling.BILINEAR).save(screen)
                        with self.subTest(frame=label, scale=scale):
                            self.assertEqual(runner._tower_success_present(screen), label == 'result')
                            self.assertEqual(runner._tower_template_present(screen, 'start_prompt.png',
                                                                           (.50, .32, .95, .75)), label == 'prompt')

    def test_success_requires_both_title_and_score_button(self):
        runner = app.TaskRunner(Mock(), Mock())
        with tempfile.TemporaryDirectory() as directory:
            with Image.open(FIXTURES / 'tower-result.png') as source:
                partial = source.copy()
                partial.paste((20, 22, 24), (780, 862, 1140, 985))
                path = Path(directory) / 'partial.png'
                partial.save(path)
            self.assertFalse(runner._tower_success_present(path))

    def test_start_scene_orb_is_located_near_center(self):
        x, y, confidence = app.TaskRunner._daily_reward_orb_location(FIXTURES / 'tower-scene.png')
        self.assertIsNotNone(x)
        self.assertLess(abs(x-960), 200)
        self.assertLess(y, 550)
        self.assertGreater(confidence, .65)


class TowerFlowTests(unittest.TestCase):
    def runner(self):
        controller = Mock()
        controller.normalize_input_binding = lambda value: value
        runner = app.TaskRunner(controller, Mock(), dry_run=False)
        runner._capture_for_matching = Mock()
        runner._sleep_interruptible = Mock()
        return runner

    def test_approach_walks_until_prompt_then_presses_f_once(self):
        runner = self.runner()
        runner._tower_success_present = Mock(return_value=False)
        runner._tower_template_present = Mock(side_effect=[False, True])
        self.assertTrue(runner._approach_tower_start(FIXTURES / 'tower-scene.png'))
        runner.controller.press_keys.assert_called_once_with(('W',), 300)
        runner.controller.press_key.assert_called_once_with('F', 100)
        runner.controller.tap.assert_not_called()

    def test_already_successful_scene_never_moves_or_starts(self):
        runner = self.runner()
        runner._tower_success_present = Mock(return_value=True)
        runner._run_tower_battle = Mock()
        runner._run_tower_challenge(Mock(timeout=1200))
        runner._run_tower_battle.assert_not_called()
        runner.controller.press_keys.assert_not_called()
        runner.controller.press_key.assert_not_called()

    def test_missing_start_prompt_does_not_press_f_blindly(self):
        runner = self.runner()
        runner._tower_success_present = Mock(return_value=False)
        runner._tower_template_present = Mock(return_value=False)
        runner.controller.press_keys.side_effect = lambda *_: runner.stop_event.set()
        self.assertFalse(runner._approach_tower_start(FIXTURES / 'tower-scene.png'))
        runner.controller.press_key.assert_not_called()

    def test_battle_uses_tower_order_and_stops_at_result_without_blood_checks(self):
        runner = self.runner()
        runner.rotation_presets = {'tower': [new_module('skill', 3), new_module('idle_attack', 1)]}
        runner.rotation_times = {'tower': {'1': 25, '2': 15, '3': 5}}
        runner.rotation_orders = {'tower': [3, 1, 2]}
        runner._tower_success_present = Mock(return_value=False)
        runner._boss_health_ratio = Mock(side_effect=AssertionError('must not inspect health'))
        runner._inspect_4c_boss_header = Mock(side_effect=AssertionError('must not inspect header'))
        monitor = Mock(error=None)
        monitor.poll.side_effect = [(False,), (False,), (True,)]
        with patch.object(app, 'BattleMonitor', return_value=monitor):
            runner._run_tower_battle(Mock(timeout=1200), FIXTURES / 'tower-scene.png')
        runner.controller.press_key.assert_called_once_with('3', 65)
        runner.controller.press_binding.assert_called_once_with('E', 65)
        runner.controller.tap.assert_not_called()
        runner._boss_health_ratio.assert_not_called()
        runner._inspect_4c_boss_header.assert_not_called()
        self.assertIsNone(runner._rotation_idle_worker)
        monitor.pause.assert_called_once()

    def test_success_at_battle_entry_sends_no_attack_or_switch_input(self):
        runner = self.runner()
        runner._tower_success_present = Mock(return_value=True)
        runner._run_tower_battle(Mock(timeout=1200), FIXTURES / 'tower-result.png')
        runner.controller.press_key.assert_not_called()
        runner.controller.middle_click.assert_not_called()
        runner.controller.press_binding.assert_not_called()
        runner.controller.left_click.assert_not_called()

    def test_battle_entry_confirms_role_only_through_first_clock_action(self):
        runner = self.runner()
        runner.rotation_presets = {'tower': [new_module('skill', 3)]}
        runner._tower_success_present = Mock(return_value=False)
        runner._select_rotation_slot = Mock(return_value=True)
        monitor = Mock(error=None)
        monitor.poll.side_effect = [(False,), (True,)]
        with patch.object(app, 'BattleMonitor', return_value=monitor):
            runner._run_tower_battle(Mock(timeout=1200), FIXTURES / 'tower-scene.png')
        runner._select_rotation_slot.assert_called_once_with(3, verify=True)

    def test_stop_after_f_prevents_battle(self):
        runner = self.runner()
        runner._approach_tower_start = Mock(side_effect=lambda _: (runner.stop_event.set(), False)[1])
        runner._run_tower_battle = Mock()
        runner._run_tower_challenge(Mock(timeout=1200))
        runner._run_tower_battle.assert_not_called()

    def test_success_does_not_invoke_automatic_shutdown(self):
        ui = app.App.__new__(app.App)
        ui._pet_feedback, ui._event_line, ui._log = Mock(), Mock(), Mock()
        ui._last_started_tasks = [Mock(steps=[app.Step(action='tower_challenge')])]
        ui.auto_shutdown_enabled = Mock(get=Mock(return_value=True))
        with patch.object(app.subprocess, 'run') as run:
            ui._handle_successful_task_completion()
        run.assert_not_called()


class TowerUiTests(unittest.TestCase):
    def test_tower_mode_can_save_an_independent_preset(self):
        root = tk.Tk()
        try:
            root.geometry('1050x800')
            with tempfile.TemporaryDirectory() as directory, patch.object(app, 'COMBAT_PRESETS_CONFIG', Path(directory)/'combat.json'):
                ui = app.App.__new__(app.App)
                ui.root = root
                ui.rotation_store = default_store()
                ui.rotation_store['presets'].append({'id': 'tower_axis', 'name': '深塔自定义',
                    'slot_order': [3, 1, 2], 'slot_times': {'1': 25, '2': 15, '3': 5},
                    'modules': [new_module('skill', 3)]})
                ui.rotation_choice = tk.StringVar()
                ui.rotation_tab = tk.Frame(root)
                ui.rotation_tab.pack(fill=tk.BOTH, expand=True)
                ui._build_rotation_tab()
                root.update()
                ui.rotation_mode_choices['tower'].set('深塔自定义')
                ui._rotation_assign_mode('tower')
                saved = load_store(app.COMBAT_PRESETS_CONFIG)
                self.assertEqual(saved['modes'], {'daily': 'default', 'combat_4c': 'default', 'tower': 'tower_axis'})
        finally:
            root.destroy()

    def test_launcher_and_legacy_mode_migration(self):
        root = tk.Tk()
        try:
            ui = app.App.__new__(app.App)
            ui.root = root
            ui.target_mode, ui.dry_run = tk.StringVar(value='client'), tk.BooleanVar(value=True)
            ui._ensure_admin_for_real_run = Mock(return_value=True)
            ui._start_worker = Mock()
            ui._start_tower_challenge()
            task = ui._start_worker.call_args.args[0][0]
            self.assertEqual(task.name, '深塔挑战')
            self.assertEqual(task.template_group, 'tower')
            self.assertEqual(task.steps[0].action, 'tower_challenge')
            self.assertFalse(ui.dry_run.get())
            store = default_store()
            del store['modes']['tower']
            self.assertEqual(validate_store(store)['modes']['tower'], 'default')
        finally:
            root.destroy()


if __name__ == '__main__':
    unittest.main()
