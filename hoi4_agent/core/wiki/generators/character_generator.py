"""
위키 데이터 → HOI4 캐릭터 파일 생성기.
DataExtractor의 결과를 HOI4 mod 파일로 변환한다.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from loguru import logger

from tools.shared.constants import CHARACTERS_DIR, TARGET_DATE
from tools.shared.file_manager import FileManager
from tools.shared.hoi4_generator import CharacterData, CharacterGenerator as BaseGen
from tools.shared.hoi4_parser import CharacterParser
from tools.wiki_updater.core.data_extractor import ExtractedPersonData


class WikiCharacterGenerator:
    """위키 데이터 → HOI4 캐릭터 파일 변환."""

    def __init__(self, mod_root: Path | None = None) -> None:
        self._base = BaseGen()
        self._parser = CharacterParser()
        self.mod_root = mod_root
        self._fm = FileManager(mod_root) if mod_root else None

    # ------------------------------------------------------------------
    # 변환
    # ------------------------------------------------------------------

    def generate_from_extracted(self, person: ExtractedPersonData) -> CharacterData:
        """``ExtractedPersonData`` → ``CharacterData``."""
        return CharacterData(
            char_id=person.char_id,
            name_key=person.char_id.replace("_char", ""),
            gender=person.gender,
            portrait_civilian=f"gfx/leaders/{person.country_tag}/{person.char_id}.png",
            country_leader_ideology=person.ideology,
            country_leader_desc=f"POLITICS_{person.char_id.upper().replace('_CHAR', '')}_DESC",
        )

    # ------------------------------------------------------------------
    # 모드 파일 조작
    # ------------------------------------------------------------------

    def add_character_to_mod(self, person: ExtractedPersonData, mod_root: Path | None = None) -> Path:
        """적절한 캐릭터 파일에 캐릭터를 추가한다."""
        root = mod_root or self.mod_root
        if root is None:
            raise ValueError("mod_root가 필요합니다")

        from hoi4_agent.core.scanner import detect_mod_prefix
        prefix = detect_mod_prefix(root)
        
        char_data = self.generate_from_extracted(person)
        chars_dir = root / "common" / "characters"
        target_file = chars_dir / f"{prefix}_characters_{person.country_tag}.txt"

        if target_file.exists():
            self._base.add_character_to_file(char_data, target_file)
        else:
            content = self._base.generate_characters_file([char_data])
            target_file.parent.mkdir(parents=True, exist_ok=True)
            target_file.write_text(content, encoding="utf-8")

        logger.info(f"캐릭터 추가: {person.char_id} → {target_file.name}")
        return target_file

    def update_character_in_mod(self, person: ExtractedPersonData, mod_root: Path | None = None) -> bool:
        """모드의 기존 캐릭터를 업데이트한다."""
        root = mod_root or self.mod_root
        if root is None:
            raise ValueError("mod_root가 필요합니다")

        from hoi4_agent.core.scanner import detect_mod_prefix
        prefix = detect_mod_prefix(root)
        
        char_data = self.generate_from_extracted(person)
        chars_dir = root / "common" / "characters"

        for fpath in chars_dir.glob(f"{prefix}_characters_*.txt"):
            if self._base.update_character_in_file(char_data, fpath):
                logger.info(f"캐릭터 업데이트: {person.char_id} in {fpath.name}")
                return True
        return False

    def remove_character_from_mod(self, char_id: str, mod_root: Path | None = None) -> bool:
        """모드에서 캐릭터를 제거한다."""
        root = mod_root or self.mod_root
        if root is None:
            raise ValueError("mod_root가 필요합니다")

        from hoi4_agent.core.scanner import detect_mod_prefix
        prefix = detect_mod_prefix(root)
        
        chars_dir = root / "common" / "characters"
        for fpath in chars_dir.glob(f"{prefix}_characters_*.txt"):
            if self._base.remove_character_from_file(char_id, fpath):
                logger.info(f"캐릭터 제거: {char_id} from {fpath.name}")
                return True
        return False

    # ------------------------------------------------------------------
    # 로컬라이제이션
    # ------------------------------------------------------------------

    def generate_localisation(self, person: ExtractedPersonData) -> dict[str, str]:
        """캐릭터 관련 로컬라이제이션 키-값 생성."""
        base_key = person.char_id.replace("_char", "")
        return {
            base_key: person.name_en or base_key.replace("_", " ").title(),
            f"POLITICS_{base_key.upper()}_DESC": person.position or "",
        }
