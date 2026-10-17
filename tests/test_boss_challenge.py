import json
from pathlib import Path
import os
import shutil
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from PIL import Image, ImageDraw

import app
from tasks.combat_4c_entrance import BOSS_AVATARS, BossChallengeEntrance, EntranceFrame
from windows_client import ClientWindowController
from windows_ocr import WindowsOcr


def make_frame(*labels, selected=None, battle=False):
    image = Image.new('RGB',(1920,1080),(35,45,50))
    lines=[]
    for text,x,y in labels:
        width=max(30,len(text)*19)
        if selected == text:
            ImageDraw.Draw(image).rectangle((x-55,y-8,x+width+55,y+34),fill=(220,220,220))
        lines.append({'words':[{'text':text,'x':x,'y':y,'width':width,'height':25}]})
    return EntranceFrame(image,lines,battle)


class EntranceTests(unittest.TestCase):
    def test_delayed_pages_and_missed_clicks_do_not_advance_without_confirmation(self):
        target=list(BOSS_AVATARS)[1]
        frames={
            'world':make_frame(),
            'guide':make_frame(('索拉指南',100,60)),
            'category':make_frame(('讨伐强敌',100,60),('战歌重奏',210,640)),
            'list':make_frame(('讨伐强敌',100,60),('战歌重奏',210,640),
                             (list(BOSS_AVATARS)[0],750,420),('直接挑战',1600,420)),
            'target':make_frame(('讨伐强敌',100,60),('战歌重奏',210,640),
                               (target,750,420),('直接挑战',1600,420)),
            'level80':make_frame(('推荐等级80',100,500),('推荐等级90',100,600),
                                ('单人挑战',1450,965),selected='推荐等级80'),
            'level90':make_frame(('推荐等级80',100,500),('推荐等级90',100,600),
                                ('单人挑战',1450,965),selected='推荐等级90'),
            'team':make_frame(('开启挑战',1500,965)),
            'loading':make_frame(), 'battle':make_frame(battle=True),
        }
        state={'phase':'world','now':0.,'pending':None,'pending_at':0.,'missed':False}
        inputs=[]
        def capture(_runner):
            if state['pending'] and state['now']>=state['pending_at']:
                state['phase'],state['pending']=state['pending'],None
            return frames[state['phase']]
        def schedule(phase,delay=1.1):
            state['pending'],state['pending_at']=phase,state['now']+delay
        def tap(x,y):
            phase=state['phase']
            inputs.append(phase)
            if phase=='guide':
                schedule('category')
            elif phase=='category':
                schedule('list')
            elif phase=='target':
                # First direct-challenge click is deliberately ignored by the game.
                if state['missed']:
                    schedule('level80')
                state['missed']=True
            elif phase=='level80':
                self.assertGreater(y,570)  # Select 90 before the footer can be used.
                schedule('level90')
            elif phase=='level90':
                schedule('team')
            elif phase=='team':
                state['phase']='loading'
                schedule('battle',delay=4.)
            else:
                self.fail('Unexpected input in '+phase)
        runner=Mock(dry_run=False,stop_event=threading.Event())
        runner.controller.tap.side_effect=tap
        runner.controller.press_key.side_effect=lambda *_args:schedule('guide')
        runner._overworld_hud_ready.side_effect=lambda *_args:state['phase']=='world'
        runner._find_daily_template.return_value=None
        runner._sleep_interruptible.side_effect=lambda seconds:state.__setitem__('now',state['now']+seconds)
        runner._swipe_ratio.side_effect=lambda *_args:state.__setitem__('phase','target')
        ocr=Mock()
        entry=BossChallengeEntrance(target,'90',ocr_factory=lambda:ocr)
        with patch('tasks.combat_4c_entrance.time.monotonic',side_effect=lambda:state['now']), \
                patch.object(entry,'_capture',side_effect=capture):
            self.assertTrue(entry.enter(runner))
        self.assertEqual(inputs,['guide','category','target','target','level80','level90','team'])
        self.assertEqual(state['phase'],'battle')
        ocr.close.assert_called_once()

    def test_stalled_page_has_bounded_retries_and_no_later_input(self):
        now=[0.]
        entry=BossChallengeEntrance()
        source=make_frame(('单人挑战',1400,965))
        runner=Mock(stop_event=threading.Event())
        runner._sleep_interruptible.side_effect=lambda delay:now.__setitem__(0,now[0]+delay)
        click=Mock()
        with patch('tasks.combat_4c_entrance.time.monotonic',side_effect=lambda:now[0]), \
                patch.object(entry,'_capture',return_value=source):
            with self.assertRaisesRegex(RuntimeError,'未能确认'):
                entry._transition(runner,'队伍页面',entry._single,click,entry._start,timeout=9)
        self.assertEqual(click.call_count,3)

    def test_before_challenge_and_bright_loading_frames_are_not_battle(self):
        runner=Mock(dry_run=False,stop_event=threading.Event())
        runner._overworld_hud_ready=app.TaskRunner._overworld_hud_ready
        entry=BossChallengeEntrance()
        with tempfile.TemporaryDirectory() as directory:
            entry.screenshot=Path(directory)/'frame.png'
            for filename in ('tower-scene.png','tower-prompt.png','daily-activity-zero.png'):
                runner.controller.screencap.side_effect=lambda path,**_kw:shutil.copyfile(
                    Path(__file__).parent/'fixtures'/filename,path)
                self.assertFalse(entry._capture(runner).battle,filename)
            image=Image.new('RGB',(1920,1080),'white')
            runner.controller.screencap.side_effect=lambda path,**_kw:image.save(path)
            self.assertFalse(entry._capture(runner).battle)

    def test_stop_and_dry_run_do_not_send_input_and_close_worker(self):
        runner=Mock(dry_run=True,stop_event=threading.Event())
        factory=Mock()
        entry=BossChallengeEntrance(ocr_factory=factory)
        self.assertTrue(entry.enter(runner))
        factory.assert_not_called()
        runner.dry_run=False
        runner.stop_event.set()
        self.assertFalse(entry.enter(runner))
        factory.return_value.close.assert_called_once()
        runner.controller.tap.assert_not_called()
        runner.controller.press_key.assert_not_called()

    def test_clipped_label_and_unselected_difficulty_are_rejected(self):
        frame=make_frame(('直接挑战',1860,450))
        self.assertIsNone(frame.find('直接挑战'))
        entry=BossChallengeEntrance(level='90')
        frame=make_frame(('推荐等级90',100,600),('单人挑战',1400,965))
        self.assertFalse(entry._selected_level(frame))
        frame=make_frame(('推荐等级90',100,600),('单人挑战',1400,965),selected='推荐等级90')
        self.assertTrue(entry._selected_level(frame))

    def test_f2_support_and_independent_settings_preserve_existing_four_c(self):
        self.assertEqual(ClientWindowController._virtual_key('F2'),0x71)
        instance=app.App.__new__(app.App)
        instance.status=Mock()
        instance.boss_challenge_target=Mock(get=lambda:list(BOSS_AVATARS)[1])
        instance.boss_challenge_level=Mock(get=lambda:'90')
        instance.boss_challenge_count=Mock(get=lambda:'53')
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(app,'APP_SETTINGS_CONFIG',Path(directory)/'settings.json'):
            app.APP_SETTINGS_CONFIG.write_text('{"four_c_count":47,"shutdown_after_task":true}')
            self.assertTrue(instance._save_boss_challenge_settings())
            saved=json.loads(app.APP_SETTINGS_CONFIG.read_text(encoding='utf-8'))
            self.assertEqual(saved['four_c_count'],47)
            self.assertTrue(saved['shutdown_after_task'])
            self.assertEqual(instance._load_boss_challenge_settings()['count'],53)
        order=app.App._normalize_start_action_order(['daily','combat_4c_10','combat_4c_custom'])
        self.assertIn('boss_challenge',order)
        self.assertLess(order.index('combat_4c_10'),order.index('combat_4c_custom'))

    def test_failed_entry_cannot_start_combat_or_absorption(self):
        entry=Mock()
        runner=app.TaskRunner(Mock(),Mock(),dry_run=False,boss_challenge=entry)
        runner._run_4c_battle=Mock()
        runner._collect_4c_reward=Mock()
        entry.enter.side_effect=RuntimeError('未能确认等级')
        with self.assertRaisesRegex(RuntimeError,'未能确认等级'):
            runner._run_4c_combat(app.Step(action='combat_4c'))
        runner._run_4c_battle.assert_not_called()
        runner._collect_4c_reward.assert_not_called()
        runner.controller.release_keys.assert_called_once()

    @unittest.skipUnless(os.name=='nt','Windows local OCR integration')
    def test_real_local_ocr_recognizes_existing_fixture_or_reports_missing_language(self):
        worker=WindowsOcr()
        try:
            try:
                path=Path(__file__).parent/'fixtures'/'daily-activity-zero.png'
                lines=worker.recognize(path)
            except RuntimeError as exc:
                self.assertIn('Chinese OCR language pack is missing',str(exc))
            else:
                with Image.open(path) as image:
                    self.assertIsNotNone(EntranceFrame(image,lines).find('活跃行迹'))
            with self.assertRaises(InterruptedError):
                worker.recognize(path,cancelled=lambda:True)
        finally:
            worker.close()
        self.assertIsNotNone(worker.process.poll())


if __name__=='__main__':
    unittest.main()
