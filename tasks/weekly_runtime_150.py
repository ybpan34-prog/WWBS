"""Small, explicit fixes around the preserved 1.5.0 weekly sequence.

Lock matching to the captured client resolution, and close an obstructing park
shop before the original sequence searches/clicks background exit controls.
"""
from pathlib import Path
import time
from dataclasses import replace

from PIL import Image

from tasks.weekly_150 import TaskRunner as OriginalRunner, original_task, APP_DIR
from tasks.models import Step
from tasks.weekly_matcher_150 import (
    TemplateMatcher, _gray_array, _scaled_template_gray, _match_single_scale_gray,
)
from tasks.weekly_rewards import WeeklyRewardsVision
from windows_client import BlankGameCapture


def weekly_neighbor_names(anchor):
    names = ['menu1.png']+original_task().steps[1].templates
    index = names.index(anchor) if anchor in names else 1
    neighbors = names[max(0, index-2):index+3]
    if anchor in ('menu2.png', 'menu3.png', 'menu4.png'):
        neighbors.append('menu99.png')
    return neighbors


class WeeklyAdvanced(Exception):
    def __init__(self, template):
        self.template = template


class WeeklyRoundRestarted(Exception):
    def __init__(self, template):
        self.template = template


class SessionMatcher(TemplateMatcher):
    def __init__(self, templates_dir, log):
        super().__init__(templates_dir)
        self.log = log
        self.current_scale = None
        self.current_size = None
        self._frame_key = None
        self._image = None
        self._gray = None
        self._templates = {}

    def frame_scale(self, path):
        path = Path(path)
        info = path.stat()
        key = (str(path.resolve()), info.st_mtime_ns, info.st_size)
        if key != self._frame_key:
            with Image.open(path) as source:
                image = source.convert('L')
            if image.size != self.current_size:
                self.current_size = image.size
                self.current_scale = image.width/1920
                self._templates.clear()
                self.log(f'    周常识别比例已锁定：{image.width}×{image.height}（{self.current_scale:.3f}），窗口尺寸不变时不再遍历其他比例。')
            self._image = image
            blur = 0.0 if abs(self.current_scale-1.0) < .015 else .7
            self._gray = _gray_array(image, blur)
            self._frame_key = key
        return self.current_scale

    def find(self, screenshot_path, template_name, threshold=.82, scales=None):
        if template_name == 'menu99.png':
            from tasks.weekly_restart import restart_match
            return restart_match(screenshot_path)
        if template_name == 'menu4.png':
            from tasks.weekly_restart import skip_match
            return skip_match(screenshot_path)
        if template_name == 'menu96.png':
            from tasks.weekly_exit import weekly_exit_match
            return weekly_exit_match(screenshot_path)
        scale = self.frame_scale(screenshot_path)
        path = self.templates_dir/template_name
        if not path.is_file():
            raise FileNotFoundError(f'模板不存在: {path}')
        info = path.stat()
        key = (str(path.resolve()), info.st_mtime_ns, info.st_size, scale)
        if key not in self._templates:
            with Image.open(path) as source:
                blur = 0.0 if abs(scale-1.0) < .015 else .7
                self._templates[key] = _scaled_template_gray(source.convert('L'), scale, blur)
        template = self._templates[key]
        if template.shape[0] >= self._gray.shape[0] or template.shape[1] >= self._gray.shape[1]:
            raise RuntimeError('模板尺寸不适合当前截图。')
        result = _match_single_scale_gray(self._gray, template)
        if result.score < threshold:
            raise RuntimeError(f'未找到模板 {template_name}，最高相似度 {result.score:.3f}，阈值 {threshold:.3f}')
        return result


class WeeklyRuntime(OriginalRunner):
    def __init__(self, *args, weekly_test_mode=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.weekly_test_mode = weekly_test_mode
        self.matcher = SessionMatcher(self.template_root, self.log)
        self._last_frame = None
        self._expected_template = None
        self._exit_click_at = None
        self._failed_template = None
        self._completed_templates = set()
        self._shop_closed_for = None
        self._board_verified = False
        self._menu2_checked = False
        self._cap_vision = WeeklyRewardsVision(Path(__file__).resolve().parent.parent/'templates/weekly')

    def run_task(self, task):
        try:
            if self.weekly_test_mode and not self.dry_run:
                from tasks.weekly_restart import restart_match
                path = APP_DIR/'_runtime_screenshot.png'
                self._capture_for_matching(path)
                if self.stop_event.is_set():
                    return
                try:
                    restart_match(path)
                except RuntimeError:
                    pass
                else:
                    self.log('    周常测试模式：从当前结算页重新挑战。')
                    self._resume_cycle_template = self._restart_and_confirm()
                    return self._run_image_cycle(original_task().steps[1])
            anchor = getattr(self, '_resume_template', None)
            if isinstance(anchor, str) and not self.dry_run:
                matches = self._probe_neighbors(anchor)
                resolved = self._resolved_checkpoint(anchor, matches)
                if resolved is not None:
                    self._resume_cycle_template = resolved
                    self.log(f'    已复核商店流程结束，直接从{resolved}接续。')
                    return self._run_image_cycle(original_task().steps[1])
                names = ['menu1.png']+original_task().steps[1].templates
                if anchor in names:
                    position = names.index(anchor)
                    backward = [name for name in names[max(0, position-2):position] if name in matches]
                    candidates = [name for name in names[position:position+3] if name in matches]
                    can_resume = candidates and (candidates[0] == anchor
                        or (anchor == 'menu2.png' and candidates[0] == 'menu3.png'))
                    if can_resume and not backward and candidates[0] != 'menu1.png':
                        self._resume_cycle_template = candidates[0]
                        self.log(f'    从失败位置{anchor}复核到{candidates[0]}，按当前画面接续，不重复寻找menu1。')
                        return self._run_image_cycle(original_task().steps[1])
            return super().run_task(task)
        except WeeklyCapReached:
            self._stop_at_cap()

    def _run_default_weekly_from_daily(self):
        try:
            return super()._run_default_weekly_from_daily()
        except WeeklyCapReached:
            self._stop_at_cap()

    def _start_weekly_travel_from_selected_page(self):
        try:
            return super()._start_weekly_travel_from_selected_page()
        except WeeklyCapReached:
            self._stop_at_cap()

    def _stop_at_cap(self):
        self.stop_event.set()
        self.log('    本周游历值已达到上限，本次周常已结束；不再重新挑战，保留当前结算页面。')
        self.notice('本周游历值已达到上限，已停止周常，保留结算页面。')

    def _cap_result(self, path):
        try:
            return (self._cap_vision.matches(path, 'cap_result.png', (1380,580,1640,680))
                    and self._cap_vision.matches(path, 'return_home.png', (1170,865,1390,975)))
        except OSError:
            return False

    def _fast_scales(self):
        if self._last_frame is not None:
            return [self.matcher.frame_scale(self._last_frame)]
        return super()._fast_scales()[:1]

    def _shop_close(self, path):
        scale = self.matcher.frame_scale(path)
        width, height = self.matcher.current_size
        def find(name, box, threshold):
            try:
                return self.matcher.find_fast(path, name, threshold, scale=scale,
                    region=tuple(round(value*(width if i % 2 == 0 else height)) for i, value in enumerate(box)))
            except (OSError, RuntimeError):
                return None
        # Require the shop's own title and close button together. The dimmed
        # park exit at the far right can score .829 while this modal is open.
        if find('shop_title.png', (.12, .02, .38, .12), .88) is None:
            return None
        return find('menu95.png', (.77, .025, .87, .105), .88)

    def _find_image(self, step):
        previous = self._expected_template
        self._expected_template = step.template
        try:
            if step.template == 'menu2.png':
                if self._menu2_checked:
                    raise RuntimeError('本轮menu2已经识别过一次，不再重复寻找。')
                self._menu2_checked = True
                self.log('    menu2本轮仅识别一次，随后只复核后续页面及跨轮menu99。')
                path = APP_DIR/'_runtime_screenshot.png'
                self._capture_for_matching(path)
                match = self.matcher.find(path, step.template, step.threshold, self._fast_scales())
                return (*match.center, match.score)
            return super()._find_image(step)
        except RuntimeError:
            self._failed_template = step.template
            raise
        finally:
            self._expected_template = previous

    def _random_click_point(self, match, offset_x, offset_y):
        if self._expected_template in ('menu96.png', 'menu97.png', 'menu99.png'):
            # These are irregular star/circle buttons. The rectangle's corners
            # include transparent/noninteractive pixels, so do not jitter here.
            return match.center
        return super()._random_click_point(match, offset_x, offset_y)

    def _click_cycle_template(self, step, x, y, recovery=False):
        if self.stop_event.is_set():
            return
        if step.template == 'menu99.png':
            self._round_entry_template = self._restart_and_confirm()
            self.last_clicked_image_step = step
            return
        if step.template == 'menu96.png':
            self.log('    menu96仅识别右上角退出按钮，连续新截图复核后精确点击中心，避开宝石栏。')
            if callable(getattr(type(self.controller), 'tap_weekly_exit', None)):
                result = self.controller.tap_weekly_exit()
            else:
                from tasks.weekly_exit import weekly_exit_match
                path = APP_DIR/'_runtime_screenshot.png'
                center = None
                for _ in range(2):
                    if self.stop_event.is_set():
                        return
                    self._capture_for_matching(path)
                    match = weekly_exit_match(path)
                    if center is not None and center != match.center:
                        raise RuntimeError('退出按钮位置变化，重新定位后再点击。')
                    center = match.center
                result = self.controller.tap(*center)
            if isinstance(result, dict):
                if result.get('cancelled'):
                    return result
                self.log(f"    退出按钮精确点击：屏幕目标{result.get('target')}，实际光标{result.get('after_move')}。")
            self.last_clicked_image_step = step
            self._exit_click_at = time.monotonic()
            return result
        result = super()._click_cycle_template(step, x, y, recovery)
        if step.template == 'menu2.png':
            matches = self._probe_neighbors('menu2.png')
            if 'menu2.png' not in matches and 'menu3.png' in matches:
                self._completed_templates.add('menu2.png')
                self.log('    已用连续新截图确认menu2点击生效，当前已到menu3，下一步寻找menu3。')
        return result

    def _restart_and_confirm(self):
        from tasks.weekly_restart import restart_match, round_entry, thumbnail
        import numpy as np
        path = APP_DIR/'_runtime_screenshot.png'
        deadline, next_click = time.monotonic()+15, 0.
        attempts, visible, stable = 0, 0, 0
        baseline, previous_state = None, None
        waiting_on_blank = False
        while not self.stop_event.is_set() and time.monotonic() < deadline:
            try:
                self._capture_for_matching(path)  # Includes the weekly-cap check.
            except BlankGameCapture:
                if not attempts:
                    raise
                if not waiting_on_blank:
                    self.log('    menu99点击后暂时截到空白画面，继续等待重开过渡，复核新截图。')
                waiting_on_blank = True
                visible, stable, previous_state = 0, 0, None
                self._sleep_interruptible(.15)
                continue
            if self.stop_event.is_set():
                break
            waiting_on_blank = False
            current = thumbnail(path)
            try:
                target = restart_match(path)
            except RuntimeError:
                target = None
            if target is not None:
                baseline = current if baseline is None else baseline
                visible += 1
                stable, previous_state = 0, None
                if visible >= 2 and attempts < 3 and time.monotonic() >= next_click:
                    if callable(getattr(type(self.controller), 'tap_weekly_restart', None)):
                        try:
                            result = self.controller.tap_weekly_restart()
                        except BlankGameCapture:
                            if not attempts:
                                raise
                            waiting_on_blank, visible = True, 0
                            self.log('    menu99补点前暂时截到空白画面，取消补点并继续复核。')
                            self._sleep_interruptible(.15)
                            continue
                        if isinstance(result, dict) and result.get('cancelled'):
                            raise RuntimeError('周常已停止。')
                    else:
                        self.controller.tap(*target.center)
                    attempts += 1
                    next_click = time.monotonic()+2
                    self.log(f'    menu99第{attempts}次精确点击重新挑战中心{target.center}，等待截图变化及下一轮页面，不提前计轮。')
            else:
                visible = 0
                state = round_entry(path)
                difference = float(np.abs(current-baseline).mean()) if baseline is not None else 0.
                valid = attempts > 0 and difference > 6 and state is not None
                stable = stable+1 if valid and state == previous_state else 1 if valid else 0
                previous_state = state
                if stable >= 2:
                    self._completed_templates.add('menu99.png')
                    self.log(f'    menu99点击已生效：截图差异{difference:.1f}，连续确认进入{state}；此时才允许开始下一轮。')
                    return state
            self._sleep_interruptible(.15)
        self._failed_template = 'menu99.png'
        if self.stop_event.is_set():
            raise RuntimeError('周常已停止。')
        if waiting_on_blank:
            raise RuntimeError('menu99点击后等待重开超时，最新截图仍为空白，未计为完成。')
        raise RuntimeError('menu99点击后未确认离开结算并进入下一轮，未计为完成，保留当前画面。')

    def _verify_final_cycle_click(self, final_step):
        if final_step.template == 'menu99.png' and 'menu99.png' in self._completed_templates:
            self.log('    最终轮menu99已完成新截图与下一页复核，无需重复点击。')
            return
        return super()._verify_final_cycle_click(final_step)

    def _probe_neighbors(self, anchor):
        from tasks.weekly_board import board_ready
        # menu2 is read only once at its actual step, never in neighbor sweeps.
        names = [name for name in weekly_neighbor_names(anchor) if name != 'menu2.png']
        stable = None
        board_frames = 0
        path = APP_DIR/'_runtime_screenshot.png'
        for _ in range(2):
            if self.stop_event.is_set():
                raise RuntimeError('周常已停止。')
            self._capture_for_matching(path)
            board_frames += int(board_ready(path))
            current = {}
            for name in names:
                try:
                    current[name] = self.matcher.find(path, name, .82 if name == anchor else .88, self._fast_scales())
                except RuntimeError:
                    pass
            stable = current if stable is None else {name: match for name, match in current.items() if name in stable}
            self._sleep_interruptible(.15)
        self.log('    前后各2个模板复核：'+', '.join(names)+'；连续确认：'+(', '.join(stable) or '无'))
        self._board_verified = board_frames == 2
        return stable

    def _resolved_checkpoint(self, anchor, matches):
        shop_steps = ('menu93.png', 'menu94.png', 'menu95.png')
        known_shop = (self._shop_closed_for in shop_steps
                      and {'menu94.png', 'menu95.png'} <= self._completed_templates)
        if (anchor in shop_steps and known_shop and self._board_verified
                and 'menu96.png' in matches and 'menu93.png' not in matches
                and 'menu94.png' not in matches and 'menu95.png' not in matches):
            self.log('    menu94已由进入商店状态确认完成，menu95关闭已复核；按顺序接续menu96，menu92仅作诊断记录。')
            return 'menu96.png'
        return None

    def _run_image_cycle(self, step):
        # Preserve the original order, but let a confirmed later state advance
        # the cursor without inventing a click on a button that already left.
        templates = step.templates or self._numbered_templates('menu', 2, 99)
        if not templates:
            raise RuntimeError('循环模板列表为空。')
        previous = self.last_clicked_image_step
        max_cycles = None if self.weekly_test_mode else self.max_cycles
        if self.weekly_test_mode:
            self.log('    周常测试模式已开启，忽略本周游历值上限和轮数限制。')
        cycle = 1
        while not self.stop_event.is_set():
            if max_cycles is not None and cycle > max_cycles:
                self.stop_event.set()
                return
            self._completed_templates.clear()
            self._shop_closed_for = None
            self._menu2_checked = False
            self.log(f'    开始第 {cycle} 轮循环。')
            resume = (getattr(self, '_resume_cycle_template', None) if cycle == 1
                      else getattr(self, '_round_entry_template', None))
            index = templates.index(resume) if resume in templates else 0
            self._resume_cycle_template = None
            self._round_entry_template = None
            while index < len(templates) and not self.stop_event.is_set():
                name = templates[index]
                if not (self.template_root/name).exists() and step.skip_missing:
                    index += 1
                    continue
                current = Step(action='tap_image', template=name, threshold=step.threshold, timeout=step.timeout,
                               offset_x=self._template_offset(step, name, 'x'),
                               offset_y=self._template_offset(step, name, 'y'), seconds=step.seconds)
                try:
                    x, y, score = self._wait_for_cycle_template(current, previous)
                except WeeklyRoundRestarted as restarted:
                    index = templates.index(restarted.template)
                    previous = None
                    self.log(f'    已确认跨轮重开，当前入口为{restarted.template}，从实际入口接续。')
                    continue
                except WeeklyAdvanced as advanced:
                    following = templates.index(advanced.template, index+1) if advanced.template in templates[index+1:] else -1
                    if following < 0 or any(name not in self._completed_templates for name in templates[index:following]):
                        raise RuntimeError('复核结果超出相邻步骤，停止以避免跳步。')
                    self.log(f'    {name}已不在当前画面，已确认{advanced.template}，更新步骤并继续寻找。')
                    index = templates.index(advanced.template, index+1)
                    previous = None
                    continue
                if self.stop_event.is_set():
                    return
                self.log(f'    找到 {name}: ({x}, {y}) 相似度 {score:.3f}')
                if not self.dry_run:
                    self._click_cycle_template(current, x, y)
                previous = current
                index += 1
                self._sleep_click_interval(step.seconds)
            if self.stop_event.is_set() or not step.loop:
                return
            if max_cycles is not None and cycle >= max_cycles:
                if previous is not None and not self.dry_run:
                    self._verify_final_cycle_click(previous)
                self.log(f'    已完成 {max_cycles} 轮循环，自动停止。')
                self.stop_event.set()
                return
            cycle += 1

    def _wait_with_neighbors(self, step, previous_step):
        names = ['menu1.png']+original_task().steps[1].templates
        index = names.index(step.template) if step.template in names else None
        if index is None or self.dry_run:
            return super()._wait_for_cycle_template(step, previous_step)
        limit = 1 if step.template == 'menu2.png' else 5
        for misses in range(1, limit+1):
            if self.stop_event.is_set():
                raise RuntimeError('周常已停止。')
            try:
                return self._find_image(step)
            except RuntimeError as error:
                self._failed_template = step.template
                matches = self._probe_neighbors(step.template)
                if step.template in ('menu2.png', 'menu3.png', 'menu4.png') and 'menu99.png' in matches:
                    self.log('    跨轮复核发现menu99，仍在上一轮结算，先完成重新挑战及画面变化复核。')
                    raise WeeklyRoundRestarted(self._restart_and_confirm())
                if step.template == 'menu2.png' and 'menu4.png' in matches and 'menu3.png' not in matches:
                    self._completed_templates.update(('menu2.png', 'menu3.png'))
                    self.log('    menu2单次识别后，已确认实际入口为menu4，接续当前选卡页面。')
                    raise WeeklyAdvanced('menu4.png')
                resolved = self._resolved_checkpoint(step.template, matches)
                if resolved is not None:
                    raise WeeklyAdvanced(resolved)
                if step.template in matches:
                    match = matches[step.template]
                    return (*match.center, match.score)
                backward = [name for name in names[max(0, index-2):index] if name in matches]
                forward = [name for name in names[index+1:index+3] if name in matches]
                next_name = names[index+1] if index+1 < len(names) else None
                if next_name in forward and not backward:
                    if step.template == 'menu2.png' and next_name == 'menu3.png':
                        self._completed_templates.add(step.template)
                    if step.template in self._completed_templates:
                        raise WeeklyAdvanced(next_name)
                if backward and forward:
                    self.log('    前后模板同时匹配，可能是重复按钮图案；暂不跳步，继续复核。')
                if (misses in (2, 4) and previous_step is not None
                        and previous_step.template in matches
                        and previous_step.template not in self._completed_templates and not forward):
                    match = matches[previous_step.template]
                    self._click_cycle_template(previous_step, *match.center, recovery=True)
                self.log(f'    等待{step.template}（第{misses}/{limit}次）：{error}')
                self._sleep_interruptible(.15)
        self.stop_event.set()
        raise RuntimeError(f'未确认{step.template}，已检查前后各2个模板，保留当前画面。')

    def _wait_for_cycle_template(self, step, previous_step=None):
        if (self.dry_run or step.template != 'menu97.png' or previous_step is None
                or previous_step.template != 'menu96.png'):
            return self._wait_with_neighbors(step, previous_step)
        self.log('    退出步骤单独复核：等待退出过渡与menu97，未响应时重新定位按钮中心补点。')
        started = time.monotonic()
        deadline, retries = started+18, 0
        next_retry = max(started, self._exit_click_at or started)+2
        probe = replace(step, timeout=.15)
        previous_probe = replace(previous_step, timeout=.15)
        last_error = None
        while not self.stop_event.is_set() and time.monotonic() < deadline:
            try:
                found = self._find_image(probe)
                if self.stop_event.is_set():
                    break
                self.log('    已确认menu97出现，退出点击已生效，继续原流程。')
                return found
            except (FileNotFoundError, OSError):
                raise
            except RuntimeError as error:
                last_error = error
            if self.stop_event.is_set():
                break
            if retries < 3 and time.monotonic() >= next_retry:
                # Fresh capture and recognition; never reuse the prior position
                # while the shop, exit overlay or a fade can change the page.
                try:
                    x,y,_score = self._find_image(previous_probe)
                except (FileNotFoundError, OSError):
                    raise
                except RuntimeError:
                    pass  # Button absent during transition: wait, do not click.
                else:
                    if self.stop_event.is_set():
                        break
                    retries += 1
                    self.log(f'    menu97尚未出现，重新识别menu96中心后补点（第{retries}/3次）。')
                    self._click_cycle_template(previous_step, x, y, recovery=True)
                next_retry = time.monotonic()+3
            self._sleep_interruptible(.15)
        if self.stop_event.is_set():
            raise RuntimeError('周常已停止。')
        raise RuntimeError(f'退出步骤已等待过渡并复核18秒，重新定位中心补点{retries}次后仍未出现menu97；'
                           f'未当作退出成功，请检查当前页面。最后识别：{last_error}')

    def _capture_for_matching(self, target):
        super()._capture_for_matching(target)
        self._last_frame = target
        if self.stop_event.is_set():
            return
        # Check the actual result before any restart/exit input. Both a win and
        # a loss use this same weekly-cap row and return-home button.
        if not self.weekly_test_mode and self._cap_result(target):
            self._sleep_interruptible(.15)
            if self.stop_event.is_set():
                return
            super()._capture_for_matching(target)
            if self._cap_result(target):
                raise WeeklyCapReached()
        self._dismiss_stage_goal(target)
        if self._expected_template is None:
            return
        close = self._shop_close(target)
        if close is None or self._expected_template == 'menu95.png':
            return
        if self._expected_template in ('menu93.png', 'menu94.png'):
            # The actual shop is the postcondition of the stage confirmation.
            # This records an observed transition, not a guessed template skip.
            self._completed_templates.add('menu94.png')
            if self._expected_template == 'menu93.png':
                self._completed_templates.add('menu93.png')
        self.log(f'    乐园商店仍在，先关闭遮挡页面，再继续等待{self._expected_template}；不点击后方退出图标。')
        deadline, next_click, attempts, absent = time.monotonic()+6, 0., 0, 0
        while not self.stop_event.is_set() and time.monotonic() < deadline:
            if close is None:
                absent += 1
                if absent >= 2:
                    self._shop_closed_for = self._expected_template
                    self._completed_templates.add('menu95.png')
                    self.log('    已用连续截图确认乐园商店关闭，继续1.5.0原流程。')
                    return
            else:
                absent = 0
                if attempts < 3 and time.monotonic() >= next_click:
                    self.controller.tap(*close.center)
                    attempts += 1
                    next_click = time.monotonic()+1
            self._sleep_interruptible(.15)
            if self.stop_event.is_set():
                break
            super()._capture_for_matching(target)
            close = self._shop_close(target)
        if self.stop_event.is_set():
            raise RuntimeError('周常已停止。')
        # Never let the original catch/retry path click behind an open shop.
        raise ShopNotClosed('乐园商店关闭后未确认消失，已停止点击后方按钮，请检查商店页面。')

    def _dismiss_stage_goal(self, target):
        from tasks.weekly_stage import stage_goal_confirm
        point = stage_goal_confirm(target)
        if point is None:
            return
        # Confirm another fresh frame before clicking; stage announcements may
        # disappear while the previous shop-close action is still settling.
        self._sleep_interruptible(.15)
        if self.stop_event.is_set():
            raise RuntimeError('周常已停止。')
        super()._capture_for_matching(target)
        point = stage_goal_confirm(target)
        self.log('    已复核乐园阶段目标弹窗，只点击确认，关闭后继续周常。')
        attempts, absent = 0, 0
        deadline, next_click = time.monotonic()+6, 0.
        while not self.stop_event.is_set() and time.monotonic() < deadline:
            if point is None:
                absent += 1
                if absent >= 2:
                    self.log('    已用连续截图确认阶段目标弹窗关闭，继续原流程。')
                    return
            else:
                absent = 0
                if attempts < 3 and time.monotonic() >= next_click:
                    self.controller.tap(*point)
                    attempts += 1
                    next_click = time.monotonic()+1
            self._sleep_interruptible(.15)
            if self.stop_event.is_set():
                break
            super()._capture_for_matching(target)
            point = stage_goal_confirm(target)
        self.stop_event.set()
        raise RuntimeError('阶段目标弹窗确认后仍未复核关闭，已停止，保留当前页面。')


class ShopNotClosed(RuntimeError):
    pass


class WeeklyCapReached(BaseException):
    """Intentional end signal, outside the original broad click-retry handlers."""
