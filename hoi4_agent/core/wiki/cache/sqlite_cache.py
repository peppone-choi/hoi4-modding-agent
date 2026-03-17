"""
API 응답 SQLite 캐시.
Wikipedia/Wikidata 응답을 30일간 캐시하여 API 호출 최소화.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from pathlib import Path
from typing import Any

from loguru import logger

from tools.shared.constants import CACHE_DIR, WIKI_CACHE_TTL_DAYS


class WikiCache:
    """SQLite 기반 API 응답 캐시."""

    def __init__(
        self,
        cache_dir: Path = CACHE_DIR,
        ttl_days: int = WIKI_CACHE_TTL_DAYS,
    ) -> None:
        self.cache_dir = cache_dir
        self.ttl_days = ttl_days
        self.db_path = cache_dir / "wiki_cache.db"
        self._init_db()

    # ── internal ──────────────────────────────────────

    def _init_db(self) -> None:
        """SQLite DB 초기화. 테이블 생성."""
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS cache_entries (
                    key        TEXT PRIMARY KEY,
                    value      TEXT    NOT NULL,
                    created_at REAL    NOT NULL,
                    source     TEXT    NOT NULL
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        """DB 연결 반환."""
        return sqlite3.connect(str(self.db_path))

    def _make_key(self, source: str, query: str) -> str:
        """캐시 키 생성 (source + query 의 SHA-256 해시)."""
        raw = f"{source}:{query}"
        return hashlib.sha256(raw.encode()).hexdigest()

    def _is_expired(self, created_at: float) -> bool:
        """항목이 TTL 을 초과했는지 확인."""
        return (time.time() - created_at) > self.ttl_days * 86_400

    @staticmethod
    def _json_default(obj: Any) -> Any:
        """dataclass/object → dict for JSON serialization."""
        import dataclasses
        if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
            return dataclasses.asdict(obj)
        raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")

    # ── public API ────────────────────────────────────

    def get(self, source: str, query: str) -> Any | None:
        """캐시에서 값 가져오기. 만료되었거나 없으면 ``None``."""
        key = self._make_key(source, query)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value, created_at FROM cache_entries WHERE key = ?",
                (key,),
            ).fetchone()
        if row is None:
            return None
        value_json, created_at = row
        if self._is_expired(created_at):
            logger.debug("캐시 만료: source={}, query={}", source, query)
            return None
        return json.loads(value_json)

    def set(self, source: str, query: str, value: Any) -> None:
        """캐시에 값 저장. 기존 항목은 덮어씀."""
        key = self._make_key(source, query)
        value_json = json.dumps(value, ensure_ascii=False, default=self._json_default)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO cache_entries (key, value, created_at, source)
                VALUES (?, ?, ?, ?)
                """,
                (key, value_json, time.time(), source),
            )
        logger.debug("캐시 저장: source={}, query={}", source, query)

    def invalidate(self, source: str, query: str) -> bool:
        """특정 캐시 항목 삭제. 삭제 여부 반환."""
        key = self._make_key(source, query)
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM cache_entries WHERE key = ?", (key,)
            )
        return cursor.rowcount > 0

    def clear_expired(self) -> int:
        """만료된 캐시 항목 모두 삭제. 삭제된 항목 수 반환."""
        cutoff = time.time() - self.ttl_days * 86_400
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM cache_entries WHERE created_at < ?", (cutoff,)
            )
        deleted = cursor.rowcount
        if deleted:
            logger.info("만료 캐시 {}건 삭제", deleted)
        return deleted

    def clear_all(self) -> None:
        """모든 캐시 삭제."""
        with self._connect() as conn:
            conn.execute("DELETE FROM cache_entries")
        logger.info("캐시 전체 삭제")

    def stats(self) -> dict:
        """캐시 통계 반환. 항목 수, 만료 항목 수, DB 파일 크기 등."""
        cutoff = time.time() - self.ttl_days * 86_400
        with self._connect() as conn:
            total = conn.execute(
                "SELECT COUNT(*) FROM cache_entries"
            ).fetchone()[0]
            expired = conn.execute(
                "SELECT COUNT(*) FROM cache_entries WHERE created_at < ?",
                (cutoff,),
            ).fetchone()[0]
            sources = conn.execute(
                "SELECT source, COUNT(*) FROM cache_entries GROUP BY source"
            ).fetchall()

        db_size = self.db_path.stat().st_size if self.db_path.exists() else 0
        return {
            "total_entries": total,
            "expired_entries": expired,
            "active_entries": total - expired,
            "db_size_bytes": db_size,
            "sources": {src: cnt for src, cnt in sources},
        }

    def get_or_fetch(
        self, source: str, query: str, fetch_fn: callable
    ) -> Any:
        """캐시에 없으면 *fetch_fn* 을 호출하여 가져오고 캐시에 저장."""
        cached = self.get(source, query)
        if cached is not None:
            logger.debug("캐시 히트: source={}, query={}", source, query)
            return cached

        logger.debug("캐시 미스 → fetch: source={}, query={}", source, query)
        result = fetch_fn()
        if result is not None:
            self.set(source, query, result)
        return result


# ── Cached client wrappers ────────────────────────────


class CachedWikipediaClient:
    """캐시가 통합된 Wikipedia 클라이언트 래퍼."""

    def __init__(self, cache: WikiCache, wiki_client: Any) -> None:
        self.cache = cache
        self.client = wiki_client

    def get_person_data(self, title: str) -> Any:
        """캐시 확인 후 Wikipedia 호출. dict→dataclass 안전 복원."""
        cached = self.cache.get(source="wikipedia", query=f"person:{title}")
        if cached is not None:
            if isinstance(cached, dict) and "birth_date" in cached:
                try:
                    from tools.wiki_updater.core.wiki_client import WikipediaPersonData
                    return WikipediaPersonData(**cached)
                except TypeError:
                    pass
            return cached

        result = self.client.get_person_data(title)
        if result is not None:
            self.cache.set(source="wikipedia", query=f"person:{title}", value=result)
        return result

    def get_page_wikitext(self, title: str) -> str | None:
        """캐시 확인 후 wikitext 가져오기."""
        return self.cache.get_or_fetch(
            source="wikipedia",
            query=f"wikitext:{title}",
            fetch_fn=lambda: self.client.get_page_wikitext(title),
        )

    def get_country_data(self, country_name: str) -> Any:
        """캐시 확인 후 국가 데이터 가져오기."""
        return self.cache.get_or_fetch(
            source="wikipedia",
            query=f"country:{country_name}",
            fetch_fn=lambda: self.client.get_country_data(country_name),
        )

    def __getattr__(self, name: str) -> Any:
        """캐시되지 않은 메서드는 원본 클라이언트로 위임."""
        return getattr(self.client, name)


class CachedWikidataClient:
    """캐시가 통합된 Wikidata 클라이언트 래퍼."""

    def __init__(self, cache: WikiCache, wikidata_client: Any) -> None:
        self.cache = cache
        self.client = wikidata_client

    def get_entity_by_qid(self, qid: str) -> Any:
        """캐시 확인 후 Wikidata 호출. dataclass → dict 자동 변환."""
        cached = self.cache.get(source="wikidata", query=f"entity:{qid}")
        if cached is not None:
            if isinstance(cached, dict) and "qid" in cached:
                from tools.wiki_updater.core.wikidata_client import WikidataEntityData
                return WikidataEntityData(**cached)
            return cached

        result = self.client.get_entity_by_qid(qid)
        if result is not None:
            self.cache.set(source="wikidata", query=f"entity:{qid}", value=result)
        return result

    def search_person(self, name: str, lang: str = "en") -> Any:
        """인물 검색은 캐시하지 않음 (빠르고 결과가 동적)."""
        return self.client.search_person(name, lang=lang)

    def __getattr__(self, name: str) -> Any:
        """캐시되지 않은 메서드는 원본 클라이언트로 위임."""
        return getattr(self.client, name)
