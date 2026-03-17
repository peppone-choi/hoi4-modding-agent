"""
위키 데이터 → HOI4 history/countries 파일 업데이트.
2026.1.1 날짜 블록 생성, 집권당 변경, 캐릭터 소환 등.
"""
from __future__ import annotations

from pathlib import Path

from loguru import logger

from tools.shared.constants import HISTORY_COUNTRIES_DIR, TARGET_DATE
from tools.shared.file_manager import FileManager
from tools.shared.hoi4_generator import DateBlock, HistoryGenerator as BaseHistGen, PoliticsData
from tools.shared.hoi4_parser import CountryHistoryParser
from tools.wiki_updater.core.data_extractor import ExtractedCountryData


class WikiHistoryGenerator:
    """위키 데이터 → HOI4 히스토리 파일 업데이트."""

    def __init__(self, mod_root: Path | None = None) -> None:
        self._base = BaseHistGen()
        self._parser = CountryHistoryParser()
        self.mod_root = mod_root

    # ------------------------------------------------------------------
    # 히스토리 파일 찾기
    # ------------------------------------------------------------------

    def _find_history_file(self, country_tag: str, mod_root: Path) -> Path | None:
        """TAG에 해당하는 history/countries/ 파일을 찾는다."""
        hist_dir = mod_root / "history" / "countries"
        for fpath in hist_dir.glob("*.txt"):
            if fpath.name.startswith(f"{country_tag} ") or fpath.name.startswith(f"{country_tag}_"):
                return fpath
        # 정확히 TAG로 시작하는 파일이 없으면 TAG.txt 시도
        simple = hist_dir / f"{country_tag}.txt"
        return simple if simple.exists() else None

    # ------------------------------------------------------------------
    # 2026 업데이트
    # ------------------------------------------------------------------

    def generate_2026_update(self, country: ExtractedCountryData, mod_root: Path | None = None) -> bool:
        """2026.1.1 날짜 블록을 history 파일에 추가한다."""
        root = mod_root or self.mod_root
        if root is None:
            raise ValueError("mod_root가 필요합니다")

        fpath = self._find_history_file(country.country_tag, root)
        if fpath is None:
            logger.warning(f"히스토리 파일 없음: {country.country_tag}")
            return False

        politics = None
        if country.ruling_ideology:
            politics = PoliticsData(
                ruling_party=country.ruling_ideology,
                elections_allowed=True,
                popularities=country.ideology_popularities,
            )

        block = DateBlock(
            date=TARGET_DATE,
            politics=politics,
            recruit_characters=[
                country.head_of_state_char_id,
                country.head_of_government_char_id,
            ] if country.head_of_state_char_id else [],
        )
        # 빈 리스트 정리
        block.recruit_characters = [c for c in block.recruit_characters if c]

        self._base.add_date_block(block, fpath)
        logger.info(f"2026 업데이트 추가: {country.country_tag} → {fpath.name}")
        return True

    # ------------------------------------------------------------------
    # 개별 업데이트
    # ------------------------------------------------------------------

    def update_ruling_party(self, country_tag: str, ideology: str, mod_root: Path | None = None) -> bool:
        """집권당 이념을 업데이트한다."""
        root = mod_root or self.mod_root
        if root is None:
            raise ValueError("mod_root가 필요합니다")

        fpath = self._find_history_file(country_tag, root)
        if fpath is None:
            logger.warning(f"히스토리 파일 없음: {country_tag}")
            return False

        politics = PoliticsData(ruling_party=ideology)
        self._base.update_politics_at_date(TARGET_DATE, politics, fpath)
        logger.info(f"집권당 업데이트: {country_tag} → {ideology}")
        return True

    def add_recruit_character(self, country_tag: str, char_id: str, mod_root: Path | None = None) -> bool:
        """히스토리 파일에 recruit_character를 추가한다."""
        root = mod_root or self.mod_root
        if root is None:
            raise ValueError("mod_root가 필요합니다")

        fpath = self._find_history_file(country_tag, root)
        if fpath is None:
            logger.warning(f"히스토리 파일 없음: {country_tag}")
            return False

        content = fpath.read_text(encoding="utf-8-sig")
        recruit_line = f"\trecruit_character = {char_id}\n"

        # 이미 존재하면 중복 추가 방지
        if f"recruit_character = {char_id}" in content:
            logger.debug(f"이미 존재: recruit_character = {char_id}")
            return True

        # 파일 끝에 추가 (마지막 닫는 중괄호 앞은 아님 — 최상위 레벨)
        content = content.rstrip() + "\n" + recruit_line
        fpath.write_text(content, encoding="utf-8")
        logger.info(f"recruit_character 추가: {country_tag} → {char_id}")
        return True
