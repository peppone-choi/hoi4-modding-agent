"""
초상화 신원 검증 모듈.

검색된 이미지가 올바른 인물인지 자동으로 검증한다.

검증 전략:
  1단계: Wikipedia 메인 이미지를 레퍼런스로 확보
  2단계: 레퍼런스 vs 후보 얼굴 임베딩 비교 (face_recognition)
  3단계: 레퍼런스 없으면 다수결 합의 (후보끼리 비교)
  4단계: OpenCV 히스토그램 fallback (face_recognition 없을 때)

사용법:
    verifier = PortraitVerifier()
    results = verifier.verify_candidates(
        person_name="Donald Trump",
        candidate_paths=[Path("candidate1.jpg"), Path("candidate2.jpg")],
        country_tag="USA",
    )
    for r in results:
        print(f"{r.path}: verified={r.verified}, score={r.score:.2f}")
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image
from loguru import logger

# FaceDetector는 mediapipe 의존 — 없으면 Haar Cascade 직접 사용
try:
    from hoi4_agent.tools.portrait.core.face_detector import FaceDetector
    _HAS_FACE_DETECTOR = True
except ImportError:
    _HAS_FACE_DETECTOR = False
    logger.warning("FaceDetector 로드 실패 (mediapipe 없음) — Haar Cascade 직접 사용")

# ImageFetcher도 안전하게 임포트
try:
    from hoi4_agent.tools.portrait.core.image_fetcher import ImageFetcher
    _HAS_IMAGE_FETCHER = True
except ImportError:
    _HAS_IMAGE_FETCHER = False
    logger.warning("ImageFetcher 로드 실패 — Wikipedia 레퍼런스 기능 비활성화")

# face_recognition은 선택적 의존성
try:
    import face_recognition as fr

    _HAS_FACE_RECOGNITION = True
    logger.info("face_recognition 라이브러리 사용 가능 — 임베딩 기반 검증 활성화")
except ImportError:
    _HAS_FACE_RECOGNITION = False
    logger.warning("face_recognition 없음 — OpenCV 히스토그램 fallback 사용")


# ── 설정 ──────────────────────────────────────────────────────────────

EMBEDDING_THRESHOLD = 0.45       # face_recognition 유클리드 거리 임계값 (낮을수록 엄격)
HISTOGRAM_THRESHOLD = 0.35       # 히스토그램 상관 임계값 (높을수록 엄격, fallback용 완화)
CONSENSUS_MIN_MATCHES = 2        # 다수결 합의에 필요한 최소 매칭 수
MIN_FACE_SIZE = 50               # 최소 얼굴 크기 (px)


@dataclass
class VerificationResult:
    """검증 결과."""

    path: Path
    verified: bool
    score: float               # 0.0~1.0 (1.0 = 완전 일치)
    method: str                 # "embedding", "histogram", "consensus", "unverified"
    reason: str = ""


class PortraitVerifier:
    """초상화 신원 검증기."""

    def __init__(
        self,
        embedding_threshold: float = EMBEDDING_THRESHOLD,
        histogram_threshold: float = HISTOGRAM_THRESHOLD,
    ):
        self.embedding_threshold = embedding_threshold
        self.histogram_threshold = histogram_threshold
        # FaceDetector는 __init__에서 mediapipe를 로드하므로 이중 방어
        self._face_detector = None
        if _HAS_FACE_DETECTOR:
            try:
                self._face_detector = FaceDetector()
            except Exception:
                logger.warning("FaceDetector 초기화 실패 — Haar Cascade fallback")
        self._image_fetcher = None
        if _HAS_IMAGE_FETCHER:
            try:
                self._image_fetcher = ImageFetcher()
            except Exception:
                logger.warning("ImageFetcher 초기화 실패 — Wikipedia 레퍼런스 비활성화")
        # Haar Cascade fallback (FaceDetector 없을 때 직접 사용)
        self._haar_cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        )

    # ------------------------------------------------------------------
    # 메인 API
    # ------------------------------------------------------------------

    def verify_candidates(
        self,
        person_name: str,
        candidate_paths: list[Path],
        country_tag: str = "",
        reference_image: Image.Image | None = None,
    ) -> list[VerificationResult]:
        """후보 이미지들을 검증한다.

        Args:
            person_name: 인물 영문명.
            candidate_paths: 후보 이미지 파일 경로 리스트.
            country_tag: HOI4 국가 태그 (Wikipedia 검색 보조).
            reference_image: 이미 확보된 레퍼런스 이미지 (없으면 Wikipedia에서 가져옴).

        Returns:
            각 후보에 대한 VerificationResult 리스트.
        """
        if not candidate_paths:
            return []

        # 1. 레퍼런스 이미지 확보
        ref_img = reference_image
        if ref_img is None:
            ref_img = self._fetch_wikipedia_reference(person_name)

        # 2. 검증 수행
        if ref_img is not None:
            return self._verify_against_reference(ref_img, candidate_paths)
        else:
            logger.info(f"'{person_name}' Wikipedia 레퍼런스 없음 → 다수결 합의 모드")
            return self._verify_by_consensus(candidate_paths)

    def get_best_candidate(
        self,
        person_name: str,
        candidate_paths: list[Path],
        country_tag: str = "",
    ) -> Path | None:
        """가장 신뢰도 높은 검증된 후보를 반환한다.

        Returns:
            검증된 최고 점수 후보의 경로, 없으면 None.
        """
        results = self.verify_candidates(person_name, candidate_paths, country_tag)
        verified = [r for r in results if r.verified]
        if not verified:
            logger.warning(f"'{person_name}' 검증된 후보 없음")
            return None
        best = max(verified, key=lambda r: r.score)
        logger.info(f"'{person_name}' 최적 후보: {best.path.name} (score={best.score:.2f}, method={best.method})")
        return best.path

    # ------------------------------------------------------------------
    # Wikipedia 레퍼런스 확보
    # ------------------------------------------------------------------

    def _fetch_wikipedia_reference(self, person_name: str) -> Image.Image | None:
        """Wikipedia에서 인물 메인 이미지를 레퍼런스로 가져온다.

        레퍼런스는 얼굴 비교 전용(비배포)이므로 라이선스 체크를 건너뛴다.
        """
        if self._image_fetcher is None:
            logger.debug("ImageFetcher 미사용 — Wikipedia 레퍼런스 건너뜀")
            return None
        try:
            import requests as _req
            from io import BytesIO as _BytesIO

            # Wikipedia API에서 메인 이미지 URL 직접 조회 (라이선스 체크 없이)
            api_url = "https://en.wikipedia.org/w/api.php"
            params = {
                "action": "query",
                "titles": person_name,
                "prop": "pageimages",
                "piprop": "original",
                "format": "json",
            }
            self._image_fetcher._throttle()
            resp = self._image_fetcher.session.get(api_url, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()

            pages = data.get("query", {}).get("pages", {})
            source_url = ""
            for page in pages.values():
                original = page.get("original", {})
                source_url = original.get("source", "")
                if source_url:
                    break

            if not source_url:
                logger.debug(f"Wikipedia 이미지 URL 없음: {person_name}")
                return None

            # 이미지 다운로드 (검증 레퍼런스 전용)
            self._image_fetcher._throttle()
            img_resp = self._image_fetcher.session.get(source_url, timeout=30)
            img_resp.raise_for_status()

            img = Image.open(_BytesIO(img_resp.content)).convert("RGB")
            # 얼굴 감지 확인
            if self._get_face_bbox(img) is None:
                logger.debug(f"Wikipedia 이미지에서 얼굴 감지 실패: {person_name}")
                return None
            logger.info(f"Wikipedia 레퍼런스 확보 (검증 전용): {person_name}")
            return img
        except Exception as exc:
            logger.error(f"Wikipedia 레퍼런스 확보 실패: {person_name} — {exc}")
            return None

    # ------------------------------------------------------------------
    # 레퍼런스 기반 검증 (face_recognition / histogram)
    # ------------------------------------------------------------------

    def _verify_against_reference(
        self, ref_img: Image.Image, candidate_paths: list[Path]
    ) -> list[VerificationResult]:
        """레퍼런스 이미지와 각 후보를 비교한다."""
        if _HAS_FACE_RECOGNITION:
            return self._verify_embedding(ref_img, candidate_paths)
        else:
            return self._verify_histogram(ref_img, candidate_paths)

    def _verify_embedding(
        self, ref_img: Image.Image, candidate_paths: list[Path]
    ) -> list[VerificationResult]:
        """face_recognition 임베딩 기반 검증."""
        ref_arr = np.array(ref_img)
        ref_encodings = fr.face_encodings(ref_arr)
        if not ref_encodings:
            logger.warning("레퍼런스 이미지에서 얼굴 인코딩 실패 → 히스토그램 fallback")
            return self._verify_histogram(ref_img, candidate_paths)

        ref_encoding = ref_encodings[0]
        results: list[VerificationResult] = []

        for path in candidate_paths:
            try:
                cand_img = Image.open(path).convert("RGB")
                cand_arr = np.array(cand_img)
                cand_encodings = fr.face_encodings(cand_arr)

                if not cand_encodings:
                    results.append(VerificationResult(
                        path=path, verified=False, score=0.0,
                        method="embedding", reason="얼굴 인코딩 실패",
                    ))
                    continue

                # 유클리드 거리 계산 (낮을수록 유사)
                distance = float(fr.face_distance([ref_encoding], cand_encodings[0])[0])
                # 거리를 0~1 점수로 변환 (1 = 동일)
                score = max(0.0, 1.0 - distance)
                verified = distance <= self.embedding_threshold

                results.append(VerificationResult(
                    path=path, verified=verified, score=score,
                    method="embedding",
                    reason=f"distance={distance:.3f}, threshold={self.embedding_threshold}",
                ))
            except Exception as exc:
                results.append(VerificationResult(
                    path=path, verified=False, score=0.0,
                    method="embedding", reason=f"오류: {exc}",
                ))

        return results

    def _verify_histogram(
        self, ref_img: Image.Image, candidate_paths: list[Path]
    ) -> list[VerificationResult]:
        """OpenCV 히스토그램 비교 기반 검증 (fallback)."""
        ref_face = self._extract_face_region(ref_img)
        if ref_face is None:
            return [
                VerificationResult(
                    path=p, verified=False, score=0.0,
                    method="histogram", reason="레퍼런스 얼굴 추출 실패",
                )
                for p in candidate_paths
            ]

        ref_hist = self._calc_face_histogram(ref_face)
        results: list[VerificationResult] = []

        for path in candidate_paths:
            try:
                cand_img = Image.open(path).convert("RGB")
                cand_face = self._extract_face_region(cand_img)

                if cand_face is None:
                    results.append(VerificationResult(
                        path=path, verified=False, score=0.0,
                        method="histogram", reason="후보 얼굴 추출 실패",
                    ))
                    continue

                cand_hist = self._calc_face_histogram(cand_face)
                # 상관 계수 비교 (1.0 = 완전 일치)
                score = float(cv2.compareHist(ref_hist, cand_hist, cv2.HISTCMP_CORREL))
                score = max(0.0, score)
                verified = score >= self.histogram_threshold

                results.append(VerificationResult(
                    path=path, verified=verified, score=score,
                    method="histogram",
                    reason=f"correlation={score:.3f}, threshold={self.histogram_threshold}",
                ))
            except Exception as exc:
                results.append(VerificationResult(
                    path=path, verified=False, score=0.0,
                    method="histogram", reason=f"오류: {exc}",
                ))

        return results

    # ------------------------------------------------------------------
    # 다수결 합의 (레퍼런스 없을 때)
    # ------------------------------------------------------------------

    def _verify_by_consensus(
        self, candidate_paths: list[Path]
    ) -> list[VerificationResult]:
        """레퍼런스 없이 후보끼리 비교하여 다수결로 검증.

        3개 이상의 후보가 서로 유사하면 해당 그룹을 '검증됨'으로 판단.
        """
        if len(candidate_paths) < 2:
            return [
                VerificationResult(
                    path=p, verified=False, score=0.0,
                    method="consensus", reason="후보 부족 (최소 2개 필요)",
                )
                for p in candidate_paths
            ]

        # 얼굴 임베딩 또는 히스토그램 수집
        features: list[tuple[Path, Any]] = []
        for path in candidate_paths:
            try:
                img = Image.open(path).convert("RGB")
                feat = self._extract_feature(img)
                if feat is not None:
                    features.append((path, feat))
            except Exception:
                continue

        if len(features) < 2:
            return [
                VerificationResult(
                    path=p, verified=False, score=0.0,
                    method="consensus", reason="유효한 얼굴 후보 부족",
                )
                for p in candidate_paths
            ]

        # 유사도 행렬 구축
        n = len(features)
        similarity_matrix = np.zeros((n, n))
        for i in range(n):
            for j in range(i + 1, n):
                sim = self._compare_features(features[i][1], features[j][1])
                similarity_matrix[i][j] = sim
                similarity_matrix[j][i] = sim

        # 각 후보의 매칭 수 계산
        threshold = (1.0 - self.embedding_threshold) if _HAS_FACE_RECOGNITION else self.histogram_threshold
        match_counts = np.sum(similarity_matrix >= threshold, axis=1)

        # 결과 매핑
        feature_paths = {feat[0] for feat in features}
        results: list[VerificationResult] = []

        for path in candidate_paths:
            if path not in feature_paths:
                results.append(VerificationResult(
                    path=path, verified=False, score=0.0,
                    method="consensus", reason="얼굴 추출 실패",
                ))
                continue

            idx = next(i for i, (p, _) in enumerate(features) if p == path)
            count = int(match_counts[idx])
            avg_sim = float(np.mean([
                similarity_matrix[idx][j]
                for j in range(n) if j != idx and similarity_matrix[idx][j] > 0
            ])) if n > 1 else 0.0

            verified = count >= CONSENSUS_MIN_MATCHES
            results.append(VerificationResult(
                path=path, verified=verified, score=avg_sim,
                method="consensus",
                reason=f"matches={count}/{n-1}, avg_sim={avg_sim:.3f}, need>={CONSENSUS_MIN_MATCHES}",
            ))

        return results

    # ------------------------------------------------------------------
    # 피처 추출 헬퍼
    # ------------------------------------------------------------------

    def _extract_feature(self, img: Image.Image) -> Any:
        """이미지에서 비교용 피처를 추출한다."""
        if _HAS_FACE_RECOGNITION:
            arr = np.array(img)
            encodings = fr.face_encodings(arr)
            return encodings[0] if encodings else None
        else:
            face = self._extract_face_region(img)
            if face is None:
                return None
            return self._calc_face_histogram(face)

    def _compare_features(self, feat1: Any, feat2: Any) -> float:
        """두 피처 간 유사도를 반환 (0~1, 높을수록 유사)."""
        if _HAS_FACE_RECOGNITION:
            distance = float(fr.face_distance([feat1], feat2)[0])
            return max(0.0, 1.0 - distance)
        else:
            return max(0.0, float(cv2.compareHist(feat1, feat2, cv2.HISTCMP_CORREL)))

    def _get_face_bbox(self, img: Image.Image) -> tuple[int, int, int, int] | None:
        """얼굴 바운딩 박스 반환 (FaceDetector 또는 Haar Cascade)."""
        if self._face_detector is not None:
            return self._face_detector.get_face_bbox(img)
        # Haar Cascade fallback
        gray = cv2.cvtColor(np.array(img.convert("RGB")), cv2.COLOR_RGB2GRAY)
        faces = self._haar_cascade.detectMultiScale(
            gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30)
        )
        if len(faces) == 0:
            return None
        faces_sorted = sorted(faces, key=lambda f: f[2] * f[3], reverse=True)
        x, y, w, h = faces_sorted[0]
        return int(x), int(y), int(w), int(h)

    def _extract_face_region(self, img: Image.Image) -> np.ndarray | None:
        """이미지에서 얼굴 영역만 크롭하여 반환."""
        bbox = self._get_face_bbox(img)
        if bbox is None:
            return None
        x, y, w, h = bbox
        if w < MIN_FACE_SIZE or h < MIN_FACE_SIZE:
            return None
        # 여유 마진 추가 (20%)
        img_w, img_h = img.size
        margin = int(max(w, h) * 0.2)
        x1 = max(0, x - margin)
        y1 = max(0, y - margin)
        x2 = min(img_w, x + w + margin)
        y2 = min(img_h, y + h + margin)
        face_crop = img.crop((x1, y1, x2, y2))
        # 표준 크기로 리사이즈 (비교 일관성)
        face_arr = np.array(face_crop.resize((128, 128), Image.LANCZOS))
        return cv2.cvtColor(face_arr, cv2.COLOR_RGB2BGR)

    @staticmethod
    def _calc_face_histogram(face_bgr: np.ndarray) -> np.ndarray:
        """얼굴 영역의 HSV 히스토그램을 계산한다."""
        hsv = cv2.cvtColor(face_bgr, cv2.COLOR_BGR2HSV)
        hist = cv2.calcHist(
            [hsv], [0, 1], None, [50, 60],
            [0, 180, 0, 256],
        )
        cv2.normalize(hist, hist, 0, 1, cv2.NORM_MINMAX)
        return hist
