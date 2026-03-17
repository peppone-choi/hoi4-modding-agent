"""
위키 조회 도구 — Wikipedia + Wikidata를 직접 조회하여 인물/국가 데이터를 가져온다.

기존 tools/wiki_updater/core/ 모듈을 래핑한다.
DuckDuckGo 등 일반 웹 검색보다 정확한 구조화 데이터를 반환한다.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from loguru import logger


def _safe_import_wiki():
    """wiki_updater 모듈을 안전하게 임포트."""
    try:
        from tools.wiki_updater.core.wiki_client import WikipediaClient
        from tools.wiki_updater.core.wikidata_client import WikidataClient
        from tools.wiki_updater.core.data_extractor import DataExtractor
        return WikipediaClient, WikidataClient, DataExtractor
    except ImportError as exc:
        logger.error("wiki_updater 임포트 실패: {}", exc)
        return None, None, None


def wiki_lookup_person(person_name: str, country_tag: str = "", lang: str = "en") -> str:
    """
    Wikipedia + Wikidata에서 인물 정보를 검색한다.

    1. Wikidata에서 구조화 데이터 (생몰년, 직위, 정당, 성별)
    2. Wikipedia에서 인포박스 + 설명
    3. 결과를 JSON-like 텍스트로 반환

    Args:
        person_name: 검색할 인물명 (영문)
        country_tag: HOI4 국가 태그 (동명이인 해소에 사용)
        lang: Wikipedia 언어 ("en" 또는 "ko")

    Returns:
        구조화된 인물 데이터 문자열. 실패 시 에러 메시지.
    """
    WikipediaClient, WikidataClient, DataExtractor = _safe_import_wiki()
    if DataExtractor is None:
        return "[위키 조회 오류] wiki_updater 모듈을 로드할 수 없습니다."

    try:
        extractor = DataExtractor()
        char_id = f"{country_tag}_{person_name.lower().replace(' ', '_')}_char" if country_tag else "UNKNOWN_char"
        result = extractor.extract_person(char_id, person_name, country_tag)

        if result is None:
            return f"[위키 조회 실패] '{person_name}'에 대한 정보를 찾을 수 없습니다."

        data = {
            "이름_영문": result.name_en,
            "이름_한국어": result.name_ko,
            "생년월일": result.birth_date,
            "사망일": result.death_date or "생존",
            "국적": result.nationality,
            "국가태그": result.country_tag,
            "직위": result.position,
            "정당": result.party,
            "이념": result.ideology,
            "성별": result.gender,
            "Wikidata_QID": result.wikidata_qid,
            "Wikipedia_EN": result.wikipedia_url_en,
            "Wikipedia_KO": result.wikipedia_url_ko,
            "초상화파일": result.portrait_filename,
            "데이터출처": result.data_sources,
            "신뢰도": f"{result.confidence:.1%}",
        }
        return json.dumps(data, ensure_ascii=False, indent=2)

    except Exception as exc:
        logger.error("wiki_lookup_person 실패 '{}': {}", person_name, exc)
        return f"[위키 조회 오류] {exc}"


def wiki_lookup_country(country_name: str, country_tag: str = "") -> str:
    """
    Wikipedia에서 국가 정치 데이터를 검색한다.

    Args:
        country_name: 국가 이름 (영문, 예: "South Korea")
        country_tag: HOI4 국가 태그

    Returns:
        구조화된 국가 데이터 문자열.
    """
    WikipediaClient, WikidataClient, DataExtractor = _safe_import_wiki()
    if WikipediaClient is None:
        return "[위키 조회 오류] wiki_updater 모듈을 로드할 수 없습니다."

    try:
        client = WikipediaClient(lang="en")
        country_data = client.get_country_data(country_name)

        if country_data is None:
            return f"[위키 조회 실패] '{country_name}'에 대한 국가 데이터를 찾을 수 없습니다."

        data = {
            "국가명": country_data.country_name,
            "정부형태": country_data.government_type,
            "국가원수": country_data.head_of_state,
            "정부수반": country_data.head_of_government,
            "집권당": country_data.ruling_party,
            "수도": country_data.capital,
            "Wikipedia_URL": country_data.wikipedia_url,
        }
        return json.dumps(data, ensure_ascii=False, indent=2)

    except Exception as exc:
        logger.error("wiki_lookup_country 실패 '{}': {}", country_name, exc)
        return f"[위키 조회 오류] {exc}"


def wiki_lookup_political_parties(country_qid: str) -> str:
    """
    Wikidata에서 특정 국가의 정당 목록을 조회한다.

    Args:
        country_qid: Wikidata 국가 QID (예: "Q30"=미국, "Q884"=한국)

    Returns:
        정당 목록 JSON 문자열.
    """
    _, WikidataClient, _ = _safe_import_wiki()
    if WikidataClient is None:
        return "[위키 조회 오류] wiki_updater 모듈을 로드할 수 없습니다."

    try:
        client = WikidataClient()
        parties = client.get_political_parties_by_country(country_qid)

        if not parties:
            return f"[위키 조회 실패] QID '{country_qid}'의 정당 데이터를 찾을 수 없습니다."

        return json.dumps(parties, ensure_ascii=False, indent=2)

    except Exception as exc:
        logger.error("wiki_lookup_political_parties 실패 '{}': {}", country_qid, exc)
        return f"[위키 조회 오류] {exc}"


def wiki_lookup_person_positions(person_qid: str, date: str = "2026-01-01") -> str:
    """
    Wikidata에서 특정 날짜 기준 인물의 직위를 조회한다.

    Args:
        person_qid: Wikidata 인물 QID (예: "Q22686"=트럼프)
        date: 기준 날짜 (ISO, 기본: 2026-01-01)

    Returns:
        직위 목록 JSON 문자열.
    """
    _, WikidataClient, _ = _safe_import_wiki()
    if WikidataClient is None:
        return "[위키 조회 오류] wiki_updater 모듈을 로드할 수 없습니다."

    try:
        client = WikidataClient()
        positions = client.get_person_positions_at_date(person_qid, date)

        if not positions:
            return f"[위키 조회 실패] QID '{person_qid}'의 직위 데이터를 찾을 수 없습니다 ({date} 기준)."

        return json.dumps(positions, ensure_ascii=False, indent=2)

    except Exception as exc:
        logger.error("wiki_lookup_person_positions 실패 '{}': {}", person_qid, exc)
        return f"[위키 조회 오류] {exc}"
