"""
초상화 생성 파이프라인 오케스트레이터.

두 가지 모드:
  - **gemini** (기본): 스마트 크롭 → 배경 제거 → Gemini 스타일 전사 → 스캔라인 → 저장
  - **local** :        스마트 크롭 → 배경 제거 → 부위별 TFR 스타일 → 스캔라인 → 보라 배경 합성 → 저장
"""
from __future__ import annotations

import os
from io import BytesIO
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from loguru import logger

from hoi4_agent.tools.portrait.core.face_detector import FaceDetector
from hoi4_agent.tools.portrait.effects.scanline import ScanlineOverlay
from hoi4_agent.tools.portrait.effects.tfr_style import TFRStyler

try:
    from hoi4_agent.tools.shared.constants import (
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

# Gemini에 보내는 크롭 크기 — 해상도가 높아야 스타일 전사 품질이 좋음
GEMINI_CROP_WIDTH = 500
GEMINI_CROP_HEIGHT = 678  # 156:210 비율 유지

# ── TFR 스타일 프롬프트 ──────────────────────────────────────────────
# Idenn의 TFR 초상화 튜토리얼 기반.
# Gemini에게 "HOI4 TFR 모드 포트레잇"이 무엇인지 최대한 명시적으로 설명.
DEFAULT_TFR_STYLE_PROMPT = (
    "Edit this portrait photo for a Hearts of Iron IV leader portrait. "
    "Keep it PHOTOREALISTIC — do NOT paint, stylize, or cartoonify.\n"
    "1. Preserve every facial detail, skin texture, hair, and clothing exactly.\n"
    "2. Desaturate ~40%. Shift color temperature slightly warm.\n"
    "3. Lower brightness ~10%, increase contrast ~20% for a moody feel.\n"
    "4. Replace the background with solid dark purple (#3D2B50).\n"
    "5. Do NOT alter the person's face, expression, clothing, or pose.\n"
    "6. Output a clean head-and-shoulders portrait with the purple background."
)


def _hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


class PortraitPipeline:
    """TFR 스타일 초상화 생성 파이프라인.

    Args:
        mode: ``"gemini"`` (Gemini 스타일 전사) 또는 ``"local"`` (로컬 TFR).
        gemini_api_key: Gemini API 키. ``None`` 이면 ``GEMINI_API_KEY`` 환경변수 사용.
        gemini_model: Gemini 이미지 생성 모델명.
        style_prompt: TFR 스타일 프롬프트. ``None`` 이면 기본 프롬프트 사용.
    """

    def __init__(
        self,
        mode: str = "gemini",
        gemini_api_key: str | None = None,
        gemini_model: str = "gemini-3.1-flash-image-preview",
        style_prompt: str | None = None,
    ) -> None:
        if mode not in ("gemini", "local"):
            raise ValueError(f"mode은 'gemini' 또는 'local'이어야 합니다: {mode!r}")

        self.mode = mode
        self.face_detector = FaceDetector()
        self.styler = TFRStyler()
        self.scanline = ScanlineOverlay()

        # Gemini 설정
        self.gemini_api_key = gemini_api_key or os.environ.get("GEMINI_API_KEY", "")
        self.gemini_model = gemini_model
        self.style_prompt = style_prompt or DEFAULT_TFR_STYLE_PROMPT
        self._gemini_client = None

    @property
    def gemini_client(self):
        """Gemini API 클라이언트 (지연 초기화)."""
        if self._gemini_client is None:
            if not self.gemini_api_key:
                raise ValueError(
                    "Gemini 모드에는 GEMINI_API_KEY가 필요합니다. "
                    "환경변수를 설정하거나 gemini_api_key를 전달하세요."
                )
            from google import genai
            self._gemini_client = genai.Client(api_key=self.gemini_api_key)
        return self._gemini_client

    # ------------------------------------------------------------------
    # 단일 이미지 처리 — 모드에 따라 분기
    # ------------------------------------------------------------------

    def process_single(self, input_path: Path, output_path: Path) -> bool:
        """이미지를 TFR 스타일 초상화로 변환한다.

        ``mode="gemini"`` 이면 Gemini 스타일 전사,
        ``mode="local"`` 이면 로컬 TFR 파이프라인을 사용한다.

        Returns:
            성공 시 ``True``.
        """
        if self.mode == "gemini":
            return self._process_gemini(input_path, output_path)
        return self._process_local(input_path, output_path)

    # ------------------------------------------------------------------
    # Gemini 파이프라인
    # ------------------------------------------------------------------

    def _process_gemini(self, input_path: Path, output_path: Path) -> bool:
        """Gemini 기반 TFR 포트레잇 생성.

        파이프라인:
        1. 원본 사진 → Gemini (컬러 그레이딩 + 보라 배경)
        2. Gemini 결과 → 스마트 크롭 (TFR 얼굴 비율)
        3. rembg 후처리 → 깨끗한 보라 배경 재합성
        4. 스캔라인 → 저장
        """
        from google.genai import types

        try:
            img = Image.open(input_path).convert("RGB")
        except Exception as exc:
            logger.error(f"이미지 로드 실패: {input_path} — {exc}")
            return False

        logger.info(
            f"[Gemini] 처리 시작: {input_path.name} ({img.size[0]}×{img.size[1]})"
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # 1. Gemini: 원본 사진 그대로 전달
        logger.info(f"[Gemini] 요청: {self.gemini_model}")
        styled = None
        try:
            response = self.gemini_client.models.generate_content(
                model=self.gemini_model,
                contents=[self.style_prompt, img],
                config=types.GenerateContentConfig(
                    response_modalities=["TEXT", "IMAGE"],
                ),
            )
            for part in response.parts:
                if part.inline_data is not None:
                    styled = Image.open(BytesIO(part.inline_data.data))
                    logger.info("[Gemini] 성공")
                    break
        except Exception as exc:
            logger.error(f"[Gemini] 실패: {exc}")

        if styled is None:
            logger.warning("[Gemini] 이미지 미반환 → 로컬 TFR fallback")
            return self._process_local(input_path, output_path)

        # 2. 스마트 크롭 (Gemini 결과에서 TFR 얼굴 비율로 크롭)
        styled_rgb = styled.convert("RGB")
        cropped = self.face_detector.smart_crop(
            styled_rgb, GEMINI_CROP_WIDTH, GEMINI_CROP_HEIGHT
        )

        # 3. rembg 후처리 → 고해상도에서 보라 배경 합성
        nobg = self._remove_background(cropped)
        person_mask = self._extract_person_mask(nobg)

        # rembg 마스크 검증 — 인물 영역이 10% 미만이면 rembg 실패로 판단
        mask_coverage = float(person_mask.mean())
        if mask_coverage < 0.10:
            logger.warning(
                f"[Gemini] rembg 마스크 부족 (coverage={mask_coverage:.1%}) → 마스크 없이 합성"
            )
            person_mask = np.ones_like(person_mask)

        nobg_path = output_path.parent / f"{output_path.stem}_nobg.png"
        nobg.resize((PORTRAIT_WIDTH, PORTRAIT_HEIGHT), Image.LANCZOS).save(
            str(nobg_path), "PNG"
        )

        final = self._composite_on_bg(cropped, person_mask)

        # 4. 스캔라인 (고해상도)
        final = self.scanline.apply_scanlines(final, blend_mode="glow")

        # 5. 최종 리사이즈 — 마지막에만 156×210
        final = final.resize((PORTRAIT_WIDTH, PORTRAIT_HEIGHT), Image.LANCZOS)
        final.save(str(output_path), "PNG")
        logger.info(f"[Gemini] 초상화 생성 완료: {output_path}")
        return True

    # ------------------------------------------------------------------
    # 로컬 TFR 파이프라인 (기존)
    # ------------------------------------------------------------------

    def _process_local(self, input_path: Path, output_path: Path) -> bool:
        """로컬 TFR 스타일 파이프라인 (Gemini 없이).

        파이프라인:
        1. 이미지 로드
        2. 스마트 크롭 (156×210)
        3. 배경 제거 + 인물 마스크
        4. 부위별 TFR 스타일 적용
        5. 스캔라인 오버레이
        6. 보라 배경 합성
        7. 저장
        """
        try:
            img = Image.open(input_path).convert("RGBA")
        except Exception as exc:
            logger.error(f"이미지 로드 실패: {input_path} — {exc}")
            return False

        logger.info(
            f"[Local] 처리 시작: {input_path.name} ({img.size[0]}×{img.size[1]})"
        )

        # 1. 스마트 크롭
        img_rgb = img.convert("RGB")
        img_cropped = self.face_detector.smart_crop(
            img_rgb, PORTRAIT_WIDTH, PORTRAIT_HEIGHT
        )

        # 2. 배경 제거 + 마스크
        img_cropped_nobg = self._remove_background(img_cropped)
        person_mask = self._extract_person_mask(img_cropped_nobg)

        import cv2 as _cv2
        kernel = _cv2.getStructuringElement(_cv2.MORPH_ELLIPSE, (5, 5))
        person_mask = _cv2.dilate(person_mask, kernel, iterations=2)

        # nobg 저장
        nobg_path = output_path.parent / f"{output_path.stem}_nobg.png"
        nobg_path.parent.mkdir(parents=True, exist_ok=True)
        img_cropped_nobg.save(str(nobg_path), "PNG")
        logger.info(f"배경 제거 이미지 저장: {nobg_path}")

        # 3. 부위별 마스크 + TFR 스타일
        region_masks, landmarks = self.face_detector.get_region_masks(img_cropped)

        if region_masks is not None:
            logger.info("부위별 TFR 스타일 적용")
            styled = self.styler.apply_regional_style(
                img_cropped, region_masks, person_mask
            )
        else:
            logger.warning("얼굴 감지 실패 → 단순 TFR 스타일 적용")
            styled = self.styler.apply_full_style(img_cropped)

        # 4. 스캔라인
        styled = self.scanline.apply_scanlines(styled, blend_mode="glow")

        # 5. 보라 배경 합성
        styled = self._composite_on_bg(styled, person_mask)

        # 6. 저장
        output_path.parent.mkdir(parents=True, exist_ok=True)
        styled.save(str(output_path), "PNG")
        logger.info(f"[Local] 초상화 생성 완료: {output_path}")
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
            from hoi4_agent.tools.portrait.rembg_wrapper import remove_background
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
