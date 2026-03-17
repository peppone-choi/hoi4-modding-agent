"""
Wikipedia MediaWiki API 클라이언트.
영어/한국어 Wikipedia에서 인물, 정치 정보를 가져온다.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any

import requests
from loguru import logger

from tools.shared.constants import (
    WIKIPEDIA_API_URL,
    WIKIPEDIA_KO_API_URL,
    WIKI_RATE_LIMIT_DELAY,
    WIKI_USER_AGENT,
)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class WikipediaPersonData:
    """Wikipedia에서 가져온 인물 데이터."""

    name: str
    birth_date: str = ""  # ISO 형식: "1946-06-14"
    death_date: str = ""  # 생존 시 빈 문자열
    nationality: str = ""
    position: str = ""  # 현재/최근 직위
    party: str = ""  # 소속 정당
    description: str = ""  # 짧은 소개
    wikipedia_url: str = ""
    image_filename: str = ""  # Commons 파일명 (예: "File:Trump.jpg")
    wikidata_id: str = ""  # Q-ID


@dataclass
class WikipediaCountryData:
    """Wikipedia에서 가져온 국가 정치 데이터."""

    country_name: str
    government_type: str = ""
    head_of_state: str = ""
    head_of_government: str = ""
    ruling_party: str = ""
    capital: str = ""
    wikipedia_url: str = ""


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class WikipediaClient:
    """Wikipedia MediaWiki API 클라이언트."""

    def __init__(
        self,
        lang: str = "en",
        rate_limit: float = WIKI_RATE_LIMIT_DELAY,
    ):
        self.lang = lang
        self.rate_limit = rate_limit
        self._last_request: float = 0.0
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": WIKI_USER_AGENT})
        self.base_url = WIKIPEDIA_KO_API_URL if lang == "ko" else WIKIPEDIA_API_URL

    # ------------------------------------------------------------------
    # Low-level helpers
    # ------------------------------------------------------------------

    def _request(self, params: dict[str, Any]) -> dict[str, Any]:
        """API 요청 (rate limit 적용)."""
        elapsed = time.time() - self._last_request
        if elapsed < self.rate_limit:
            time.sleep(self.rate_limit - elapsed)

        params.setdefault("format", "json")
        response = self.session.get(self.base_url, params=params, timeout=30)
        response.raise_for_status()
        self._last_request = time.time()
        return response.json()

    @staticmethod
    def _strip_wikitext_markup(text: str) -> str:
        """위키텍스트 마크업에서 순수 텍스트를 추출한다."""
        # [[link|display]] → display,  [[link]] → link
        text = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]+)\]\]", r"\1", text)
        # {{small|...}} 등 간단한 템플릿 → 내부 값
        text = re.sub(r"\{\{[^|{}]+\|([^{}]+)\}\}", r"\1", text)
        # 나머지 {{ }} 제거
        text = re.sub(r"\{\{[^{}]*\}\}", "", text)
        # HTML 태그 제거
        text = re.sub(r"<[^>]+>", "", text)
        # ref 태그 내용 제거
        text = re.sub(r"<ref[^>]*>.*?</ref>", "", text, flags=re.DOTALL)
        text = re.sub(r"<ref[^/]*/?>", "", text)
        return text.strip()

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search_person(self, name: str, limit: int = 5) -> list[dict[str, Any]]:
        """인물 검색. 검색 결과 목록 반환.

        Returns:
            [{"title": ..., "pageid": ..., "snippet": ...}, ...]
        """
        params = {
            "action": "query",
            "list": "search",
            "srsearch": name,
            "srlimit": limit,
            "srprop": "snippet",
        }
        data = self._request(params)
        results: list[dict[str, Any]] = []
        for item in data.get("query", {}).get("search", []):
            results.append(
                {
                    "title": item.get("title", ""),
                    "pageid": item.get("pageid", 0),
                    "snippet": item.get("snippet", ""),
                }
            )
        logger.debug("search_person '{}': {} results", name, len(results))
        return results

    # ------------------------------------------------------------------
    # Page content
    # ------------------------------------------------------------------

    def get_page_wikitext(self, title: str) -> str:
        """페이지의 wikitext 가져오기."""
        params = {
            "action": "parse",
            "page": title,
            "prop": "wikitext",
        }
        data = self._request(params)
        return data.get("parse", {}).get("wikitext", {}).get("*", "")

    # ------------------------------------------------------------------
    # Infobox parsing
    # ------------------------------------------------------------------

    def extract_infobox(self, wikitext: str) -> dict[str, str]:
        """wikitext에서 Infobox 파싱. 필드명 → 값 딕셔너리.

        ``{{Infobox person`` / ``{{Infobox officeholder`` 등을 지원한다.
        중첩 ``{{ }}`` 를 올바르게 처리한다.
        """
        # Infobox 시작 위치 탐색
        match = re.search(r"\{\{Infobox\s+\w+", wikitext, re.IGNORECASE)
        if not match:
            return {}

        start = match.start()
        depth = 0
        end = start
        for i in range(start, len(wikitext) - 1):
            two = wikitext[i : i + 2]
            if two == "{{":
                depth += 1
            elif two == "}}":
                depth -= 1
                if depth == 0:
                    end = i + 2
                    break

        infobox_text = wikitext[start:end]

        # 각 필드 추출: "| key = value"
        result: dict[str, str] = {}
        # 최상위 레벨의 | key = value 만 추출 (중첩 템플릿 내부 제외)
        field_pattern = re.compile(r"^\s*\|\s*(\w[\w\s]*?)\s*=\s*(.*)", re.MULTILINE)
        for m in field_pattern.finditer(infobox_text):
            key = m.group(1).strip().lower()
            raw_value = m.group(2).strip()
            result[key] = self._strip_wikitext_markup(raw_value)

        logger.debug("extract_infobox: {} fields parsed", len(result))
        return result

    # ------------------------------------------------------------------
    # Date extraction
    # ------------------------------------------------------------------

    _BIRTH_DATE_PATTERNS = [
        # {{Birth date and age|YYYY|M|D}}  /  {{Birth date|YYYY|M|D}}
        re.compile(
            r"\{\{\s*(?:[Bb]irth[_ ]date(?:[_ ]and[_ ]age)?|[Dd]ob)"
            r"\s*\|(?:\s*(?:df|mf)\s*=\s*\w+\s*\|)?"
            r"\s*(\d{4})\s*\|\s*(\d{1,2})\s*\|\s*(\d{1,2})",
        ),
        # ISO 형식 직접 기재: birth_date = 1946-06-14
        re.compile(r"birth[_ ]?date\s*=\s*(\d{4})-(\d{1,2})-(\d{1,2})"),
    ]

    _DEATH_DATE_PATTERNS = [
        # {{Death date and age|...}}  /  {{Death date|...}}
        re.compile(
            r"\{\{\s*[Dd]eath[_ ]date(?:[_ ]and[_ ]age)?"
            r"\s*\|(?:\s*(?:df|mf)\s*=\s*\w+\s*\|)?"
            r"\s*(\d{4})\s*\|\s*(\d{1,2})\s*\|\s*(\d{1,2})",
        ),
    ]

    def extract_birth_date(self, wikitext: str) -> str:
        """wikitext에서 생년월일 추출. ISO 형식 ``YYYY-MM-DD`` 반환."""
        for pattern in self._BIRTH_DATE_PATTERNS:
            m = pattern.search(wikitext)
            if m:
                year, month, day = m.group(1), m.group(2), m.group(3)
                return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
        return ""

    def extract_death_date(self, wikitext: str) -> str:
        """wikitext에서 사망일 추출. 생존 시 빈 문자열."""
        for pattern in self._DEATH_DATE_PATTERNS:
            m = pattern.search(wikitext)
            if m:
                year, month, day = m.group(1), m.group(2), m.group(3)
                return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
        return ""

    # ------------------------------------------------------------------
    # Image
    # ------------------------------------------------------------------

    def get_page_image(self, title: str) -> str:
        """페이지의 주 이미지 파일명 반환 (Commons 파일명).

        ``pageimages`` API를 사용하며, 결과가 없으면 빈 문자열을 돌려준다.
        """
        params = {
            "action": "query",
            "titles": title,
            "prop": "pageimages",
            "piprop": "original",
        }
        data = self._request(params)
        pages = data.get("query", {}).get("pages", {})
        for page in pages.values():
            original = page.get("original", {})
            source = original.get("source", "")
            if source:
                # URL에서 파일명 추출 → "File:xxx.jpg"
                filename = source.rsplit("/", 1)[-1]
                return f"File:{filename}"
        return ""

    # ------------------------------------------------------------------
    # Wikidata
    # ------------------------------------------------------------------

    def get_wikidata_id(self, title: str) -> str:
        """페이지의 Wikidata Q-ID 반환."""
        params = {
            "action": "query",
            "titles": title,
            "prop": "pageprops",
            "ppprop": "wikibase_item",
        }
        data = self._request(params)
        pages = data.get("query", {}).get("pages", {})
        for page in pages.values():
            return page.get("pageprops", {}).get("wikibase_item", "")
        return ""

    # ------------------------------------------------------------------
    # Person aggregate
    # ------------------------------------------------------------------

    def get_person_data(self, title: str) -> WikipediaPersonData | None:
        """페이지 제목으로 인물 데이터 가져오기.

        wikitext 를 파싱하여 infobox, 생년월일, 사망일, 이미지 등을 추출한다.
        """
        try:
            wikitext = self.get_page_wikitext(title)
        except requests.HTTPError:
            logger.warning("get_person_data: page '{}' not found", title)
            return None

        if not wikitext:
            return None

        infobox = self.extract_infobox(wikitext)
        birth_date = self.extract_birth_date(wikitext)
        death_date = self.extract_death_date(wikitext)
        image = self.get_page_image(title)
        wikidata_id = self.get_wikidata_id(title)

        lang_prefix = f"{self.lang}." if self.lang != "en" else ""
        wiki_url = f"https://{lang_prefix}wikipedia.org/wiki/{title.replace(' ', '_')}"

        return WikipediaPersonData(
            name=infobox.get("name", title),
            birth_date=birth_date,
            death_date=death_date,
            nationality=infobox.get("nationality", ""),
            position=infobox.get("office", infobox.get("title", "")),
            party=infobox.get("party", ""),
            description=infobox.get("caption", ""),
            wikipedia_url=wiki_url,
            image_filename=image,
            wikidata_id=wikidata_id,
        )

    # ------------------------------------------------------------------
    # Country data
    # ------------------------------------------------------------------

    def get_country_data(self, country_name: str) -> WikipediaCountryData | None:
        """국가 정치 데이터 가져오기.

        ``Politics of {country}`` 또는 국가 문서의 infobox에서 정보를 추출한다.
        """
        try:
            wikitext = self.get_page_wikitext(country_name)
        except requests.HTTPError:
            logger.warning("get_country_data: page '{}' not found", country_name)
            return None

        if not wikitext:
            return None

        infobox = self.extract_infobox(wikitext)

        lang_prefix = f"{self.lang}." if self.lang != "en" else ""
        wiki_url = (
            f"https://{lang_prefix}wikipedia.org/wiki/"
            f"{country_name.replace(' ', '_')}"
        )

        return WikipediaCountryData(
            country_name=country_name,
            government_type=infobox.get("government_type", ""),
            head_of_state=infobox.get("leader_name1", infobox.get("head of state", "")),
            head_of_government=infobox.get(
                "leader_name2", infobox.get("head of government", "")
            ),
            ruling_party=infobox.get("ruling_party", infobox.get("party", "")),
            capital=infobox.get("capital", ""),
            wikipedia_url=wiki_url,
        )
