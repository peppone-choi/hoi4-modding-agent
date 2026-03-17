"""
초상화 생성 파이프라인 오케스트레이터.
원본 이미지 → 배경 제거 → 얼굴 감지 + 부위 마스크 → 스마트 크롭
→ 부위별 TFR 스타일 → 스캔라인 → 보라 배경 합성 → 저장.
"""
from __future__ import annotations

from io import BytesIO
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from loguru import logger

from tools.portrait_generator.core.face_detector import FaceDetector
from tools.portrait_generator.effects.scanline import ScanlineOverlay
from tools.portrait_generator.effects.tfr_style import TFRStyler

try:
    from tools.shared.constants import (
        GFX_LEADERS_DIR,
        PORTRAIT_HEIGHT,
        PORTRAIT_WIDTH,
        BG_COLOR_HEX,
    )
except ImportError:
    PORTRAIT_WIDTH = 156
    PORTRAIT_HEIGHT = 210
    GFX_LEADERS_DIR = Path("gfx/leaders")
    BG_COLOR_HEX = "#3D2B50"


def _hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


class PortraitPipeline:
    """TFR 스타일 초상화 생성 파이프라인."""

    def __init__(self) -> None:
        self.face_detector = FaceDetector()
        self.styler = TFRStyler()
        self.scanline = ScanlineOverlay()

    # ------------------------------------------------------------------
    # 단일 이미지 처리 (핵심)
    # ------------------------------------------------------------------

    def process_single(self, input_path: Path, output_path: Path) -> bool:
        """로컬 이미지를 TFR 스타일 초상화로 변환한다.

        전체 파이프라인:
        1. 이미지 로드
        2. 배경 제거 (rembg)
        3. 인물 마스크 추출
        4. 얼굴 감지 + 스마트 크롭
        5. 부위별 마스크 생성
        6. 부위별 TFR 스타일 적용 (옷 색상 보존)
        7. 스캔라인 오버레이
        8. 보라색 배경 합성
        9. 저장

        Returns:
            성공 시 ``True``.
        """
        try:
            img = Image.open(input_path).convert("RGBA")
        except Exception as exc:
            logger.error(f"이미지 로드 실패: {input_path} — {exc}")
            return False

        logger.info(f"처리 시작: {input_path.name} ({img.size[0]}×{img.size[1]})")

        # 1. 원본 RGB로 얼굴 감지 + 스마트 크롭 (배경 제거 전!)
        img_rgb = img.convert("RGB")
        img_cropped = self.face_detector.smart_crop(
            img_rgb, PORTRAIT_WIDTH, PORTRAIT_HEIGHT
        )

        # 2. 크롭된 이미지에서 배경 제거
        img_cropped_nobg = self._remove_background(img_cropped)
        person_mask = self._extract_person_mask(img_cropped_nobg)

        # 마스크 팽창(dilate) — rembg가 머리카락 등을 과하게 잘라내는 문제 보완
        import cv2 as _cv2
        kernel = _cv2.getStructuringElement(_cv2.MORPH_ELLIPSE, (5, 5))
        person_mask = _cv2.dilate(person_mask, kernel, iterations=2)

        # 배경 제거 이미지 별도 저장 (나중에 GFX용)
        nobg_path = output_path.parent / f"{output_path.stem}_nobg.png"
        img_cropped_nobg.save(str(nobg_path), "PNG")
        logger.info(f"배경 제거 이미지 저장: {nobg_path}")

        # 3. 부위별 마스크 생성 (원본 크롭 RGB에서 — 배경 있는 상태)
        region_masks, landmarks = self.face_detector.get_region_masks(img_cropped)

        # 4. 스타일 적용
        if region_masks is not None:
            # 부위별 처리 (얼굴 감지 성공)
            logger.info("부위별 TFR 스타일 적용")
            styled = self.styler.apply_regional_style(
                img_cropped, region_masks, person_mask
            )
        else:
            # 얼굴 감지 실패 → 단순 전체 스타일
            logger.warning("얼굴 감지 실패 → 단순 TFR 스타일 적용")
            styled = self.styler.apply_full_style(img_cropped)

        # 5. 스캔라인 오버레이
        styled = self.scanline.apply_scanlines(styled, blend_mode="glow")

        # 6. 보라색 배경 합성
        styled = self._composite_on_bg(styled, person_mask)

        # 7. 저장
        output_path.parent.mkdir(parents=True, exist_ok=True)
        styled.save(str(output_path), "PNG")
        logger.info(f"초상화 생성 완료: {output_path}")
        return True

    # ------------------------------------------------------------------
    # 배치 처리
    # ------------------------------------------------------------------

    def batch_process(
        self,
        input_dir: Path,
        output_dir: Path,
        tag: str = "",
        name_prefix: str = "",
    ) -> dict[str, bool]:
        """디렉토리의 모든 이미지를 일괄 처리한다.

        Args:
            input_dir: 원본 이미지 디렉토리.
            output_dir: 출력 디렉토리.
            tag: 국가 태그 (예: "USA"). 출력 파일명 접두사.
            name_prefix: 인물명 접두사 (예: "donald_trump").

        Returns:
            ``{파일명: 성공 여부}`` 딕셔너리.
        """
        results: dict[str, bool] = {}
        suffixes = {".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".webp"}
        files = sorted(
            p for p in input_dir.iterdir() if p.suffix.lower() in suffixes
        )

        for idx, path in enumerate(files):
            # 출력 파일명 생성
            if tag and name_prefix:
                suffix = "" if idx == 0 else str(idx)
                out_name = f"{tag}_{name_prefix}{suffix}.png"
            else:
                out_name = path.with_suffix(".png").name
            out = output_dir / out_name
            results[path.name] = self.process_single(path, out)

        return results

    # ------------------------------------------------------------------
    # 플레이스홀더
    # ------------------------------------------------------------------

    def generate_placeholder(self, output_path: Path) -> Path:
        """회색 실루엣 플레이스홀더 초상화를 생성한다."""
        img = Image.new("RGB", (PORTRAIT_WIDTH, PORTRAIT_HEIGHT), (60, 60, 60))
        draw = ImageDraw.Draw(img)
        cx, cy_head = PORTRAIT_WIDTH // 2, PORTRAIT_HEIGHT // 3
        r = PORTRAIT_WIDTH // 5
        draw.ellipse([cx - r, cy_head - r, cx + r, cy_head + r], fill=(90, 90, 90))
        shoulder_y = cy_head + r + 10
        draw.ellipse(
            [cx - r * 2, shoulder_y, cx + r * 2, shoulder_y + r * 3],
            fill=(80, 80, 80),
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        img.save(str(output_path), "PNG")
        logger.info(f"플레이스홀더 생성: {output_path}")
        return output_path

    # ------------------------------------------------------------------
    # 내부 헬퍼
    # ------------------------------------------------------------------

    @staticmethod
    def _remove_background(image: Image.Image) -> Image.Image:
        """rembg로 배경을 제거한다."""
        try:
            from tools.portrait_generator.rembg_wrapper import remove_background
            return remove_background(image)
        except Exception as exc:
            logger.debug(f"배경 제거 실패 — 원본 반환: {exc}")
            return image

    @staticmethod
    def _extract_person_mask(image: Image.Image) -> np.ndarray:
        """RGBA 이미지에서 인물 마스크(alpha)를 추출한다."""
        if image.mode == "RGBA":
            alpha = np.array(image.split()[3], dtype=np.float32) / 255.0
            return alpha
        return np.ones(
            (image.size[1], image.size[0]), dtype=np.float32
        )

    @staticmethod
    def _composite_on_bg(
        image: Image.Image,
        person_mask: np.ndarray,
        bg_color: str = BG_COLOR_HEX,
    ) -> Image.Image:
        """인물을 보라색 배경 위에 합성한다."""
        rgb = _hex_to_rgb(bg_color)
        img_arr = np.array(image.convert("RGB"), dtype=np.float64)
        bg_arr = np.full_like(img_arr, rgb, dtype=np.float64)

        mask_3d = person_mask[:, :, np.newaxis]
        result = bg_arr * (1 - mask_3d) + img_arr * mask_3d
        return Image.fromarray(np.clip(result, 0, 255).astype(np.uint8))
