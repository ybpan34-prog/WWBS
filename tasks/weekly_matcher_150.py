from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter


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
        template_path = self.templates_dir / template_name
        if not template_path.exists():
            raise FileNotFoundError(f"模板不存在: {template_path}")

        screenshot_image = Image.open(screenshot_path).convert("L")
        template_image = Image.open(template_path).convert("L")
        scales = scales or [1.0, 0.95, 1.05, 0.9, 1.1]

        best: MatchResult | None = None
        tested_sizes: set[tuple[int, int]] = set()
        screenshot_cache: dict[float, np.ndarray] = {}
        for scale in scales:
            blur_radius = 0.0 if abs(scale - 1.0) < 0.015 else 0.7
            if blur_radius not in screenshot_cache:
                screenshot_cache[blur_radius] = _gray_array(screenshot_image, blur_radius)
            screenshot = screenshot_cache[blur_radius]
            template = _scaled_template_gray(template_image, scale, blur_radius)
            template_size = (template.shape[1], template.shape[0])
            if template_size in tested_sizes:
                continue
            tested_sizes.add(template_size)
            if template.shape[0] >= screenshot.shape[0] or template.shape[1] >= screenshot.shape[1]:
                continue
            result = _match_single_scale_gray(screenshot, template)
            if best is None or result.score > best.score:
                best = result

        if best is None:
            raise RuntimeError("没有可用的模板匹配结果。")
        if best.score < threshold:
            raise RuntimeError(f"未找到模板 {template_name}，最高相似度 {best.score:.3f}，阈值 {threshold:.3f}")
        return best

    def find_fast(
        self,
        screenshot_path: Path,
        template_name: str,
        threshold: float = 0.82,
        scale: float = 1.0,
        max_width: int = 1920,
        region: tuple[int, int, int, int] | None = None,
        template_crop: tuple[int, int, int, int] | None = None,
    ) -> MatchResult:
        """Fast presence check using one grayscale FFT, capped at 1920px for 4K input."""
        template_path = self.templates_dir / template_name
        if not template_path.exists():
            raise FileNotFoundError(f"模板不存在: {template_path}")

        with Image.open(screenshot_path) as source:
            screenshot_image = source.convert("L")
        origin_x = 0
        origin_y = 0
        if region is not None:
            left, top, right, bottom = region
            left = max(0, min(screenshot_image.width - 1, int(left)))
            top = max(0, min(screenshot_image.height - 1, int(top)))
            right = max(left + 1, min(screenshot_image.width, int(right)))
            bottom = max(top + 1, min(screenshot_image.height, int(bottom)))
            screenshot_image = screenshot_image.crop((left, top, right, bottom))
            origin_x, origin_y = left, top
        reduction = min(1.0, max_width / max(1, screenshot_image.width))
        reduced_size = (
            max(8, round(screenshot_image.width * reduction)),
            max(8, round(screenshot_image.height * reduction)),
        )
        screenshot = np.asarray(
            screenshot_image.resize(reduced_size, Image.Resampling.BILINEAR),
            dtype=np.float64,
        ) / 255.0

        with Image.open(template_path) as source:
            template_image = source.convert("L")
        if template_crop is not None:
            crop_left, crop_top, crop_right, crop_bottom = template_crop
            crop_left = max(0, min(template_image.width - 1, int(crop_left)))
            crop_top = max(0, min(template_image.height - 1, int(crop_top)))
            crop_right = max(crop_left + 1, min(template_image.width, int(crop_right)))
            crop_bottom = max(crop_top + 1, min(template_image.height, int(crop_bottom)))
            template_image = template_image.crop((crop_left, crop_top, crop_right, crop_bottom))
        template_size = (
            max(8, round(template_image.width * scale * reduction)),
            max(8, round(template_image.height * scale * reduction)),
        )
        template = np.asarray(
            template_image.resize(template_size, Image.Resampling.BILINEAR),
            dtype=np.float64,
        ) / 255.0
        if template.shape[0] >= screenshot.shape[0] or template.shape[1] >= screenshot.shape[1]:
            raise RuntimeError("模板尺寸不适合当前截图。")

        reduced = _match_single_scale_gray(screenshot, template)
        result = MatchResult(
            x=round(reduced.x / reduction) + origin_x,
            y=round(reduced.y / reduction) + origin_y,
            width=round(reduced.width / reduction),
            height=round(reduced.height / reduction),
            score=reduced.score,
        )
        if result.score < threshold:
            raise RuntimeError(f"未找到模板 {template_name}，最高相似度 {result.score:.3f}，阈值 {threshold:.3f}")
        return result


def _load_rgb(path: Path) -> np.ndarray:
    return np.asarray(Image.open(path).convert("RGB"), dtype=np.float64) / 255.0


def _gray_array(image: Image.Image, blur_radius: float = 0.0) -> np.ndarray:
    if blur_radius > 0:
        image = image.filter(ImageFilter.GaussianBlur(blur_radius))
    return np.asarray(image, dtype=np.float64) / 255.0


def _scaled_template(image: Image.Image, scale: float) -> np.ndarray:
    width = max(8, int(image.width * scale))
    height = max(8, int(image.height * scale))
    resized = image.resize((width, height), Image.Resampling.BILINEAR)
    return np.asarray(resized, dtype=np.float64) / 255.0


def _scaled_template_gray(image: Image.Image, scale: float, blur_radius: float = 0.0) -> np.ndarray:
    width = max(8, round(image.width * scale))
    height = max(8, round(image.height * scale))
    resized = image.resize((width, height), Image.Resampling.LANCZOS)
    if blur_radius > 0:
        resized = resized.filter(ImageFilter.GaussianBlur(blur_radius))
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
        channel_numerator = _fft_convolve_valid(channel_image, channel_template[::-1, ::-1])
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


def _match_single_scale_gray(image: np.ndarray, template: np.ndarray) -> MatchResult:
    th, tw = template.shape
    template_zero = template - template.mean()
    template_norm = float(np.sqrt(np.sum(template_zero * template_zero)))
    if template_norm < 1e-6:
        raise RuntimeError("模板内容过于单一，请裁剪包含文字、图标或边框的区域。")

    numerator = _fft_convolve_valid(image, template_zero[::-1, ::-1])
    window_area = float(th * tw)
    image_sum = _window_sum(image, th, tw)
    image_sum_sq = _window_sum(image * image, th, tw)
    image_norm = np.sqrt(np.maximum(image_sum_sq - image_sum * image_sum / window_area, 0.0))
    denominator = image_norm * template_norm
    scores = np.divide(numerator, denominator, out=np.full_like(numerator, -1.0), where=denominator > 1e-8)
    scores[image_norm < (template_norm * 0.08)] = -1.0
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


def _fft_convolve_valid(image: np.ndarray, kernel: np.ndarray) -> np.ndarray:
    """NumPy-only equivalent of scipy.signal.fftconvolve(..., mode='valid')."""
    image_height, image_width = image.shape
    kernel_height, kernel_width = kernel.shape
    if kernel_height > image_height or kernel_width > image_width:
        raise ValueError("卷积模板不能大于截图。")

    full_shape = (
        image_height + kernel_height - 1,
        image_width + kernel_width - 1,
    )
    image_fft = np.fft.rfft2(image, full_shape)
    kernel_fft = np.fft.rfft2(kernel, full_shape)
    full = np.fft.irfft2(image_fft * kernel_fft, full_shape)
    return full[
        kernel_height - 1 : image_height,
        kernel_width - 1 : image_width,
    ]
