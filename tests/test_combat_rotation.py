"""Three-column execution, migration, mode assignment and real Tk drag events."""
import tempfile
import tkinter as tk
import unittest
import threading
import time
from pathlib import Path
from unittest.mock import Mock, call, patch

import app
from combat_rotation import (BattleMonitor, IdleAttackWorker, RotationClock, active_modules, default_store,
                             load_store, new_module, save_store, validate_store)


class RotationTests(unittest.TestCase):
    def clock(self, modules, duration=5):
        return RotationClock(modules, 0, slot_times={str(n): duration for n in (1, 2, 3)})

    def test_default_keeps_intervals_and_heavy_frequency(self):
        modules = [m for m in active_modules(default_store()) if m['slot'] == 1]
        self.assertEqual([m['kind'] for m in modules], ['skill', 'ultimate', 'echo', 'approach', 'idle_attack'])
        self.assertEqual(modules[-1]['value'], 15)
        self.assertEqual(modules[1]['interval'], 15)
        self.assertEqual(modules[0]['interval'], 10)

    def test_default_healing_sequence_runs_q_before_return_in_both_modes(self):
        for mode in ('daily', 'combat_4c'):
            with self.subTest(mode=mode):
                store = default_store()
                modules = active_modules(store, mode)
                third = [m for m in modules if m['slot'] == 3]
                self.assertEqual([m['kind'] for m in third],
                                 ['wait', 'skill', 'wait', 'jump_attack', 'wait',
                                  'jump_attack', 'wait', 'echo', 'wait', 'idle_attack'])
                controller = Mock()
                runner = app.TaskRunner(controller, lambda _: None)
                tick = [0.0]
                inputs = []
                def sleep(duration):
                    tick[0] += duration
                def press(key, duration):
                    inputs.append((tick[0], key))
                    tick[0] += duration / 1000
                controller.press_key.side_effect = press
                controller.press_binding.side_effect = press
                controller.left_click.side_effect = lambda: inputs.append((tick[0], 'click'))
                runner._sleep_interruptible = sleep
                clock = RotationClock(modules, 0, slot_times=store['presets'][0]['slot_times'],
                                      background_idle=True)
                with patch.object(app.time, 'monotonic', side_effect=lambda: tick[0]):
                    while tick[0] < 14:
                        action = clock.next_action(tick[0])
                        runner._run_rotation_action(action, clock, 'E', 'R', threading.Event(),
                                                    threading.Lock(), daily=mode == 'daily')
                        tick[0] += .05
                selected = next(i for i, (_, key) in enumerate(inputs) if key == '3')
                returned = next(i for i in range(selected+1, len(inputs)) if inputs[i][1] == '1')
                healing = inputs[selected+1:returned]
                self.assertEqual([key for _, key in healing],
                                 ['E', 'SPACE', 'click', 'click', 'click',
                                  'SPACE', 'click', 'click', 'click', 'Q'])
                self.assertGreaterEqual(inputs[returned][0] - healing[-1][0], .8)

    def test_loading_old_default_adds_healing_but_preserves_customizations(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'combat.json'
            old = default_store()
            preset = old['presets'][0]
            preset['modules'] = [m for m in preset['modules'] if m['slot'] == 1]
            preset['slot_times']['3'] = 5
            save_store(path, old)
            upgraded = load_store(path)
            self.assertEqual(upgraded['presets'][0]['slot_times']['3'], 8)
            self.assertTrue(any(m['slot'] == 3 and m['kind'] == 'echo'
                                for m in active_modules(upgraded)))
            save_store(path, upgraded)
            self.assertEqual(load_store(path), upgraded)
            for field, value in (('time', 20), ('count', 23), ('order', None)):
                custom = validate_store(old)
                if field == 'time':
                    custom['presets'][0]['slot_times']['1'] = value
                elif field == 'count':
                    custom['presets'][0]['modules'][-1]['value'] = value
                else:
                    custom['presets'][0]['modules'].reverse()
                save_store(path, custom)
                self.assertEqual(load_store(path), custom)

    def test_columns_are_ordered_and_empty_second_is_skipped(self):
        first, third = new_module('skill', 1), new_module('echo', 3)
        clock = self.clock([third, first], 2)
        self.assertEqual(clock.next_action(0)['module']['slot'], 1)
        self.assertEqual(clock.next_action(.1)['kind'], 'skill')
        self.assertIsNone(clock.next_action(1))
        self.assertEqual(clock.next_action(2)['module']['slot'], 3)
        self.assertEqual(clock.next_action(2.1)['kind'], 'echo')
        self.assertEqual(clock.next_action(4)['module']['slot'], 1)

    def test_cooldown_is_checked_next_visit_and_top_to_bottom_order_is_preserved(self):
        skill, ult, idle = new_module('skill'), new_module('ultimate'), new_module('idle_attack')
        other = new_module('wait', 2)
        clock = self.clock([skill, ult, idle, other], 3)
        clock.next_action(0)
        self.assertEqual(clock.next_action(.1)['kind'], 'skill')
        self.assertEqual(clock.next_action(.2)['kind'], 'ultimate')
        clock.next_action(3)
        clock.next_action(3.1)
        clock.next_action(6)
        self.assertEqual(clock.next_action(6.1)['kind'], 'left_click')
        clock.next_action(9)
        clock.next_action(12)
        self.assertEqual(clock.next_action(12.1)['kind'], 'skill')
        self.assertEqual(clock.next_action(12.2)['kind'], 'left_click')
        clock.next_action(15)
        clock.next_action(18)
        self.assertEqual(clock.next_action(18.1)['kind'], 'ultimate')  # skill still cooling
        self.assertEqual(clock.next_action(18.2)['kind'], 'left_click')
        # ultimate is due, but no action may be fired once this visit's ordered pass ended
        self.assertNotEqual(clock.next_action(19)['kind'], 'ultimate')

    def test_ready_skill_then_ultimate_on_same_visit(self):
        skill, ult = new_module('skill'), new_module('ultimate')
        clock = self.clock([skill, ult], 16)
        clock.next_action(0)
        self.assertEqual(clock.next_action(.1)['kind'], 'skill')
        self.assertEqual(clock.next_action(.2)['kind'], 'ultimate')
        clock.next_action(16)
        self.assertEqual(clock.next_action(16.1)['kind'], 'skill')
        self.assertEqual(clock.next_action(16.2)['kind'], 'ultimate')

    def test_fixed_click_count_then_idle_heavy(self):
        attack, idle = new_module('attack_count'), new_module('idle_attack')
        attack['value'], idle['value'] = 2, 2
        clock = self.clock([attack, idle], 10)
        clock.next_action(0)
        self.assertEqual(clock.next_action(.1)['kind'], 'left_click')
        self.assertIsNone(clock.next_action(.2))
        self.assertEqual(clock.next_action(.3)['kind'], 'left_click')
        self.assertIsNone(clock.next_action(.31))
        self.assertEqual(clock.next_action(.5)['kind'], 'left_click')
        self.assertEqual(clock.next_action(.7)['kind'], 'left_click')
        self.assertEqual(clock.next_action(.9)['kind'], 'hold_left')

    def test_idle_does_not_attack_during_wait_or_timed_attack(self):
        wait, attacks, idle = new_module('wait'), new_module('attack_seconds'), new_module('idle_attack')
        wait['value'], attacks['value'] = 1, 1
        clock = self.clock([idle, wait, attacks])
        clock.next_action(0)
        self.assertEqual(clock.next_action(.1)['kind'], 'wait')
        self.assertIsNone(clock.next_action(.5))
        self.assertEqual(clock.next_action(1.1)['module']['id'], attacks['id'])
        self.assertEqual(clock.next_action(1.3)['module']['id'], attacks['id'])
        self.assertEqual(clock.next_action(2.2)['module']['id'], idle['id'])

    def test_jump_before_exact_number_of_clicks(self):
        jump = new_module('jump_attack')
        jump['value'] = 2
        clock = self.clock([jump])
        clock.next_action(0)
        self.assertEqual(clock.next_action(.1)['kind'], 'jump')
        self.assertIsNone(clock.next_action(.2))
        self.assertEqual(clock.next_action(.3)['kind'], 'left_click')
        self.assertEqual(clock.next_action(.5)['kind'], 'left_click')
        self.assertIsNone(clock.next_action(.7))

    def test_station_deadline_truncates_wait_and_attack_module(self):
        for kind in ('wait', 'attack_count', 'attack_seconds', 'heavy_count'):
            item = new_module(kind)
            item['value'] = 20
            clock = self.clock([item, new_module('skill', 2)], 1)
            clock.next_action(0)
            clock.next_action(.1)
            result = clock.next_action(1)
            self.assertEqual((result['kind'], result['module']['slot']), ('select_slot', 2))

    def test_station_time_and_mode_assignment_are_persistent(self):
        store = default_store()
        other = {'id': 'custom', 'name': '自定义', 'slot_times': {'1': 7, '2': 3.5, '3': 4},
                 'modules': [new_module('jump_attack', 3)]}
        store['presets'].append(other)
        store['modes']['daily'] = 'custom'
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'combat.json'
            save_store(path, store)
            loaded = load_store(path)
            self.assertEqual(loaded['presets'][1]['slot_times']['2'], 3.5)
            self.assertEqual(active_modules(loaded, 'daily')[0]['slot'], 3)
            snapshot = active_modules(loaded, 'daily')
            snapshot[0]['value'] = 9
            self.assertEqual(active_modules(loaded, 'daily')[0]['value'], 3)

    def test_old_continuous_migrates_without_losing_slots_or_parameters(self):
        store = default_store()
        store['version'] = 2
        store['presets'][0]['modules'] = [m for m in store['presets'][0]['modules'] if m['slot'] == 1]
        item = next(m for m in store['presets'][0]['modules'] if m['kind'] == 'idle_attack')
        item.update(kind='continuous', value=23, slot=3)
        migrated = validate_store(store)
        self.assertEqual(migrated['version'], 3)
        migrated_item = next(m for m in migrated['presets'][0]['modules'] if m['id'] == item['id'])
        self.assertEqual(migrated_item['kind'], 'idle_attack')
        self.assertEqual(migrated_item['value'], 23)
        self.assertEqual(migrated_item['slot'], 3)

    def test_beta2_heal_removed_and_default_ten_migrates_to_fifteen(self):
        store = default_store()
        store['version'] = 1
        del store['modes']
        modules = store['presets'][0]['modules']
        modules[:] = [m for m in modules if m['slot'] == 1]
        for item in modules:
            item.pop('slot')
            if item['kind'] == 'idle_attack':
                item.update(kind='continuous', value=10)
            if item['kind'] == 'ultimate':
                item['interval'] = 10
        modules.append({'id': 'legacy', 'kind': 'heal'})
        migrated = validate_store(store)
        kinds = {m['kind']: m for m in active_modules(migrated)}
        self.assertNotIn('heal', kinds)
        self.assertEqual(kinds['idle_attack']['value'], 15)
        self.assertEqual(kinds['ultimate']['interval'], 15)

    def test_invalid_times_counts_and_duplicate_idle_in_one_column_rejected(self):
        for bad in (0, float('nan'), float('inf'), 121):
            store = default_store()
            store['presets'][0]['slot_times']['1'] = bad
            with self.assertRaises(ValueError):
                validate_store(store)
        store = default_store()
        store['presets'][0]['modules'].append(new_module('idle_attack'))
        with self.assertRaises(ValueError):
            validate_store(store)
        store['presets'][0]['modules'][-1]['slot'] = 2
        validate_store(store)
        store['presets'][0]['modules'].append(new_module('attack_count'))
        store['presets'][0]['modules'][-1]['value'] = 1.5
        with self.assertRaises(ValueError):
            validate_store(store)

    def test_action_switches_slot_without_restoring_another_background_character(self):
        controller = Mock()
        runner = app.TaskRunner(controller, lambda _: None)
        runner._sleep_interruptible = Mock()
        item = new_module('echo', 3)
        clock = RotationClock([item], 100)
        enabled = app.threading.Event()
        with patch.object(app.time, 'monotonic', return_value=100.1):
            runner._run_rotation_action({'kind': 'echo', 'module': item}, clock, 'E', 'R', enabled, app.threading.Lock())
        self.assertEqual(controller.method_calls, [call.press_key('3', 65), call.press_key('Q', 120)])
        self.assertFalse(enabled.is_set())

    def test_heavy_input_is_clipped_at_station_deadline(self):
        controller = Mock()
        runner = app.TaskRunner(controller, lambda _: None)
        item = new_module('heavy_count')
        clock = self.clock([item], 1)
        with patch.object(app.time, 'monotonic', return_value=.8):
            runner._run_rotation_action({'kind': 'hold_left', 'module': item}, clock, 'E', 'R',
                                        app.threading.Event(), app.threading.Lock())
        controller.hold_left_button.assert_called_once_with(200)

    def test_each_battle_uses_its_mode_and_station_times(self):
        controller = Mock()
        runner = app.TaskRunner(controller, lambda _: None, dry_run=False,
                                rotation_presets={'daily': [new_module('echo', 3)], 'combat_4c': [new_module('skill', 2)]},
                                rotation_times={'daily': {'1': 8, '2': 8, '3': 8}, 'combat_4c': {'1': 9, '2': 9, '3': 9}})
        runner._sleep_interruptible = Mock()
        runner._inspect_4c_boss_header = Mock(return_value=True)
        controller.press_binding.side_effect = lambda *_: runner.stop_event.set()
        ticks = iter(i / 10 for i in range(1, 3000))
        with patch.object(app.time, 'monotonic', side_effect=lambda: next(ticks)):
            runner._run_4c_battle(Mock(timeout=100), 'E', 'R', 1)
        controller.press_binding.assert_called_once_with('E', 65)
        controller.press_key.assert_any_call('2', 65)
        runner.stop_event.clear()
        controller.reset_mock()
        runner._select_daily_slot_one_after_loading = Mock()
        runner._capture_for_matching = Mock()
        runner._daily_reward_stage_present = Mock(return_value=False)
        runner._daily_battle_task_present = Mock(return_value=True)
        controller.press_key.side_effect = lambda key, _: runner.stop_event.set() if key == 'Q' else None
        ticks = iter(i / 10 for i in range(1, 3000))
        with patch.object(app.time, 'monotonic', side_effect=lambda: next(ticks)):
            runner._run_daily_battle(Mock(timeout=100), 'E', 'R', 1)
        self.assertEqual(controller.press_key.call_args_list, [call('3', 65), call('Q', 120)])

    def build_ui(self, root):
        window = app.App.__new__(app.App)
        window.root = root
        window.rotation_store = default_store()
        window.rotation_choice = tk.StringVar()
        window.rotation_tab = tk.Frame(root, bg=app.COLORS['panel'])
        window.rotation_tab.pack(fill=tk.BOTH, expand=True)
        root.geometry('960x740+60+60')
        window._build_rotation_tab()
        root.update()
        return window

    def test_ui_station_time_mode_selection_add_and_cross_column_move_are_saved(self):
        root = tk.Tk()
        try:
            with tempfile.TemporaryDirectory() as tmp, patch.object(app, 'COMBAT_PRESETS_CONFIG', Path(tmp)/'combat.json'):
                window = self.build_ui(root)
                window._rotation_time_fields[2].set('7.5')
                self.assertTrue(window._rotation_save())
                window._rotation_add_choices[2].set('跳跃普攻')
                window._rotation_add(2)
                module = next(m for m in window._rotation_current_preset()['modules'] if m['slot'] == 2)
                self.assertEqual((module['slot'], module['kind']), (2, 'jump_attack'))
                window._rotation_drop(module['id'], 3, 0)
                self.assertEqual(next(m for m in active_modules(load_store(app.COMBAT_PRESETS_CONFIG))
                                      if m['id'] == module['id'])['slot'], 3)
                self.assertEqual(load_store(app.COMBAT_PRESETS_CONFIG)['presets'][0]['slot_times']['2'], 7.5)
                store = window.rotation_store
                store['presets'].append({'id': 'custom', 'name': '自定义', 'modules': [new_module('wait')]})
                window._rotation_save_new_structure()
                window._rotation_refresh_picker()
                window.rotation_mode_choices['daily'].set('自定义')
                window._rotation_assign_mode('daily')
                self.assertEqual(load_store(app.COMBAT_PRESETS_CONFIG)['modes'], {'daily': 'custom', 'combat_4c': 'default'})
        finally:
            root.destroy()

    def test_live_drag_keeps_source_mapped_follows_pointer_and_releases_without_grab(self):
        root = tk.Tk()
        try:
            with tempfile.TemporaryDirectory() as tmp, patch.object(app, 'COMBAT_PRESETS_CONFIG', Path(tmp)/'combat.json'):
                window = self.build_ui(root)
                modules = window._rotation_current_preset()['modules']
                key = modules[0]['id']
                card = window._rotation_cards[key]
                x, y = card.winfo_rootx(), card.winfo_rooty()
                card.event_generate('<ButtonPress-1>', x=19, y=31)
                card.event_generate('<B1-Motion>', x=39, y=70, rootx=x+39, rooty=y+70)
                root.update()
                ghost = card._drag_ghost
                self.assertIsNone(root.grab_current())
                self.assertTrue(card.winfo_ismapped())
                self.assertEqual(modules[0]['id'], key)  # don't repack mid-drag
                self.assertEqual((ghost.winfo_rootx(), ghost.winfo_rooty()), (x+20, y+39))
                # Rounded corners have a matching solid fill and no isolated outline circles.
                preview = ghost.winfo_children()[0]
                for shape in preview.find_all():
                    if preview.type(shape) == 'oval':
                        self.assertIn(preview.itemcget(shape, 'outline'), ('', preview.itemcget(shape, 'fill')))
                target_x = window._rotation_columns[2]['canvas'].winfo_rootx()+30
                root.event_generate('<B1-Motion>', x=100, y=400, rootx=target_x, rooty=y+100)
                root.update()
                self.assertEqual(ghost.winfo_rootx(), target_x-19)
                root.event_generate('<ButtonRelease-1>', x=100, y=400)
                root.update()
                self.assertIsNone(root.grab_current())
                self.assertFalse(ghost.winfo_exists())
                self.assertEqual(next(m for m in active_modules(load_store(app.COMBAT_PRESETS_CONFIG)) if m['id'] == key)['slot'], 2)
                moved = window._rotation_cards[key]
                with patch.object(window._rotation_columns[2]['canvas'], 'yview_scroll') as scroll:
                    moved.event_generate('<MouseWheel>', delta=-120)
                    root.update()
                    scroll.assert_called_once_with(3, 'units')
                for column in window._rotation_columns.values():
                    self.assertIsInstance(column['scrollbar'], tk.Canvas)
                    self.assertEqual(column['scrollbar'].winfo_reqwidth(), 7)
        finally:
            root.destroy()

    def test_escape_cancels_drag_and_card_click_still_works(self):
        root = tk.Tk()
        try:
            with tempfile.TemporaryDirectory() as tmp, patch.object(app, 'COMBAT_PRESETS_CONFIG', Path(tmp)/'combat.json'):
                window = self.build_ui(root)
                before = [m['id'] for m in window._rotation_current_preset()['modules']]
                card = window._rotation_cards[before[0]]
                card.event_generate('<ButtonPress-1>', x=19, y=31)
                card.event_generate('<B1-Motion>', x=40, y=110)
                root.update()
                root.focus_force()
                root.event_generate('<Escape>')
                root.update()
                self.assertIsNone(card._drag_ghost)
                self.assertEqual([m['id'] for m in window._rotation_current_preset()['modules']], before)
                with patch.object(window, '_rotation_edit') as edit:
                    card.event_generate('<ButtonPress-1>', x=60, y=31)
                    card.event_generate('<ButtonRelease-1>', x=60, y=31)
                    root.update()
                    edit.assert_called_once_with(before[0])
        finally:
            root.destroy()

    def test_release_from_dropdown_or_added_card_does_not_open_editor(self):
        root = tk.Tk()
        try:
            with tempfile.TemporaryDirectory() as tmp, patch.object(app, 'COMBAT_PRESETS_CONFIG', Path(tmp)/'combat.json'):
                window = self.build_ui(root)
                window._rotation_add_choices[3].set('跳跃普攻')
                with patch.object(window, '_rotation_edit') as edit:
                    outer = window._rotation_columns[3]['canvas'].master.master
                    addition = outer.winfo_children()[2]
                    button = next(w for w in addition.winfo_children() if isinstance(w, tk.Canvas) and not getattr(w, '_is_rounded_picker', False))
                    button.event_generate('<ButtonPress-1>', x=20, y=20)
                    button.event_generate('<ButtonRelease-1>', x=20, y=20)
                    root.update()
                    added = window._rotation_current_preset()['modules'][-1]
                    card = window._rotation_cards[added['id']]
                    picker = next(w for w in addition.winfo_children() if getattr(w, '_is_rounded_picker', False))
                    picker.event_generate('<Button-1>', x=20, y=20)
                    root.update()
                    surface = picker._popup_window.winfo_children()[0]
                    target = next(i for i in surface.find_all() if surface.type(i) == 'text'
                                  and surface.itemcget(i, 'text') == '跳跃普攻')
                    x, y = surface.coords(target)
                    surface.event_generate('<Button-1>', x=round(x), y=round(y))
                    root.update()
                    self.assertIsNone(picker._popup_window)
                    # A popup selected on mouse-down disappears before mouse-up;
                    # Tk can deliver that release to the card now underneath it.
                    card.event_generate('<ButtonRelease-1>', x=60, y=31)
                    root.update()
                    edit.assert_not_called()
                    card.event_generate('<ButtonPress-1>', x=60, y=31)
                    card.event_generate('<ButtonRelease-1>', x=60, y=31)
                    root.update()
                    edit.assert_called_once_with(added['id'])
                    edit.reset_mock()
                    card.event_generate('<ButtonRelease-1>', x=60, y=31)
                    root.update()
                    edit.assert_not_called()
        finally:
            root.destroy()

    def test_handle_click_or_cancelled_body_click_does_not_open_editor(self):
        root = tk.Tk()
        try:
            with tempfile.TemporaryDirectory() as tmp, patch.object(app, 'COMBAT_PRESETS_CONFIG', Path(tmp)/'combat.json'):
                window = self.build_ui(root)
                card = next(iter(window._rotation_cards.values()))
                with patch.object(window, '_rotation_edit') as edit:
                    # Pressing the reorder handle is not an edit click.
                    card.event_generate('<ButtonPress-1>', x=19, y=31)
                    card.event_generate('<ButtonRelease-1>', x=31, y=31)
                    # A click dragged out of the body is cancelled.
                    card.event_generate('<ButtonPress-1>', x=60, y=31)
                    card.event_generate('<B1-Motion>', x=100, y=31)
                    card.event_generate('<ButtonRelease-1>', x=100, y=31)
                    card.event_generate('<ButtonPress-1>', x=60, y=31)
                    card.event_generate('<ButtonRelease-1>', x=card.winfo_width()+10, y=31)
                    root.update()
                    edit.assert_not_called()
        finally:
            root.destroy()

    def test_module_editor_fits_large_font_and_saves_parameters(self):
        root = tk.Tk()
        try:
            root.tk.call('tk', 'scaling', 2.0)
            with tempfile.TemporaryDirectory() as tmp, patch.object(app, 'COMBAT_PRESETS_CONFIG', Path(tmp)/'combat.json'):
                window = self.build_ui(root)
                key = window._rotation_current_preset()['modules'][0]['id']
                window._rotation_edit(key)
                root.update()
                dialog = next(w for w in root.winfo_children() if isinstance(w, tk.Toplevel))
                def walk(node):
                    yield node
                    for child in node.winfo_children():
                        yield from walk(child)
                entries = [w for w in walk(dialog) if isinstance(w, tk.Entry)]
                entries[0].delete(0, tk.END)
                entries[0].insert(0, '2')
                entries[1].delete(0, tk.END)
                entries[1].insert(0, '12')
                save = next(w for w in walk(dialog) if isinstance(w, tk.Canvas) and any(
                    w.type(i) == 'text' and w.itemcget(i, 'text') == '保存' for i in w.find_all()))
                self.assertTrue(save.winfo_ismapped())
                self.assertLessEqual(save.winfo_rooty()+save.winfo_height(), dialog.winfo_rooty()+dialog.winfo_height())
                save.event_generate('<ButtonRelease-1>', x=20, y=20)
                root.update()
                self.assertFalse(dialog.winfo_exists())
                module = next(m for m in active_modules(load_store(app.COMBAT_PRESETS_CONFIG)) if m['id'] == key)
                self.assertEqual((module['value'], module['interval']), (2, 12))
        finally:
            root.destroy()

    def test_time_entry_allows_incomplete_draft_then_autosaves_without_save_button(self):
        root = tk.Tk()
        try:
            with tempfile.TemporaryDirectory() as tmp, patch.object(app, 'COMBAT_PRESETS_CONFIG', Path(tmp)/'combat.json'), \
                 patch.object(app.messagebox, 'showerror') as error:
                window = self.build_ui(root)
                entry = window._rotation_time_entries[1]
                entry.delete(0, tk.END)
                self.assertFalse(window._rotation_commit_time(1))
                self.assertEqual(entry.get(), '')
                window._rotation_rebuild_cards()
                self.assertEqual(entry.get(), '')
                entry.insert(0, '12.5')
                root.after(650, root.quit)
                root.mainloop()
                self.assertEqual(load_store(app.COMBAT_PRESETS_CONFIG)['presets'][0]['slot_times']['1'], 12.5)
                self.assertEqual(entry.get(), '12.5')
                error.assert_not_called()
        finally:
            root.destroy()

    def test_module_dropdown_does_not_cover_time_entries_near_screen_bottom(self):
        root = tk.Tk()
        try:
            window = self.build_ui(root)
            root.geometry(f'960x600+40+{max(0, root.winfo_screenheight()-660)}')
            root.update()
            entry = window._rotation_time_entries[1]
            outer = window._rotation_columns[1]['canvas'].master.master
            picker = next(w for w in outer.winfo_children()[2].winfo_children()
                          if getattr(w, '_is_rounded_picker', False))
            picker.event_generate('<Button-1>', x=20, y=20)
            root.update()
            popup = picker._popup_window
            self.assertIsNotNone(popup)
            x, y = entry.winfo_rootx()+20, entry.winfo_rooty()+entry.winfo_height()//2
            self.assertIs(root.winfo_containing(x, y), entry)
            self.assertGreaterEqual(popup.winfo_rooty(), picker.winfo_rooty()+picker.winfo_height())
        finally:
            root.destroy()

    def test_opening_second_picker_closes_first_and_time_click_accepts_typing(self):
        root = tk.Tk()
        try:
            with tempfile.TemporaryDirectory() as tmp, patch.object(app, 'COMBAT_PRESETS_CONFIG', Path(tmp)/'combat.json'):
                window = self.build_ui(root)
                root.focus_force()
                root.update()
                pickers = []
                for column in window._rotation_columns.values():
                    outer = column['canvas'].master.master
                    pickers.append(next(w for w in outer.winfo_children()[2].winfo_children()
                                        if getattr(w, '_is_rounded_picker', False)))
                pickers[0].event_generate('<Button-1>', x=20, y=20)
                root.update()
                first_popup = pickers[0]._popup_window
                pickers[1].event_generate('<Button-1>', x=20, y=20)
                root.update()
                self.assertFalse(first_popup.winfo_exists())
                self.assertIsNone(pickers[0]._popup_window)
                entry = window._rotation_time_entries[1]
                entry.event_generate('<ButtonPress-1>', x=20, y=12)
                entry.event_generate('<ButtonRelease-1>', x=20, y=12)
                root.update()
                self.assertIs(root.focus_get(), entry)
                self.assertIsNone(pickers[1]._popup_window)
                entry.event_generate('<Control-a>')
                entry.event_generate('<KeyPress-7>')
                entry.event_generate('<KeyPress-period>')
                entry.event_generate('<KeyPress-5>')
                root.update()
                self.assertEqual(entry.get(), '7.5')
        finally:
            root.destroy()

    def test_editing_one_time_does_not_block_saving_another_or_lose_drafts(self):
        root = tk.Tk()
        try:
            with tempfile.TemporaryDirectory() as tmp, patch.object(app, 'COMBAT_PRESETS_CONFIG', Path(tmp)/'combat.json'):
                window = self.build_ui(root)
                window._rotation_time_fields[1].set('.')
                window._rotation_time_fields[2].set('9')
                self.assertTrue(window._rotation_commit_time(2))
                window._rotation_rebuild_cards()
                self.assertEqual(window._rotation_time_fields[1].get(), '.')
                self.assertEqual(window._rotation_time_fields[2].get(), '9')
                window._rotation_time_fields[1].set('7.5')
                window._rotation_time_entries[1].event_generate('<FocusOut>')
                root.update()
                saved = load_store(app.COMBAT_PRESETS_CONFIG)['presets'][0]['slot_times']
                self.assertEqual((saved['1'], saved['2']), (7.5, 9))
        finally:
            root.destroy()

    def test_module_editor_save_keeps_time_changed_while_dialog_is_open(self):
        root = tk.Tk()
        try:
            with tempfile.TemporaryDirectory() as tmp, patch.object(app, 'COMBAT_PRESETS_CONFIG', Path(tmp)/'combat.json'):
                window = self.build_ui(root)
                key = window._rotation_current_preset()['modules'][0]['id']
                window._rotation_edit(key)
                root.update()
                window._rotation_time_fields[1].set('20')
                dialog = next(w for w in root.winfo_children() if isinstance(w, tk.Toplevel))
                def walk(node):
                    yield node
                    for child in node.winfo_children():
                        yield from walk(child)
                save = next(w for w in walk(dialog) if isinstance(w, tk.Canvas) and any(
                    w.type(i) == 'text' and w.itemcget(i, 'text') == '保存' for i in w.find_all()))
                save.event_generate('<ButtonRelease-1>', x=20, y=20)
                root.update()
                self.assertEqual(window._rotation_time_fields[1].get(), '20')
                self.assertEqual(load_store(app.COMBAT_PRESETS_CONFIG)['presets'][0]['slot_times']['1'], 20)
        finally:
            root.destroy()

    def test_new_preset_copies_station_times_and_switch_ignores_old_pending_save(self):
        root = tk.Tk()
        try:
            with tempfile.TemporaryDirectory() as tmp, patch.object(app, 'COMBAT_PRESETS_CONFIG', Path(tmp)/'combat.json'), \
                 patch.object(app.App, '_ask_text', return_value='新轴'):
                window = self.build_ui(root)
                window._rotation_time_fields[1].set('18')
                window._rotation_new()
                self.assertEqual(window._rotation_current_preset()['slot_times']['1'], 18)
                self.assertEqual(window._rotation_time_fields[1].get(), '18.0')
                window._rotation_time_fields[1].set('22')
                pending = window._rotation_time_jobs[1]
                self.assertFalse(window._rotation_commit_time(1, 'default'))
                self.assertEqual(window._rotation_time_jobs[1], pending)
                self.assertTrue(window._rotation_commit_time(1))
                self.assertEqual(load_store(app.COMBAT_PRESETS_CONFIG)['presets'][0]['slot_times']['1'], 18)
                self.assertEqual(load_store(app.COMBAT_PRESETS_CONFIG)['presets'][1]['slot_times']['1'], 22)
        finally:
            root.destroy()

    def test_background_clock_does_not_emit_duplicate_clicks(self):
        module = new_module('idle_attack')
        clock = RotationClock([module], 0, background_idle=True)
        self.assertEqual(clock.next_action(0)['kind'], 'select_slot')
        for tick in (.1, .2, .3):
            self.assertEqual(clock.next_action(tick)['kind'], 'idle_attack')

    def test_task_start_commits_visible_time_and_uses_independent_snapshot(self):
        root = tk.Tk()
        try:
            with tempfile.TemporaryDirectory() as tmp, patch.object(app, 'COMBAT_PRESETS_CONFIG', Path(tmp)/'combat.json'), \
                 patch.object(app.threading, 'Thread') as thread:
                window = self.build_ui(root)
                window.worker = None
                window.stop_event = threading.Event()
                window._ensure_admin_for_real_run = Mock(return_value=True)
                window._pet_feedback = Mock()
                window._event_line = Mock(return_value='start')
                window._set_pet_working = Mock()
                window._rotation_time_fields[1].set('17')
                window._start_worker([])
                thread.return_value.start.assert_called_once()
                self.assertEqual(window._rotation_run_store['presets'][0]['slot_times']['1'], 17)
                self.assertEqual(load_store(app.COMBAT_PRESETS_CONFIG)['presets'][0]['slot_times']['1'], 17)
                window._rotation_time_fields[1].set('22')
                window._rotation_commit_time(1)
                self.assertEqual(window._rotation_run_store['presets'][0]['slot_times']['1'], 17)
        finally:
            root.destroy()

    def test_idle_worker_stops_at_deadline_without_main_loop_tick(self):
        controller = Mock()
        stop = threading.Event()
        worker = IdleAttackWorker(controller, stop, threading.Lock(), attack_interval=.01)
        try:
            module = new_module('idle_attack')
            module['value'] = 100
            worker.arm(module, time.monotonic()+.08)
            time.sleep(.14)
            count = controller.left_click.call_count
            self.assertGreaterEqual(count, 3)
            time.sleep(.05)
            self.assertEqual(controller.left_click.call_count, count)
        finally:
            worker.close()
        self.assertFalse(worker.thread.is_alive())

    def test_idle_worker_pause_waits_for_heavy_release_and_suspends_clicks(self):
        controller = Mock()
        entered, released, paused = threading.Event(), threading.Event(), threading.Event()
        controller.hold_left_button.side_effect = lambda _: (entered.set(), released.wait(2))
        worker = IdleAttackWorker(controller, threading.Event(), threading.Lock(), attack_interval=.01)
        pause_thread = None
        try:
            module = new_module('idle_attack')
            module['value'] = 1
            worker.arm(module, time.monotonic()+2)
            self.assertTrue(entered.wait(1))
            pause_thread = threading.Thread(target=lambda: (worker.pause(), paused.set()))
            pause_thread.start()
            self.assertFalse(paused.wait(.03))
            released.set()
            self.assertTrue(paused.wait(1))
            count = controller.left_click.call_count
            time.sleep(.04)
            self.assertEqual(controller.left_click.call_count, count)
        finally:
            released.set()
            worker.close()
            if pause_thread:
                pause_thread.join(1)

    def test_idle_worker_errors_stop_battle_and_are_not_silent(self):
        controller = Mock()
        controller.left_click.side_effect = RuntimeError('input failed')
        stop = threading.Event()
        errors = []
        worker = IdleAttackWorker(controller, stop, threading.Lock(), on_error=errors.append)
        try:
            worker.arm(new_module('idle_attack'), time.monotonic()+1)
            self.assertTrue(stop.wait(1))
        finally:
            worker.close()
        self.assertIsInstance(worker.error, RuntimeError)
        self.assertEqual(errors, [worker.error])

    def test_both_battles_keep_clicking_during_slow_screenshot(self):
        for mode in ('combat_4c', 'daily'):
            with self.subTest(mode=mode):
                controller = Mock()
                click_times, capture_span = [], []
                controller.left_click.side_effect = lambda: click_times.append(time.monotonic())
                idle = new_module('idle_attack')
                idle['value'] = 100
                runner = app.TaskRunner(controller, lambda _: None, dry_run=False,
                                        rotation_presets={mode: [idle]})
                runner.MAIN_ATTACK_CLICK_INTERVAL = .015
                runner.BOSS_HEADER_CHECK_INTERVAL = .045
                runner.DAILY_BATTLE_END_CHECK_INTERVAL = .045
                runner._select_daily_slot_one_after_loading = Mock()
                runner._sleep_interruptible = lambda duration: time.sleep(min(duration, .025))
                count = [0]
                def inspect(*_args, **_kwargs):
                    count[0] += 1
                    if count[0] == 2:
                        capture_span.append(time.monotonic())
                        time.sleep(.25)  # main battle thread blocked by recognition
                        capture_span.append(time.monotonic())
                        runner.stop_event.set()
                    return True
                if mode == 'combat_4c':
                    runner._inspect_4c_boss_header = inspect
                    runner._run_4c_battle(Mock(timeout=30), 'E', 'R', 1)
                else:
                    runner._capture_for_matching = inspect
                    runner._daily_reward_stage_present = Mock(return_value=False)
                    runner._daily_battle_task_present = Mock(return_value=True)
                    runner._run_daily_battle(Mock(timeout=180), 'E', 'R', 1)
                self.assertEqual(len(capture_span), 2)
                during = [t for t in click_times if capture_span[0] < t < capture_span[1]]
                self.assertGreaterEqual(len(during), 5)
                self.assertIsNone(runner._rotation_idle_worker)
                count = len(click_times)
                time.sleep(.035)
                self.assertEqual(len(click_times), count)


    def test_finite_jump_attacks_switching_and_skills_continue_during_slow_capture(self):
        for mode in ('combat_4c', 'daily'):
            with self.subTest(mode=mode):
                controller = Mock()
                events, capture_span = [], []
                controller.left_click.side_effect = lambda: events.append((time.monotonic(), 'click'))
                controller.press_key.side_effect = lambda key, _: events.append((time.monotonic(), key))
                controller.press_binding.side_effect = lambda key, _: events.append((time.monotonic(), key))
                jump, skill, idle = new_module('jump_attack'), new_module('skill', 2), new_module('idle_attack', 2)
                idle['value'] = 100
                runner = app.TaskRunner(controller, lambda _: None, dry_run=False,
                    rotation_presets={mode: [jump, skill, idle]},
                    rotation_times={mode: {'1': .24, '2': .5, '3': .24}})
                runner.MAIN_ATTACK_CLICK_INTERVAL = .015
                runner.BOSS_HEADER_CHECK_INTERVAL = .015
                runner.DAILY_BATTLE_END_CHECK_INTERVAL = .015
                runner._select_daily_slot_one_after_loading = Mock()
                runner._sleep_interruptible = lambda duration: time.sleep(min(duration, .002))
                calls = [0]
                def inspect(*_args, **_kwargs):
                    calls[0] += 1
                    if calls[0] == 2:
                        capture_span.append(time.monotonic())
                        time.sleep(.45)
                        capture_span.append(time.monotonic())
                        runner.stop_event.set()
                    return True
                if mode == 'combat_4c':
                    runner._inspect_4c_boss_header = inspect
                    runner._run_4c_battle(Mock(timeout=30), 'E', 'R', 1)
                else:
                    runner._capture_for_matching = inspect
                    runner._daily_reward_stage_present = Mock(return_value=False)
                    runner._daily_battle_task_present = Mock(return_value=True)
                    runner._run_daily_battle(Mock(timeout=180), 'E', 'R', 1)
                during = [key for tick, key in events if capture_span[0] < tick < capture_span[1]]
                self.assertGreaterEqual(during.count('click'), 2)
                self.assertIn('2', during)
                self.assertIn('E', during)
                self.assertIsNone(runner._rotation_idle_worker)

    def test_monitor_pause_drains_capture_and_discards_stale_results(self):
        entered, release, paused = threading.Event(), threading.Event(), threading.Event()
        inspect = Mock(side_effect=lambda: (entered.set(), release.wait(1), True)[-1])
        monitor = BattleMonitor(inspect, False, threading.Event())
        thread = None
        try:
            self.assertEqual(monitor.poll(), (False,))
            monitor.request()
            self.assertTrue(entered.wait(1))
            for _ in range(5):
                monitor.request()
            thread = threading.Thread(target=lambda: (monitor.pause(), paused.set()))
            thread.start()
            self.assertFalse(paused.wait(.03))
            release.set()
            self.assertTrue(paused.wait(1))
            self.assertIsNone(monitor.poll())
            self.assertEqual(inspect.call_count, 1)
            monitor.resume()
            monitor.request()
            limit = time.monotonic()+1
            checked = None
            while checked is None and time.monotonic() < limit:
                time.sleep(.005)
                checked = monitor.poll()
            self.assertEqual(checked, (True,))
        finally:
            release.set()
            monitor.close()
            if thread:
                thread.join(1)
        self.assertFalse(monitor.thread.is_alive())

    def test_monitor_error_stops_and_propagates_from_both_battles(self):
        for mode in ('combat_4c', 'daily'):
            with self.subTest(mode=mode):
                runner = app.TaskRunner(Mock(), lambda _: None, dry_run=False,
                                        rotation_presets={mode: [new_module('idle_attack')]})
                runner.BOSS_HEADER_CHECK_INTERVAL = .01
                runner.DAILY_BATTLE_END_CHECK_INTERVAL = .01
                runner._sleep_interruptible = lambda duration: time.sleep(min(duration, .002))
                runner._select_daily_slot_one_after_loading = Mock()
                inspect = Mock(side_effect=[True, RuntimeError('capture failed')])
                if mode == 'combat_4c':
                    runner._inspect_4c_boss_header = inspect
                    run = runner._run_4c_battle
                else:
                    runner._capture_for_matching = inspect
                    runner._daily_reward_stage_present = Mock(return_value=False)
                    runner._daily_battle_task_present = Mock(return_value=True)
                    run = runner._run_daily_battle
                with self.assertRaisesRegex(RuntimeError, 'capture failed'):
                    run(Mock(timeout=30), 'E', 'R', 1)
                self.assertIsNone(runner._rotation_idle_worker)

    def test_explicit_wait_replaces_duplicate_settle_delay_and_idle_resumes_after_wait(self):
        skill, wait, idle = new_module('echo'), new_module('wait'), new_module('idle_attack')
        wait['value'] = .8
        clock = self.clock([skill, wait, idle], 5)
        runner = app.TaskRunner(Mock(), lambda _: None)
        runner._sleep_interruptible = Mock()
        clock.next_action(0)
        action = clock.next_action(.1)
        with patch.object(app.time, 'monotonic', return_value=.1):
            runner._run_rotation_action(action, clock, 'E', 'R', threading.Event(), threading.Lock())
        runner._sleep_interruptible.assert_not_called()
        self.assertEqual(clock.next_action(.2)['kind'], 'wait')
        self.assertIsNone(clock.next_action(.5))
        self.assertEqual(clock.next_action(1.01)['kind'], 'left_click')

    def test_beta7_default_upgrade_preserves_ids_but_custom_waits_are_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'combat.json'
            old = default_store()
            modules = old['presets'][0]['modules']
            modules.pop()
            modules[5]['value'] = 2
            ids = [m['id'] for m in modules]
            save_store(path, old)
            upgraded = load_store(path)
            result = upgraded['presets'][0]['modules']
            self.assertEqual([m['id'] for m in result[:-1]], ids)
            self.assertEqual(result[5]['value'], .35)
            self.assertEqual((result[-1]['kind'], result[-1]['slot']), ('idle_attack', 3))
            modules[5]['value'] = 3
            save_store(path, old)
            self.assertEqual(load_store(path), validate_store(old))


if __name__ == '__main__':
    unittest.main()
