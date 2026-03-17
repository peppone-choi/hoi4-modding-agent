"""
얼굴 감지 및 스마트 크롭.
Mediapipe Face Mesh (468 랜드마크)를 사용하여 얼굴을 감지하고
부위별 마스크를 생성하며, HOI4 초상화 규격(156×210)으로 크롭한다.
"""
from __future__ import annotations

import cv2
import numpy as np
from PIL import Image
from loguru import logger

try:
    from tools.shared.constants import PORTRAIT_WIDTH, PORTRAIT_HEIGHT
except ImportError:
    PORTRAIT_WIDTH = 156
    PORTRAIT_HEIGHT = 210

from tools.portrait_generator.core.region_masks import (
    FACE_OVAL,
    create_all_region_masks,
    landmarks_to_points,
)


class FaceDetector:
    """Mediapipe Face Mesh 기반 얼굴 감지 + 부위별 마스크 + 스마트 크롭."""

    def __init__(self) -> None:
        import mediapipe as mp
        self._face_mesh = mp.solutions.face_mesh.FaceMesh(
            static_image_mode=True,
            max_num_faces=1,
            refine_landmarks=True,
            min_detection_confidence=0.5,
        )
        # fallback용 OpenCV Haar Cascade
        self._haar_cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        )

    # ------------------------------------------------------------------
    # 얼굴 감지 (Mediapipe)
    # ------------------------------------------------------------------

    def detect_landmarks(self, image: Image.Image) -> list | None:
        """이미지에서 얼굴 랜드마크 468개를 반환한다.

        Returns:
            landmark 리스트 (468개) 또는 감지 실패 시 ``None``.
        """
        img_rgb = np.array(image.convert("RGB"))
        results = self._face_mesh.process(img_rgb)
        if not results.multi_face_landmarks:
            return None
        return results.multi_face_landmarks[0].landmark

    # ------------------------------------------------------------------
    # 부위별 마스크 생성
    # ------------------------------------------------------------------

    def get_region_masks(
        self, image: Image.Image
    ) -> tuple[dict[str, np.ndarray], list] | tuple[None, None]:
        """이미지에서 얼굴 부위별 마스크를 생성한다.

        Returns:
            ``(masks_dict, landmarks)`` 또는 감지 실패 시 ``(None, None)``.
        """
        landmarks = self.detect_landmarks(image)
        if landmarks is None:
            logger.debug("Mediapipe 얼굴 감지 실패")
            return None, None

        img_w, img_h = image.size
        masks = create_all_region_masks(img_w, img_h, landmarks)
        return masks, landmarks

    # ------------------------------------------------------------------
    # 얼굴 바운딩 박스 (크롭용)
    # ------------------------------------------------------------------

    def get_face_bbox(
        self, image: Image.Image
    ) -> tuple[int, int, int, int] | None:
        """얼굴 바운딩 박스를 반환한다.

        Mediapipe 우선, 실패 시 Haar Cascade fallback.

        Returns:
            ``(x, y, w, h)`` 또는 ``None``.
        """
        landmarks = self.detect_landmarks(image)
        if landmarks is not None:
            img_w, img_h = image.size
            points = landmarks_to_points(landmarks, FACE_OVAL, img_w, img_h)
            x, y, w, h = cv2.boundingRect(points)
            return int(x), int(y), int(w), int(h)

        # Haar Cascade fallback
        gray = cv2.cvtColor(np.array(image.convert("RGB")), cv2.COLOR_RGB2GRAY)
        faces = self._haar_cascade.detectMultiScale(
            gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30)
        )
        if len(faces) == 0:
            return None
        faces_sorted = sorted(faces, key=lambda f: f[2] * f[3], reverse=True)
        x, y, w, h = faces_sorted[0]
        return int(x), int(y), int(w), int(h)

    # ------------------------------------------------------------------
    # 스마트 크롭
    # ------------------------------------------------------------------

    def smart_crop(
        self,
        image: Image.Image,
        target_w: int = PORTRAIT_WIDTH,
        target_h: int = PORTRAIT_HEIGHT,
    ) -> Image.Image:
        """얼굴 기반 스마트 크롭. 얼굴이 상단 ~30%에 위치하도록 조정."""
        face = self.get_face_bbox(image)
        if face is None:
            logger.debug("얼굴 감지 실패 → 중앙 크롭 fallback")
            return self._center_crop(image, target_w, target_h)

        fx, fy, fw, fh = face
        img_w, img_h = image.size
        aspect = target_w / target_h

        # 얼굴 중심
        face_cx = fx + fw // 2
        face_cy = fy + fh // 2

        # 크롭 영역: 얼굴이 프레임의 ~49% 높이를 차지하도록 (TFR 기준)
        target_face_h_ratio = 0.492
        crop_h = min(int(fh / target_face_h_ratio), img_h)
        crop_w = int(crop_h * aspect)
        if crop_w > img_w:
            crop_w = img_w
            crop_h = int(crop_w / aspect)

        # 얼굴 중심이 Y 51% 위치에 오도록 (TFR 기준)
        desired_face_y = int(crop_h * 0.508)
        crop_y = face_cy - desired_face_y
        crop_x = face_cx - crop_w // 2

        # 경계 클램핑
        crop_x = max(0, min(crop_x, img_w - crop_w))
        crop_y = max(0, min(crop_y, img_h - crop_h))

        cropped = image.crop((crop_x, crop_y, crop_x + crop_w, crop_y + crop_h))
        return cropped.resize((target_w, target_h), Image.LANCZOS)

    # ------------------------------------------------------------------
    # Fallback
    # ------------------------------------------------------------------

    @staticmethod
    def _center_crop(
        image: Image.Image,
        target_w: int = PORTRAIT_WIDTH,
        target_h: int = PORTRAIT_HEIGHT,
    ) -> Image.Image:
        """중앙 크롭 fallback."""
        img_w, img_h = image.size
        aspect = target_w / target_h
        current_aspect = img_w / img_h

        if current_aspect > aspect:
            new_w = int(img_h * aspect)
            offset = (img_w - new_w) // 2
            cropped = image.crop((offset, 0, offset + new_w, img_h))
        else:
            new_h = int(img_w / aspect)
            cropped = image.crop((0, 0, img_w, new_h))

        return cropped.resize((target_w, target_h), Image.LANCZOS)
