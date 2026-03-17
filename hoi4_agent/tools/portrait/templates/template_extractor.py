"""
기존 포트레잇에서 군복/모자 템플릿 자동 추출.
이미 TFR 스타일로 처리된 포트레잇에서 얼굴 영역을 제거하고
군복/의상 부분만 투명 PNG로 저장한다.
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
from PIL import Image
from loguru import logger

try:
    from hoi4_agent.tools.shared.constants import PORTRAIT_WIDTH, PORTRAIT_HEIGHT
except ImportError:
    PORTRAIT_WIDTH = 156
    PORTRAIT_HEIGHT = 210

from hoi4_agent.tools.portrait.core.face_detector import FaceDetector
from hoi4_agent.tools.portrait.core.region_masks import (
    FACE_OVAL,
    landmarks_to_points,
)


class TemplateExtractor:
    """기존 포트레잇에서 의상/모자 템플릿을 추출한다."""

    def __init__(self) -> None:
        self.face_detector = FaceDetector()

    # ------------------------------------------------------------------
    # 군복(의상) 템플릿 추출
    # ------------------------------------------------------------------

    def extract_uniform(
        self,
        portrait_path: Path,
        output_path: Path,
        margin: int = 8,
    ) -> bool:
        """포트레잇에서 군복/의상 템플릿을 추출한다.

        얼굴 영역(+ margin)을 투명으로 만들어 의상 부분만 남긴다.

        Args:
            portrait_path: 기존 처리된 포트레잇 경로 (156×210).
            output_path: 출력 경로 (RGBA PNG).
            margin: 얼굴 마스크 확장 픽셀 수.

        Returns:
            성공 시 ``True``.
        """
        try:
            img = Image.open(portrait_path).convert("RGB")
        except Exception as exc:
            logger.error(f"이미지 로드 실패: {portrait_path} — {exc}")
            return False

        landmarks = self.face_detector.detect_landmarks(img)
        if landmarks is None:
            logger.warning(f"얼굴 감지 실패: {portrait_path.name}")
            return False

        img_w, img_h = img.size

        # 얼굴 윤곽 마스크 생성
        face_points = landmarks_to_points(landmarks, FACE_OVAL, img_w, img_h)
        face_mask = np.zeros((img_h, img_w), dtype=np.uint8)
        cv2.fillConvexPoly(face_mask, face_points, 255)

        # 마스크 확장 (margin) — 얼굴 주변 여백 확보
        if margin > 0:
            kernel = cv2.getStructuringElement(
                cv2.MORPH_ELLIPSE, (margin * 2, margin * 2)
            )
            face_mask = cv2.dilate(face_mask, kernel, iterations=1)

        # 마스크 페더링 (부드러운 경계)
        face_mask = cv2.GaussianBlur(face_mask, (11, 11), 0)

        # 알파 채널: 얼굴 = 투명, 의상 = 불투명
        alpha = 255 - face_mask

        # RGBA 이미지 생성
        img_arr = np.array(img)
        rgba = np.dstack([img_arr, alpha])
        result = Image.fromarray(rgba, "RGBA")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        result.save(str(output_path), "PNG")
        logger.info(f"군복 템플릿 추출: {portrait_path.name} → {output_path}")
        return True

    # ------------------------------------------------------------------
    # 모자/헬멧 템플릿 추출
    # ------------------------------------------------------------------

    def extract_headgear(
        self,
        portrait_path: Path,
        output_path: Path,
    ) -> bool:
        """포트레잇에서 모자/헬멧 영역만 추출한다.

        눈썹 위 + 얼굴 윤곽 상단 영역을 추출.

        Returns:
            성공 시 ``True``.
        """
        try:
            img = Image.open(portrait_path).convert("RGB")
        except Exception as exc:
            logger.error(f"이미지 로드 실패: {portrait_path} — {exc}")
            return False

        landmarks = self.face_detector.detect_landmarks(img)
        if landmarks is None:
            logger.warning(f"얼굴 감지 실패: {portrait_path.name}")
            return False

        img_w, img_h = img.size

        # 눈썹 상단 Y 좌표 (랜드마크 10=이마 중앙 상단, 67/297=눈썹 양끝)
        forehead_indices = [10, 67, 109, 103, 54, 21, 162, 338, 297, 332, 284, 251]
        forehead_y = min(int(landmarks[i].y * img_h) for i in forehead_indices)

        # 모자 영역 = 이마 위 전체
        hat_mask = np.zeros((img_h, img_w), dtype=np.uint8)
        hat_mask[:forehead_y + 5, :] = 255  # 이마 약간 아래까지

        # 얼굴 윤곽 바깥만 남기기 (이마 안쪽은 제거)
        face_points = landmarks_to_points(landmarks, FACE_OVAL, img_w, img_h)
        face_inner = np.zeros((img_h, img_w), dtype=np.uint8)
        cv2.fillConvexPoly(face_inner, face_points, 255)

        # 페더링
        hat_mask = cv2.GaussianBlur(hat_mask, (7, 7), 0)

        # RGBA
        img_arr = np.array(img)
        rgba = np.dstack([img_arr, hat_mask])
        result = Image.fromarray(rgba, "RGBA")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        result.save(str(output_path), "PNG")
        logger.info(f"모자 템플릿 추출: {portrait_path.name} → {output_path}")
        return True

    # ------------------------------------------------------------------
    # 배치 추출 (국가 태그별)
    # ------------------------------------------------------------------

    def batch_extract_by_tag(
        self,
        leaders_dir: Path,
        output_dir: Path,
        tag: str,
    ) -> dict[str, bool]:
        """특정 국가 태그의 모든 포트레잇에서 군복 템플릿을 추출한다.

        Args:
            leaders_dir: ``gfx/Leaders/`` 디렉토리.
            output_dir: 템플릿 출력 디렉토리.
            tag: 국가 태그 (예: "AFG", "USA").

        Returns:
            ``{파일명: 성공 여부}``
        """
        tag_dir = leaders_dir / tag
        if not tag_dir.exists():
            logger.error(f"디렉토리 없음: {tag_dir}")
            return {}

        results: dict[str, bool] = {}
        out_tag_dir = output_dir / tag
        out_tag_dir.mkdir(parents=True, exist_ok=True)

        for path in sorted(tag_dir.glob("*.png")):
            # generals 하위 디렉토리 건너뛰기
            if "generals" in str(path):
                continue
            out = out_tag_dir / f"{path.stem}_uniform.png"
            results[path.name] = self.extract_uniform(path, out)

        success = sum(1 for v in results.values() if v)
        logger.info(f"[{tag}] 군복 템플릿 추출: {success}/{len(results)}")
        return results

    def batch_extract_all(
        self,
        leaders_dir: Path,
        output_dir: Path,
    ) -> dict[str, dict[str, bool]]:
        """전체 국가의 포트레잇에서 군복 템플릿을 추출한다."""
        all_results: dict[str, dict[str, bool]] = {}
        for tag_dir in sorted(leaders_dir.iterdir()):
            if tag_dir.is_dir() and tag_dir.name.isupper():
                tag = tag_dir.name
                all_results[tag] = self.batch_extract_by_tag(
                    leaders_dir, output_dir, tag
                )
        return all_results
