"""
AI 기반 인물 추천 시스템.
모드에 누락된 주요 인물을 자동으로 제안한다.
Wikidata에서 각 국가의 국가원수, 정부수반, 주요 정치인, 군사 지도자를 가져와
모드에 없는 인물을 추천한다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from loguru import logger

import re

from tools.shared.constants import MOD_ROOT, TARGET_DATE
from tools.shared.hoi4_parser import CharacterParser, CountryHistoryParser
from tools.wiki_updater.core.data_extractor import (
    COUNTRY_NAME_TO_TAG,
    DataExtractor,
    ExtractedPersonData,
)
from tools.wiki_updater.core.wikidata_client import WikidataClient


@dataclass
class Recommendation:
    """추천 인물."""
    name: str
    country_tag: str
    suggested_char_id: str
    role: str                    # "head_of_state", "head_of_government", "minister", "military"
    reason: str                  # 추천 이유
    wikidata_qid: str = ""
    priority: int = 0            # 높을수록 중요 (0~100)
    wikipedia_url: str = ""


# =====================================================================
# 국가별 핵심 직위 — 반드시 있어야 하는 인물
# =====================================================================

ESSENTIAL_ROLES = {
    "head_of_state": {
        "description": "국가 원수 (대통령/국왕/주석 등)",
        "priority": 100,
        "wikidata_prop": "P35",  # head of state
    },
    "head_of_government": {
        "description": "정부 수반 (총리/국무총리 등)",
        "priority": 90,
        "wikidata_prop": "P6",   # head of government
    },
    "foreign_minister": {
        "description": "외무장관",
        "priority": 60,
        "wikidata_prop": "P1313",
    },
    "defense_minister": {
        "description": "국방장관",
        "priority": 70,
        "wikidata_prop": None,   # 직접 검색 필요
    },
}

PRIORITY_COUNTRIES = [
    ("USA", "United States"), ("SOV", "Russia"), ("PRC", "China"),
    ("ENG", "United Kingdom"), ("GER", "Germany"), ("FRA", "France"),
    ("JAP", "Japan"), ("KOR", "South Korea"), ("PRK", "North Korea"),
    ("RAJ", "India"), ("BRA", "Brazil"), ("TUR", "Turkey"),
    ("SAU", "Saudi Arabia"), ("ISR", "Israel"), ("UKR", "Ukraine"),
    ("ITA", "Italy"), ("CAN", "Canada"), ("AST", "Australia"),
    ("PAK", "Pakistan"), ("EGY", "Egypt"),
]

ALL_COUNTRIES: list[tuple[str, str]] = [
    *PRIORITY_COUNTRIES,
    ("SPR", "Spain"), ("POR", "Portugal"), ("GRE", "Greece"),
    ("ROM", "Romania"), ("BUL", "Bulgaria"), ("SER", "Serbia"),
    ("CRO", "Croatia"), ("HUN", "Hungary"), ("POL", "Poland"),
    ("CZE", "Czech Republic"), ("SLO", "Slovakia"),
    ("SWE", "Sweden"), ("NOR", "Norway"), ("DEN", "Denmark"), ("FIN", "Finland"),
    ("HOL", "Netherlands"), ("BEL", "Belgium"), ("SWI", "Switzerland"),
    ("AUS", "Austria"), ("IRE", "Ireland"),
    ("MEX", "Mexico"), ("ARG", "Argentina"), ("COL", "Colombia"),
    ("CHL", "Chile"), ("PER", "Peru"), ("VEN", "Venezuela"),
    ("CUB", "Cuba"), ("ECU", "Ecuador"), ("BOL", "Bolivia"),
    ("PAR", "Paraguay"), ("URG", "Uruguay"),
    ("INS", "Indonesia"), ("SIA", "Thailand"), ("PHI", "Philippines"),
    ("MAL", "Malaysia"), ("MYA", "Myanmar"), ("VIN", "Vietnam"),
    ("CAM", "Cambodia"), ("LAO", "Laos"),
    ("PER", "Iran"), ("IRQ", "Iraq"), ("SYR", "Syria"),
    ("LEB", "Lebanon"), ("YEM", "Yemen"), ("AFG", "Afghanistan"),
    ("JOR", "Jordan"), ("KUW", "Kuwait"), ("QAT", "Qatar"),
    ("UAE", "United Arab Emirates"), ("OMA", "Oman"), ("BHR", "Bahrain"),
    ("ETH", "Ethiopia"), ("NGA", "Nigeria"), ("SAF", "South Africa"),
    ("KEN", "Kenya"), ("TAN", "Tanzania"), ("UGA", "Uganda"),
    ("GHA", "Ghana"), ("MOZ", "Mozambique"), ("ANG", "Angola"),
    ("COG", "Congo"), ("SUD", "Sudan"), ("ALG", "Algeria"),
    ("MOR", "Morocco"), ("TUN", "Tunisia"), ("LBA", "Libya"),
    ("ZIM", "Zimbabwe"), ("RWA", "Rwanda"), ("SOM", "Somalia"),
    ("NZL", "New Zealand"),
    ("GEO", "Georgia"), ("AZR", "Azerbaijan"), ("ARM", "Armenia"),
    ("KAZ", "Kazakhstan"), ("UZB", "Uzbekistan"),
    ("MON", "Mongolia"), ("NEP", "Nepal"), ("SRL", "Sri Lanka"),
    ("BAN", "Bangladesh"),
    ("BLR", "Belarus"), ("MOL", "Moldova"), ("LIT", "Lithuania"),
    ("LAT", "Latvia"), ("EST", "Estonia"),
]


class CharacterRecommender:
    """모드에 누락된 인물을 추천한다."""

    def __init__(self, mod_root: Path = MOD_ROOT) -> None:
        self.mod_root = mod_root
        self._parser = CharacterParser()
        self._extractor = DataExtractor()
        self._wikidata = WikidataClient()

    def get_existing_char_ids(self) -> set[str]:
        """모드의 기존 캐릭터 ID 집합."""
        chars = self._parser.parse_all_characters(
            self.mod_root / "common" / "characters"
        )
        return set(chars.keys())

    def _name_to_char_id(self, name: str, country_tag: str) -> str:
        """이름 → 캐릭터 ID 변환."""
        safe = name.lower().replace(" ", "_").replace("-", "_").replace("'", "")
        safe = "".join(c for c in safe if c.isalnum() or c == "_")
        return f"{country_tag}_{safe}_char"

    def _name_fuzzy_match(self, name: str, existing_ids: set[str], country_tag: str) -> bool:
        """이름이 기존 캐릭터와 유사한지 확인 (퍼지 매칭)."""
        # 정확한 ID 매칭
        cid = self._name_to_char_id(name, country_tag)
        if cid in existing_ids:
            return True
        # 성(last name)만으로 매칭
        parts = name.lower().split()
        if parts:
            last = parts[-1]
            return any(last in eid.lower() for eid in existing_ids if eid.startswith(country_tag))
        return False

    # ------------------------------------------------------------------
    # 핵심 인물 추천
    # ------------------------------------------------------------------

    def recommend_essential(
        self, countries: list[tuple[str, str]] | None = None
    ) -> list[Recommendation]:
        """모든 국가의 핵심 직위 인물 중 모드에 없는 것을 추천한다."""
        if countries is None:
            countries = ALL_COUNTRIES

        existing = self.get_existing_char_ids()
        recommendations: list[Recommendation] = []

        for tag, country_name in countries:
            logger.info(f"추천 분석: {tag} ({country_name})")

            # Wikipedia에서 국가 데이터 가져오기
            try:
                country_data = self._extractor.wiki_en.get_country_data(country_name)
            except Exception as exc:
                logger.warning(f"  {tag}: 국가 데이터 실패 — {exc}")
                continue

            if not country_data:
                continue

            # 국가 원수 확인
            if country_data.head_of_state:
                hos_name = country_data.head_of_state
                if not self._name_fuzzy_match(hos_name, existing, tag):
                    cid = self._name_to_char_id(hos_name, tag)
                    recommendations.append(Recommendation(
                        name=hos_name,
                        country_tag=tag,
                        suggested_char_id=cid,
                        role="head_of_state",
                        reason=f"{country_name}의 현재 국가 원수가 모드에 없음",
                        priority=100,
                    ))

            # 정부 수반 확인
            if country_data.head_of_government:
                hog_name = country_data.head_of_government
                if hog_name != getattr(country_data, 'head_of_state', '') and \
                   not self._name_fuzzy_match(hog_name, existing, tag):
                    cid = self._name_to_char_id(hog_name, tag)
                    recommendations.append(Recommendation(
                        name=hog_name,
                        country_tag=tag,
                        suggested_char_id=cid,
                        role="head_of_government",
                        reason=f"{country_name}의 현재 정부 수반이 모드에 없음",
                        priority=90,
                    ))

        # 우선순위 정렬
        recommendations.sort(key=lambda r: -r.priority)
        return recommendations

    # ------------------------------------------------------------------
    # 사망자 감지
    # ------------------------------------------------------------------

    def find_dead_characters(self) -> list[dict[str, str]]:
        """모드에 있지만 2026.1.1 이전에 사망한 인물을 찾는다."""
        existing = self.get_existing_char_ids()
        dead_chars: list[dict[str, str]] = []

        # 샘플링: 주요 국가 캐릭터만 확인 (전체는 너무 오래 걸림)
        for tag, _ in PRIORITY_COUNTRIES:
            tag_chars = [cid for cid in existing if cid.startswith(f"{tag}_")]
            for cid in tag_chars[:10]:  # 국가당 10명 샘플
                name = cid.replace(f"{tag}_", "").replace("_char", "").replace("_", " ").title()
                try:
                    person = self._extractor.extract_person(cid, name, tag)
                    if person and not person.is_alive:
                        dead_chars.append({
                            "char_id": cid,
                            "name": person.name_en or name,
                            "death_date": person.death_date,
                            "country": tag,
                        })
                except Exception:
                    continue

        return dead_chars

    # ------------------------------------------------------------------
    # 전체 추천 리포트
    # ------------------------------------------------------------------

    def generate_report(
        self, countries: list[tuple[str, str]] | None = None
    ) -> str:
        """추천 결과를 사람이 읽을 수 있는 리포트로 생성한다."""
        recs = self.recommend_essential(countries)

        lines = [
            f"=== Breaking-Point 인물 추천 리포트 ({TARGET_DATE}) ===",
            f"대상 국가: {len(countries or ALL_COUNTRIES)}개",
            f"추천 인물: {len(recs)}명",
            "",
        ]

        if recs:
            lines.append("--- 누락된 핵심 인물 ---")
            for r in recs:
                lines.append(
                    f"  [{r.priority}] {r.country_tag} | {r.name} ({r.role})"
                )
                lines.append(f"        → {r.reason}")
                lines.append(f"        → 제안 ID: {r.suggested_char_id}")
                lines.append("")

        return "\n".join(lines)
