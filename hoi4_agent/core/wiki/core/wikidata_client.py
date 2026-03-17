"""
Wikidata SPARQL 클라이언트.
구조화된 데이터(생몰년, 직위, 국적 등)를 쿼리한다.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import requests
from loguru import logger

from tools.shared.constants import (
    WIKIDATA_SPARQL_URL,
    WIKI_USER_AGENT,
    WIKI_RATE_LIMIT_DELAY,
)


@dataclass
class WikidataEntityData:
    """Wikidata 엔티티 데이터."""

    qid: str  # Q-ID (예: Q22686)
    label: str = ""  # 이름
    description: str = ""
    birth_date: str = ""  # ISO 형식
    death_date: str = ""
    nationality: str = ""  # 국가명
    positions: list[str] = field(default_factory=list)  # 직위 목록
    parties: list[str] = field(default_factory=list)  # 정당 목록
    military_ranks: list[str] = field(default_factory=list)
    image: str = ""  # Commons 파일명
    gender: str = ""  # "male" / "female"


class WikidataClient:
    """Wikidata 클라이언트 (REST API 전용 (검색/엔티티), SPARQL (분석 쿼리용))."""

    WBSEARCH_URL = "https://www.wikidata.org/w/api.php"
    REST_ENTITY_URL = "https://www.wikidata.org/wiki/Special:EntityData/{qid}.json"

    def __init__(self, rate_limit: float = WIKI_RATE_LIMIT_DELAY) -> None:
        self.rate_limit = rate_limit
        self._last_request: float = 0.0
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": WIKI_USER_AGENT,
                "Accept": "application/json",
            }
        )

    # ------------------------------------------------------------------
    # 내부 헬퍼
    # ------------------------------------------------------------------

    def _throttle(self) -> None:
        elapsed = time.time() - self._last_request
        if elapsed < self.rate_limit:
            time.sleep(self.rate_limit - elapsed)

    def _sparql_query(self, query: str) -> list[dict]:
        """SPARQL 쿼리 실행. 결과 rows 반환."""
        self._throttle()
        logger.debug("SPARQL query:\n{}", query[:200])
        try:
            response = self.session.get(
                WIKIDATA_SPARQL_URL,
                params={"query": query, "format": "json"},
                timeout=15,
            )
            response.raise_for_status()
            self._last_request = time.time()
            data = response.json()
            return data.get("results", {}).get("bindings", [])
        except (requests.Timeout, requests.HTTPError) as exc:
            logger.warning("SPARQL timeout/error, will use REST API: {}", exc)
            return []

    def _rest_get_entity(self, qid: str) -> dict | None:
        """Wikidata REST API로 엔티티 JSON 가져오기. 429 시 retry."""
        max_retries = 3
        url = self.REST_ENTITY_URL.format(qid=qid)
        for attempt in range(max_retries):
            self._throttle()
            try:
                resp = self.session.get(url, timeout=15)
                if resp.status_code == 429:
                    wait = 2 ** (attempt + 1)
                    logger.warning("429 rate limited on REST {}, retry in {}s", qid, wait)
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                self._last_request = time.time()
                data = resp.json()
                return data.get("entities", {}).get(qid)
            except Exception as exc:
                if attempt < max_retries - 1:
                    time.sleep(2 ** (attempt + 1))
                    continue
                logger.warning("REST entity fetch failed for {}: {}", qid, exc)
                return None
        return None

    def _wbsearch(self, name: str, lang: str = "en", limit: int = 5) -> list[dict]:
        """Wikidata wbsearchentities API. 429 시 exponential backoff retry."""
        max_retries = 3
        for attempt in range(max_retries):
            self._throttle()
            try:
                resp = self.session.get(self.WBSEARCH_URL, params={
                    "action": "wbsearchentities",
                    "search": name,
                    "language": lang,
                    "type": "item",
                    "limit": str(limit),
                    "format": "json",
                }, timeout=10)
                if resp.status_code == 429:
                    wait = 2 ** (attempt + 1)
                    logger.warning("429 rate limited, retry in {}s (attempt {}/{})", wait, attempt + 1, max_retries)
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                self._last_request = time.time()
                return resp.json().get("search", [])
            except Exception as exc:
                if attempt < max_retries - 1:
                    time.sleep(2 ** (attempt + 1))
                    continue
                logger.warning("wbsearch failed for '{}': {}", name, exc)
                return []
        return []

    def _parse_rest_entity(self, entity_json: dict) -> WikidataEntityData:
        """REST API JSON → WikidataEntityData 파싱."""
        qid = entity_json.get("id", "")
        labels = entity_json.get("labels", {})
        descriptions = entity_json.get("descriptions", {})
        claims = entity_json.get("claims", {})

        label = labels.get("en", {}).get("value", labels.get("ko", {}).get("value", ""))
        desc = descriptions.get("en", {}).get("value", "")

        def _claim_val(prop: str, idx: int = 0) -> str:
            cl = claims.get(prop, [])
            if idx < len(cl):
                ms = cl[idx].get("mainsnak", {}).get("datavalue", {}).get("value", {})
                if isinstance(ms, dict):
                    return ms.get("time", ms.get("id", ms.get("text", str(ms))))
                return str(ms)
            return ""

        def _claim_vals(prop: str) -> list[str]:
            return [
                c.get("mainsnak", {}).get("datavalue", {}).get("value", {}).get("id", "")
                for c in claims.get(prop, [])
                if c.get("mainsnak", {}).get("datavalue", {}).get("value", {}).get("id")
            ]

        birth_raw = _claim_val("P569")  # date of birth
        death_raw = _claim_val("P570")  # date of death
        gender_qid = _claim_val("P21")   # gender

        # 이미지
        image_claims = claims.get("P18", [])
        image = ""
        if image_claims:
            img_val = image_claims[0].get("mainsnak", {}).get("datavalue", {}).get("value", "")
            if isinstance(img_val, str):
                image = img_val

        entity = WikidataEntityData(
            qid=qid,
            label=label,
            description=desc,
            birth_date=birth_raw[1:11] if birth_raw.startswith("+") else birth_raw[:10],
            death_date=death_raw[1:11] if death_raw.startswith("+") else death_raw[:10],
            gender="male" if gender_qid == "Q6581097" else ("female" if gender_qid == "Q6581072" else ""),
            image=image,
        )

        # 직위 (P39) - QID만 가져옴, 라벨은 나중에
        entity.positions = _claim_vals("P39")
        # 정당 (P102)
        entity.parties = _claim_vals("P102")
        # 군사 계급 (P410)
        entity.military_ranks = _claim_vals("P410")

        return entity

    def _extract_value(self, binding: dict, key: str) -> str:
        """SPARQL 결과에서 값 추출 헬퍼."""
        return binding.get(key, {}).get("value", "")

    @staticmethod
    def _qid_from_uri(uri: str) -> str:
        """``http://www.wikidata.org/entity/Q22686`` → ``Q22686``."""
        return uri.rsplit("/", 1)[-1] if "/" in uri else uri

    @staticmethod
    def _commons_filename(url: str) -> str:
        """Commons 파일 URL → 파일명."""
        # http://commons.wikimedia.org/wiki/Special:FilePath/Example.jpg
        if "Special:FilePath/" in url:
            return url.split("Special:FilePath/")[-1]
        return url.rsplit("/", 1)[-1] if "/" in url else url

    # ------------------------------------------------------------------
    # 엔티티 조회
    # ------------------------------------------------------------------

    def get_entity_by_qid(self, qid: str) -> WikidataEntityData | None:
        """Q-ID로 엔티티 데이터 가져오기 (REST API only)."""
        entity_json = self._rest_get_entity(qid)
        if entity_json:
            entity = self._parse_rest_entity(entity_json)
            if entity.label:
                logger.debug("REST API로 {} 조회 성공: {}", qid, entity.label)
                return entity
        
        logger.warning("REST API failed for QID {}", qid)
        return None

    # ------------------------------------------------------------------
    # 검색
    # ------------------------------------------------------------------

    def search_person(self, name: str, lang: str = "en") -> list[WikidataEntityData]:
        """이름으로 인물 검색 (wbsearchentities only)."""
        wb_results = self._wbsearch(name, lang=lang, limit=10)
        if not wb_results:
            logger.warning("No wbsearch results for '{}'", name)
            return []
        
        results: list[WikidataEntityData] = []
        for item in wb_results:
            qid = item.get("id", "")
            results.append(
                WikidataEntityData(
                    qid=qid,
                    label=item.get("label", ""),
                    description=item.get("description", ""),
                )
            )
        return results

    # ------------------------------------------------------------------
    # 국가 원수 / 정부 수반
    # ------------------------------------------------------------------

    def get_current_heads_of_state(self) -> list[dict]:
        """현재(2026-01-01 기준) 국가 원수 목록."""
        query = """
SELECT DISTINCT ?person ?personLabel ?country ?countryLabel ?startDate
WHERE {
  ?country wdt:P35 ?person .
  OPTIONAL {
    ?country p:P35 ?statement .
    ?statement ps:P35 ?person ;
               pq:P580 ?startDate .
    FILTER NOT EXISTS {
      ?statement pq:P582 ?endDate .
      FILTER(?endDate < "2026-01-01"^^xsd:dateTime)
    }
  }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en,ko" . }
}
LIMIT 200
"""
        try:
            rows = self._sparql_query(query)
        except requests.HTTPError as exc:
            logger.error("Failed to fetch heads of state: {}", exc)
            return []

        results: list[dict] = []
        for row in rows:
            results.append(
                {
                    "qid": self._qid_from_uri(self._extract_value(row, "person")),
                    "name": self._extract_value(row, "personLabel"),
                    "country_qid": self._qid_from_uri(
                        self._extract_value(row, "country")
                    ),
                    "country": self._extract_value(row, "countryLabel"),
                    "start_date": self._extract_value(row, "startDate")[:10]
                    if self._extract_value(row, "startDate")
                    else "",
                }
            )
        return results

    def get_current_heads_of_government(self) -> list[dict]:
        """현재(2026-01-01 기준) 정부 수반 목록."""
        query = """
SELECT DISTINCT ?person ?personLabel ?country ?countryLabel ?startDate
WHERE {
  ?country wdt:P6 ?person .
  OPTIONAL {
    ?country p:P6 ?statement .
    ?statement ps:P6 ?person ;
               pq:P580 ?startDate .
    FILTER NOT EXISTS {
      ?statement pq:P582 ?endDate .
      FILTER(?endDate < "2026-01-01"^^xsd:dateTime)
    }
  }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en,ko" . }
}
LIMIT 200
"""
        try:
            rows = self._sparql_query(query)
        except requests.HTTPError as exc:
            logger.error("Failed to fetch heads of government: {}", exc)
            return []

        results: list[dict] = []
        for row in rows:
            results.append(
                {
                    "qid": self._qid_from_uri(self._extract_value(row, "person")),
                    "name": self._extract_value(row, "personLabel"),
                    "country_qid": self._qid_from_uri(
                        self._extract_value(row, "country")
                    ),
                    "country": self._extract_value(row, "countryLabel"),
                    "start_date": self._extract_value(row, "startDate")[:10]
                    if self._extract_value(row, "startDate")
                    else "",
                }
            )
        return results

    # ------------------------------------------------------------------
    # 군사 / 정당
    # ------------------------------------------------------------------

    def get_military_commanders(
        self, country_qid: str
    ) -> list[WikidataEntityData]:
        """특정 국가의 군사 지도자 목록."""
        query = f"""
SELECT DISTINCT ?person ?personLabel ?birthDate ?deathDate
       ?rank ?rankLabel ?position ?positionLabel
WHERE {{
  ?person wdt:P27 wd:{country_qid} ;
          wdt:P31 wd:Q5 .
  {{ ?person wdt:P410 ?rank }}
  UNION
  {{ ?person wdt:P39 ?position .
     ?position wdt:P31*/wdt:P279* wd:Q2100994 }}
  OPTIONAL {{ ?person wdt:P569 ?birthDate }}
  OPTIONAL {{ ?person wdt:P570 ?deathDate }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en" . }}
}}
LIMIT 100
"""
        try:
            rows = self._sparql_query(query)
        except requests.HTTPError as exc:
            logger.error(
                "Failed to fetch military commanders for {}: {}",
                country_qid,
                exc,
            )
            return []

        entities: dict[str, WikidataEntityData] = {}
        for row in rows:
            uri = self._extract_value(row, "person")
            qid = self._qid_from_uri(uri)
            if qid not in entities:
                birth_raw = self._extract_value(row, "birthDate")
                death_raw = self._extract_value(row, "deathDate")
                entities[qid] = WikidataEntityData(
                    qid=qid,
                    label=self._extract_value(row, "personLabel"),
                    birth_date=birth_raw[:10] if birth_raw else "",
                    death_date=death_raw[:10] if death_raw else "",
                )

            rnk = self._extract_value(row, "rankLabel")
            if rnk and rnk not in entities[qid].military_ranks:
                entities[qid].military_ranks.append(rnk)

            pos = self._extract_value(row, "positionLabel")
            if pos and pos not in entities[qid].positions:
                entities[qid].positions.append(pos)

        return list(entities.values())

    def get_political_parties_by_country(self, country_qid: str) -> list[dict]:
        """특정 국가의 정당 목록."""
        query = f"""
SELECT DISTINCT ?party ?partyLabel ?ideology ?ideologyLabel ?founded
WHERE {{
  ?party wdt:P31 wd:Q7278 ;
         wdt:P17 wd:{country_qid} .
  OPTIONAL {{ ?party wdt:P1142 ?ideology }}
  OPTIONAL {{ ?party wdt:P571 ?founded }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en" . }}
}}
LIMIT 100
"""
        try:
            rows = self._sparql_query(query)
        except requests.HTTPError as exc:
            logger.error(
                "Failed to fetch parties for {}: {}", country_qid, exc
            )
            return []

        results: list[dict] = []
        for row in rows:
            founded_raw = self._extract_value(row, "founded")
            results.append(
                {
                    "qid": self._qid_from_uri(
                        self._extract_value(row, "party")
                    ),
                    "name": self._extract_value(row, "partyLabel"),
                    "ideology": self._extract_value(row, "ideologyLabel"),
                    "founded": founded_raw[:10] if founded_raw else "",
                }
            )
        return results

    # ------------------------------------------------------------------
    # 직위 (날짜 필터)
    # ------------------------------------------------------------------

    def get_person_positions_at_date(
        self, qid: str, date: str = "2026-01-01"
    ) -> list[dict]:
        """특정 날짜에 인물이 가진 직위 목록. *date* 는 ISO 형식."""
        query = f"""
SELECT ?position ?positionLabel ?startDate ?endDate ?ofLabel
WHERE {{
  wd:{qid} p:P39 ?stmt .
  ?stmt ps:P39 ?position .
  OPTIONAL {{ ?stmt pq:P580 ?startDate }}
  OPTIONAL {{ ?stmt pq:P582 ?endDate }}
  OPTIONAL {{ ?stmt pq:P642 ?of }}
  FILTER(
    (!BOUND(?startDate) || ?startDate <= "{date}"^^xsd:dateTime) &&
    (!BOUND(?endDate) || ?endDate >= "{date}"^^xsd:dateTime)
  )
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en" . }}
}}
"""
        try:
            rows = self._sparql_query(query)
        except requests.HTTPError as exc:
            logger.error(
                "Failed to fetch positions for {} at {}: {}", qid, date, exc
            )
            return []

        results: list[dict] = []
        for row in rows:
            start_raw = self._extract_value(row, "startDate")
            end_raw = self._extract_value(row, "endDate")
            results.append(
                {
                    "position_qid": self._qid_from_uri(
                        self._extract_value(row, "position")
                    ),
                    "position": self._extract_value(row, "positionLabel"),
                    "start_date": start_raw[:10] if start_raw else "",
                    "end_date": end_raw[:10] if end_raw else "",
                    "of": self._extract_value(row, "ofLabel"),
                }
            )
        return results
