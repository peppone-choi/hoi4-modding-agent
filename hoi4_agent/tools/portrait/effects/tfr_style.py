"""
TFR 스타일 이미지 이펙트.
Idenn의 TFR 초상화 튜토리얼 기반.
B&W 변환 → Camera Raw → 부위별 Overlay 컬러라이제이션 → 가우시안 블러 레이어.

부위별 색상 (Overlay 블렌드):
  - 피부(기본): #936F60, 100%
  - 입술:       #936B60, 100%
  - 볼:         #936B60, 40-80%
  - 턱:         #706560, 40-80%
  - 눈 흰자:    #898989, 100%
  - 코:         #936258, 20-40%
"""
from __future__ import annotations

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter
from loguru import logger


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


# TFR 상수
try:
    from tools.shared.constants import (
        SKIN_COLOR_HEX,
        LIP_COLOR_HEX,
        JAW_COLOR_HEX,
        EYE_COLOR_HEX,
        NOSE_COLOR_HEX,
        GAUSSIAN_BLUR_RADIUS_1,
        GAUSSIAN_BLUR_RADIUS_3,
        GAUSSIAN_BLUR_OPACITY_3,
    )
except ImportError:
    SKIN_COLOR_HEX = "#936F60"
    LIP_COLOR_HEX = "#936B60"
    JAW_COLOR_HEX = "#706560"
    EYE_COLOR_HEX = "#898989"
    NOSE_COLOR_HEX = "#936258"
    GAUSSIAN_BLUR_RADIUS_1 = 10.0
    GAUSSIAN_BLUR_RADIUS_3 = 2.0
    GAUSSIAN_BLUR_OPACITY_3 = 0.9

# 부위별 색상 + 투명도 설정
REGION_COLORS: dict[str, tuple[tuple[int, int, int], float]] = {
    "skin":   (_hex_to_rgb(SKIN_COLOR_HEX), 1.0),     # 피부 기본
    "lips":   (_hex_to_rgb(LIP_COLOR_HEX),  1.0),     # 입술
    "cheeks": (_hex_to_rgb(LIP_COLOR_HEX),  0.6),     # 볼 (40-80% → 60%)
    "jaw":    (_hex_to_rgb(JAW_COLOR_HEX),  0.6),     # 턱 (40-80% → 60%)
    "eyes":   (_hex_to_rgb(EYE_COLOR_HEX),  1.0),     # 눈 흰자
    "nose":   (_hex_to_rgb(NOSE_COLOR_HEX), 0.3),     # 코 (20-40% → 30%)
}


class TFRStyler:
    """TFR 스타일 이미지 이펙트 파이프라인."""

    # ------------------------------------------------------------------
    # 전체 파이프라인 (단순 — 얼굴 마스크 없이 전체 적용)
    # ------------------------------------------------------------------

    def apply_full_style(self, image: Image.Image) -> Image.Image:
        """전체 TFR 스타일 적용 (단순 모드, 마스크 없음)."""
        img = self.to_grayscale(image)
        img = self.apply_camera_raw(img)
        img = self.colorize_uniform(img)
        img = self.apply_gaussian_layers(img)
        return img

    # ------------------------------------------------------------------
    # 부위별 파이프라인 (핵심 — 얼굴 마스크 기반)
    # ------------------------------------------------------------------

    def apply_regional_style(
        self,
        image: Image.Image,
        region_masks: dict[str, np.ndarray],
        person_mask: np.ndarray | None = None,
    ) -> Image.Image:
        """부위별 TFR 스타일 적용.

        Args:
            image: 원본 RGB 이미지.
            region_masks: ``{부위명: mask}`` (face_detector에서 생성).
            person_mask: 인물 영역 마스크 (rembg alpha). None이면 전체.

        Returns:
            스타일이 적용된 이미지.
        """
        img_arr = np.array(image.convert("RGB"), dtype=np.float64)
        img_w, img_h = image.size

        # 1. 그레이스케일 변환 (얼굴 영역용)
        gray = np.array(self.to_grayscale(image), dtype=np.float64)

        # 2. Camera Raw 적용 (그레이스케일에)
        gray_pil = Image.fromarray(gray.astype(np.uint8))
        gray_raw = np.array(self.apply_camera_raw(gray_pil), dtype=np.float64)

        # 3. 얼굴 영역: B&W + Camera Raw 기반
        face_mask = region_masks.get("face_oval")
        if face_mask is not None:
            face_mask_3d = face_mask[:, :, np.newaxis]
            # 얼굴 영역은 B&W Camera Raw 처리된 것으로 교체
            result = img_arr * (1 - face_mask_3d) + gray_raw * face_mask_3d
        else:
            result = gray_raw.copy()

        # 4. 부위별 Overlay 컬러라이제이션
        for region_name, (color, opacity) in REGION_COLORS.items():
            mask = region_masks.get(region_name)
            if mask is None:
                continue
            result = self._apply_overlay_to_region(result, mask, color, opacity)

        # 5. 옷 영역: 원본 색상 유지 + 채도↓ + 어둡게
        if person_mask is not None and face_mask is not None:
            clothes_mask = np.clip(person_mask - face_mask, 0, 1)
            result = self._process_clothes(img_arr, result, clothes_mask)

        # 6. 가우시안 블러
        result_pil = Image.fromarray(np.clip(result, 0, 255).astype(np.uint8))
        result_pil = self.apply_gaussian_layers(result_pil)

        return result_pil

    # ------------------------------------------------------------------
    # 1. 그레이스케일 변환
    # ------------------------------------------------------------------

    def to_grayscale(self, image: Image.Image) -> Image.Image:
        """RGB → 그레이스케일 (3채널 유지)."""
        return image.convert("L").convert("RGB")

    # ------------------------------------------------------------------
    # 2. Camera Raw 시뮬레이션
    # ------------------------------------------------------------------

    def apply_camera_raw(self, image: Image.Image) -> Image.Image:
        """Contrast, Brightness, Sharpness 조정."""
        img = ImageEnhance.Contrast(image).enhance(1.3)
        img = ImageEnhance.Brightness(img).enhance(1.15)
        img = ImageEnhance.Sharpness(img).enhance(1.2)
        return img

    # ------------------------------------------------------------------
    # 3. 단일색 컬러라이제이션 (단순 모드)
    # ------------------------------------------------------------------

    def colorize_uniform(self, image: Image.Image) -> Image.Image:
        """전체 이미지에 스킨톤 Overlay 블렌드."""
        skin_rgb = _hex_to_rgb(SKIN_COLOR_HEX)
        skin_layer = Image.new("RGB", image.size, skin_rgb)
        return self._blend_overlay_pil(image, skin_layer)

    # ------------------------------------------------------------------
    # 4. 가우시안 블러 레이어
    # ------------------------------------------------------------------

    def apply_gaussian_layers(self, image: Image.Image) -> Image.Image:
        """TFR 블러 레이어 체인."""
        # Layer 1: Soft Light
        blurred_1 = image.filter(ImageFilter.GaussianBlur(radius=GAUSSIAN_BLUR_RADIUS_1))
        img = self._blend_soft_light(image, blurred_1)

        # Layer 3: Normal at 90%
        blurred_3 = img.filter(ImageFilter.GaussianBlur(radius=GAUSSIAN_BLUR_RADIUS_3))
        img = Image.blend(img, blurred_3, alpha=GAUSSIAN_BLUR_OPACITY_3)

        return img

    # ------------------------------------------------------------------
    # 부위별 Overlay 적용 (numpy 배열 기반)
    # ------------------------------------------------------------------

    def _apply_overlay_to_region(
        self,
        base_arr: np.ndarray,
        mask: np.ndarray,
        color: tuple[int, int, int],
        opacity: float,
    ) -> np.ndarray:
        """특정 부위에 Overlay 블렌드로 색상을 적용한다.

        Args:
            base_arr: (H, W, 3) float64 배열.
            mask: (H, W) float32 마스크.
            color: RGB 색상.
            opacity: 적용 강도 (0.0~1.0).
        """
        b = base_arr / 255.0
        o = np.array(color, dtype=np.float64) / 255.0

        # Overlay 블렌드
        overlay_result = np.where(
            b < 0.5,
            2.0 * b * o,
            1.0 - 2.0 * (1.0 - b) * (1.0 - o),
        )
        overlay_result *= 255.0

        # 마스크 + opacity로 블렌딩
        mask_3d = (mask * opacity)[:, :, np.newaxis]
        result = base_arr * (1 - mask_3d) + overlay_result * mask_3d
        return result

    # ------------------------------------------------------------------
    # 옷 처리 (원본 색상 보존 + 채도↓ + 어둡게)
    # ------------------------------------------------------------------

    @staticmethod
    def _process_clothes(
        original_arr: np.ndarray,
        current_arr: np.ndarray,
        clothes_mask: np.ndarray,
        desaturation: float = 0.4,
        darken: float = 0.80,
    ) -> np.ndarray:
        """옷 영역: 원본 색상 유지하되 채도를 낮추고 어둡게.

        Args:
            original_arr: 원본 이미지 (H,W,3) float64.
            current_arr: 현재 처리된 이미지.
            clothes_mask: 옷 영역 마스크.
            desaturation: 채도 감소량 (0=원본, 1=완전 회색).
            darken: 밝기 배수 (1=원본, 0=검정).
        """
        # 원본의 그레이스케일
        gray = np.mean(original_arr, axis=2, keepdims=True)
        # 채도 낮춤: original * (1-desat) + gray * desat
        desaturated = original_arr * (1 - desaturation) + gray * desaturation
        # 어둡게
        darkened = desaturated * darken

        mask_3d = clothes_mask[:, :, np.newaxis]
        result = current_arr * (1 - mask_3d) + darkened * mask_3d
        return result

    # ------------------------------------------------------------------
    # 블렌드 모드 (PIL 기반)
    # ------------------------------------------------------------------

    @staticmethod
    def _blend_overlay_pil(base: Image.Image, overlay: Image.Image) -> Image.Image:
        """Overlay 블렌드 모드 (PIL Image)."""
        b = np.array(base, dtype=np.float64) / 255.0
        o = np.array(overlay, dtype=np.float64) / 255.0
        result = np.where(
            b < 0.5,
            2.0 * b * o,
            1.0 - 2.0 * (1.0 - b) * (1.0 - o),
        )
        result = np.clip(result * 255, 0, 255).astype(np.uint8)
        return Image.fromarray(result)

    @staticmethod
    def _blend_soft_light(base: Image.Image, overlay: Image.Image) -> Image.Image:
        """Soft Light 블렌드 모드."""
        b = np.array(base, dtype=np.float64) / 255.0
        o = np.array(overlay, dtype=np.float64) / 255.0
        mask = o < 0.5
        result = np.where(
            mask,
            b - (1 - 2 * o) * b * (1 - b),
            b + (2 * o - 1) * (np.sqrt(b) - b),
        )
        result = np.clip(result * 255, 0, 255).astype(np.uint8)
        return Image.fromarray(result)

    @staticmethod
    def _blend_multiply(base: Image.Image, overlay: Image.Image) -> Image.Image:
        """Multiply 블렌드 모드."""
        b = np.array(base, dtype=np.float64)
        o = np.array(overlay, dtype=np.float64)
        result = np.clip(b * o / 255.0, 0, 255).astype(np.uint8)
        return Image.fromarray(result)
