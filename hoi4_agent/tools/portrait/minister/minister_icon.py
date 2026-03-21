"""
장관 아이콘 생성기.
156x210 리더 포트레잇에서 62x67 기울어진 사각형 장관 아이콘을 추출한다.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image
from loguru import logger

MINISTER_WIDTH = 62
MINISTER_HEIGHT = 67
ROTATION_ANGLE = 3.24

_BORDER_FRAME = None
_FRAME_MASK = None
_INNER_OFFSET = None


def _load_border_frame() -> Image.Image:
    global _BORDER_FRAME
    if _BORDER_FRAME is None:
        frame_path = Path(__file__).parent / "border_frame.png"
        _BORDER_FRAME = Image.open(frame_path).convert("RGBA")
    return _BORDER_FRAME


def _load_frame_mask() -> Image.Image:
    global _FRAME_MASK
    if _FRAME_MASK is None:
        mask_path = Path(__file__).parent / "frame_mask.png"
        _FRAME_MASK = Image.open(mask_path).convert("L")
    return _FRAME_MASK


def _load_inner_offset() -> tuple[float, float]:
    global _INNER_OFFSET
    if _INNER_OFFSET is None:
        offset_path = Path(__file__).parent / "inner_offset.npy"
        data = np.load(offset_path, allow_pickle=True).item()
        _INNER_OFFSET = (data['offset_x'], data['offset_y'])
    return _INNER_OFFSET


class MinisterIconGenerator:
    """장관 아이콘 생성기 (62x67 기울어진 사각형)."""
    
    def generate_from_portrait(
        self,
        portrait: Image.Image,
        crop_offset_x: int = 0,
        crop_offset_y: int = 0,
    ) -> Image.Image:
        portrait_rgb = portrait.convert("RGB")
        w, h = portrait_rgb.size
        
        aspect = MINISTER_WIDTH / MINISTER_HEIGHT
        crop_h = int(w / aspect)
        crop_w = w
        
        y_start = max(0, min(h - crop_h, crop_offset_y))
        y_end = y_start + crop_h
        x_start = max(0, min(w - crop_w, crop_offset_x))
        x_end = x_start + crop_w
        
        face_crop = portrait_rgb.crop((x_start, y_start, x_end, y_end))
        resized = face_crop.resize((MINISTER_WIDTH, MINISTER_HEIGHT), Image.Resampling.LANCZOS)
        
        rotated = self._rotate_image(resized, ROTATION_ANGLE)
        aligned = self._align_to_inner_area(rotated)
        minister_icon = self._apply_border_frame(aligned)
        
        logger.info(f"장관 아이콘 생성: {MINISTER_WIDTH}x{MINISTER_HEIGHT} (회전 {ROTATION_ANGLE}°, offset: x={crop_offset_x}, y={crop_offset_y})")
        return minister_icon
    
    @staticmethod
    def _rotate_image(image: Image.Image, angle: float) -> Image.Image:
        rgba = image.convert("RGBA")
        rotated = rgba.rotate(
            angle,
            resample=Image.Resampling.BICUBIC,
            expand=False,
            fillcolor=(0, 0, 0, 0)
        )
        return rotated
    
    @staticmethod
    def _align_to_inner_area(image: Image.Image) -> Image.Image:
        offset_x, offset_y = _load_inner_offset()
        
        result = Image.new("RGBA", (MINISTER_WIDTH, MINISTER_HEIGHT), (0, 0, 0, 0))
        
        paste_x = int(round(offset_x))
        paste_y = int(round(offset_y))
        
        result.paste(image, (paste_x, paste_y), image)
        
        return result
    
    @staticmethod
    def _apply_border_frame(image: Image.Image) -> Image.Image:
        rgba = image.convert("RGBA")
        frame_mask = _load_frame_mask()
        border_frame = _load_border_frame()
        
        rgba.putalpha(frame_mask)
        
        result = Image.alpha_composite(rgba, border_frame)
        
        return result
