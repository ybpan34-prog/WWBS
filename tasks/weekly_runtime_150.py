"""Small, explicit fixes around the preserved 1.5.0 weekly sequence.

Lock matching to the captured client resolution, and close an obstructing park
shop before the original sequence searches/clicks background exit controls.
"""
from pathlib import Path
import time

from PIL import Image

from tasks.weekly_150 import TaskRunner as OriginalRunner
from tasks.weekly_matcher_150 import (
    TemplateMatcher, _gray_array, _scaled_template_gray, _match_single_scale_gray,
)


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

    def _capture_for_matching(self, target):
        super()._capture_for_matching(target)
        self._last_frame = target
        if self.stop_event.is_set() or self._expected_template is None:
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
