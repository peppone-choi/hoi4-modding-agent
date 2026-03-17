"""
Wikimedia Commons 이미지 페처.
Wikipedia/Wikimedia Commons에서 인물 사진을 다운로드하고 라이선스를 확인한다.
"""
from __future__ import annotations

import time
from io import BytesIO
from pathlib import Path
from typing import Any

import requests
from loguru import logger

from tools.shared.constants import (
    WIKIMEDIA_COMMONS_API_URL,
    WIKIPEDIA_API_URL,
    WIKI_USER_AGENT,
    WIKI_RATE_LIMIT_DELAY,
    ALLOWED_LICENSES,
)


class ImageFetcher:
    """Wikimedia Commons 이미지 다운로더."""

    def __init__(self, rate_limit: float = WIKI_RATE_LIMIT_DELAY):
        self.rate_limit = rate_limit
        self._last_request = 0.0
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": WIKI_USER_AGENT})

    # ------------------------------------------------------------------
    # 내부 헬퍼
    # ------------------------------------------------------------------

    def _throttle(self) -> None:
        elapsed = time.time() - self._last_request
        if elapsed < self.rate_limit:
            time.sleep(self.rate_limit - elapsed)

    def _api_get(self, url: str, params: dict) -> dict:
        self._throttle()
        params.setdefault("format", "json")
        resp = self.session.get(url, params=params, timeout=30)
        resp.raise_for_status()
        self._last_request = time.time()
        return resp.json()

    # ------------------------------------------------------------------
    # 퍼블릭 API
    # ------------------------------------------------------------------

    def get_image_url(self, filename: str, width: int = 500) -> str:
        """Commons 파일의 썸네일 URL 반환."""
        if not filename.startswith("File:"):
            filename = f"File:{filename}"
        data = self._api_get(WIKIMEDIA_COMMONS_API_URL, {
            "action": "query",
            "titles": filename,
            "prop": "imageinfo",
            "iiprop": "url",
            "iiurlwidth": str(width),
        })
        pages = data.get("query", {}).get("pages", {})
        for page in pages.values():
            ii = page.get("imageinfo", [{}])[0]
            return ii.get("thumburl", ii.get("url", ""))
        return ""

    def check_license(self, filename: str) -> tuple[bool, str]:
        """이미지 라이선스 확인. ``(허용 여부, 라이선스명)``."""
        if not filename.startswith("File:"):
            filename = f"File:{filename}"
        data = self._api_get(WIKIMEDIA_COMMONS_API_URL, {
            "action": "query",
            "titles": filename,
            "prop": "imageinfo",
            "iiprop": "extmetadata",
        })
        pages = data.get("query", {}).get("pages", {})
        for page in pages.values():
            meta = page.get("imageinfo", [{}])[0].get("extmetadata", {})
            license_short = meta.get("LicenseShortName", {}).get("value", "")
            license_url = meta.get("LicenseUrl", {}).get("value", "")
            allowed = any(al.lower() in license_short.lower() for al in ALLOWED_LICENSES)
            return allowed, license_short
        return False, "unknown"

    def fetch_from_commons(self, filename: str, width: int = 500) -> bytes | None:
        """Commons에서 이미지 바이트 다운로드."""
        url = self.get_image_url(filename, width=width)
        if not url:
            logger.warning(f"이미지 URL을 찾을 수 없음: {filename}")
            return None
        self._throttle()
        try:
            resp = self.session.get(url, timeout=30)
            resp.raise_for_status()
            self._last_request = time.time()
            return resp.content
        except requests.RequestException as exc:
            logger.error(f"이미지 다운로드 실패: {filename} — {exc}")
            return None

    def fetch_person_image(self, person_name: str, lang: str = "en") -> tuple[bytes | None, str]:
        """인물명으로 Wikipedia에서 메인 이미지를 검색·다운로드한다.

        Returns:
            ``(이미지 바이트 | None, 라이선스명)``
        """
        api_url = WIKIPEDIA_API_URL if lang == "en" else f"https://{lang}.wikipedia.org/w/api.php"
        # 페이지의 메인 이미지 파일명 조회
        data = self._api_get(api_url, {
            "action": "query",
            "titles": person_name,
            "prop": "pageimages",
            "piprop": "original",
        })
        pages = data.get("query", {}).get("pages", {})
        for page in pages.values():
            original = page.get("original", {})
            source_url = original.get("source", "")
            if not source_url:
                continue
            # 파일명 추출
            filename = source_url.rsplit("/", 1)[-1]
            allowed, license_name = self.check_license(filename)
            if not allowed:
                logger.warning(f"라이선스 미허용: {filename} ({license_name})")
                return None, license_name
            image_bytes = self.fetch_from_commons(filename, width=500)
            return image_bytes, license_name
        return None, ""

    def save_raw_image(self, image_bytes: bytes, output_path: Path) -> Path:
        """원본 이미지를 지정 경로에 저장."""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(image_bytes)
        logger.info(f"이미지 저장: {output_path} ({len(image_bytes):,} bytes)")
        return output_path
