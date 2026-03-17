"""
HOI4 mod 파일 파서.
HOI4의 PDX 스크립트 포맷을 파이썬 딕셔너리로 변환한다.

PDX 스크립트 포맷 특징:
- 중괄호 기반 블록 구조: key = { ... }
- # 주석
- 값: 문자열(따옴표), 숫자, 식별자, 중첩 블록
- 같은 키가 여러 번 나올 수 있음 → 리스트로 변환
- 날짜 블록: 2026.1.1 = { ... }
- BOM(UTF-8 BOM) 가능
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from loguru import logger


class HOI4Parser:
    """HOI4 PDX 스크립트 포맷 파서."""

    def parse_file(self, path: Path) -> dict[str, Any]:
        """파일을 파싱하여 딕셔너리로 반환."""
        path = Path(path)
        if not path.exists():
            logger.error(f"파일을 찾을 수 없음: {path}")
            return {}
        try:
            content = path.read_text(encoding="utf-8-sig")  # BOM 자동 처리
            return self.parse_string(content)
        except Exception as e:
            logger.error(f"파일 파싱 실패 ({path}): {e}")
            return {}

    def parse_string(self, content: str) -> dict[str, Any]:
        """문자열을 파싱하여 딕셔너리로 반환."""
        if not content or not content.strip():
            return {}
        content = self._strip_bom(content)
        content = self._strip_comments(content)
        tokens = self._tokenize(content)
        if not tokens:
            return {}
        result, _ = self._parse_tokens(tokens, 0)
        return result

    @staticmethod
    def _strip_bom(content: str) -> str:
        """UTF-8 BOM 제거."""
        if content.startswith("\ufeff"):
            return content[1:]
        return content

    @staticmethod
    def _strip_comments(content: str) -> str:
        """주석 제거. 따옴표 안의 #은 보존."""
        result: list[str] = []
        in_quote = False
        i = 0
        while i < len(content):
            ch = content[i]
            if ch == '"':
                in_quote = not in_quote
                result.append(ch)
            elif ch == "#" and not in_quote:
                # 줄 끝까지 스킵
                while i < len(content) and content[i] != "\n":
                    i += 1
                continue
            else:
                result.append(ch)
            i += 1
        return "".join(result)

    def _tokenize(self, content: str) -> list[str]:
        """내용을 토큰으로 분리.

        토큰 종류: { } = "문자열" 식별자(숫자/단어/날짜 등)
        """
        tokens: list[str] = []
        i = 0
        n = len(content)
        while i < n:
            ch = content[i]
            # 공백 스킵
            if ch in " \t\r\n":
                i += 1
                continue
            # 구조 토큰
            if ch in "{}=<>":
                # <= >= 처리
                if ch in "<>" and i + 1 < n and content[i + 1] == "=":
                    tokens.append(ch + "=")
                    i += 2
                    continue
                tokens.append(ch)
                i += 1
                continue
            # 따옴표 문자열
            if ch == '"':
                j = i + 1
                while j < n and content[j] != '"':
                    if content[j] == "\\" and j + 1 < n:
                        j += 2
                    else:
                        j += 1
                token = content[i + 1 : j]  # 따옴표 제거
                tokens.append(f'"{token}"')
                i = j + 1
                continue
            # 일반 토큰 (식별자, 숫자, 날짜 등)
            j = i
            while j < n and content[j] not in " \t\r\n{}=<>\"#":
                j += 1
            token = content[i:j]
            if token:
                tokens.append(token)
            i = j
        return tokens

    def _parse_tokens(self, tokens: list[str], pos: int = 0) -> tuple[dict[str, Any], int]:
        """토큰 리스트를 파싱하여 딕셔너리와 다음 위치 반환.

        같은 키가 여러 번 나오면:
        - 기존 값이 리스트가 아니면 [기존값, 새값] 리스트로 변환
        - 기존 값이 리스트면 append
        """
        result: dict[str, Any] = {}
        n = len(tokens)

        while pos < n:
            token = tokens[pos]

            # 블록 종료
            if token == "}":
                return result, pos + 1

            # key = value 패턴
            if pos + 1 < n and tokens[pos + 1] in ("=", "<", ">", "<=", ">="):
                key = self._unquote(token)
                operator = tokens[pos + 1]
                pos += 2

                if pos >= n:
                    break

                # 블록 값
                if tokens[pos] == "{":
                    pos += 1
                    # 비어있는 블록 체크
                    if pos < n and tokens[pos] == "}":
                        value: Any = {}
                        pos += 1
                    else:
                        # 블록 내부가 key=value 패턴인지, 단순 값 리스트인지 판별
                        value, pos = self._parse_block_content(tokens, pos)
                else:
                    # 단순 값
                    value = self._parse_value(tokens[pos])
                    pos += 1

                # 비교 연산자인 경우 특수 처리
                if operator in ("<", ">", "<=", ">="):
                    value = {"operator": operator, "value": value}

                # 같은 키 여러 번 → 리스트 변환
                self._add_to_dict(result, key, value)
            else:
                # key = value 아닌 단독 토큰 (블록 안의 단순 값)
                # 이 경우는 _parse_block_content에서 처리됨
                pos += 1

        return result, pos

    def _parse_block_content(self, tokens: list[str], pos: int) -> tuple[Any, int]:
        """블록 내용 파싱. key=value 블록인지 값 리스트인지 자동 감지."""
        # 먼저 내부를 스캔하여 = 이 있으면 dict, 없으면 값 리스트
        scan_pos = pos
        depth = 0
        has_equals = False
        while scan_pos < len(tokens):
            t = tokens[scan_pos]
            if t == "{":
                depth += 1
            elif t == "}":
                if depth == 0:
                    break
                depth -= 1
            elif t in ("=", "<", ">", "<=", ">=") and depth == 0:
                has_equals = True
                break
            scan_pos += 1

        if has_equals:
            # key = value 딕셔너리 블록
            return self._parse_tokens(tokens, pos)
        else:
            # 값 리스트 블록
            return self._parse_value_list(tokens, pos)

    def _parse_value_list(self, tokens: list[str], pos: int) -> tuple[list[Any], int]:
        """중괄호 블록 안의 단순 값 리스트 파싱."""
        values: list[Any] = []
        while pos < len(tokens):
            if tokens[pos] == "}":
                return values, pos + 1
            if tokens[pos] == "{":
                # 중첩 블록
                pos += 1
                inner, pos = self._parse_block_content(tokens, pos)
                values.append(inner)
            else:
                values.append(self._parse_value(tokens[pos]))
                pos += 1
        return values, pos

    @staticmethod
    def _unquote(token: str) -> str:
        """따옴표 제거."""
        if token.startswith('"') and token.endswith('"'):
            return token[1:-1]
        return token

    @staticmethod
    def _parse_value(token: str) -> Any:
        """토큰을 적절한 타입으로 변환."""
        # 따옴표 문자열
        if token.startswith('"') and token.endswith('"'):
            return token[1:-1]
        # yes / no
        if token == "yes":
            return True
        if token == "no":
            return False
        # 정수
        try:
            return int(token)
        except ValueError:
            pass
        # 소수
        try:
            return float(token)
        except ValueError:
            pass
        # 식별자 (문자열로 반환)
        return token

    @staticmethod
    def _add_to_dict(d: dict[str, Any], key: str, value: Any) -> None:
        """딕셔너리에 값 추가. 중복 키는 리스트로 변환."""
        if key not in d:
            d[key] = value
        else:
            existing = d[key]
            if isinstance(existing, list):
                existing.append(value)
            else:
                d[key] = [existing, value]


class CharacterParser:
    """common/characters/*.txt 파일 파서."""

    def __init__(self) -> None:
        self._parser = HOI4Parser()

    def parse_characters_file(self, path: Path) -> dict[str, dict]:
        """캐릭터 파일 파싱. 캐릭터 ID → 캐릭터 데이터 딕셔너리 반환."""
        data = self._parser.parse_file(path)
        characters = data.get("characters", {})
        if not isinstance(characters, dict):
            logger.warning(f"characters 블록이 없거나 유효하지 않음: {path}")
            return {}
        return characters

    def parse_all_characters(self, characters_dir: Path) -> dict[str, dict]:
        """characters/ 디렉토리의 모든 파일 파싱."""
        characters_dir = Path(characters_dir)
        if not characters_dir.is_dir():
            logger.error(f"디렉토리를 찾을 수 없음: {characters_dir}")
            return {}
        all_chars: dict[str, dict] = {}
        for txt_file in sorted(characters_dir.glob("*.txt")):
            chars = self.parse_characters_file(txt_file)
            all_chars.update(chars)
            logger.debug(f"{txt_file.name}: {len(chars)}개 캐릭터 파싱")
        logger.info(f"총 {len(all_chars)}개 캐릭터 파싱 완료 ({characters_dir})")
        return all_chars

    @staticmethod
    def get_character_country(char_id: str) -> str:
        """캐릭터 ID에서 국가 코드 추출. 예: USA_trump_char → USA"""
        parts = char_id.split("_")
        if parts:
            return parts[0]
        return ""


class CountryHistoryParser:
    """history/countries/*.txt 파일 파서."""

    def __init__(self) -> None:
        self._parser = HOI4Parser()

    def parse_history_file(self, path: Path) -> dict[str, Any]:
        """국가 히스토리 파일 파싱."""
        return self._parser.parse_file(path)

    def parse_all_histories(self, history_dir: Path) -> dict[str, dict]:
        """history/countries/ 디렉토리의 모든 파일 파싱. TAG → 데이터"""
        history_dir = Path(history_dir)
        if not history_dir.is_dir():
            logger.error(f"디렉토리를 찾을 수 없음: {history_dir}")
            return {}
        all_histories: dict[str, dict] = {}
        for txt_file in sorted(history_dir.glob("*.txt")):
            tag = self.get_country_tag(txt_file)
            if tag:
                data = self.parse_history_file(txt_file)
                all_histories[tag] = data
                logger.debug(f"{tag}: {txt_file.name} 파싱 완료")
        logger.info(f"총 {len(all_histories)}개 국가 히스토리 파싱 완료")
        return all_histories

    @staticmethod
    def get_country_tag(filepath: Path) -> str:
        """파일명에서 국가 TAG 추출. 예: 'USA - United States.txt' → 'USA'"""
        name = Path(filepath).stem
        # "TAG - Name" 또는 "TAG- Name" 또는 "TAG -Name" 패턴
        match = re.match(r"^([A-Za-z0-9]+)\s*-", name)
        if match:
            return match.group(1).strip()
        return name.strip()

    @staticmethod
    def get_recruited_characters(history_data: dict) -> list[str]:
        """recruit_character 목록 추출."""
        rc = history_data.get("recruit_character")
        if rc is None:
            return []
        if isinstance(rc, list):
            return [str(c) for c in rc]
        return [str(rc)]

    @staticmethod
    def get_ruling_party(history_data: dict) -> str | None:
        """현재 집권당 이념 추출. set_politics.ruling_party"""
        sp = history_data.get("set_politics")
        if isinstance(sp, dict):
            rp = sp.get("ruling_party")
            return str(rp) if rp is not None else None
        # 여러 set_politics가 있는 경우 (리스트)
        if isinstance(sp, list):
            for item in reversed(sp):
                if isinstance(item, dict) and "ruling_party" in item:
                    return str(item["ruling_party"])
        return None


class GFXParser:
    """interface/*.gfx 파일 파서."""

    def __init__(self) -> None:
        self._parser = HOI4Parser()

    def parse_gfx_file(self, path: Path) -> dict[str, str]:
        """GFX 파일 파싱. sprite_name → texture_path 딕셔너리 반환."""
        data = self._parser.parse_file(path)
        sprites: dict[str, str] = {}

        sprite_types = data.get("spriteTypes", {})
        if not isinstance(sprite_types, dict):
            return sprites

        # spriteType은 여러 개 → 리스트
        st = sprite_types.get("spriteType")
        if st is None:
            return sprites

        sprite_list = st if isinstance(st, list) else [st]
        for sprite in sprite_list:
            if isinstance(sprite, dict):
                name = sprite.get("name", "")
                texture = sprite.get("texturefile", "")
                if name and texture:
                    sprites[str(name)] = str(texture)
        return sprites

    def parse_all_gfx(self, interface_dir: Path) -> dict[str, str]:
        """interface/ 디렉토리의 모든 .gfx 파일 파싱."""
        interface_dir = Path(interface_dir)
        if not interface_dir.is_dir():
            logger.error(f"디렉토리를 찾을 수 없음: {interface_dir}")
            return {}
        all_sprites: dict[str, str] = {}
        for gfx_file in sorted(interface_dir.glob("*.gfx")):
            sprites = self.parse_gfx_file(gfx_file)
            all_sprites.update(sprites)
            logger.debug(f"{gfx_file.name}: {len(sprites)}개 스프라이트 파싱")
        logger.info(f"총 {len(all_sprites)}개 스프라이트 파싱 완료")
        return all_sprites
