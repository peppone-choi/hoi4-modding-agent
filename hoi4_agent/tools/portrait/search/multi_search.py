"""
멀티소스 이미지 검색 오케스트레이터.
Google, Yandex, Bing, DuckDuckGo, Wikimedia Commons에서 병렬 검색 후
중복 제거 + 품질 필터링.
"""
from __future__ import annotations

import hashlib
import re
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
        request_delay: float = 1.5,
    ):
        self.cache_dir = cache_dir or Path("/tmp/portrait_search_cache")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.max_per_source = max_per_source
        self.min_size = min_size
        self.request_delay = request_delay
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "HOI4ModdingAgent/1.0 (https://github.com; portrait-search) Python/3.11",
            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
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
            for query in queries[:8]:
                futures.append(pool.submit(self._search_tavily, query))
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

    def _search_tavily(self, query: str) -> list[ImageCandidate]:
        """Tavily 이미지 검색. TAVILY_API_KEY 필요."""
        import os
        api_key = os.environ.get("TAVILY_API_KEY", "")
        if not api_key:
            return []
        try:
            from tavily import TavilyClient
            client = TavilyClient(api_key=api_key)
            response = client.search(
                query=f"{query} portrait photo",
                max_results=self.max_per_source,
                include_images=True,
                search_depth="advanced",
            )
            results = []
            for url in response.get("images", []):
                if url and isinstance(url, str):
                    results.append(ImageCandidate(
                        url=url, source="tavily", query=query,
                        width=0, height=0,
                    ))
            logger.debug(f"Tavily 이미지 {len(results)}개: [{query}]")
            return results
        except Exception as exc:
            logger.debug(f"Tavily 검색 실패 [{query}]: {exc}")
            return []

    def _search_duckduckgo(self, query: str) -> list[ImageCandidate]:
        """DuckDuckGo 이미지 검색."""
        try:
            from ddgs import DDGS
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
        self, candidate: ImageCandidate, person_name: str, max_retries: int = 5,
    ) -> Path | None:
        """이미지를 다운로드하고 품질을 확인한다. 429 시 exponential backoff."""
        url = candidate.url
        try:
            if url.startswith("file://"):
                local_path = Path(url.replace("file://", ""))
                if not local_path.exists():
                    return None
                img = Image.open(local_path)
            else:
                time.sleep(self.request_delay)
                
                dl_url = _wikimedia_thumbnail_url(url, size=800)
                headers = {}
                if "wikimedia.org" in dl_url or "wikipedia.org" in dl_url:
                    headers["Referer"] = "https://en.wikipedia.org/"
                
                resp = None
                for attempt in range(max_retries):
                    resp = self.session.get(dl_url, timeout=15, headers=headers)
                    if resp.status_code == 429:
                        wait = min(2 ** attempt, 30)
                        logger.debug(f"429 rate limit, retry in {wait}s: {dl_url[:60]}")
                        time.sleep(wait)
                        continue
                    break
                
                if resp is None:
                    logger.debug(f"다운로드 실패 (no response): {dl_url[:60]}")
                    return None
                
                resp.raise_for_status()
                
                Image.MAX_IMAGE_PIXELS = 200_000_000
                img = Image.open(BytesIO(resp.content))

            w, h = img.size
            if w < self.min_size or h < self.min_size:
                return None

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


def _wikimedia_thumbnail_url(url: str, size: int = 800) -> str:
    """Wikimedia URL을 적절한 크기의 썸네일 URL로 변환.

    WikiMedia는 full-size 다운로드 시 429 rate limit을 적용하므로
    썸네일을 사용하는 것이 권장됨. (https://w.wiki/GHai)
    
    /commons/a/ab/File.jpg → /commons/thumb/a/ab/File.jpg/800px-File.jpg
    /commons/thumb/a/ab/File.jpg/500px-File.jpg → /commons/thumb/a/ab/File.jpg/800px-File.jpg
    """
    base_match = re.match(
        r"(https://upload\.wikimedia\.org/wikipedia/commons)/(\w/\w\w/)(.+)",
        url,
    )
    if not base_match:
        return url
    
    base = base_match.group(1)
    path = base_match.group(2)
    filename = base_match.group(3)
    
    if filename.startswith("thumb/"):
        filename = re.sub(r"^thumb/", "", filename)
        filename = re.sub(r"/\d+px-.+$", "", filename)
    
    return f"{base}/thumb/{path}{filename}/{size}px-{filename}"
