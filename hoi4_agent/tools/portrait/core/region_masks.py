"""
얼굴 부위별 마스크 정의.
Mediapipe Face Mesh 468 랜드마크 기반 영역 폴리곤.
"""
from __future__ import annotations

import cv2
import numpy as np
from PIL import Image

# ===== Mediapipe Face Mesh 랜드마크 인덱스 (부위별) =====

# 얼굴 윤곽 (face oval)
FACE_OVAL = [
    10, 338, 297, 332, 284, 251, 389, 356, 454, 323, 361, 288,
    397, 365, 379, 378, 400, 377, 152, 148, 176, 149, 150, 136,
    172, 58, 132, 93, 234, 127, 162, 21, 54, 103, 67, 109,
]

# 입술 (외곽)
LIPS_OUTER = [
    61, 146, 91, 181, 84, 17, 314, 405, 321, 375,
    291, 409, 270, 269, 267, 0, 37, 39, 40, 185,
]

# 왼쪽 눈
LEFT_EYE = [
    33, 246, 161, 160, 159, 158, 157, 173,
    133, 155, 154, 153, 145, 144, 163, 7,
]

# 오른쪽 눈
RIGHT_EYE = [
    362, 398, 384, 385, 386, 387, 388, 466,
    263, 249, 390, 373, 374, 380, 381, 382,
]

# 코 (콧대 + 콧볼)
NOSE_BRIDGE = [168, 6, 197, 195, 5, 4]
NOSE_TIP = [
    1, 2, 98, 327,
    326, 97, 99, 328,
    240, 460, 94, 19,
]

# 턱/아래턱 (face oval 하단부 - 입 아래)
JAW_LINE = [
    152, 148, 176, 149, 150, 136, 172, 58,
    132, 93, 234, 127,  # 왼쪽
    356, 454, 323, 361, 288, 397, 365, 379, 378, 400, 377,  # 오른쪽
]

# 볼 영역 (근사치 - 눈 아래 ~ 입 옆)
LEFT_CHEEK = [116, 117, 118, 119, 100, 36, 205, 187, 123, 50, 101, 47]
RIGHT_CHEEK = [345, 346, 347, 348, 329, 266, 425, 411, 352, 280, 330, 277]

# 이마 (face oval 상단 + 눈썹 위)
FOREHEAD_BOUNDARY = [
    10, 109, 67, 103, 54, 21, 162, 127,  # face oval 상단
    338, 297, 332, 284, 251,  # 오른쪽 상단
]


def landmarks_to_points(
    landmarks: list,
    indices: list[int],
    img_w: int,
    img_h: int,
) -> np.ndarray:
    """랜드마크 인덱스 리스트를 픽셀 좌표 배열로 변환."""
    points = []
    for idx in indices:
        lm = landmarks[idx]
        x = int(lm.x * img_w)
        y = int(lm.y * img_h)
        points.append([x, y])
    return np.array(points, dtype=np.int32)


def create_region_mask(
    img_w: int,
    img_h: int,
    landmarks: list,
    region_indices: list[int],
) -> np.ndarray:
    """특정 부위의 바이너리 마스크를 생성한다.

    Returns:
        (img_h, img_w) float32 마스크, 0.0~1.0.
    """
    points = landmarks_to_points(landmarks, region_indices, img_w, img_h)
    mask = np.zeros((img_h, img_w), dtype=np.float32)
    cv2.fillConvexPoly(mask, points, 1.0)
    return mask


def create_all_region_masks(
    img_w: int,
    img_h: int,
    landmarks: list,
) -> dict[str, np.ndarray]:
    """모든 얼굴 부위 마스크를 생성한다.

    Returns:
        ``{부위명: mask}`` 딕셔너리. 각 mask는 (img_h, img_w) float32.
    """
    masks: dict[str, np.ndarray] = {}

    # 얼굴 윤곽 (전체)
    masks["face_oval"] = create_region_mask(img_w, img_h, landmarks, FACE_OVAL)

    # 입술
    masks["lips"] = create_region_mask(img_w, img_h, landmarks, LIPS_OUTER)

    # 눈 (좌+우 합산)
    left_eye = create_region_mask(img_w, img_h, landmarks, LEFT_EYE)
    right_eye = create_region_mask(img_w, img_h, landmarks, RIGHT_EYE)
    masks["eyes"] = np.clip(left_eye + right_eye, 0, 1)

    # 코
    nose_pts = NOSE_BRIDGE + NOSE_TIP
    masks["nose"] = create_region_mask(img_w, img_h, landmarks, nose_pts)

    # 볼 (좌+우 합산)
    left_cheek = create_region_mask(img_w, img_h, landmarks, LEFT_CHEEK)
    right_cheek = create_region_mask(img_w, img_h, landmarks, RIGHT_CHEEK)
    masks["cheeks"] = np.clip(left_cheek + right_cheek, 0, 1)

    # 턱 (face oval 하단 영역)
    jaw_mask = create_region_mask(img_w, img_h, landmarks, JAW_LINE)
    # 턱은 입 아래 영역만
    lip_bottom = max(
        int(landmarks[idx].y * img_h) for idx in [17, 84, 181, 91, 146, 314, 405, 321]
    )
    jaw_mask[:lip_bottom, :] = 0
    masks["jaw"] = jaw_mask

    # 피부 = 얼굴 윤곽 - 눈 - 입술 - 코 - 턱
    skin = masks["face_oval"].copy()
    skin = skin - masks["eyes"] - masks["lips"] - masks["nose"] - masks["jaw"]
    masks["skin"] = np.clip(skin, 0, 1)

    return masks
