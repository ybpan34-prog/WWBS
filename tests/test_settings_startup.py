from contextlib import ExitStack
import json
from pathlib import Path
import tempfile
import time
import tkinter as tk
import unittest
from unittest.mock import patch

from PIL import ImageGrab

import app
from combat_rotation import default_store
from local_settings import Installation, apply_import, prepare_import, save_import_receipt, settings_files
from ui_controls import show_ready_main_window
from ui_controls import RoundedButton


class SettingsStartupTests(unittest.TestCase):
    def test_settings_button_mouse_click_opens_import_confirmation(self):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as patches:
            base = Path(directory)
            source, target = base/'old', base/'current'
            source.mkdir()
            target.mkdir()
            (source/'theme-settings.json').write_text('{"theme":"cartethyia"}')
            installation = Installation(source, '1.5.4 beta3', settings_files(source))
            patches.enter_context(patch.object(app, 'USER_SETTINGS_DIR', target))
            for constant in ('THEME_CONFIG', 'COMBAT_CONFIG', 'PET_CONFIG', 'PET_DISPLAY_CONFIG',
                    'COMBAT_PRESETS_CONFIG', 'DAILY_CONFIG', 'APP_SETTINGS_CONFIG', 'UI_CONFIG',
                    'CARTETHYIA_AGENT_CONFIG', 'CONNECTION_CONFIG'):
                patches.enter_context(patch.object(app, constant, target/(constant+'.json')))
            for method in ('_load_config', '_start_stop_hotkey', '_start_desktop_pet',
                           '_scan_local_models', '_show_startup_notice_once'):
                patches.enter_context(patch.object(app.App, method))
            patches.enter_context(patch.object(app, 'discover_latest', return_value=installation))
            root = tk.Tk()
            errors = []
            root.report_callback_exception = lambda *args: errors.append(args)
            try:
                ui = app.App(root)
                ui._select_top_tab(4)
                root.update()
                def walk(widget):
                    yield widget
                    for child in widget.winfo_children():
                        yield from walk(child)
                button = next(w for w in walk(ui.settings_tab) if isinstance(w, RoundedButton)
                              and w.cget('text') == '检测本地设置')
                self.assertTrue(button.winfo_ismapped())
                button.event_generate('<ButtonPress-1>', x=30, y=15)
                button.event_generate('<ButtonRelease-1>', x=30, y=15)
                self.assertTrue(ui._settings_progress_window.winfo_exists())
                deadline = time.monotonic()+2.5
                def wait_for_confirmation():
                    window = getattr(ui, '_settings_import_window', None)
                    if window is not None and window.winfo_ismapped():
                        root.quit()
                    elif time.monotonic() >= deadline:
                        root.quit()
                    else:
                        root.after(20, wait_for_confirmation)
                root.after(20, wait_for_confirmation)
                root.mainloop()
                self.assertEqual(errors, [])
                self.assertFalse(ui._settings_scan_running)
                self.assertIsNone(ui._settings_progress_window)
                self.assertTrue(ui._settings_import_window.winfo_ismapped())
                self.assertIn('找到', ui.local_settings_status.get())
                self.assertFalse((target/'theme-settings.json').exists())
            finally:
                root.destroy()

    def test_real_ui_loaders_use_imported_keys_theme_and_axis_after_restart(self):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as patches:
            base = Path(directory)
            source, target = base/'old', base/'current'
            (source/'_internal').mkdir(parents=True)
            target.mkdir()
            axis = default_store()
            axis['presets'][0]['name'] = '我的排轴'
            axis['presets'][0]['slot_order'] = [3, 2, 1]
            values = {'theme-settings.json': {'theme': 'cartethyia'},
                      'combat-settings.json': {'skill_key': 'XBUTTON2', 'ultimate_key': 'XBUTTON1'},
                      'combat-presets.json': axis, 'pet-settings.json': {'pet': 'cartethyia'},
                      'pet-display-settings.json': {'percent': 85, 'visible': False}}
            values['rain-settings.json'] = {'mode': '持续下雨', 'level': '大雨', 'strength': '明显', 'volume': 50}
            values['connection-settings.json'] = {'target_mode': 'adb', 'window_title': '失效旧窗口',
                                                  'expected_resolution': 'bad', 'adb_path': 'adb'}
            for name, value in values.items():
                (source/'_internal'/name).write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
            plan = prepare_import(Installation(source, '1.5.4 beta3', settings_files(source)), target)
            apply_import(plan, target)
            save_import_receipt(plan, target)
            patches.enter_context(patch.object(app, 'USER_SETTINGS_DIR', target))
            for constant, name in {'THEME_CONFIG': 'theme-settings.json', 'COMBAT_CONFIG': 'combat-settings.json',
                    'PET_CONFIG': 'pet-settings.json', 'PET_DISPLAY_CONFIG': 'pet-display-settings.json',
                    'COMBAT_PRESETS_CONFIG': 'combat-presets.json', 'DAILY_CONFIG': 'daily-settings.json',
                    'APP_SETTINGS_CONFIG': 'app-settings.json', 'UI_CONFIG': 'ui-settings.json',
                    'CARTETHYIA_AGENT_CONFIG': 'cartethyia-agent-settings.json',
                    'CONNECTION_CONFIG': 'connection-settings.json', 'RAIN_CONFIG': 'rain-settings.json'}.items():
                patches.enter_context(patch.object(app, constant, target/name))
            for method in ('_load_config', '_start_stop_hotkey', '_start_desktop_pet',
                           '_scan_local_models', '_show_startup_notice_once'):
                patches.enter_context(patch.object(app.App, method))
            root = tk.Tk()
            root.withdraw()
            try:
                ui = app.App(root)
                self.assertFalse(root.winfo_ismapped())
                self.assertEqual(ui.target_mode.get(), 'client')
                self.assertEqual(ui.window_title.get(), '自动')
                self.assertEqual(ui._parse_resolution(), (1920, 1080))
                with patch.object(app, 'ClientWindowController') as controller:
                    ui._make_controller()
                    controller.assert_called_once_with('自动', (1920, 1080))
                def labels(widget):
                    try:
                        yield str(widget.cget('text'))
                    except tk.TclError:
                        pass
                    for child in widget.winfo_children():
                        yield from labels(child)
                texts = set(labels(ui.settings_tab))
                self.assertFalse(texts & {'操作目标', '窗口标题', '模板基准', '模拟器 / ADB'})
                self.assertIn('检查 HDR 与识别环境', texts)
                self.assertEqual(ui.theme_id, 'cartethyia')
                self.assertEqual(ui.combat_skill_key.get(), app.App._combat_binding_display('XBUTTON2'))
                self.assertEqual(ui.combat_ultimate_key.get(), app.App._combat_binding_display('XBUTTON1'))
                self.assertEqual(ui.pet_id, 'cartethyia')
                self.assertEqual(ui.pet_size.get(), '85%')
                self.assertEqual(ui.rain_mode.get(), '关闭')
                self.assertEqual(ui.rain_level.get(), '大雨')
                self.assertEqual(ui.rain_strength.get(), '明显')
                self.assertEqual(ui.rain_volume.get(), '50%')
                self.assertIsNone(ui.rain_overlay)
                self.assertIsNone(ui._boss_rain_watcher)
                self.assertFalse(ui.rain_music.playing)
                self.assertEqual(ui.rotation_store['presets'][0]['name'], '我的排轴')
                self.assertEqual(ui.rotation_store['presets'][0]['slot_order'], [3, 2, 1])
                self.assertEqual(ui._settings_import_receipt['failed'], [])
                exposed = []
                real_show = root.deiconify
                def show():
                    exposed.append(root.attributes('-alpha'))
                    real_show()
                ready = []
                root.attributes('-topmost', True)
                def record_first_frame():
                    x, y = root.winfo_rootx(), root.winfo_rooty()
                    frame = ImageGrab.grab((x, y, x+root.winfo_width(), y+root.winfo_height()))
                    black_pixels = frame.convert('L').histogram()[0]
                    ready.append(black_pixels < frame.width*frame.height*.15)
                with patch.object(root, 'deiconify', side_effect=show), \
                        patch.object(root, 'attributes', wraps=root.attributes) as attributes:
                    show_ready_main_window(root, record_first_frame)
                    self.assertFalse(any(call.args[:1] == ('-alpha',) and len(call.args) > 1
                                         for call in attributes.call_args_list))
                root.after(80, root.quit)
                root.mainloop()
                self.assertTrue(root.winfo_ismapped())
                self.assertTrue(exposed)
                self.assertEqual(exposed[0], 1.0)
                self.assertEqual(root.attributes('-alpha'), 1.0)
                self.assertEqual(ready, [True])
                self.assertTrue(all(canvas.find_all() for canvas, _title in ui._nav_buttons))
            finally:
                root.destroy()


if __name__ == '__main__':
    unittest.main()
