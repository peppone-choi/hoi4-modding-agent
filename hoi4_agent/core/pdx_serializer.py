"""
범용 PDX Script 직렬화기.
HOI4Parser가 생성한 dict를 다시 PDX Script 형식의 문자열로 변환한다.

파서(HOI4Parser)가 parse-only이므로, 이 모듈이 round-trip의 쓰기 측을 담당한다.
HOI4 파일은 탭(\t) 들여쓰기, yes/no 불리언, 따옴표 문자열을 사용한다.

사용법:
    from tools.shared.pdx_serializer import PDXSerializer
    
    serializer = PDXSerializer()
    text = serializer.serialize(data_dict)
    
    # 특정 블록만 직렬화
    text = serializer.serialize_block("characters", char_dict, depth=0)
"""
from __future__ import annotations

import re
from typing import Any


class PDXSerializer:
    """HOI4 PDX Script 직렬화기.

    dict/list 구조를 PDX Script 문자열로 변환한다.
    탭 들여쓰기, yes/no 불리언, 적절한 따옴표 처리를 수행한다.
    """

    def __init__(self, indent: str = "\t") -> None:
        self._indent = indent
        # 따옴표가 필요한 패턴: 공백, 특수문자, 빈 문자열
        self._needs_quote_re = re.compile(r'[\s={}#"\'<>]|^$')
        # 숫자 패턴
        self._int_re = re.compile(r"^-?\d+$")
        self._float_re = re.compile(r"^-?\d+\.\d+$")
        # 날짜 패턴 (YYYY.M.D)
        self._date_re = re.compile(r"^\d{4}\.\d{1,2}\.\d{1,2}$")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def serialize(self, data: dict[str, Any]) -> str:
        """최상위 dict를 PDX Script 전체 파일 문자열로 변환."""
        lines: list[str] = []
        self._serialize_pairs(data, lines, depth=0)
        # 마지막 줄바꿈 보장
        result = "\n".join(lines)
        if not result.endswith("\n"):
            result += "\n"
        return result

    def serialize_block(
        self, key: str, value: Any, depth: int = 0
    ) -> str:
        """단일 key = value 블록을 직렬화."""
        lines: list[str] = []
        self._serialize_kv(key, value, lines, depth)
        return "\n".join(lines)

    def serialize_value(self, value: Any, depth: int = 0) -> str:
        """단일 값을 PDX 문자열로 변환."""
        lines: list[str] = []
        self._write_value(value, lines, depth)
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Core serialization
    # ------------------------------------------------------------------

    def _serialize_pairs(
        self,
        data: dict[str, Any],
        lines: list[str],
        depth: int,
    ) -> None:
        """dict의 모든 key-value 쌍을 직렬화."""
        for key, value in data.items():
            self._serialize_kv(key, value, lines, depth)

    def _serialize_kv(
        self,
        key: str,
        value: Any,
        lines: list[str],
        depth: int,
    ) -> None:
        """단일 key = value 직렬화.

        list value인 경우 같은 키로 여러 번 반복 출력한다.
        (HOI4 PDX Script에서 동일 키 여러 개 = 파서가 list로 수집)
        """
        prefix = self._indent * depth

        if isinstance(value, list):
            self._serialize_list(key, value, lines, depth)
        elif isinstance(value, dict):
            # 빈 dict → key = { }
            if not value:
                lines.append(f"{prefix}{key} = {{ }}")
            else:
                lines.append(f"{prefix}{key} = {{")
                self._serialize_pairs(value, lines, depth + 1)
                lines.append(f"{prefix}}}")
        else:
            formatted = self._format_scalar(value)
            lines.append(f"{prefix}{key} = {formatted}")

    def _serialize_list(
        self,
        key: str,
        values: list,
        lines: list[str],
        depth: int,
    ) -> None:
        """list 값 직렬화.

        HOI4 PDX Script에서 list는 두 가지 형태로 나타난다:
        1. 같은 키 반복: key = val1 / key = val2  (option, prerequisite 등)
        2. 값 목록 블록: key = { val1 val2 val3 }  (traits, provinces 등)

        구분 기준:
        - dict 원소가 있으면 → 같은 키 반복 (각 dict는 별도 블록)
        - 모두 스칼라면 → 값 목록 블록
        - 혼합이면 → 같은 키 반복
        """
        prefix = self._indent * depth

        if not values:
            lines.append(f"{prefix}{key} = {{ }}")
            return

        # 모든 원소가 스칼라인지 확인
        all_scalar = all(
            isinstance(v, (str, int, float, bool)) for v in values
        )

        # 원소에 dict가 섞여 있는지
        has_dict = any(isinstance(v, dict) for v in values)

        if all_scalar and len(values) <= 20:
            # 인라인 목록: key = { val1 val2 val3 }
            formatted = " ".join(self._format_scalar(v) for v in values)
            lines.append(f"{prefix}{key} = {{ {formatted} }}")
        elif all_scalar:
            # 긴 목록: 블록으로 펼침
            lines.append(f"{prefix}{key} = {{")
            inner = self._indent * (depth + 1)
            for v in values:
                lines.append(f"{inner}{self._format_scalar(v)}")
            lines.append(f"{prefix}}}")
        elif has_dict:
            # 같은 키로 dict 블록 반복
            for v in values:
                if isinstance(v, dict):
                    lines.append(f"{prefix}{key} = {{")
                    self._serialize_pairs(v, lines, depth + 1)
                    lines.append(f"{prefix}}}")
                else:
                    formatted = self._format_scalar(v)
                    lines.append(f"{prefix}{key} = {formatted}")
        else:
            # fallback: 같은 키 반복
            for v in values:
                self._serialize_kv(key, v, lines, depth)

    def _write_value(
        self, value: Any, lines: list[str], depth: int
    ) -> None:
        """값만 직렬화 (키 없이)."""
        prefix = self._indent * depth
        if isinstance(value, dict):
            lines.append(f"{prefix}{{")
            self._serialize_pairs(value, lines, depth + 1)
            lines.append(f"{prefix}}}")
        elif isinstance(value, list):
            for v in value:
                self._write_value(v, lines, depth)
        else:
            lines.append(f"{prefix}{self._format_scalar(value)}")

    # ------------------------------------------------------------------
    # Scalar formatting
    # ------------------------------------------------------------------

    def _format_scalar(self, value: Any) -> str:
        """스칼라 값을 PDX 형식 문자열로 포맷."""
        if isinstance(value, bool):
            return "yes" if value else "no"
        if isinstance(value, int):
            return str(value)
        if isinstance(value, float):
            # 소수점 이하 불필요한 0 제거, 최소 1자리
            if value == int(value):
                return f"{value:.1f}"
            return f"{value:g}"
        if isinstance(value, str):
            return self._format_string(value)
        # operator dict (파서가 < > <= >= 를 dict로 저장)
        if isinstance(value, dict) and "operator" in value:
            op = value["operator"]
            val = self._format_scalar(value["value"])
            return f"{op} {val}"
        return str(value)

    def _format_string(self, s: str) -> str:
        """문자열을 PDX 형식으로 포맷.

        - 이미 따옴표로 감싸진 경우 그대로
        - yes/no → 그대로 (불리언으로 해석됨)
        - 숫자/날짜 → 따옴표 없이
        - 공백/특수문자 포함 → 따옴표
        - 그 외 → 따옴표 없이
        """
        if not s:
            return '""'
        # 이미 따옴표
        if s.startswith('"') and s.endswith('"'):
            return s
        # yes/no 리터럴
        if s in ("yes", "no"):
            return s
        # 날짜 리터럴
        if self._date_re.match(s):
            return s
        # 순수 숫자
        if self._int_re.match(s) or self._float_re.match(s):
            return s
        # 따옴표 필요한 경우
        if self._needs_quote_re.search(s):
            escaped = s.replace("\\", "\\\\").replace('"', '\\"')
            return f'"{escaped}"'
        return s

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    def inject_block(
        self,
        existing_content: str,
        key: str,
        value: Any,
        depth: int = 1,
    ) -> str:
        """기존 파일 내용의 마지막 닫는 괄호 앞에 새 블록을 삽입.

        캐릭터/이벤트 등 기존 파일에 항목 추가 시 사용한다.
        """
        block = self.serialize_block(key, value, depth=depth)

        # 마지막 } 위치 찾기
        last_brace = existing_content.rfind("}")
        if last_brace == -1:
            # 괄호가 없으면 끝에 추가
            return existing_content + "\n" + block + "\n"

        before = existing_content[:last_brace]
        after = existing_content[last_brace:]

        # 깔끔한 줄바꿈
        if not before.endswith("\n"):
            before += "\n"

        return before + block + "\n" + after

    def remove_block(
        self,
        content: str,
        block_id: str,
    ) -> str:
        """파일 내용에서 특정 ID의 블록을 제거.

        block_id를 포함하는 최상위 블록 (key = { ... })을 찾아 제거한다.
        """
        # block_id가 포함된 블록의 시작 위치 찾기
        pattern = re.compile(
            rf"^\s*{re.escape(block_id)}\s*=\s*\{{",
            re.MULTILINE,
        )
        match = pattern.search(content)
        if not match:
            return content

        start = match.start()
        # 매칭된 위치에서 중괄호 쌍 찾기
        brace_count = 0
        end = match.end()
        brace_count = 1  # 여는 괄호 1개 찾음

        while end < len(content) and brace_count > 0:
            if content[end] == "{":
                brace_count += 1
            elif content[end] == "}":
                brace_count -= 1
            end += 1

        # 블록 뒤의 빈 줄도 제거
        while end < len(content) and content[end] in ("\n", "\r"):
            end += 1

        return content[:start] + content[end:]
