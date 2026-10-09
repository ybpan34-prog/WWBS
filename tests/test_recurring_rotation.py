import tempfile
import threading
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import app
from combat_rotation import RotationClock, default_store, new_module, validate_store


class RecurringRotationTests(unittest.TestCase):
    def test_all_timed_casts_repeat_in_one_visit_in_order_then_stop_at_deadline(self):
        modules = [new_module(kind) for kind in ('idle_attack','skill','ultimate','echo')]
        clock = RotationClock(modules+[new_module('wait',3)],0,
                              slot_times={'1':25,'2':15,'3':5},background_idle=True)
        casts=[]
        for tick in range(500):
            now=tick*.05
            action=clock.next_action(now)
            if action and action['kind'] in ('skill','ultimate','echo'):
                casts.append((now,action['kind']))
        self.assertEqual([kind for _,kind in casts[:3]],['skill','ultimate','echo'])
        for kind,interval,count in (('skill',5,5),('ultimate',15,2),('echo',20,2)):
            times=[now for now,k in casts if k==kind]
            self.assertEqual(len(times),count)
            self.assertTrue(all(b-a>=interval-.00001 for a,b in zip(times,times[1:])))
        self.assertEqual(clock.next_action(25)['module']['slot'],3)

    def test_finite_attacks_and_waits_do_not_repeat_with_timed_casts(self):
        attack,wait,skill,idle=[new_module(k) for k in ('attack_count','wait','skill','idle_attack')]
        attack['value']=2
        wait['value']=.2
        clock=RotationClock([attack,wait,skill,idle],0,slot_times={'1':20},background_idle=True)
        actions=[clock.next_action(tick*.05) for tick in range(400)]
        kinds=[action['kind'] for action in actions if action]
        self.assertEqual(kinds.count('left_click'),2)
        self.assertEqual(kinds.count('wait'),1)
        self.assertEqual(kinds.count('skill'),4)
        self.assertIn('idle_attack',kinds)

    def test_overdue_casts_fire_once_after_return_without_catching_up(self):
        skill=new_module('skill')
        clock=RotationClock([skill,new_module('wait',3)],0,slot_times={'1':25,'3':5})
        clock.next_action(0)
        clock.next_action(.1)
        clock.next_action(25)
        clock.next_action(30)
        self.assertEqual(clock.next_action(30.1)['kind'],'skill')
        self.assertIsNone(clock.next_action(30.2))
        self.assertEqual(clock.next_action(35.1)['kind'],'skill')

    def test_legacy_cast_counts_migrate_and_send_only_one_press(self):
        for kind in ('skill','ultimate','echo'):
            with self.subTest(kind=kind):
                store=default_store()
                item=next(m for m in store['presets'][0]['modules'] if m['kind']==kind)
                item['value']=5
                checked=validate_store(store)
                self.assertEqual(next(m for m in checked['presets'][0]['modules'] if m['id']==item['id'])['value'],1)
                runner=app.TaskRunner(Mock(),lambda _: None)
                runner._sleep_interruptible=Mock()
                runner._cast_timed_ultimate=Mock()
                clock=RotationClock([item],0,slot_times={'1':25})
                clock.next_action(0)
                action=clock.next_action(.1)
                with patch.object(app.time,'monotonic',return_value=.1):
                    runner._run_rotation_action(action,clock,'E','R',threading.Event(),threading.Lock())
                if kind=='skill':
                    runner.controller.press_binding.assert_called_once_with('E',65)
                elif kind=='ultimate':
                    runner._cast_timed_ultimate.assert_called_once()
                else:
                    runner.controller.press_key.assert_called_once_with('Q',120)

    def test_maximized_rotation_lists_fill_viewport_and_shrink_remains_scrollable(self):
        root=tk.Tk()
        try:
            ui=app.App.__new__(app.App)
            ui.root=root
            ui.rotation_store=default_store()
            ui.rotation_choice=tk.StringVar()
            shell=tk.Frame(root)
            shell.pack(fill=tk.BOTH,expand=True)
            ui.rotation_tab,ui.rotation_scroll_canvas=ui._create_scrollable_tab(shell,stretch=True)
            with tempfile.TemporaryDirectory() as tmp, patch.object(app,'COMBAT_PRESETS_CONFIG',Path(tmp)/'combat.json'):
                ui._build_rotation_tab()
                for width,height in ((900,600),(1900,1200),(900,600)):
                    root.geometry(f'{width}x{height}')
                    root.update()
                    outer=ui.rotation_scroll_canvas
                    content=ui.rotation_tab
                    self.assertGreaterEqual(content.winfo_height(),outer.winfo_height())
                    for column in ui._rotation_columns.values():
                        canvas=column['canvas']
                        bottom=canvas.winfo_rooty()+canvas.winfo_height()
                        # Outer page padding plus the new rounded role border.
                        self.assertLess(content.winfo_rooty()+content.winfo_height()-bottom,32)
                    if height==600:
                        self.assertLess(outer.yview()[1]-outer.yview()[0],1)
        finally:
            root.destroy()


if __name__=='__main__':
    unittest.main()
