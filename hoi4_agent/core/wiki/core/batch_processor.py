"""
병렬 배치 프로세서.
concurrent.futures로 3워커 병렬 처리 + SQLite 캐시 연동.

3,189 캐릭터 전체를 위키 데이터로 대조하는 배치 업데이트를 ~35분에 완료.
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from loguru import logger

from tools.shared.constants import MOD_ROOT, WIKI_MAX_CONCURRENT
from tools.shared.hoi4_parser import CharacterParser
from tools.shared.localisation_generator import LocalisationGenerator
from tools.wiki_updater.cache.sqlite_cache import WikiCache
from tools.wiki_updater.core.data_extractor import DataExtractor, ExtractedPersonData


# =====================================================================
# 결과 모델
# =====================================================================


@dataclass
class CharacterResult:
    """단일 캐릭터 처리 결과."""

    char_id: str
    status: str  # "updated" | "not_found" | "error" | "skipped"
    name: str = ""
    error: str = ""
    data: ExtractedPersonData | None = None


@dataclass
class BatchResult:
    """배치 처리 전체 결과."""

    total: int = 0
    updated: int = 0
    not_found: int = 0
    errors: int = 0
    skipped: int = 0
    elapsed_seconds: float = 0.0
    results: list[CharacterResult] = field(default_factory=list)

    @property
    def success_rate(self) -> float:
        """성공률 (0.0~1.0)."""
        return self.updated / self.total if self.total > 0 else 0.0

    def summary(self) -> str:
        """사람이 읽을 수 있는 요약."""
        minutes = self.elapsed_seconds / 60
        return (
            f"배치 처리 완료: {self.total}건\n"
            f"  ✓ 업데이트: {self.updated}\n"
            f"  ✗ 미발견:   {self.not_found}\n"
            f"  ⚠ 오류:     {self.errors}\n"
            f"  ⏭ 건너뜀:   {self.skipped}\n"
            f"  ⏱ 소요시간: {minutes:.1f}분\n"
            f"  📊 성공률:   {self.success_rate:.1%}"
        )


# =====================================================================
# 배치 프로세서
# =====================================================================


class BatchProcessor:
    """병렬 배치 업데이트 프로세서.

    Parameters
    ----------
    mod_root : Path
        모드 루트 경로.
    max_workers : int
        동시 실행 워커 수 (기본 3, wiki rate limit 맞춤).
    use_cache : bool
        SQLite 캐시 사용 여부 (기본 True).
    """

    def __init__(
        self,
        mod_root: Path = MOD_ROOT,
        max_workers: int = WIKI_MAX_CONCURRENT,
        use_cache: bool = True,
    ) -> None:
        self.mod_root = mod_root
        self.max_workers = max_workers
        self._parser = CharacterParser()

        # 캐시 초기화
        self._cache: WikiCache | None = None
        if use_cache:
            self._cache = WikiCache()

        # DataExtractor (캐시 연동)
        self._extractor = DataExtractor(cache=self._cache)

        # 로컬라이제이션에서 실제 이름 매핑 로드
        self._loc = LocalisationGenerator(mod_root)
        self._loc_names = self._loc.read_file()

    # ------------------------------------------------------------------
    # 이름 해석
    # ------------------------------------------------------------------

    def _resolve_search_name(self, char_id: str, country_tag: str) -> str:
        """로컬라이제이션 → char_id 추론 순서로 검색 이름 결정."""
        # 1. 로컬라이제이션에서 실제 표시 이름 (가장 정확)
        name_key = char_id.replace("_char", "")
        if name_key in self._loc_names:
            return self._loc_names[name_key]
        if char_id in self._loc_names:
            return self._loc_names[char_id]

        # 2. char_id에서 추론 (fallback)
        name_part = char_id.replace(f"{country_tag}_", "").replace("_char", "")
        return name_part.replace("_", " ").title()

    # ------------------------------------------------------------------
    # 단일 캐릭터 처리
    # ------------------------------------------------------------------

    def _process_single_character(
        self,
        char_id: str,
        country_tag: str,
        search_name: str,
        dry_run: bool = False,
    ) -> CharacterResult:
        """단일 캐릭터를 위키에서 대조하여 업데이트한다."""
        try:
            person = self._extractor.extract_person(
                char_id, search_name, country_tag
            )
            if person is None:
                return CharacterResult(
                    char_id=char_id,
                    status="not_found",
                    name=search_name,
                )

            if not dry_run:
                from tools.wiki_updater.generators.character_generator import (
                    WikiCharacterGenerator,
                )

                gen = WikiCharacterGenerator(self.mod_root)
                if not gen.update_character_in_mod(person, self.mod_root):
                    gen.add_character_to_mod(person, self.mod_root)

            return CharacterResult(
                char_id=char_id,
                status="updated",
                name=person.name_en or search_name,
                data=person,
            )
        except Exception as exc:
            logger.error("캐릭터 처리 실패 {}: {}", char_id, exc)
            return CharacterResult(
                char_id=char_id,
                status="error",
                name=search_name,
                error=str(exc),
            )

    # ------------------------------------------------------------------
    # 배치 캐릭터 처리
    # ------------------------------------------------------------------

    def process_all_characters(
        self,
        country_filter: str | None = None,
        dry_run: bool = False,
        progress_callback: Callable[[CharacterResult, int, int], None] | None = None,
    ) -> BatchResult:
        """모든 캐릭터를 병렬로 위키 대조한다.

        Parameters
        ----------
        country_filter : str | None
            특정 국가만 처리 (TAG). None이면 전체.
        dry_run : bool
            True이면 파일 수정 없이 대조만.
        progress_callback : callable | None
            (result, current, total) 콜백.

        Returns
        -------
        BatchResult
        """
        chars_dir = self.mod_root / "common" / "characters"
        all_chars = self._parser.parse_all_characters(chars_dir)

        if country_filter:
            all_chars = {
                cid: data
                for cid, data in all_chars.items()
                if self._parser.get_character_country(cid) == country_filter
            }

        total = len(all_chars)
        logger.info("배치 처리 시작: {}건 (workers={})", total, self.max_workers)
        start_time = time.time()

        result = BatchResult(total=total)

        # 작업 목록 생성 (로컬라이제이션에서 실제 이름 우선 사용)
        tasks: list[tuple[str, str, str]] = []
        for char_id in all_chars:
            ctag = self._parser.get_character_country(char_id)
            search_name = self._resolve_search_name(char_id, ctag)
            tasks.append((char_id, ctag, search_name))

        # 병렬 실행
        completed = 0
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_char = {
                executor.submit(
                    self._process_single_character,
                    char_id,
                    ctag,
                    search_name,
                    dry_run,
                ): char_id
                for char_id, ctag, search_name in tasks
            }

            for future in as_completed(future_to_char):
                char_id = future_to_char[future]
                try:
                    char_result = future.result(timeout=60)
                except Exception as exc:
                    char_result = CharacterResult(
                        char_id=char_id,
                        status="error",
                        error=str(exc),
                    )

                result.results.append(char_result)
                completed += 1

                # 집계
                if char_result.status == "updated":
                    result.updated += 1
                elif char_result.status == "not_found":
                    result.not_found += 1
                elif char_result.status == "error":
                    result.errors += 1
                elif char_result.status == "skipped":
                    result.skipped += 1

                # 콜백
                if progress_callback:
                    progress_callback(char_result, completed, total)

                # 로그 (100건마다)
                if completed % 100 == 0:
                    elapsed = time.time() - start_time
                    rate = completed / elapsed if elapsed > 0 else 0
                    logger.info(
                        "진행: {}/{} ({:.0f}/min)",
                        completed,
                        total,
                        rate * 60,
                    )

        result.elapsed_seconds = time.time() - start_time
        logger.info(result.summary())

        # 캐시 정리
        if self._cache:
            expired = self._cache.clear_expired()
            if expired:
                logger.info("만료 캐시 {}건 삭제", expired)

        return result

    # ------------------------------------------------------------------
    # 배치 국가 처리
    # ------------------------------------------------------------------

    def process_all_countries(
        self,
        country_filter: str | None = None,
        dry_run: bool = False,
        progress_callback: Callable[[dict, int, int], None] | None = None,
    ) -> BatchResult:
        """모든 국가를 위키에서 대조하여 2026.1.1 정치 데이터를 업데이트한다."""
        from tools.shared.hoi4_parser import CountryHistoryParser
        from tools.wiki_updater.core.data_extractor import COUNTRY_NAME_TO_TAG

        hist_parser = CountryHistoryParser()
        hist_dir = self.mod_root / "history" / "countries"
        all_histories = hist_parser.parse_all_histories(hist_dir)

        tag_to_name = {v: k for k, v in COUNTRY_NAME_TO_TAG.items()}

        if country_filter:
            all_histories = {
                tag: data
                for tag, data in all_histories.items()
                if tag == country_filter
            }

        total = len(all_histories)
        logger.info("국가 배치 처리 시작: {}건", total)
        start_time = time.time()

        result = BatchResult(total=total)
        completed = 0

        # 국가는 순차 처리 (각 국가당 API 호출이 적음)
        for tag, _data in all_histories.items():
            country_name = tag_to_name.get(tag, tag)
            try:
                country = self._extractor.extract_country(tag, country_name)
                if country:
                    if not dry_run:
                        from tools.wiki_updater.generators.history_generator import (
                            WikiHistoryGenerator,
                        )

                        gen = WikiHistoryGenerator(self.mod_root)
                        gen.generate_2026_update(country, self.mod_root)

                    result.updated += 1
                    char_result = CharacterResult(
                        char_id=tag, status="updated", name=country_name
                    )
                else:
                    result.not_found += 1
                    char_result = CharacterResult(
                        char_id=tag, status="not_found", name=country_name
                    )
            except Exception as exc:
                result.errors += 1
                char_result = CharacterResult(
                    char_id=tag,
                    status="error",
                    name=country_name,
                    error=str(exc),
                )
                logger.error("국가 처리 실패 {}: {}", tag, exc)

            result.results.append(char_result)
            completed += 1

            if progress_callback:
                progress_callback(
                    {"tag": tag, "status": char_result.status},
                    completed,
                    total,
                )

        result.elapsed_seconds = time.time() - start_time
        logger.info(result.summary())
        return result
