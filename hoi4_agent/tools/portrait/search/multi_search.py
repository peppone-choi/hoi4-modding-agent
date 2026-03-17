"""
멀티소스 이미지 검색 오케스트레이터.
Google, Yandex, Bing, DuckDuckGo, Wikimedia Commons에서 병렬 검색 후
중복 제거 + 품질 필터링.
"""
from __future__ import annotations

import hashlib
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from io import BytesIO
from pathlib import Path
from typing import NamedTuple

import requests
from loguru import logger
from PIL import Image

from hoi4_agent.tools.portrait.search.query_expander import (
    expand_queries,
    get_search_languages,
)


class ImageCandidate(NamedTuple):
    """검색 결과 이미지 후보."""
    url: str
    source: str          # "google", "yandex", "bing", "ddg", "wikimedia"
    query: str
    width: int
    height: int


class MultiSourceSearch:
    """멀티소스 이미지 검색 + 다운로드 + 필터링."""

    def __init__(
        self,
        cache_dir: Path | None = None,
        max_per_source: int = 10,
        min_size: int = 200,
    ):
        self.cache_dir = cache_dir or Path("/tmp/portrait_search_cache")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.max_per_source = max_per_source
        self.min_size = min_size
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        })

    # ------------------------------------------------------------------
    # 메인 검색
    # ------------------------------------------------------------------

    def search_person(
        self,
        person_name: str,
        native_name: str | None = None,
        title: str | None = None,
        country_tag: str | None = None,
        max_results: int = 30,
    ) -> list[Path]:
        """인물 사진을 멀티소스에서 검색하고 다운로드한다.

        Returns:
            다운로드된 이미지 파일 경로 리스트.
        """
        queries = expand_queries(person_name, native_name, title, country_tag)
        logger.info(f"검색 쿼리 {len(queries)}개 생성: {queries[:5]}...")

        # 각 소스에서 병렬 검색
        all_candidates: list[ImageCandidate] = []
        with ThreadPoolExecutor(max_workers=5) as pool:
            futures = []
            for query in queries[:8]:  # 쿼리 수 제한
                futures.append(pool.submit(self._search_duckduckgo, query))
                futures.append(pool.submit(self._search_bing, query))
                futures.append(pool.submit(self._search_wikimedia, query))

            for future in as_completed(futures):
                try:
                    candidates = future.result()
                    all_candidates.extend(candidates)
                except Exception as exc:
                    logger.debug(f"검색 실패: {exc}")

        logger.info(f"총 후보 {len(all_candidates)}개 수집")

        # 중복 제거 (URL 기반)
        seen_urls: set[str] = set()
        unique: list[ImageCandidate] = []
        for c in all_candidates:
            if c.url not in seen_urls:
                seen_urls.add(c.url)
                unique.append(c)

        logger.info(f"중복 제거 후 {len(unique)}개")

        # 다운로드 + 품질 필터
        downloaded: list[Path] = []
        for candidate in unique[:max_results * 2]:  # 여유롭게 다운로드
            path = self._download_image(candidate, person_name)
            if path is not None:
                downloaded.append(path)
            if len(downloaded) >= max_results:
                break

        logger.info(f"최종 다운로드 {len(downloaded)}개")
        return downloaded

    # ------------------------------------------------------------------
    # 개별 소스 검색
    # ------------------------------------------------------------------

    def _search_duckduckgo(self, query: str) -> list[ImageCandidate]:
        """DuckDuckGo 이미지 검색."""
        try:
            from duckduckgo_search import DDGS
            results = []
            with DDGS() as ddgs:
                for r in ddgs.images(query, max_results=self.max_per_source):
                    results.append(ImageCandidate(
                        url=r.get("image", ""),
                        source="duckduckgo",
                        query=query,
                        width=r.get("width", 0),
                        height=r.get("height", 0),
                    ))
            return results
        except Exception as exc:
            logger.debug(f"DuckDuckGo 검색 실패 [{query}]: {exc}")
            return []

    def _search_bing(self, query: str) -> list[ImageCandidate]:
        """Bing 이미지 검색 (icrawler 기반)."""
        try:
            from icrawler.builtin import BingImageCrawler
            import tempfile
            import os

            tmpdir = tempfile.mkdtemp()
            crawler = BingImageCrawler(
                storage={"root_dir": tmpdir},
                log_level=50,  # CRITICAL only
            )
            crawler.crawl(
                keyword=query,
                max_num=self.max_per_source,
            )

            results = []
            for fname in os.listdir(tmpdir):
                fpath = os.path.join(tmpdir, fname)
                results.append(ImageCandidate(
                    url=f"file://{fpath}",
                    source="bing",
                    query=query,
                    width=0,
                    height=0,
                ))
            return results
        except Exception as exc:
            logger.debug(f"Bing 검색 실패 [{query}]: {exc}")
            return []

    def _search_wikimedia(self, query: str) -> list[ImageCandidate]:
        """Wikimedia Commons 검색."""
        try:
            params = {
                "action": "query",
                "format": "json",
                "generator": "search",
                "gsrsearch": f"File: {query}",
                "gsrnamespace": "6",
                "gsrlimit": str(self.max_per_source),
                "prop": "imageinfo",
                "iiprop": "url|size",
                "iiurlwidth": "500",
            }
            resp = self.session.get(
                "https://commons.wikimedia.org/w/api.php",
                params=params,
                timeout=15,
            )
            data = resp.json()
            pages = data.get("query", {}).get("pages", {})

            results = []
            for page in pages.values():
                ii = page.get("imageinfo", [{}])[0]
                url = ii.get("thumburl", ii.get("url", ""))
                if url:
                    results.append(ImageCandidate(
                        url=url,
                        source="wikimedia",
                        query=query,
                        width=ii.get("width", 0),
                        height=ii.get("height", 0),
                    ))
            return results
        except Exception as exc:
            logger.debug(f"Wikimedia 검색 실패 [{query}]: {exc}")
            return []

    # ------------------------------------------------------------------
    # 다운로드 + 품질 필터
    # ------------------------------------------------------------------

    def _download_image(
        self, candidate: ImageCandidate, person_name: str
    ) -> Path | None:
        """이미지를 다운로드하고 품질을 확인한다."""
        url = candidate.url
        try:
            if url.startswith("file://"):
                # icrawler가 이미 다운로드한 로컬 파일
                local_path = Path(url.replace("file://", ""))
                if not local_path.exists():
                    return None
                img = Image.open(local_path)
            else:
                resp = self.session.get(url, timeout=15)
                resp.raise_for_status()
                img = Image.open(BytesIO(resp.content))

            # 품질 필터: 최소 크기
            w, h = img.size
            if w < self.min_size or h < self.min_size:
                return None

            # 저장
            safe_name = person_name.replace(" ", "_").lower()
            url_hash = hashlib.md5(url.encode()).hexdigest()[:8]
            out_path = self.cache_dir / f"{safe_name}_{candidate.source}_{url_hash}.png"
            img.convert("RGB").save(str(out_path), "PNG")
            return out_path

        except Exception as exc:
            logger.debug(f"다운로드 실패 [{url[:60]}]: {exc}")
            return None

    # ------------------------------------------------------------------
    # 이미지 해시 기반 중복 제거
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # 군복/의상 템플릿 검색
    # ------------------------------------------------------------------

    def search_uniform_template(
        self,
        country_name: str,
        uniform_type: str = "military",
        max_results: int = 5,
    ) -> list[Path]:
        """군복/의상 템플릿 이미지를 웹에서 검색한다.

        Args:
            country_name: 국가명 (예: "Afghanistan", "United States").
            uniform_type: "military", "suit", "guerrilla" 등.
            max_results: 최대 결과 수.

        Returns:
            다운로드된 이미지 경로 리스트.
        """
        queries = [
            f"{country_name} {uniform_type} uniform portrait transparent",
            f"{country_name} {uniform_type} uniform template PNG",
            f"{country_name} army officer portrait",
            f"{uniform_type} uniform headless template",
            f"{country_name} soldier portrait no face",
        ]

        all_candidates: list[ImageCandidate] = []
        for query in queries[:3]:
            try:
                all_candidates.extend(self._search_duckduckgo(query))
            except Exception:
                pass

        # 중복 제거 + 다운로드
        seen: set[str] = set()
        unique = [c for c in all_candidates if c.url not in seen and not seen.add(c.url)]

        downloaded: list[Path] = []
        for candidate in unique[:max_results * 2]:
            path = self._download_image(candidate, f"template_{uniform_type}")
            if path:
                downloaded.append(path)
            if len(downloaded) >= max_results:
                break

        logger.info(f"군복 템플릿 검색 결과: {len(downloaded)}개 ({country_name} {uniform_type})")
        return downloaded

    @staticmethod
    def deduplicate_by_hash(image_paths: list[Path], threshold: int = 5) -> list[Path]:
        """perceptual hash로 유사 이미지를 제거한다."""
        try:
            import imagehash
        except ImportError:
            logger.debug("imagehash 미설치 — 해시 중복 제거 건너뜀")
            return image_paths

        hashes: list[tuple[Path, imagehash.ImageHash]] = []
        unique: list[Path] = []

        for path in image_paths:
            try:
                img = Image.open(path)
                h = imagehash.phash(img)

                is_dup = False
                for _, existing_h in hashes:
                    if abs(h - existing_h) < threshold:
                        is_dup = True
                        break

                if not is_dup:
                    hashes.append((path, h))
                    unique.append(path)
            except Exception:
                continue

        logger.info(f"해시 중복 제거: {len(image_paths)} → {len(unique)}")
        return unique
