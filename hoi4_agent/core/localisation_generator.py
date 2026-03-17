"""
HOI4 로컬라이제이션 파일 생성/업데이트.
캐릭터 추가/수정 시 localisation/english/TFR_characters_l_english.yml을 자동 업데이트한다.

HOI4 로컬라이제이션 형식:
    파일 인코딩: UTF-8 BOM (\\ufeff)
    헤더: l_english:
    항목: <공백>KEY: "Value"

사용법:
    from tools.shared.localisation_generator import LocalisationGenerator
    
    gen = LocalisationGenerator(mod_root)
    
    # 캐릭터 로컬라이제이션 추가
    gen.add_character_loc("USA_donald_trump_char", "Donald Trump")
    
    # 여러 항목 일괄 추가
    gen.add_entries({
        "USA_donald_trump_char": "Donald Trump",
        "POLITICS_USA_DONALD_TRUMP_DESC": "45th President",
    })
    
    # 키 존재 여부 확인
    gen.has_key("USA_donald_trump_char")
    
    # 누락 키 감지
    missing = gen.find_missing_character_keys(mod_root)
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from loguru import logger

from tools.shared.constants import MOD_ROOT
from tools.shared.hoi4_parser import CharacterParser


# =====================================================================
# 로컬라이제이션 파서/생성기
# =====================================================================


class LocalisationGenerator:
    """HOI4 로컬라이제이션 파일 관리.

    UTF-8 BOM + l_<lang>: 헤더 형식을 처리한다.
    """

    BOM = "\ufeff"
    HEADER = "l_english:"

    def __init__(
        self,
        mod_root: Path = MOD_ROOT,
        lang: str = "english",
    ) -> None:
        self.mod_root = mod_root
        self.lang = lang
        self._loc_dir = mod_root / "localisation" / lang
        self._char_file = self._loc_dir / f"TFR_characters_l_{lang}.yml"

    # ------------------------------------------------------------------
    # 읽기
    # ------------------------------------------------------------------

    def read_file(self, file_path: Path | None = None) -> dict[str, str]:
        """로컬라이제이션 파일을 key→value dict로 파싱."""
        path = file_path or self._char_file
        if not path.exists():
            return {}

        entries: dict[str, str] = {}
        content = path.read_text(encoding="utf-8-sig")

        for line in content.splitlines():
            line = line.strip()
            # 주석이나 헤더 건너뛰기
            if not line or line.startswith("#") or line.startswith("l_"):
                continue

            # KEY:0 "Value" 또는 KEY: "Value" 패턴
            # HOI4 loc 형식: KEY: "Value" (콜론은 키 이름의 일부가 아님)
            m = re.match(r'^(\S+?):(?:\d*)?\s+"(.*)"', line)
            if m:
                entries[m.group(1)] = m.group(2)

        return entries

    def has_key(self, key: str, file_path: Path | None = None) -> bool:
        """키가 로컬라이제이션 파일에 존재하는지."""
        entries = self.read_file(file_path)
        return key in entries

    def get_value(
        self, key: str, file_path: Path | None = None
    ) -> str | None:
        """키의 값을 반환. 없으면 None."""
        entries = self.read_file(file_path)
        return entries.get(key)

    # ------------------------------------------------------------------
    # 쓰기
    # ------------------------------------------------------------------

    def add_character_loc(
        self,
        char_id: str,
        display_name: str,
        description: str = "",
    ) -> bool:
        """캐릭터 로컬라이제이션 항목 추가.

        추가되는 키:
        - char_id (예: USA_donald_trump_char) → display_name
        - char_id에서 _char 제거한 키 → display_name (name 키)
        - POLITICS_{upper}_DESC → description (있으면)
        """
        entries: dict[str, str] = {}

        # 기본 이름 키 (char_id 자체가 name 키로도 사용)
        base_key = char_id.replace("_char", "")
        entries[base_key] = display_name

        # char_id 키도 추가 (일부 모드에서 사용)
        entries[char_id] = display_name

        # 설명
        if description:
            desc_key = f"POLITICS_{base_key.upper()}_DESC"
            entries[desc_key] = description

        return self.add_entries(entries)

    def add_entries(
        self,
        entries: dict[str, str],
        file_path: Path | None = None,
    ) -> bool:
        """여러 로컬라이제이션 항목을 파일에 추가.

        이미 존재하는 키는 건너뛴다 (덮어쓰지 않음).
        """
        path = file_path or self._char_file
        existing = self.read_file(path)

        new_entries: dict[str, str] = {}
        for key, value in entries.items():
            if key not in existing:
                new_entries[key] = value

        if not new_entries:
            logger.debug("추가할 새 항목 없음")
            return True

        # 파일에 추가
        lines_to_add: list[str] = []
        for key, value in new_entries.items():
            # 따옴표 이스케이프
            escaped = value.replace('"', '\\"')
            lines_to_add.append(f' {key}: "{escaped}"')

        if path.exists():
            content = path.read_text(encoding="utf-8-sig")
            # 마지막 줄바꿈 보장
            if not content.endswith("\n"):
                content += "\n"
            content += "\n".join(lines_to_add) + "\n"
        else:
            # 새 파일 생성
            path.parent.mkdir(parents=True, exist_ok=True)
            content = (
                f"{self.HEADER}\n"
                + "\n".join(lines_to_add)
                + "\n"
            )

        # UTF-8 BOM으로 저장
        path.write_text(
            self.BOM + content.lstrip(self.BOM),
            encoding="utf-8",
        )

        logger.info(
            "로컬라이제이션 {}건 추가: {}",
            len(new_entries),
            path.name,
        )
        return True

    def update_entry(
        self,
        key: str,
        new_value: str,
        file_path: Path | None = None,
    ) -> bool:
        """기존 로컬라이제이션 항목의 값을 업데이트."""
        path = file_path or self._char_file
        if not path.exists():
            return False

        content = path.read_text(encoding="utf-8-sig")
        escaped_new = new_value.replace('"', '\\"')

        # 정확한 키 매칭으로 교체
        pattern = re.compile(
            rf'^(\s*{re.escape(key)}(?::\d+)?\s+)".*"',
            re.MULTILINE,
        )

        new_content, count = pattern.subn(
            rf'\1"{escaped_new}"', content
        )

        if count == 0:
            return False

        path.write_text(
            self.BOM + new_content.lstrip(self.BOM),
            encoding="utf-8",
        )

        logger.info("로컬라이제이션 업데이트: {} → {}", key, new_value)
        return True

    def remove_entry(
        self,
        key: str,
        file_path: Path | None = None,
    ) -> bool:
        """로컬라이제이션 항목 제거."""
        path = file_path or self._char_file
        if not path.exists():
            return False

        content = path.read_text(encoding="utf-8-sig")

        # 키가 포함된 줄 전체 제거
        pattern = re.compile(
            rf'^\s*{re.escape(key)}(?::\d+)?\s+".*"\s*$\n?',
            re.MULTILINE,
        )

        new_content, count = pattern.subn("", content)

        if count == 0:
            return False

        path.write_text(
            self.BOM + new_content.lstrip(self.BOM),
            encoding="utf-8",
        )

        logger.info("로컬라이제이션 제거: {}", key)
        return True

    # ------------------------------------------------------------------
    # 누락 감지
    # ------------------------------------------------------------------

    def find_missing_character_keys(
        self,
        mod_root: Path | None = None,
    ) -> list[dict[str, str]]:
        """모드의 캐릭터 중 로컬라이제이션이 없는 것을 찾는다.

        반환: [{"char_id": "...", "name_key": "...", "country": "..."}, ...]
        """
        root = mod_root or self.mod_root
        parser = CharacterParser()
        chars = parser.parse_all_characters(root / "common" / "characters")

        existing = self.read_file()
        missing: list[dict[str, str]] = []

        for char_id in chars:
            name_key = char_id.replace("_char", "")
            # name_key 또는 char_id 어느 쪽이든 없으면 누락
            if name_key not in existing and char_id not in existing:
                country = parser.get_character_country(char_id)
                missing.append({
                    "char_id": char_id,
                    "name_key": name_key,
                    "country": country,
                })

        return missing

    def generate_missing_report(
        self, mod_root: Path | None = None
    ) -> str:
        """누락 로컬라이제이션 보고서."""
        missing = self.find_missing_character_keys(mod_root)
        if not missing:
            return "✅ 모든 캐릭터에 로컬라이제이션이 있습니다."

        lines = [f"⚠️ 로컬라이제이션 누락: {len(missing)}건\n"]

        # 국가별 그룹
        by_country: dict[str, list[str]] = {}
        for item in missing:
            tag = item["country"]
            by_country.setdefault(tag, []).append(item["char_id"])

        for tag in sorted(by_country):
            chars = by_country[tag]
            lines.append(f"  {tag} ({len(chars)}건):")
            for cid in chars[:10]:
                lines.append(f"    - {cid}")
            if len(chars) > 10:
                lines.append(f"    ... +{len(chars) - 10}건")

        return "\n".join(lines)

    def auto_generate_missing(
        self,
        mod_root: Path | None = None,
    ) -> int:
        """누락된 캐릭터 로컬라이제이션을 자동 생성.

        char_id에서 이름을 추론: USA_donald_trump_char → Donald Trump
        """
        missing = self.find_missing_character_keys(mod_root)
        if not missing:
            return 0

        entries: dict[str, str] = {}
        for item in missing:
            name_key = item["name_key"]
            country = item["country"]

            # char_id에서 이름 추론
            name_part = name_key.replace(f"{country}_", "")
            display_name = name_part.replace("_", " ").title()

            entries[name_key] = display_name

        self.add_entries(entries)
        return len(entries)
