"""
Wikipedia + Wikidata 데이터 통합 추출기.
여러 소스에서 데이터를 결합하여 HOI4 모드에 필요한 구조화된 데이터를 반환한다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any

from loguru import logger

from tools.wiki_updater.core.wiki_client import WikipediaClient, WikipediaPersonData
from tools.wiki_updater.core.wikidata_client import WikidataClient, WikidataEntityData
from tools.shared.constants import TARGET_DATE, TARGET_YEAR

if TYPE_CHECKING:
    from tools.wiki_updater.cache.sqlite_cache import WikiCache


# =====================================================================
# 매핑 테이블
# =====================================================================

PARTY_TO_IDEOLOGY: dict[str, str] = {
    # 미국
    "Republican Party": "conservatism",
    "Democratic Party": "social_democracy",
    # 중국
    "Chinese Communist Party": "maoism",
    "Communist Party of China": "maoism",
    # 러시아
    "United Russia": "despotism",
    # 북한
    "Korean Workers' Party": "jucheism",
    "Workers' Party of Korea": "jucheism",
    # 한국
    "People Power Party": "conservatism",
    "Democratic Party of Korea": "liberalism",
    # 일본
    "Liberal Democratic Party": "conservatism",
    # 영국
    "Labour Party": "social_democracy",
    "Conservative Party": "conservatism",
    # 독일
    "Social Democratic Party of Germany": "social_democracy",
    "Christian Democratic Union of Germany": "conservatism",
    # 프랑스
    "Renaissance": "liberalism",
    "National Rally": "ultranationalism",
    # 일반
    "Communist Party": "marxism_leninism",
    "Liberal Party": "liberalism",
    "Social Democratic Party": "social_democracy",
    "Green Party": "progressivism",
    "Socialist Party": "social_democracy",
}

COUNTRY_NAME_TO_TAG: dict[str, str] = {
    "United States": "USA",
    "United States of America": "USA",
    "American": "USA",
    "China": "CHI",
    "People's Republic of China": "CHI",
    "Russia": "SOV",
    "Russian Federation": "SOV",
    "United Kingdom": "ENG",
    "British": "ENG",
    "Germany": "GER",
    "France": "FRA",
    "Japan": "JAP",
    "South Korea": "SOK",
    "Republic of Korea": "SOK",
    "North Korea": "PRK",
    "Democratic People's Republic of Korea": "PRK",
    "India": "RAJ",
    "Brazil": "BRA",
    "Canada": "CAN",
    "Australia": "AST",
    "Italy": "ITA",
    "Spain": "SPR",
    "Turkey": "TUR",
    "Mexico": "MEX",
    "Saudi Arabia": "SAU",
    "Iran": "PER",
    "Israel": "ISR",
    "Poland": "POL",
    "Ukraine": "UKR",
    "Egypt": "EGY",
}


# =====================================================================
# 데이터 클래스
# =====================================================================


@dataclass
class ExtractedPersonData:
    """통합 인물 데이터 (HOI4 모드에 필요한 형태)."""

    char_id: str  # HOI4 캐릭터 ID (예: USA_donald_trump_char)
    name_en: str = ""
    name_ko: str = ""
    birth_date: str = ""  # ISO: "1946-06-14"
    death_date: str = ""  # 생존 시 빈 문자열
    is_alive: bool = True
    nationality: str = ""  # 국가명 (예: "United States of America")
    country_tag: str = ""  # HOI4 국가 태그
    ideology: str = ""  # HOI4 이념 코드
    position: str = ""  # 현재 직위 (2026년 기준)
    party: str = ""
    military_rank: str = ""
    gender: str = "male"
    portrait_url: str = ""  # Wikimedia Commons URL
    portrait_filename: str = ""  # Commons 파일명
    wikidata_qid: str = ""
    wikipedia_url_en: str = ""
    wikipedia_url_ko: str = ""
    data_sources: list[str] = field(default_factory=list)  # 사용된 소스 목록
    confidence: float = 0.0  # 데이터 신뢰도 0.0~1.0


@dataclass
class ExtractedCountryData:
    """통합 국가 데이터."""

    country_tag: str  # HOI4 국가 태그 (예: "USA")
    country_name: str = ""
    ruling_party_ideology: str = ""  # HOI4 이념 코드
    head_of_state_char_id: str = ""
    head_of_government_char_id: str = ""
    ideology_popularities: dict[str, int] = field(default_factory=dict)
    wikidata_qid: str = ""


# =====================================================================
# 추출기
# =====================================================================


class DataExtractor:
    """다중 소스 데이터 통합 추출기."""

    def __init__(self, cache: WikiCache | None = None) -> None:
        wiki_en = WikipediaClient(lang="en")
        wiki_ko = WikipediaClient(lang="ko")
        wikidata = WikidataClient()

        if cache is not None:
            from tools.wiki_updater.cache.sqlite_cache import (
                CachedWikipediaClient,
                CachedWikidataClient,
            )
            self.wiki_en = CachedWikipediaClient(cache, wiki_en)
            self.wiki_ko = CachedWikipediaClient(cache, wiki_ko)
            self.wikidata = CachedWikidataClient(cache, wikidata)
        else:
            self.wiki_en = wiki_en
            self.wiki_ko = wiki_ko
            self.wikidata = wikidata

        self._cache = cache

    # ------------------------------------------------------------------
    # Person extraction
    # ------------------------------------------------------------------

    def extract_person(
        self,
        char_id: str,
        search_name: str,
        country_tag: str = "",
    ) -> ExtractedPersonData | None:
        """
        캐릭터 ID와 이름으로 인물 데이터 추출.

        Wikidata -> Wikipedia EN -> Wikipedia KO 순으로 시도하며,
        가용한 모든 소스를 결합하여 최대한 완전한 데이터를 구축한다.
        """
        result = ExtractedPersonData(char_id=char_id)
        result.country_tag = country_tag
        sources: list[str] = []

        # Phase 1: Wikidata (primary) --------------------------------
        wd_entity = self._fetch_wikidata(search_name, country_tag)
        if wd_entity:
            sources.append("wikidata")
            self._merge_wikidata(result, wd_entity)

        # Phase 2: Wikipedia EN (supplement / fallback) ---------------
        wp_en_data = self._fetch_wikipedia(self.wiki_en, search_name)
        if wp_en_data:
            sources.append("wikipedia_en")
            self._merge_wikipedia_en(result, wp_en_data)

        # Phase 3: Wikipedia KO (Korean name / supplement) ------------
        wp_ko_data = self._fetch_wikipedia(self.wiki_ko, search_name)
        if wp_ko_data:
            sources.append("wikipedia_ko")
            self._merge_wikipedia_ko(result, wp_ko_data)

        # 소스가 하나도 없으면 None
        if not sources:
            logger.warning(
                "No data found for '{}' from any source", search_name
            )
            return None

        # Post-processing
        self._post_process(result, search_name, country_tag, sources)
        return result

    # ------------------------------------------------------------------
    # Country extraction
    # ------------------------------------------------------------------

    def extract_country(
        self,
        country_tag: str,
        country_name: str,
    ) -> ExtractedCountryData | None:
        """국가 정치 데이터 추출."""
        result = ExtractedCountryData(country_tag=country_tag)
        result.country_name = country_name

        country_data = None
        try:
            country_data = self.wiki_en.get_country_data(country_name)
        except Exception as exc:
            logger.warning(
                "Country data extraction failed for '{}': {}",
                country_name,
                exc,
            )

        if not country_data:
            logger.warning("No country data found for '{}'", country_name)
            return None

        if country_data.ruling_party:
            result.ruling_party_ideology = self._map_position_to_ideology(
                "", country_data.ruling_party
            )

        return result

    # ------------------------------------------------------------------
    # Fetch helpers
    # ------------------------------------------------------------------

    def _fetch_wikidata(
        self, search_name: str, country_tag: str = ""
    ) -> WikidataEntityData | None:
        """Wikidata 검색 + 동명이인 해소 + 엔티티 조회.
        
        검색 결과를 생년, 국적, 이름 일치도로 점수를 매겨 최적 후보를 선택한다.
        """
        try:
            search_results = self.wikidata.search_person(search_name)
            if not search_results:
                return None
            
            # 후보가 1명이면 바로 사용
            if len(search_results) == 1:
                return self.wikidata.get_entity_by_qid(search_results[0].qid)
            
            # 상위 5개 후보에 대해 엔티티 데이터 가져와서 점수 매기기
            best_entity: WikidataEntityData | None = None
            best_score: float = -1.0
            
            for candidate in search_results[:5]:
                try:
                    entity = self.wikidata.get_entity_by_qid(candidate.qid)
                    if entity is None:
                        continue
                    
                    score = self._score_candidate(
                        entity, search_name, country_tag
                    )
                    if score > best_score:
                        best_score = score
                        best_entity = entity
                except Exception:
                    continue
            
            return best_entity
        except Exception as exc:
            logger.warning(
                "Wikidata lookup failed for '{}': {}", search_name, exc
            )
        return None

    def _score_candidate(
        self,
        entity: WikidataEntityData,
        search_name: str,
        country_tag: str,
    ) -> float:
        """동명이인 후보 점수 산출.
        
        - 생년이 1900 이후: +30
        - 2026.1.1 기준 생존: +20
        - 이름 정확 일치: +20
        - 국적이 country_tag와 일치: +20
        - 직위/정당 정보 있음: +10
        """
        score = 0.0
        
        # 생년 점수
        if entity.birth_date:
            try:
                year = int(entity.birth_date[:4])
                if year > 1900:
                    score += 30.0
                if year > 1950:
                    score += 10.0  # 더 최근이면 가산
            except (ValueError, IndexError):
                pass
        
        # 생존 여부
        if not entity.death_date:
            score += 20.0
        else:
            try:
                death_year = int(entity.death_date[:4])
                if death_year >= 2026:
                    score += 20.0
            except (ValueError, IndexError):
                pass
        
        # 이름 일치도
        if entity.label:
            if entity.label.lower() == search_name.lower():
                score += 20.0
            elif search_name.lower() in entity.label.lower():
                score += 10.0
        
        # 국적 일치
        if country_tag and entity.nationality:
            mapped_tag = self._get_country_tag(entity.nationality)
            if mapped_tag == country_tag:
                score += 20.0
        
        # 직위/정당 정보 보유
        if entity.positions:
            score += 5.0
        if entity.parties:
            score += 5.0
        
        return score

    @staticmethod
    def _fetch_wikipedia(
        client: WikipediaClient, search_name: str
    ) -> WikipediaPersonData | None:
        """Wikipedia 인물 데이터 조회. 실패 시 *None*."""
        try:
            return client.get_person_data(search_name)
        except Exception as exc:
            logger.debug(
                "Wikipedia ({}) failed for '{}': {}",
                client.lang,
                search_name,
                exc,
            )
        return None

    # ------------------------------------------------------------------
    # Merge helpers
    # ------------------------------------------------------------------

    def _merge_wikidata(
        self, result: ExtractedPersonData, wd: WikidataEntityData
    ) -> None:
        """Wikidata 엔티티 데이터를 result에 병합."""
        result.wikidata_qid = wd.qid
        result.name_en = wd.label or result.name_en
        result.birth_date = self._parse_iso_date(wd.birth_date)
        result.death_date = self._parse_iso_date(wd.death_date)
        result.nationality = wd.nationality
        result.position = wd.positions[0] if wd.positions else ""
        result.party = wd.parties[0] if wd.parties else ""
        result.gender = wd.gender or "male"
        result.military_rank = (
            wd.military_ranks[0] if wd.military_ranks else ""
        )
        if wd.image:
            result.portrait_filename = wd.image
            result.portrait_url = (
                f"https://commons.wikimedia.org/wiki/File:{wd.image}"
            )

    def _merge_wikipedia_en(
        self, result: ExtractedPersonData, wp: WikipediaPersonData
    ) -> None:
        """Wikipedia EN 데이터를 result에 보충 병합 (빈 필드만 채움)."""
        if not result.name_en:
            result.name_en = wp.name
        result.wikipedia_url_en = wp.wikipedia_url
        if not result.birth_date and wp.birth_date:
            result.birth_date = self._parse_iso_date(wp.birth_date)
        if not result.death_date and wp.death_date:
            result.death_date = self._parse_iso_date(wp.death_date)
        if not result.nationality:
            result.nationality = wp.nationality
        if not result.position:
            result.position = wp.position
        if not result.party:
            result.party = wp.party
        if not result.portrait_filename and wp.image_filename:
            result.portrait_filename = wp.image_filename
        if not result.wikidata_qid and wp.wikidata_id:
            result.wikidata_qid = wp.wikidata_id

    @staticmethod
    def _merge_wikipedia_ko(
        result: ExtractedPersonData, wp: WikipediaPersonData
    ) -> None:
        """Wikipedia KO 데이터를 result에 보충 병합 (한국어 이름 중심)."""
        if not result.name_ko:
            result.name_ko = wp.name
        result.wikipedia_url_ko = wp.wikipedia_url
        if not result.birth_date and wp.birth_date:
            result.birth_date = wp.birth_date
        if not result.death_date and wp.death_date:
            result.death_date = wp.death_date

    # ------------------------------------------------------------------
    # Post-processing
    # ------------------------------------------------------------------

    def _post_process(
        self,
        result: ExtractedPersonData,
        search_name: str,
        country_tag: str,
        sources: list[str],
    ) -> None:
        """이름, 태그, 이념, 생존 여부, 신뢰도 등 후처리."""
        if not result.name_en:
            result.name_en = search_name
        if not result.country_tag and result.nationality:
            result.country_tag = self._get_country_tag(result.nationality)
        if not result.nationality and country_tag:
            for name, tag in COUNTRY_NAME_TO_TAG.items():
                if tag == country_tag:
                    result.nationality = name
                    break
        result.ideology = self._map_position_to_ideology(
            result.position, result.party
        )
        result.is_alive = self._is_alive_at_date(result.death_date)
        result.data_sources = sources
        result.confidence = self._calculate_confidence(sources, result)

    # ------------------------------------------------------------------
    # Ideology mapping
    # ------------------------------------------------------------------

    @staticmethod
    def _map_position_to_ideology(position: str, party: str) -> str:
        """직위/정당명을 HOI4 이념 코드로 매핑. PartyMapper 기반."""
        if not party and not position:
            return ""

        from tools.wiki_updater.core.party_mapper import PartyMapper

        mapper = PartyMapper()

        if party:
            # 레거시 테이블 우선 (하위 호환)
            if party in PARTY_TO_IDEOLOGY:
                return PARTY_TO_IDEOLOGY[party]

            mapping = mapper.map_party(party)
            if mapping.sub_ideology:
                return mapping.sub_ideology
            if mapping.ideology_group:
                return mapping.ideology_group

        if position:
            pos_lower = position.lower()
            if "communist" in pos_lower:
                return "marxism_leninism"
            if "fascis" in pos_lower:
                return "fascism"

        return ""

    # ------------------------------------------------------------------
    # Date helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_iso_date(date_str: str) -> str:
        """다양한 날짜 형식을 ISO ``YYYY-MM-DD`` 로 정규화.

        지원 형식: ISO, Wikidata ``T`` 접미사, ``June 14, 1946``,
        ``14 June 1946``, ``1946.06.14``, ``06/14/1946`` 등.
        """
        if not date_str:
            return ""
        date_str = date_str.strip()

        # 이미 ISO 형식
        if re.match(r"^\d{4}-\d{2}-\d{2}$", date_str):
            return date_str

        # Wikidata 형식: "1946-06-14T00:00:00Z"
        m = re.match(r"^(\d{4})-(\d{2})-(\d{2})T", date_str)
        if m:
            return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"

        # 텍스트 날짜 형식
        formats = [
            "%B %d, %Y",  # June 14, 1946
            "%d %B %Y",  # 14 June 1946
            "%Y.%m.%d",  # 1946.06.14
            "%m/%d/%Y",  # 06/14/1946
        ]
        for fmt in formats:
            try:
                dt = datetime.strptime(date_str, fmt)
                return dt.strftime("%Y-%m-%d")
            except ValueError:
                continue

        # 최후 수단: 문자열 내 날짜 패턴 추출
        m = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", date_str)
        if m:
            return (
                f"{int(m.group(1)):04d}-"
                f"{int(m.group(2)):02d}-"
                f"{int(m.group(3)):02d}"
            )

        logger.warning("Could not parse date: '{}'", date_str)
        return ""

    @staticmethod
    def _is_alive_at_date(
        death_date: str, target_date: str = "2026-01-01"
    ) -> bool:
        """특정 날짜에 생존 여부 확인.

        사망일이 없거나 목표 날짜 이후이면 생존으로 판정한다.
        """
        if not death_date:
            return True
        try:
            death = datetime.strptime(death_date, "%Y-%m-%d")
            target = datetime.strptime(target_date, "%Y-%m-%d")
            return death >= target
        except ValueError:
            return True

    # ------------------------------------------------------------------
    # Country tag mapping
    # ------------------------------------------------------------------

    @staticmethod
    def _get_country_tag(nationality: str) -> str:
        """국가명 -> HOI4 국가 태그 매핑.

        정확한 일치 우선, 없으면 부분 문자열 매칭.
        """
        if not nationality:
            return ""
        if nationality in COUNTRY_NAME_TO_TAG:
            return COUNTRY_NAME_TO_TAG[nationality]
        # 부분 문자열 매칭
        nat_lower = nationality.lower()
        for name, tag in COUNTRY_NAME_TO_TAG.items():
            if name.lower() in nat_lower or nat_lower in name.lower():
                return tag
        return ""

    # ------------------------------------------------------------------
    # Confidence scoring
    # ------------------------------------------------------------------

    @staticmethod
    def _calculate_confidence(
        sources: list[str], result: ExtractedPersonData
    ) -> float:
        """데이터 신뢰도 계산 (0.0~1.0).

        - Wikidata: +0.4
        - Wikipedia EN: +0.3
        - Wikipedia KO: +0.1
        - 생년월일 있음: +0.1
        - 초상화 있음: +0.1
        """
        score = 0.0
        if "wikidata" in sources:
            score += 0.4
        if "wikipedia_en" in sources:
            score += 0.3
        if "wikipedia_ko" in sources:
            score += 0.1
        if result.birth_date:
            score += 0.1
        if result.portrait_filename:
            score += 0.1
        return min(score, 1.0)
