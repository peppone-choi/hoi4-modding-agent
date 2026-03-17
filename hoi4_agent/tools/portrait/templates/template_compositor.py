"""
의상 템플릿 합성기.
배경 제거된 얼굴 + 군복/의상 템플릿을 합성한다.
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
from PIL import Image
from loguru import logger

try:
    from tools.shared.constants import PORTRAIT_WIDTH, PORTRAIT_HEIGHT
except ImportError:
    PORTRAIT_WIDTH = 156
    PORTRAIT_HEIGHT = 210

from tools.portrait_generator.core.face_detector import FaceDetector
from tools.portrait_generator.core.region_masks import (
    FACE_OVAL,
    landmarks_to_points,
)


class TemplateCompositor:
    """얼굴 + 의상 템플릿 합성."""

    def __init__(self) -> None:
        self.face_detector = FaceDetector()

    # ------------------------------------------------------------------
    # 얼굴 + 군복 합성
    # ------------------------------------------------------------------

    def composite(
        self,
        face_image: Image.Image,
        uniform_template: Image.Image,
        hat_template: Image.Image | None = None,
    ) -> Image.Image:
        """배경 제거된 얼굴을 군복 템플릿 위에 합성한다.

        Args:
            face_image: 인물 이미지 (RGB, 156×210, 크롭 완료).
            uniform_template: 군복 템플릿 (RGBA, 156×210, 얼굴 부분 투명).
            hat_template: 모자 템플릿 (RGBA, 156×210). Optional.

        Returns:
            합성된 RGB 이미지 (156×210).
        """
        # 크기 맞추기
        face = face_image.convert("RGBA").resize(
            (PORTRAIT_WIDTH, PORTRAIT_HEIGHT), Image.LANCZOS
        )
        uniform = uniform_template.convert("RGBA").resize(
            (PORTRAIT_WIDTH, PORTRAIT_HEIGHT), Image.LANCZOS
        )

        # 얼굴에서 face mesh로 얼굴 영역 마스크 생성
        landmarks = self.face_detector.detect_landmarks(face_image)

        if landmarks is not None:
            # 정확한 얼굴-군복 경계 생성
            result = self._composite_with_landmarks(face, uniform, landmarks)
        else:
            # fallback: 단순 알파 합성
            logger.debug("얼굴 감지 실패 → 단순 합성")
            result = Image.alpha_composite(uniform, face)

        # 모자/헬멧 추가
        if hat_template is not None:
            hat = hat_template.convert("RGBA").resize(
                (PORTRAIT_WIDTH, PORTRAIT_HEIGHT), Image.LANCZOS
            )
            result = Image.alpha_composite(result, hat)

        return result.convert("RGB")

    # ------------------------------------------------------------------
    # 랜드마크 기반 정밀 합성
    # ------------------------------------------------------------------

    def _composite_with_landmarks(
        self,
        face: Image.Image,
        uniform: Image.Image,
        landmarks: list,
    ) -> Image.Image:
        """랜드마크 기반으로 얼굴과 군복을 정밀 합성한다.

        전략:
        - 얼굴 윤곽 안쪽 = face 이미지 사용
        - 얼굴 윤곽 바깥 = uniform 템플릿 사용
        - 경계는 페더링으로 자연스럽게 블렌딩
        """
        img_w, img_h = PORTRAIT_WIDTH, PORTRAIT_HEIGHT

        # 얼굴 마스크 생성
        face_points = landmarks_to_points(landmarks, FACE_OVAL, img_w, img_h)
        face_mask = np.zeros((img_h, img_w), dtype=np.float32)
        cv2.fillConvexPoly(face_mask, face_points, 1.0)

        # 마스크 확장 (얼굴 + 목 영역 포함)
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (10, 10))
        face_mask = cv2.dilate(face_mask, kernel, iterations=1)

        # 페더링 (부드러운 경계)
        face_mask = cv2.GaussianBlur(face_mask, (15, 15), 0)

        # 블렌딩
        face_arr = np.array(face.convert("RGB"), dtype=np.float64)
        uniform_arr = np.array(uniform.convert("RGB"), dtype=np.float64)

        mask_3d = face_mask[:, :, np.newaxis]
        result_arr = face_arr * mask_3d + uniform_arr * (1 - mask_3d)
        result = Image.fromarray(np.clip(result_arr, 0, 255).astype(np.uint8))

        return result.convert("RGBA")

    # ------------------------------------------------------------------
    # 편의 메서드
    # ------------------------------------------------------------------

    def composite_from_paths(
        self,
        face_path: Path,
        uniform_path: Path,
        output_path: Path,
        hat_path: Path | None = None,
    ) -> bool:
        """파일 경로 기반 합성."""
        try:
            face = Image.open(face_path)
            uniform = Image.open(uniform_path)
            hat = Image.open(hat_path) if hat_path else None
        except Exception as exc:
            logger.error(f"이미지 로드 실패: {exc}")
            return False

        result = self.composite(face, uniform, hat)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        result.save(str(output_path), "PNG")
        logger.info(f"합성 완료: {output_path}")
        return True

    def find_best_template(
        self,
        templates_dir: Path,
        tag: str,
        template_type: str = "uniform",
    ) -> Path | None:
        """국가 태그에 맞는 최적 템플릿을 찾는다.

        우선순위:
        1. TAG별 전용 템플릿 (예: AFG_military_uniform.png)
        2. 태그 디렉토리의 첫 번째 템플릿
        3. generic 템플릿

        Args:
            templates_dir: 템플릿 디렉토리.
            tag: 국가 태그.
            template_type: "uniform" 또는 "hat".

        Returns:
            템플릿 경로 또는 ``None``.
        """
        # 1. TAG별 전용
        tag_dir = templates_dir / tag
        if tag_dir.exists():
            candidates = sorted(tag_dir.glob(f"*_{template_type}.png"))
            if candidates:
                return candidates[0]

        # 2. generic
        generic = templates_dir / f"generic_{template_type}.png"
        if generic.exists():
            return generic

        return None
