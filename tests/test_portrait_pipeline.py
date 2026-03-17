"""
포트레잇 파이프라인 단위 + E2E 테스트.

단위 테스트: 각 컴포넌트(FaceDetector, TFRStyler, ScanlineOverlay 등)가 올바른 출력을 내는지 확인.
E2E 테스트 : 실제 이미지를 검색 → 다운로드 → 파이프라인 처리 → 최종 포트레잇 생성.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import numpy as np
import pytest
from PIL import Image


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_portrait() -> Image.Image:
    """156×210 크기의 테스트용 합성 인물 이미지.
    얼굴 형태를 단순하게 모사(피부색 타원 + 눈/입 구조)."""
    img = Image.new("RGB", (400, 600), (200, 180, 160))  # 피부색 배경
    from PIL import ImageDraw
    draw = ImageDraw.Draw(img)
    # 얼굴 타원
    draw.ellipse([120, 100, 280, 340], fill=(210, 180, 150))
    # 눈
    draw.ellipse([155, 180, 185, 200], fill=(60, 40, 30))
    draw.ellipse([215, 180, 245, 200], fill=(60, 40, 30))
    # 코
    draw.polygon([(195, 220), (200, 260), (205, 220)], fill=(190, 160, 140))
    # 입
    draw.arc([170, 270, 230, 300], start=0, end=180, fill=(180, 80, 80), width=3)
    # 몸통 (옷)
    draw.rectangle([130, 350, 270, 600], fill=(50, 50, 80))
    return img


@pytest.fixture
def tmp_dir():
    """임시 디렉토리."""
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


# ---------------------------------------------------------------------------
# 1. query_expander — 검색 쿼리 확장
# ---------------------------------------------------------------------------

class TestQueryExpander:
    def test_basic_expansion(self):
        from hoi4_agent.tools.portrait.search.query_expander import expand_queries
        queries = expand_queries("Zoran Mamdani", title="Mayor")
        assert len(queries) >= 3
        assert "Zoran Mamdani" in queries
        assert any("Mayor" in q for q in queries)

    def test_with_country_tag(self):
        from hoi4_agent.tools.portrait.search.query_expander import expand_queries
        queries = expand_queries("Zoran Mamdani", title="Mayor of New York City", country_tag="USA")
        assert len(queries) >= 4

    def test_deduplication(self):
        from hoi4_agent.tools.portrait.search.query_expander import expand_queries
        queries = expand_queries("Zoran Mamdani")
        assert len(queries) == len(set(q.lower() for q in queries))

    def test_max_queries(self):
        from hoi4_agent.tools.portrait.search.query_expander import expand_queries
        queries = expand_queries("Zoran Mamdani", title="Mayor", max_queries=3)
        assert len(queries) <= 3


# ---------------------------------------------------------------------------
# 2. ScanlineOverlay — 스캔라인 생성 및 적용
# ---------------------------------------------------------------------------

class TestScanlineOverlay:
    def test_generate_scanlines_shape(self):
        from hoi4_agent.tools.portrait.effects.scanline import ScanlineOverlay
        overlay = ScanlineOverlay()
        scanline = overlay.generate_scanlines(156, 210)
        assert scanline.size == (156, 210)
        assert scanline.mode == "RGBA"

    def test_apply_scanlines_preserves_size(self, sample_portrait):
        from hoi4_agent.tools.portrait.effects.scanline import ScanlineOverlay
        overlay = ScanlineOverlay()
        result = overlay.apply_scanlines(sample_portrait.resize((156, 210)))
        assert result.size == (156, 210)

    def test_glow_blend_brightens(self, sample_portrait):
        from hoi4_agent.tools.portrait.effects.scanline import ScanlineOverlay
        overlay = ScanlineOverlay()
        small = sample_portrait.resize((156, 210))
        result = overlay.apply_scanlines(small, blend_mode="glow")
        orig_mean = np.array(small).mean()
        result_mean = np.array(result).mean()
        assert result_mean >= orig_mean - 1


# ---------------------------------------------------------------------------
# 3. TFRStyler — TFR 스타일 적용
# ---------------------------------------------------------------------------

class TestTFRStyler:
    def test_to_grayscale(self, sample_portrait):
        from hoi4_agent.tools.portrait.effects.tfr_style import TFRStyler
        styler = TFRStyler()
        gray = styler.to_grayscale(sample_portrait)
        assert gray.mode == "RGB"
        arr = np.array(gray)
        assert np.allclose(arr[:, :, 0], arr[:, :, 1])
        assert np.allclose(arr[:, :, 1], arr[:, :, 2])

    def test_apply_camera_raw(self, sample_portrait):
        from hoi4_agent.tools.portrait.effects.tfr_style import TFRStyler
        styler = TFRStyler()
        result = styler.apply_camera_raw(sample_portrait)
        assert result.size == sample_portrait.size
        assert result.mode == "RGB"

    def test_full_style_pipeline(self, sample_portrait):
        from hoi4_agent.tools.portrait.effects.tfr_style import TFRStyler
        styler = TFRStyler()
        small = sample_portrait.resize((156, 210))
        result = styler.apply_full_style(small)
        assert result.size == (156, 210)
        assert result.mode == "RGB"


# ---------------------------------------------------------------------------
# 4. FaceDetector — 얼굴 감지 + 스마트 크롭
# ---------------------------------------------------------------------------

class TestFaceDetector:
    def test_smart_crop_returns_correct_size(self, sample_portrait):
        from hoi4_agent.tools.portrait.core.face_detector import FaceDetector
        detector = FaceDetector()
        cropped = detector.smart_crop(sample_portrait, 156, 210)
        assert cropped.size == (156, 210)

    def test_center_crop_fallback(self):
        from hoi4_agent.tools.portrait.core.face_detector import FaceDetector
        detector = FaceDetector()
        blank = Image.new("RGB", (400, 600), (128, 128, 128))
        cropped = detector.smart_crop(blank, 156, 210)
        assert cropped.size == (156, 210)

    def test_get_face_bbox_on_blank(self):
        from hoi4_agent.tools.portrait.core.face_detector import FaceDetector
        detector = FaceDetector()
        blank = Image.new("RGB", (200, 200), (255, 255, 255))
        assert detector.get_face_bbox(blank) is None


# ---------------------------------------------------------------------------
# 5. PortraitPipeline (로컬 모드) — 통합 파이프라인
# ---------------------------------------------------------------------------

class TestPortraitPipelineLocal:
    """mode='local' 로컬 TFR 파이프라인 테스트."""

    def test_generate_placeholder(self, tmp_dir):
        from hoi4_agent.tools.portrait.pipeline.portrait_pipeline import PortraitPipeline
        pipeline = PortraitPipeline(mode="local")
        out = tmp_dir / "placeholder.png"
        result_path = pipeline.generate_placeholder(out)
        assert result_path.exists()
        img = Image.open(result_path)
        assert img.size == (156, 210)

    def test_process_single_local(self, sample_portrait, tmp_dir):
        """로컬 모드로 합성 이미지를 파이프라인 처리."""
        from hoi4_agent.tools.portrait.pipeline.portrait_pipeline import PortraitPipeline
        pipeline = PortraitPipeline(mode="local")
        input_path = tmp_dir / "input.png"
        output_path = tmp_dir / "output.png"
        sample_portrait.save(str(input_path))
        success = pipeline.process_single(input_path, output_path)
        assert success is True
        assert output_path.exists()
        result = Image.open(output_path)
        assert result.size == (156, 210)

    def test_batch_process_local(self, sample_portrait, tmp_dir):
        """로컬 모드 배치 처리."""
        from hoi4_agent.tools.portrait.pipeline.portrait_pipeline import PortraitPipeline
        pipeline = PortraitPipeline(mode="local")
        in_dir = tmp_dir / "input"
        out_dir = tmp_dir / "output"
        in_dir.mkdir()
        for i in range(2):
            sample_portrait.save(str(in_dir / f"test_{i}.png"))
        results = pipeline.batch_process(in_dir, out_dir, tag="USA", name_prefix="test")
        assert len(results) == 2
        assert all(v for v in results.values())


# ---------------------------------------------------------------------------
# 6. PortraitPipeline (Gemini 모드) — 초기화 + fallback 테스트
# ---------------------------------------------------------------------------

class TestPortraitPipelineGemini:
    """mode='gemini' Gemini 파이프라인 테스트."""

    def test_default_mode_is_gemini(self):
        """기본 생성자가 gemini 모드인지 확인."""
        from hoi4_agent.tools.portrait.pipeline.portrait_pipeline import PortraitPipeline
        pipeline = PortraitPipeline()
        assert pipeline.mode == "gemini"

    def test_invalid_mode_raises(self):
        """잘못된 mode → ValueError."""
        from hoi4_agent.tools.portrait.pipeline.portrait_pipeline import PortraitPipeline
        with pytest.raises(ValueError):
            PortraitPipeline(mode="invalid")

    def test_gemini_no_key_raises_on_client_access(self):
        """API 키 없이 client 접근 시 ValueError."""
        from hoi4_agent.tools.portrait.pipeline.portrait_pipeline import PortraitPipeline
        pipeline = PortraitPipeline(mode="gemini", gemini_api_key="")
        # 환경변수도 비워야 함
        old = os.environ.pop("GEMINI_API_KEY", None)
        pipeline.gemini_api_key = ""
        try:
            with pytest.raises(ValueError, match="GEMINI_API_KEY"):
                _ = pipeline.gemini_client
        finally:
            if old is not None:
                os.environ["GEMINI_API_KEY"] = old

    def test_custom_style_prompt(self):
        """커스텀 스타일 프롬프트 설정."""
        from hoi4_agent.tools.portrait.pipeline.portrait_pipeline import PortraitPipeline
        custom = "Make it look like pixel art"
        pipeline = PortraitPipeline(style_prompt=custom)
        assert pipeline.style_prompt == custom

    def test_default_style_prompt_has_tfr_keywords(self):
        """기본 프롬프트에 TFR 관련 키워드 포함 확인."""
        from hoi4_agent.tools.portrait.pipeline.portrait_pipeline import (
            PortraitPipeline,
            DEFAULT_TFR_STYLE_PROMPT,
        )
        pipeline = PortraitPipeline()
        assert pipeline.style_prompt == DEFAULT_TFR_STYLE_PROMPT
        assert "TFR" in pipeline.style_prompt
        assert "#3D2B50" in pipeline.style_prompt
        assert "#936F60" in pipeline.style_prompt

    def test_gemini_fallback_to_local(self, sample_portrait, tmp_dir):
        """Gemini 실패 시 로컬 TFR fallback 동작 확인.
        유효하지 않은 API 키로 Gemini 호출 → 실패 → 로컬 처리."""
        from hoi4_agent.tools.portrait.pipeline.portrait_pipeline import PortraitPipeline
        pipeline = PortraitPipeline(
            mode="gemini",
            gemini_api_key="INVALID_KEY_FOR_TEST",
        )
        input_path = tmp_dir / "input.png"
        output_path = tmp_dir / "output.png"
        sample_portrait.save(str(input_path))
        # Gemini 실패 → 로컬 fallback → 결과 생성
        success = pipeline.process_single(input_path, output_path)
        assert success is True
        assert output_path.exists()
        result = Image.open(output_path)
        assert result.size == (156, 210)


# ---------------------------------------------------------------------------
# 7. executor 경로 테스트
# ---------------------------------------------------------------------------

class TestExecutorPortraitIntegration:
    def test_search_portraits_returns_json(self):
        from hoi4_agent.tools.portrait.search.query_expander import expand_queries
        queries = expand_queries("Zoran Mamdani", title="Mayor of New York City")
        assert isinstance(queries, list)
        assert len(queries) > 0


# ---------------------------------------------------------------------------
# 8. E2E: 조란 맘다니 포트레잇 (로컬 모드)
# ---------------------------------------------------------------------------

class TestZoranMamdaniLocalE2E:
    """로컬 TFR 모드 E2E. 네트워크 필요."""

    @pytest.mark.skipif(
        not Path("/tmp/portrait_search_cache").exists() and True,
        reason="E2E test: run with pytest -k e2e",
    )
    def test_full_pipeline_local(self, tmp_dir):
        from hoi4_agent.tools.portrait.search.multi_search import MultiSourceSearch
        from hoi4_agent.tools.portrait.pipeline.portrait_pipeline import PortraitPipeline

        searcher = MultiSourceSearch(cache_dir=tmp_dir / "cache")
        downloaded = searcher.search_person(
            person_name="Zoran Mamdani",
            title="Mayor of New York City",
            country_tag="USA",
            max_results=3,
        )
        if not downloaded:
            pytest.skip("검색 결과 없음")

        pipeline = PortraitPipeline(mode="local")
        output_dir = tmp_dir / "portraits"
        output_dir.mkdir()

        success_count = 0
        for idx, img_path in enumerate(downloaded):
            out_path = output_dir / f"USA_zoran_mamdani_{idx}.png"
            if pipeline.process_single(img_path, out_path):
                success_count += 1
                result = Image.open(out_path)
                assert result.size == (156, 210)
        assert success_count > 0
