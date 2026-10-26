"""Small, explicit fixes around the preserved 1.5.0 weekly sequence.

Lock matching to the captured client resolution, and close an obstructing park
shop before the original sequence searches/clicks background exit controls.
"""
from pathlib import Path
import time
from dataclasses import replace

from PIL import Image

from tasks.weekly_150 import TaskRunner as OriginalRunner
from tasks.weekly_matcher_150 import (
    TemplateMatcher, _gray_array, _scaled_template_gray, _match_single_scale_gray,
)
from tasks.weekly_rewards import WeeklyRewardsVision


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
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.matcher = SessionMatcher(self.template_root, self.log)
        self._last_frame = None
        self._expected_template = None
        self._exit_click_at = None
        self._cap_vision = WeeklyRewardsVision(Path(__file__).resolve().parent.parent/'templates/weekly')

    def run_task(self, task):
        try:
            return super().run_task(task)
        except WeeklyCapReached:
            self._stop_at_cap()

    def _run_default_weekly_from_daily(self):
        try:
            return super()._run_default_weekly_from_daily()
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
            return super()._find_image(step)
        finally:
            self._expected_template = previous

    def _random_click_point(self, match, offset_x, offset_y):
        if self._expected_template in ('menu96.png', 'menu97.png'):
            # These are irregular star/circle buttons. The rectangle's corners
            # include transparent/noninteractive pixels, so do not jitter here.
            return match.center
        return super()._random_click_point(match, offset_x, offset_y)

    def _click_cycle_template(self, step, x, y, recovery=False):
        if self.stop_event.is_set():
            return
        result = super()._click_cycle_template(step, x, y, recovery)
        if step.template == 'menu96.png':
            self._exit_click_at = time.monotonic()
        return result

    def _wait_for_cycle_template(self, step, previous_step=None):
        if (self.dry_run or step.template != 'menu97.png' or previous_step is None
                or previous_step.template != 'menu96.png'):
            return super()._wait_for_cycle_template(step, previous_step)
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
        if self._cap_result(target):
            self._sleep_interruptible(.15)
            if self.stop_event.is_set():
                return
            super()._capture_for_matching(target)
            if self._cap_result(target):
                raise WeeklyCapReached()
        if self._expected_template is None:
            return
        close = self._shop_close(target)
        if close is None or self._expected_template == 'menu95.png':
            return
        self.log(f'    乐园商店仍在，先关闭遮挡页面，再继续等待{self._expected_template}；不点击后方退出图标。')
        deadline, next_click, attempts, absent = time.monotonic()+6, 0., 0, 0
        while not self.stop_event.is_set() and time.monotonic() < deadline:
            if close is None:
                absent += 1
                if absent >= 2:
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


class ShopNotClosed(RuntimeError):
    pass


class WeeklyCapReached(BaseException):
    """Intentional end signal, outside the original broad click-retry handlers."""
