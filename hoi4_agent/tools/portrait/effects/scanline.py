"""
스캔라인 오버레이.
TFR 스타일 초상화에 CRT 스캔라인 효과를 적용한다.
Glow(Screen) 블렌드 모드 사용.
"""
from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw


class ScanlineOverlay:
    """스캔라인 오버레이 생성 및 적용."""

    def generate_scanlines(
        self,
        width: int,
        height: int,
        line_spacing: int = 3,
        opacity: float = 0.08,
    ) -> Image.Image:
        """스캔라인 패턴 이미지를 생성한다.

        Args:
            width: 이미지 너비.
            height: 이미지 높이.
            line_spacing: 라인 간격 (px).
            opacity: 라인 밝기 (0.0 ~ 1.0).

        Returns:
            RGBA 스캔라인 패턴 이미지.
        """
        scanline = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(scanline)
        line_alpha = int(255 * opacity)
        for y in range(0, height, line_spacing):
            draw.line([(0, y), (width, y)], fill=(255, 255, 255, line_alpha))
        return scanline

    def apply_scanlines(
        self,
        image: Image.Image,
        blend_mode: str = "glow",
        line_spacing: int = 3,
        opacity: float = 0.08,
    ) -> Image.Image:
        """이미지에 스캔라인 오버레이를 적용한다.

        Args:
            image: 원본 이미지.
            blend_mode: ``'glow'`` (Screen) 또는 ``'normal'``.
            line_spacing: 라인 간격.
            opacity: 라인 밝기.

        Returns:
            스캔라인이 적용된 이미지.
        """
        w, h = image.size
        scanline_img = self.generate_scanlines(w, h, line_spacing, opacity)

        if blend_mode == "glow":
            return self._blend_screen(image, scanline_img)

        # Normal blend fallback
        base_rgba = image.convert("RGBA")
        return Image.alpha_composite(base_rgba, scanline_img).convert("RGB")

    @staticmethod
    def _blend_screen(base: Image.Image, overlay: Image.Image) -> Image.Image:
        """Screen (Glow) 블렌드 모드.

        공식: ``result = 1 - (1 - base) * (1 - overlay)``
        """
        b = np.array(base.convert("RGB"), dtype=np.float64) / 255.0
        # 오버레이에서 알파 채널 추출
        o_rgba = np.array(overlay.convert("RGBA"), dtype=np.float64) / 255.0
        o_rgb = o_rgba[:, :, :3]
        o_alpha = o_rgba[:, :, 3:4]

        screened = 1.0 - (1.0 - b) * (1.0 - o_rgb)
        # 알파로 블렌딩
        result = b * (1.0 - o_alpha) + screened * o_alpha
        result = np.clip(result * 255, 0, 255).astype(np.uint8)
        return Image.fromarray(result)
