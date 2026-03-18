"""
DeOldify 기반 흑백 사진 채색.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image
from loguru import logger


def is_grayscale(image: Image.Image, threshold: float = 0.05) -> bool:
    """이미지가 흑백인지 판단한다."""
    img_rgb = image.convert("RGB")
    img_arr = np.array(img_rgb)
    
    r = img_arr[:, :, 0].astype(float)
    g = img_arr[:, :, 1].astype(float)
    b = img_arr[:, :, 2].astype(float)
    
    rg_diff = np.abs(r - g).mean()
    rb_diff = np.abs(r - b).mean()
    gb_diff = np.abs(g - b).mean()
    
    avg_diff = (rg_diff + rb_diff + gb_diff) / 3
    max_val = 255.0
    
    return (avg_diff / max_val) < threshold


def colorize_image(
    image: Image.Image,
    render_factor: int = 35,
    artistic: bool = True,
) -> Image.Image:
    """DeOldify로 흑백 이미지를 채색한다."""
    try:
        from deoldify import device
        from deoldify.visualize import get_image_colorizer
        
        logger.info("DeOldify 초기화 중...")
        colorizer = get_image_colorizer(artistic=artistic)
        
        temp_path = Path("/tmp/temp_bw_input.jpg")
        image.convert("RGB").save(temp_path, "JPEG", quality=95)
        
        logger.info(f"흑백 이미지 채색 중... (render_factor={render_factor})")
        colorized = colorizer.get_transformed_image(
            str(temp_path),
            render_factor=render_factor,
            watermarked=False,
        )
        
        temp_path.unlink(missing_ok=True)
        
        logger.info("채색 완료")
        return colorized
        
    except ImportError:
        logger.warning("DeOldify가 설치되지 않음 — pip install deoldify")
        return image
    except Exception as exc:
        logger.error(f"DeOldify 채색 실패: {exc}")
        return image


def auto_colorize_if_needed(
    image: Image.Image,
    force: bool = False,
    render_factor: int = 35,
) -> tuple[Image.Image, bool]:
    """흑백 이미지를 자동 감지하고 채색한다.
    
    Returns:
        (colorized_image, was_colorized)
    """
    if force or is_grayscale(image):
        logger.info("흑백 이미지 감지 → 자동 채색")
        colorized = colorize_image(image, render_factor=render_factor)
        return colorized, True
    
    return image, False
