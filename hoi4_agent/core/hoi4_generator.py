"""
HOI4 mod 파일 생성기.
Python 데이터 구조를 HOI4 PDX 스크립트 포맷으로 변환한다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from loguru import logger

# ---------------------------------------------------------------------------
# 데이터 모델
# ---------------------------------------------------------------------------

_T = "\t"  # HOI4 컨벤션: 탭 들여쓰기


@dataclass
class CharacterData:
    """캐릭터 데이터 모델."""

    char_id: str  # 예: USA_donald_trump_char
    name_key: str  # localisation key
    gender: str = "male"  # male/female/undefined
    portrait_civilian: str = ""  # gfx 경로
    portrait_army: str = ""
    portrait_navy: str = ""
    country_leader_ideology: str = ""  # 국가 지도자 이념
    country_leader_traits: list[str] = field(default_factory=list)
    country_leader_desc: str = ""
    corps_commander_traits: list[str] = field(default_factory=list)
    corps_commander_skill: int = 1
    corps_commander_attack: int = 1
    corps_commander_defense: int = 1
    corps_commander_planning: int = 1
    corps_commander_logistics: int = 1
    field_marshal_traits: list[str] = field(default_factory=list)
    field_marshal_skill: int = 1
    field_marshal_attack: int = 1
    field_marshal_defense: int = 1
    field_marshal_planning: int = 1
    field_marshal_logistics: int = 1
    is_field_marshal: bool = False
    navy_leader_traits: list[str] = field(default_factory=list)
    navy_leader_skill: int = 1
    navy_leader_attack: int = 1
    navy_leader_defense: int = 1
    navy_leader_maneuvering: int = 1
    navy_leader_coordination: int = 1

    # ---------- 편의 속성 ----------

    @property
    def has_country_leader(self) -> bool:
        return bool(self.country_leader_ideology)

    @property
    def has_corps_commander(self) -> bool:
        return bool(self.corps_commander_traits) or self.corps_commander_skill > 1

    @property
    def has_field_marshal(self) -> bool:
        return self.is_field_marshal or bool(self.field_marshal_traits)

    @property
    def has_navy_leader(self) -> bool:
        return bool(self.navy_leader_traits) or self.navy_leader_skill > 1


@dataclass
class PoliticsData:
    """국가 정치 데이터."""

    ruling_party: str
    elections_allowed: bool = True
    election_frequency: int = 48
    last_election: str = ""
    popularities: dict[str, int] = field(default_factory=dict)  # ideology → %


@dataclass
class DateBlock:
    """날짜 블록 데이터. history/countries/*.txt 에서 2026.1.1 = { ... } 형태."""

    date: str  # 예: "2026.1.1"
    politics: PoliticsData | None = None
    recruit_characters: list[str] = field(default_factory=list)
    retire_characters: list[str] = field(default_factory=list)
    custom_commands: list[str] = field(default_factory=list)  # 자유형식 명령어


# ---------------------------------------------------------------------------
# 유틸리티
# ---------------------------------------------------------------------------


def _bool_str(v: bool) -> str:
    """Python bool → HOI4 yes/no."""
    return "yes" if v else "no"


def _quoted(v: str) -> str:
    """따옴표로 감싸기 (이미 감싸져 있으면 그대로)."""
    if v.startswith('"') and v.endswith('"'):
        return v
    return f'"{v}"'


def _traits_block(traits: list[str], depth: int) -> str:
    """traits = { ... } 블록 생성. 빈 리스트면 빈 블록."""
    indent = _T * depth
    inner = _T * (depth + 1)
    lines = [f"{indent}traits = {{"]
    for t in traits:
        lines.append(f"{inner}{t}")
    lines.append(f"{indent}}}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# PDX 스크립트 경량 파서 (검증용)
# ---------------------------------------------------------------------------


class PDXParseError(Exception):
    """PDX 스크립트 파싱 에러."""


def parse_pdx_to_tokens(text: str) -> list[str]:
    """PDX 스크립트를 토큰 리스트로 분리한다 (검증용).

    토큰: 식별자, 문자열리터럴, ``=``, ``{``, ``}``.
    주석(``#``)은 제거한다.
    """
    tokens: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        # 공백/줄바꿈 건너뛰기
        if c in " \t\r\n":
            i += 1
            continue
        # 주석
        if c == "#":
            while i < n and text[i] != "\n":
                i += 1
            continue
        # 구조 문자
        if c in "={}":
            tokens.append(c)
            i += 1
            continue
        # 따옴표 문자열
        if c == '"':
            j = i + 1
            while j < n and text[j] != '"':
                if text[j] == "\\":
                    j += 1  # 이스케이프
                j += 1
            tokens.append(text[i : j + 1])
            i = j + 1
            continue
        # 식별자 / 숫자
        j = i
        while j < n and text[j] not in " \t\r\n={}#\"":
            j += 1
        tokens.append(text[i:j])
        i = j
    return tokens


def validate_pdx_braces(text: str) -> bool:
    """중괄호 균형 검증. 불균형이면 False."""
    depth = 0
    for tok in parse_pdx_to_tokens(text):
        if tok == "{":
            depth += 1
        elif tok == "}":
            depth -= 1
            if depth < 0:
                return False
    return depth == 0


# ---------------------------------------------------------------------------
# CharacterGenerator
# ---------------------------------------------------------------------------


class CharacterGenerator:
    """캐릭터 파일 생성/업데이트."""

    def generate_character_block(self, char: CharacterData) -> str:
        """단일 캐릭터 블록 생성."""
        lines: list[str] = []
        d1, d2, d3, d4 = _T, _T * 2, _T * 3, _T * 4

        lines.append(f"{d1}{char.char_id} = {{")

        # -- name (name_key가 있으면)
        if char.name_key:
            lines.append(f"{d2}name = {char.name_key}")

        # -- portraits
        has_any_portrait = char.portrait_civilian or char.portrait_army or char.portrait_navy
        if has_any_portrait:
            lines.append(f"{d2}portraits = {{")
            if char.portrait_civilian:
                lines.append(f"{d3}civilian = {{")
                lines.append(f"{d4}large = {_quoted(char.portrait_civilian)}")
                lines.append(f"{d3}}}")
            if char.portrait_army:
                lines.append(f"{d3}army = {{")
                lines.append(f"{d4}large = {_quoted(char.portrait_army)}")
                lines.append(f"{d3}}}")
            if char.portrait_navy:
                lines.append(f"{d3}army = {{")
                lines.append(f"{d4}large = {_quoted(char.portrait_navy)}")
                lines.append(f"{d3}}}")
            lines.append(f"{d2}}}")

        # -- gender
        if char.gender and char.gender != "male":
            lines.append(f"{d2}gender = {char.gender}")

        # -- country_leader
        if char.has_country_leader:
            lines.append(f"{d2}country_leader = {{")
            if char.country_leader_desc:
                lines.append(f"{d3}desc = {_quoted(char.country_leader_desc)}")
            lines.append(f"{d3}ideology = {char.country_leader_ideology}")
            if char.country_leader_traits:
                lines.append(_traits_block(char.country_leader_traits, 3))
            lines.append(f"{d2}}}")

        # -- field_marshal
        if char.has_field_marshal:
            lines.append(f"{d2}field_marshal = {{")
            if char.field_marshal_traits:
                lines.append(_traits_block(char.field_marshal_traits, 3))
            lines.append(f"{d3}skill = {char.field_marshal_skill}")
            lines.append(f"{d3}attack_skill = {char.field_marshal_attack}")
            lines.append(f"{d3}defense_skill = {char.field_marshal_defense}")
            lines.append(f"{d3}planning_skill = {char.field_marshal_planning}")
            lines.append(f"{d3}logistics_skill = {char.field_marshal_logistics}")
            lines.append(f"{d2}}}")

        # -- corps_commander
        if char.has_corps_commander:
            lines.append(f"{d2}corps_commander = {{")
            if char.corps_commander_traits:
                lines.append(_traits_block(char.corps_commander_traits, 3))
            lines.append(f"{d3}skill = {char.corps_commander_skill}")
            lines.append(f"{d3}attack_skill = {char.corps_commander_attack}")
            lines.append(f"{d3}defense_skill = {char.corps_commander_defense}")
            lines.append(f"{d3}planning_skill = {char.corps_commander_planning}")
            lines.append(f"{d3}logistics_skill = {char.corps_commander_logistics}")
            lines.append(f"{d2}}}")

        # -- navy_leader
        if char.has_navy_leader:
            lines.append(f"{d2}navy_leader = {{")
            if char.navy_leader_traits:
                lines.append(_traits_block(char.navy_leader_traits, 3))
            lines.append(f"{d3}skill = {char.navy_leader_skill}")
            lines.append(f"{d3}attack_skill = {char.navy_leader_attack}")
            lines.append(f"{d3}defense_skill = {char.navy_leader_defense}")
            lines.append(f"{d3}maneuvering_skill = {char.navy_leader_maneuvering}")
            lines.append(f"{d3}coordination_skill = {char.navy_leader_coordination}")
            lines.append(f"{d2}}}")

        lines.append(f"{d1}}}")
        return "\n".join(lines)

    def generate_characters_file(self, chars: list[CharacterData]) -> str:
        """전체 characters 파일 내용 생성."""
        blocks = [self.generate_character_block(c) for c in chars]
        inner = "\n".join(blocks)
        return f"characters = {{\n{inner}\n}}\n"

    def add_character_to_file(self, char: CharacterData, filepath: Path) -> None:
        """기존 파일에 캐릭터 추가.

        ``characters = { ... }`` 블록의 마지막 ``}`` 바로 앞에 삽입한다.
        파일이 없으면 새로 생성한다.
        """
        block = self.generate_character_block(char)

        if not filepath.exists():
            logger.info("파일 생성: {}", filepath)
            filepath.parent.mkdir(parents=True, exist_ok=True)
            filepath.write_text(f"characters = {{\n{block}\n}}\n", encoding="utf-8-sig")
            return

        content = filepath.read_text(encoding="utf-8-sig")
        # 이미 존재하는 캐릭터인지 확인
        if f"{char.char_id} = {{" in content or f"{char.char_id}={{" in content:
            logger.warning("캐릭터 {} 이미 존재. add 대신 update를 사용하세요.", char.char_id)
            return

        # 마지막 닫는 중괄호를 찾아 그 앞에 삽입
        last_brace = content.rfind("}")
        if last_brace == -1:
            raise ValueError(f"유효하지 않은 characters 파일: {filepath}")

        new_content = content[:last_brace] + block + "\n" + content[last_brace:]
        filepath.write_text(new_content, encoding="utf-8-sig")
        logger.info("캐릭터 {} 추가 -> {}", char.char_id, filepath)

    def update_character_in_file(self, char: CharacterData, filepath: Path) -> bool:
        """기존 파일의 캐릭터 업데이트. 없으면 False 반환."""
        if not filepath.exists():
            return False

        content = filepath.read_text(encoding="utf-8-sig")
        # 캐릭터 블록 찾기: char_id = { ... } (중첩 중괄호 처리)
        start, end = self._find_character_span(char.char_id, content)
        if start == -1:
            return False

        new_block = self.generate_character_block(char)
        new_content = content[:start] + new_block + content[end:]
        filepath.write_text(new_content, encoding="utf-8-sig")
        logger.info("캐릭터 {} 업데이트 -> {}", char.char_id, filepath)
        return True

    def remove_character_from_file(self, char_id: str, filepath: Path) -> bool:
        """기존 파일에서 캐릭터 제거. 없으면 False 반환."""
        if not filepath.exists():
            return False

        content = filepath.read_text(encoding="utf-8-sig")
        start, end = self._find_character_span(char_id, content)
        if start == -1:
            return False

        # 블록 뒤 빈 줄도 같이 제거
        while end < len(content) and content[end] in "\r\n":
            end += 1

        new_content = content[:start] + content[end:]
        filepath.write_text(new_content, encoding="utf-8-sig")
        logger.info("캐릭터 {} 제거 <- {}", char_id, filepath)
        return True

    # ------------------------------------------------------------------
    @staticmethod
    def _find_character_span(char_id: str, content: str) -> tuple[int, int]:
        """캐릭터 블록의 (start, end) 인덱스를 반환. 없으면 (-1, -1).

        ``\\t<char_id> = {`` 로 시작하는 블록을 찾고, 중첩 ``{}`` 를 추적하여
        대응하는 닫는 ``}`` 까지를 범위로 잡는다.
        """
        # 탭으로 시작하는 패턴 (depth=1)
        pattern = re.compile(rf"^\t{re.escape(char_id)}\s*=\s*\{{", re.MULTILINE)
        m = pattern.search(content)
        if not m:
            return (-1, -1)

        start = m.start()
        # 여는 중괄호 위치부터 중첩 추적
        brace_start = m.end() - 1  # '{' 위치
        depth = 1
        i = brace_start + 1
        in_string = False
        in_comment = False
        while i < len(content) and depth > 0:
            c = content[i]
            if in_comment:
                if c == "\n":
                    in_comment = False
            elif in_string:
                if c == "\\":
                    i += 1  # 이스케이프 건너뛰기
                elif c == '"':
                    in_string = False
            else:
                if c == "#":
                    in_comment = True
                elif c == '"':
                    in_string = True
                elif c == "{":
                    depth += 1
                elif c == "}":
                    depth -= 1
            i += 1

        if depth != 0:
            return (-1, -1)

        return (start, i)


# ---------------------------------------------------------------------------
# HistoryGenerator
# ---------------------------------------------------------------------------


class HistoryGenerator:
    """history/countries/*.txt 파일 생성/업데이트."""

    def generate_date_block(self, block: DateBlock) -> str:
        """날짜 블록 문자열 생성."""
        d1, d2, d3 = _T, _T * 2, _T * 3
        lines: list[str] = [f"{block.date} = {{"]

        # recruit_character
        for cid in block.recruit_characters:
            lines.append(f"{d1}recruit_character = {cid}")

        # retire_character
        for cid in block.retire_characters:
            lines.append(f"{d1}retire_character = {cid}")

        # set_politics
        if block.politics:
            p = block.politics
            lines.append(f"{d1}set_politics = {{")
            if p.last_election:
                lines.append(f"{d2}last_election = {_quoted(p.last_election)}")
            lines.append(f"{d2}elections_allowed = {_bool_str(p.elections_allowed)}")
            lines.append(f"{d2}election_frequency = {p.election_frequency}")
            lines.append(f"{d2}ruling_party = {p.ruling_party}")
            lines.append(f"{d1}}}")
            # set_popularities
            if p.popularities:
                lines.append(f"{d1}set_popularities = {{")
                for ideology, pct in p.popularities.items():
                    lines.append(f"{d2}{ideology} = {pct}")
                lines.append(f"{d1}}}")

        # custom_commands
        for cmd in block.custom_commands:
            lines.append(f"{d1}{cmd}")

        lines.append("}")
        return "\n".join(lines)

    def add_date_block(self, block: DateBlock, filepath: Path) -> None:
        """히스토리 파일에 날짜 블록 추가 또는 업데이트.

        같은 날짜 블록이 이미 존재하면 교체, 없으면 파일 끝에 추가.
        """
        new_block = self.generate_date_block(block)

        if not filepath.exists():
            filepath.parent.mkdir(parents=True, exist_ok=True)
            filepath.write_text(new_block + "\n", encoding="utf-8-sig")
            logger.info("히스토리 파일 생성: {}", filepath)
            return

        content = filepath.read_text(encoding="utf-8-sig")
        start, end = self._find_date_block_span(block.date, content)

        if start != -1:
            # 기존 블록 교체
            new_content = content[:start] + new_block + content[end:]
            filepath.write_text(new_content, encoding="utf-8-sig")
            logger.info("날짜 블록 {} 업데이트 -> {}", block.date, filepath)
        else:
            # 파일 끝에 추가
            if not content.endswith("\n"):
                content += "\n"
            content += "\n" + new_block + "\n"
            filepath.write_text(content, encoding="utf-8-sig")
            logger.info("날짜 블록 {} 추가 -> {}", block.date, filepath)

    def update_politics_at_date(
        self, date: str, politics: PoliticsData, filepath: Path
    ) -> None:
        """특정 날짜의 정치 데이터 업데이트.

        날짜 블록이 없으면 새로 생성한다.
        """
        block = DateBlock(date=date, politics=politics)
        self.add_date_block(block, filepath)

    # ------------------------------------------------------------------
    @staticmethod
    def _find_date_block_span(date: str, content: str) -> tuple[int, int]:
        """날짜 블록의 (start, end) 인덱스. 없으면 (-1, -1)."""
        pattern = re.compile(
            rf"^{re.escape(date)}\s*=\s*\{{", re.MULTILINE
        )
        m = pattern.search(content)
        if not m:
            return (-1, -1)

        start = m.start()
        brace_start = content.index("{", m.start())
        depth = 1
        i = brace_start + 1
        in_string = False
        in_comment = False
        while i < len(content) and depth > 0:
            c = content[i]
            if in_comment:
                if c == "\n":
                    in_comment = False
            elif in_string:
                if c == "\\":
                    i += 1
                elif c == '"':
                    in_string = False
            else:
                if c == "#":
                    in_comment = True
                elif c == '"':
                    in_string = True
                elif c == "{":
                    depth += 1
                elif c == "}":
                    depth -= 1
            i += 1

        if depth != 0:
            return (-1, -1)
        return (start, i)


# ---------------------------------------------------------------------------
# GFXGenerator
# ---------------------------------------------------------------------------


class GFXGenerator:
    """interface/*.gfx 파일 업데이트."""

    def generate_sprite_entry(self, sprite_name: str, texture_path: str) -> str:
        """spriteType 블록 생성."""
        d1, d2 = _T, _T * 2
        return (
            f"{d1}spriteType = {{\n"
            f"{d2}name = {_quoted(sprite_name)}\n"
            f"{d2}texturefile = {_quoted(texture_path)}\n"
            f"{d1}}}"
        )

    def add_sprite_to_gfx(
        self, sprite_name: str, texture_path: str, gfx_filepath: Path
    ) -> None:
        """GFX 파일에 sprite 추가 (중복 확인 후).

        ``spriteTypes = { ... }`` 블록의 마지막 ``}`` 앞에 삽입.
        파일이 없으면 새로 생성한다.
        """
        entry = self.generate_sprite_entry(sprite_name, texture_path)

        if not gfx_filepath.exists():
            gfx_filepath.parent.mkdir(parents=True, exist_ok=True)
            gfx_filepath.write_text(
                f"spriteTypes = {{\n{entry}\n}}\n", encoding="utf-8-sig"
            )
            logger.info("GFX 파일 생성: {}", gfx_filepath)
            return

        content = gfx_filepath.read_text(encoding="utf-8-sig")

        # 중복 확인
        if sprite_name in content:
            logger.warning("스프라이트 {} 이미 존재. 추가 건너뜀.", sprite_name)
            return

        # spriteTypes의 마지막 } 앞에 삽입
        last_brace = content.rfind("}")
        if last_brace == -1:
            raise ValueError(f"유효하지 않은 GFX 파일: {gfx_filepath}")

        new_content = content[:last_brace] + entry + "\n" + content[last_brace:]
        gfx_filepath.write_text(new_content, encoding="utf-8-sig")
        logger.info("스프라이트 {} 추가 -> {}", sprite_name, gfx_filepath)

    def remove_sprite_from_gfx(self, sprite_name: str, gfx_filepath: Path) -> bool:
        """GFX 파일에서 sprite 제거. 없으면 False."""
        if not gfx_filepath.exists():
            return False

        content = gfx_filepath.read_text(encoding="utf-8-sig")
        start, end = self._find_sprite_span(sprite_name, content)
        if start == -1:
            return False

        # 블록 뒤 빈 줄도 같이 제거
        while end < len(content) and content[end] in "\r\n":
            end += 1

        new_content = content[:start] + content[end:]
        gfx_filepath.write_text(new_content, encoding="utf-8-sig")
        logger.info("스프라이트 {} 제거 <- {}", sprite_name, gfx_filepath)
        return True

    # ------------------------------------------------------------------
    @staticmethod
    def _find_sprite_span(sprite_name: str, content: str) -> tuple[int, int]:
        """sprite 블록의 (start, end) 인덱스. 없으면 (-1, -1).

        ``spriteType = {`` 로 시작하고 내부에 ``name = "<sprite_name>"`` 를 포함하는
        블록 전체를 찾는다.
        """
        # name = "..." 위치를 먼저 찾기
        name_pattern = re.compile(
            rf'name\s*=\s*"{re.escape(sprite_name)}"'
        )
        m = name_pattern.search(content)
        if not m:
            return (-1, -1)

        # name 위치에서 역방향으로 spriteType = { 를 찾기
        search_area = content[: m.start()]
        sprite_type_pattern = re.compile(r"spriteType\s*=\s*\{")
        last_match = None
        for match in sprite_type_pattern.finditer(search_area):
            last_match = match
        if last_match is None:
            return (-1, -1)

        # 들여쓰기 포함하여 시작 위치 조정
        start = last_match.start()
        # 줄 시작까지 확장 (탭 등 포함)
        while start > 0 and content[start - 1] in " \t":
            start -= 1

        # 여는 중괄호부터 닫는 중괄호까지
        brace_start = content.index("{", last_match.start())
        depth = 1
        i = brace_start + 1
        while i < len(content) and depth > 0:
            c = content[i]
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
            i += 1

        if depth != 0:
            return (-1, -1)
        return (start, i)
