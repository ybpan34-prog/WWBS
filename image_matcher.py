from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

try:
    from scipy.signal import fftconvolve
except Exception as exc:  # pragma: no cover - shown to users at runtime
    fftconvolve = None
    SCIPY_IMPORT_ERROR = exc
else:
    SCIPY_IMPORT_ERROR = None


@dataclass
class MatchResult:
    x: int
    y: int
    width: int
    height: int
    score: float

    @property
    def center(self) -> tuple[int, int]:
        return self.x + self.width // 2, self.y + self.height // 2


class TemplateMatcher:
    def __init__(self, templates_dir: Path):
        self.templates_dir = templates_dir

    def find(
        self,
        screenshot_path: Path,
        template_name: str,
        threshold: float = 0.82,
        scales: list[float] | None = None,
    ) -> MatchResult:
        if fftconvolve is None:
            raise RuntimeError(f"缺少 scipy，无法进行模板识别: {SCIPY_IMPORT_ERROR}")

        template_path = self.templates_dir / template_name
        if not template_path.exists():
            raise FileNotFoundError(f"模板不存在: {template_path}")

        screenshot = _load_rgb(screenshot_path)
        template_image = Image.open(template_path).convert("RGB")
        scales = scales or [1.0, 0.95, 1.05, 0.9, 1.1]

        best: MatchResult | None = None
        for scale in scales:
            template = _scaled_template(template_image, scale)
            if template.shape[0] >= screenshot.shape[0] or template.shape[1] >= screenshot.shape[1]:
                continue
            result = _match_single_scale_rgb(screenshot, template)
            if best is None or result.score > best.score:
                best = result

        if best is None:
            raise RuntimeError("没有可用的模板匹配结果。")
        if best.score < threshold:
            raise RuntimeError(f"未找到模板 {template_name}，最高相似度 {best.score:.3f}，阈值 {threshold:.3f}")
        return best


def _load_rgb(path: Path) -> np.ndarray:
    return np.asarray(Image.open(path).convert("RGB"), dtype=np.float64) / 255.0


def _scaled_template(image: Image.Image, scale: float) -> np.ndarray:
    width = max(8, int(image.width * scale))
    height = max(8, int(image.height * scale))
    resized = image.resize((width, height), Image.Resampling.BILINEAR)
    return np.asarray(resized, dtype=np.float64) / 255.0


def _match_single_scale_rgb(image: np.ndarray, template: np.ndarray) -> MatchResult:
    th, tw, channels = template.shape
    template_zero = template - template.mean(axis=(0, 1), keepdims=True)
    template_norm = float(np.sqrt(np.sum(template_zero * template_zero)))
    if template_norm < 1e-6:
        raise RuntimeError("模板内容过于单一，请裁剪包含文字、图标或边框的区域。")

    numerator = None
    image_var_total = None
    window_area = float(th * tw)
    for channel in range(channels):
        channel_image = image[:, :, channel]
        channel_template = template_zero[:, :, channel]
        channel_numerator = fftconvolve(channel_image, channel_template[::-1, ::-1], mode="valid")
        image_sum = _window_sum(channel_image, th, tw)
        image_sum_sq = _window_sum(channel_image * channel_image, th, tw)
        image_var = image_sum_sq - (image_sum * image_sum / window_area)
        numerator = channel_numerator if numerator is None else numerator + channel_numerator
        image_var_total = image_var if image_var_total is None else image_var_total + image_var
    image_norm = np.sqrt(np.maximum(image_var_total, 0.0))
    denominator = image_norm * template_norm
    low_texture = image_norm < (template_norm * 0.08)
    scores = np.divide(numerator, denominator, out=np.full_like(numerator, -1.0), where=denominator > 1e-8)
    scores[low_texture] = -1.0
    scores = np.clip(scores, -1.0, 1.0)

    y, x = np.unravel_index(np.argmax(scores), scores.shape)
    return MatchResult(x=int(x), y=int(y), width=int(tw), height=int(th), score=float(scores[y, x]))


def _window_sum(image: np.ndarray, height: int, width: int) -> np.ndarray:
    integral = np.pad(image, ((1, 0), (1, 0)), mode="constant").cumsum(axis=0).cumsum(axis=1)
    return (
        integral[height:, width:]
        - integral[:-height, width:]
        - integral[height:, :-width]
        + integral[:-height, :-width]
    )
