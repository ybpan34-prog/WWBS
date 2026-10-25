from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import app
from combat_rotation import default_store
import local_settings as settings


class LocalSettingsTests(unittest.TestCase):
    def installation(self, parent, folder, version, values):
        root = parent/folder
        (root/'_internal').mkdir(parents=True)
        (root/'wwbs.exe').write_bytes(b'fixture')
        (root/'_internal'/'wwbs-version.json').write_text(json.dumps({'version': version}))
        for name, value in values.items():
            (root/'_internal'/name).write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
        return root

    def test_same_version_other_directory_is_available_but_current_is_excluded(self):
        with tempfile.TemporaryDirectory() as directory:
            parent=Path(directory)
            current=self.installation(parent,'current','1.5.4',{'pet-settings.json':{'pet':'daniya'}})
            same=self.installation(parent,'same','1.5.4',{'pet-settings.json':{'pet':'aemeath'}})
            self.installation(parent,'old','1.5.4 beta3',{'pet-settings.json':{'pet':'daniya'}})
            self.installation(parent,'newer','1.5.4 beta4',{'pet-settings.json':{'pet':'cartethyia'}})
            result=settings.discover_latest(current,'1.5.4',[parent])
            self.assertEqual(result.root,same.resolve())

    def test_noop_preview_ignores_json_format_and_reports_missing_files(self):
        source = settings.Installation(Path('old'), '1.5.5', {})
        plan = settings.ImportPlan(source, {'combat-settings.json': b'{"skill_key":"E"}'},
                                   {'combat-settings.json': b'{ "skill_key": "E" }'})
        self.assertEqual(settings.changed_settings(plan), [])
        changed = settings.ImportPlan(source, plan.payloads, {'combat-settings.json': None})
        self.assertEqual(settings.changed_settings(changed), ['combat-settings.json'])

    def test_current_installation_alias_and_generated_roots_are_never_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            current = self.installation(parent, 'current', '1.5.6', {'combat-settings.json': {'skill_key': 'E'}})
            generated = parent/'_release-work'
            self.installation(generated, 'wwbs-v1.5.6-build2-smoke', '9.9.9', {'rain-settings.json': {'mode': '持续下雨'}})
            self.installation(parent, 'other-smoke', '9.9.9', {'combat-settings.json': {'skill_key': 'T'}})
            real = self.installation(parent, 'used-same-version', '1.5.6', {'combat-settings.json': {'skill_key': 'Q'}})
            found = []
            source = settings.discover_latest(current, '1.5.6', [current, generated, parent], sources=found.extend)
            self.assertEqual(source.root, real.resolve())
            self.assertEqual([s.root for s in found], [real.resolve()])
            self.assertTrue(settings.excluded_settings_source(current/'..'/'current', current))
            self.assertTrue(settings.excluded_settings_source(generated, current))

    def test_embedded_executable_version_beats_stale_readme(self):
        root=Path('_release-work/wwbs-v1.5.4-beta4/wwbs')
        if not (root/'wwbs.exe').exists():
            self.skipTest('local release fixture is optional')
        self.assertEqual(settings.installation_version(root),'1.5.4 beta4')

    def test_newest_version_without_settings_is_not_a_source(self):
        with tempfile.TemporaryDirectory() as directory:
            parent=Path(directory)
            self.installation(parent,'no-settings','1.8.0',{})
            old=self.installation(parent,'with-settings','1.5.3',{'theme-settings.json':{'theme':'jingran'}})
            result=settings.discover_latest(parent/'current','1.5.4',[parent])
            self.assertEqual(result.root,old.resolve())
            self.assertIsNone(settings.discover_latest(parent/'current','1.5.4',[parent],cancelled=lambda:True))

    def test_fresh_newer_zip_does_not_hide_real_older_user_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            self.installation(parent, 'fresh-beta4', '1.5.4 beta4', {'weekly_tasks.json': {'tasks': []}})
            used = self.installation(parent, 'used-beta3', '1.5.4 beta3', {
                'theme-settings.json': {'theme': 'cartethyia'},
                'combat-settings.json': {'skill_key': 'XBUTTON2', 'ultimate_key': 'XBUTTON1'},
                'combat-presets.json': default_store()})
            source = settings.discover_latest(parent/'current', '1.5.4', [parent])
            self.assertEqual(source.root, used.resolve())
            target = parent/'current'
            plan = settings.prepare_import(source, target)
            settings.apply_import(plan, target)
            settings.save_import_receipt(plan, target)
            result = settings.verify_import_receipt(target)
            self.assertEqual(result['failed'], [])
            self.assertEqual(len(result['hashes']), 3)
            self.assertIsNone(settings.verify_import_receipt(target))
            self.assertIn('XBUTTON2', settings.describe_import(plan))
            self.assertIn('cartethyia', settings.describe_import(plan))

    def test_restart_verification_reports_changed_imported_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            source = settings.Installation(target/'old', '1.5.4 beta3', {})
            plan = settings.ImportPlan(source, {'theme-settings.json': b'{"theme":"cartethyia"}'}, {})
            settings.save_import_receipt(plan, target)
            (target/'theme-settings.json').write_text('{"theme":"simple"}')
            self.assertEqual(settings.verify_import_receipt(target)['failed'], ['程序主题'])

    def test_same_version_repair_is_compared_using_package_revision(self):
        with patch.object(app, 'APP_VERSION', '1.5.4'), patch.object(app, 'APP_BUILD', 1):
            self.assertTrue(app.App._release_is_newer('v1.5.4', {'body': '<!-- WWBS_BUILD:2 -->'}))
            self.assertFalse(app.App._release_is_newer('v1.5.4', {'body': ''}))
        with patch.object(app, 'APP_VERSION', '1.5.4'), patch.object(app, 'APP_BUILD', 4):
            self.assertFalse(app.App._release_is_newer('v1.5.4', {'body': '<!-- WWBS_BUILD:2 -->'}))
        self.assertFalse(app.App._release_is_newer('v1.5.3', {'body': '<!-- WWBS_BUILD:999 -->'}))

    def test_plan_is_read_only_and_apply_carries_theme_keys_axis_and_modes(self):
        with tempfile.TemporaryDirectory() as directory:
            parent=Path(directory)
            target=parent/'target'
            target.mkdir()
            axis=default_store()
            axis['presets'][0]['name']='自己的轴'
            axis['presets'][0]['slot_order']=[3,2,1]
            values={'theme-settings.json':{'theme':'cartethyia'},
                    'combat-settings.json':{'skill_key':'XBUTTON2','ultimate_key':'XBUTTON1'},
                    'combat-presets.json':axis,'pet-display-settings.json':{'percent':'85%','visible':False}}
            original=deepcopy(values)
            source_root=self.installation(parent,'old','1.5.4 beta4',values)
            source=settings.Installation(source_root,'1.5.4 beta4',settings.settings_files(source_root))
            plan=settings.prepare_import(source,target)
            self.assertEqual(list(target.iterdir()),[])
            self.assertEqual(values,original)
            settings.apply_import(plan,target)
            theme=json.loads((target/'theme-settings.json').read_text())
            self.assertEqual(theme,{'theme':'cartethyia','explicit':True,'source':'theme-picker'})
            imported=json.loads((target/'combat-presets.json').read_text(encoding='utf-8'))
            self.assertEqual(imported['presets'][0]['slot_order'],[3,2,1])
            self.assertEqual(imported['modes'],axis['modes'])
            self.assertEqual(json.loads((target/'pet-display-settings.json').read_text())['percent'],85)

    def test_changed_target_after_preview_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            target=root/'target'
            target.mkdir()
            source_root=self.installation(root,'source','1.5.3',{'theme-settings.json':{'theme':'simple'}})
            plan=settings.prepare_import(settings.Installation(source_root,'1.5.3',settings.settings_files(source_root)),target)
            (target/'theme-settings.json').write_text('changed')
            with self.assertRaisesRegex(ValueError,'已改变'):
                settings.apply_import(plan,target)
            self.assertEqual((target/'theme-settings.json').read_text(),'changed')

    def test_corrupt_settings_abort_before_any_target_write(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            source_root=self.installation(root,'source','1.5.3',{'combat-presets.json':{'presets':[]},
                                                                 'theme-settings.json':{'theme':'simple'}})
            target=root/'target'
            with self.assertRaises(ValueError):
                settings.prepare_import(settings.Installation(source_root,'1.5.3',settings.settings_files(source_root)),target)
            self.assertFalse(target.exists())

    def test_write_failure_restores_original_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            source_root=self.installation(root,'source','1.5.3',{'theme-settings.json':{'theme':'simple'},
                                                             'pet-settings.json':{'pet':'daniya'}})
            target=root/'target'
            target.mkdir()
            (target/'theme-settings.json').write_text('original')
            plan=settings.prepare_import(settings.Installation(source_root,'1.5.3',settings.settings_files(source_root)),target)
            real=settings.os.replace
            calls=[0]
            def replace(source,destination):
                calls[0]+=1
                if calls[0]==2:
                    raise OSError('fixture failure')
                return real(source,destination)
            with patch.object(settings.os,'replace',side_effect=replace),self.assertRaises(OSError):
                settings.apply_import(plan,target)
            self.assertEqual((target/'theme-settings.json').read_text(),'original')
            self.assertFalse((target/'pet-settings.json').exists())

    def test_update_snapshot_includes_internal_settings_without_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            old=self.installation(root,'old','1.5.3',{'theme-settings.json':{'theme':'jingran'},
                    'cartethyia-agent-settings.json':{'model':'local','api_key':'secret'}})
            settings.snapshot_settings(old,root/'snapshot')
            data=json.loads((root/'snapshot'/'cartethyia-agent-settings.json').read_text())
            self.assertNotIn('api_key',data)
            self.assertEqual(data['model'],'local')

    def test_old_updater_backup_bootstraps_all_preferences_into_executable_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            bundled=root/'_internal'
            bundled.mkdir()
            backup=root/'.wwbs-update-backup-fixture'
            old=backup/'_internal'
            old.mkdir(parents=True)
            for name,value in {'theme-settings.json':{'theme':'aemeath'},
                               'pet-display-settings.json':{'percent':85},
                               'weekly_tasks.json':{'tasks':[]}}.items():
                (old/name).write_text(json.dumps(value))
            settings.bootstrap_own_settings(root,bundled)
            self.assertTrue((root/'weekly_tasks.json').exists())
            self.assertEqual(json.loads((root/'theme-settings.json').read_text())['theme'],'aemeath')
            (old/'pet-display-settings.json').write_text('{"percent":115}')
            settings.bootstrap_own_settings(root,bundled)
            self.assertEqual(json.loads((root/'pet-display-settings.json').read_text())['percent'],85)

    def test_confirmation_applies_keys_live_and_old_callbacks_cannot_overwrite_them(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root/'current'
            target.mkdir()
            keyfile = target/'combat-settings.json'
            keyfile.write_text('{"skill_key":"E","ultimate_key":"R"}')
            old = self.installation(root, 'old', '1.5.5', {'combat-settings.json': {'skill_key': 'XBUTTON2', 'ultimate_key': 'XBUTTON1'}})
            plan = settings.prepare_import(settings.Installation(old, '1.5.5', settings.settings_files(old)), target)
            ui = app.App.__new__(app.App)
            ui.root, ui.status, ui.worker = Mock(), Mock(), None
            ui.combat_skill_key, ui.combat_ultimate_key = Mock(), Mock()
            ui._log = Mock()
            ui._rotation_seed_window = Mock(return_value=(Mock(), Mock(), Mock()))
            commands = {}
            def button(_parent, *, text, command, **options):
                commands[text] = command
                return Mock()
            ui._ui_button = button
            # Simulate queued old-window autosave during close/restart.
            ui._restart_app = ui._save_combat_settings
            with patch.object(app, 'USER_SETTINGS_DIR', target), patch.object(app, 'COMBAT_CONFIG', keyfile), \
                    patch.object(app, 'Label', return_value=Mock()):
                ui._offer_local_settings(plan, False)
                commands['确认继承并重启']()
            self.assertEqual(json.loads(keyfile.read_text()), {'skill_key': 'XBUTTON2', 'ultimate_key': 'XBUTTON1'})
            ui.combat_skill_key.set.assert_called_with('鼠标侧键2')
            ui.combat_ultimate_key.set.assert_called_with('鼠标侧键1')
            self.assertEqual(settings.verify_import_receipt(target)['failed'], [])

    def test_identical_import_does_not_write_or_restart(self):
        ui = app.App.__new__(app.App)
        ui.root, ui.status, ui.worker = Mock(), Mock(), None
        ui._rotation_seed_window = Mock(return_value=(Mock(), Mock(), Mock()))
        ui._restart_app = Mock()
        commands = {}
        def button(_parent, *, text, command, **_options):
            commands[text] = command
            return Mock()
        ui._ui_button = button
        source = settings.Installation(Path('old'), '1.5.5', {})
        plan = settings.ImportPlan(source, {'theme-settings.json': b'{"theme":"simple"}'},
                                   {'theme-settings.json': b'{"theme":"simple"}'})
        with patch.object(app, 'apply_import') as apply, patch.object(app, 'Label', return_value=Mock()), \
                patch.object(app.messagebox, 'showinfo') as info:
            ui._offer_local_settings(plan, False)
            commands['确认继承并重启']()
            apply.assert_not_called()
            ui._restart_app.assert_not_called()
            info.assert_called_once()
        self.assertIn('选择其他文件夹', commands)

    def test_cancel_confirmation_never_calls_apply(self):
        ui=app.App.__new__(app.App)
        ui.root,ui.status,ui.worker=Mock(),Mock(),None
        ui._rotation_seed_window=Mock(return_value=(Mock(),Mock(),Mock()))
        commands={}
        def button(_parent,*,text,command,**_options):
            commands[text]=command
            return Mock()
        ui._ui_button=button
        source=settings.Installation(Path('fixture'),'1.5.3',{})
        plan=settings.ImportPlan(source,{'theme-settings.json':b'{}'},{'theme-settings.json':None})
        with patch.object(app,'apply_import') as apply, patch.object(app,'Label',return_value=Mock()):
            ui._offer_local_settings(plan,False)
            commands['取消']()
            apply.assert_not_called()
        ui._rotation_seed_window.assert_called_once()
        self.assertIn('执行后无法撤回',ui._rotation_seed_window.call_args.args[1])


if __name__=='__main__':
    unittest.main()
