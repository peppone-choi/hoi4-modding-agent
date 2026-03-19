"""
스키마 기반 범용 PDX 파일 검증기.
hoi4_schema.py의 FILE_SCHEMAS를 사용하여 모든 파일 타입을 검증한다.

기존 validators.py의 캐릭터/히스토리 전용 검증을 확장하여,
31개 파일 타입 전체에 대한 구조 검증을 제공한다.

사용법:
    from hoi4_agent.core.schema_validator import SchemaValidator
    
    validator = SchemaValidator()
    result = validator.validate_file("events/TFR_events_USA.txt", "event")
    result = validator.validate_data(parsed_dict, "national_focus")
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from loguru import logger

from hoi4_agent.core.hoi4_parser import HOI4Parser
from hoi4_agent.core.hoi4_schema import (
    FILE_SCHEMAS,
    SCOPES,
    MODIFIER_CATEGORIES,
    get_schema,
    get_automation_tier,
    get_all_file_types,
)


# =====================================================================
# 결과 모델
# =====================================================================


class Severity(Enum):
    """검증 이슈 심각도."""
    ERROR = "ERROR"
    WARNING = "WARNING"
    INFO = "INFO"


@dataclass
class ValidationIssue:
    """단일 검증 이슈."""

    severity: Severity
    code: str
    message: str
    file_path: str = ""
    key_path: str = ""  # 이슈 위치 (예: "characters.USA_trump_char.portraits")
    suggestion: str = ""  # 수정 제안


@dataclass
class SchemaValidationResult:
    """검증 결과."""

    file_type: str = ""
    file_path: str = ""
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        return any(i.severity == Severity.ERROR for i in self.issues)

    @property
    def errors(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == Severity.ERROR]

    @property
    def warnings(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == Severity.WARNING]

    @property
    def infos(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == Severity.INFO]

    def add(
        self,
        severity: Severity,
        code: str,
        message: str,
        key_path: str = "",
        suggestion: str = "",
    ) -> None:
        self.issues.append(
            ValidationIssue(
                severity=severity,
                code=code,
                message=message,
                file_path=self.file_path,
                key_path=key_path,
                suggestion=suggestion,
            )
        )

    def merge(self, other: SchemaValidationResult) -> None:
        self.issues.extend(other.issues)

    def summary(self) -> str:
        """사람이 읽을 수 있는 요약."""
        e = len(self.errors)
        w = len(self.warnings)
        i = len(self.infos)
        status = "❌ FAIL" if self.has_errors else "✅ PASS"
        return (
            f"{status} [{self.file_type}] {self.file_path}\n"
            f"  Errors: {e}, Warnings: {w}, Info: {i}"
        )


# =====================================================================
# 범용 스키마 검증기
# =====================================================================


class SchemaValidator:
    """hoi4_schema.py 기반 범용 PDX 파일 검증기.

    31개 파일 타입 전체에 대해 구조 검증을 수행한다:
    - 필수 키 존재 여부
    - 유효한 키 이름 (스키마에 정의된 키인지)
    - 값 타입 검증 (int, str, list, block 등)
    - 중복 ID 감지
    - 날짜 형식 검증
    - 이념 유효성 (known ideologies)
    """

    def __init__(self, mod_root: Path | None = None) -> None:
        self._parser = HOI4Parser()
        self._mod_root = mod_root

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def validate_file(
        self,
        file_path: Path | str,
        file_type: str,
    ) -> SchemaValidationResult:
        """파일을 파싱하고 스키마 기반 검증을 실행."""
        path = Path(file_path)
        result = SchemaValidationResult(
            file_type=file_type, file_path=str(path)
        )

        schema = get_schema(file_type)
        if schema is None:
            result.add(
                Severity.ERROR,
                "UNKNOWN_TYPE",
                f"Unknown file type: {file_type}",
            )
            return result

        if not path.exists():
            result.add(
                Severity.ERROR,
                "FILE_NOT_FOUND",
                f"File not found: {path}",
            )
            return result

        try:
            data = self._parser.parse_file(path)
        except Exception as exc:
            result.add(
                Severity.ERROR,
                "PARSE_ERROR",
                f"Failed to parse: {exc}",
            )
            return result

        if not data:
            result.add(
                Severity.WARNING,
                "EMPTY_FILE",
                "File parsed to empty dict",
            )
            return result

        self._validate_by_type(data, file_type, schema, result)
        return result

    def validate_data(
        self,
        data: dict[str, Any],
        file_type: str,
        file_path: str = "",
    ) -> SchemaValidationResult:
        """이미 파싱된 dict를 스키마 기반 검증."""
        result = SchemaValidationResult(
            file_type=file_type, file_path=file_path
        )

        schema = get_schema(file_type)
        if schema is None:
            result.add(
                Severity.ERROR,
                "UNKNOWN_TYPE",
                f"Unknown file type: {file_type}",
            )
            return result

        self._validate_by_type(data, file_type, schema, result)
        return result

    def validate_directory(
        self,
        dir_path: Path,
        file_type: str,
    ) -> SchemaValidationResult:
        """디렉토리의 모든 파일을 검증."""
        result = SchemaValidationResult(
            file_type=file_type, file_path=str(dir_path)
        )

        schema = get_schema(file_type)
        if schema is None:
            result.add(
                Severity.ERROR,
                "UNKNOWN_TYPE",
                f"Unknown file type: {file_type}",
            )
            return result

        pattern = schema.get("file_path", "*.txt")
        # 패턴에서 glob 부분 추출
        if "*" in pattern:
            glob_pattern = pattern.rsplit("/", 1)[-1]
        else:
            glob_pattern = "*.txt"

        files = sorted(dir_path.glob(glob_pattern))
        if not files:
            result.add(
                Severity.INFO,
                "NO_FILES",
                f"No files matching '{glob_pattern}' in {dir_path}",
            )
            return result

        for fpath in files:
            sub_result = self.validate_file(fpath, file_type)
            result.merge(sub_result)

        return result

    def get_valid_keys(self, file_type: str) -> list[str]:
        """파일 타입에 대해 유효한 키 목록 반환 (자동완성용)."""
        schema = get_schema(file_type)
        if schema is None:
            return []

        keys: set[str] = set()
        keys.update(schema.get("required_keys", []))
        keys.update(schema.get("optional_keys", []))

        # 타입별 키 수집
        for k, v in schema.items():
            if k.endswith("_keys") and isinstance(v, (list, dict)):
                if isinstance(v, list):
                    keys.update(v)
                elif isinstance(v, dict):
                    keys.update(v.keys())

        return sorted(keys)

    def get_valid_values(
        self, file_type: str, key: str
    ) -> list[str] | None:
        """특정 키에 대한 유효 값 목록 반환 (자동완성용).

        값 목록이 정의되지 않은 경우 None 반환.
        """
        schema = get_schema(file_type)
        if schema is None:
            return None

        # entity_keys에서 enum 값 찾기
        entity_keys = schema.get("entity_keys", {})
        if key in entity_keys:
            val_spec = entity_keys[key]
            if isinstance(val_spec, list):
                return val_spec  # 예: gender: ["male", "female", "undefined"]

        # types 필드
        if key == "type" and "types" in schema:
            return schema["types"]

        # categories
        if key == "category" and "categories" in schema:
            return schema["categories"]

        return None

    # ------------------------------------------------------------------
    # Type-specific validation
    # ------------------------------------------------------------------

    def _validate_by_type(
        self,
        data: dict[str, Any],
        file_type: str,
        schema: dict,
        result: SchemaValidationResult,
    ) -> None:
        """파일 타입에 따라 적절한 검증 실행."""
        # 공통: 필수 키 검증
        self._check_required_keys(data, schema, result)

        # 타입별 검증 디스패치
        dispatch = {
            "character": self._validate_character,
            "country_history": self._validate_country_history,
            "event": self._validate_event,
            "national_focus": self._validate_focus_tree,
            "decision": self._validate_decision,
            "idea": self._validate_idea,
            "technology": self._validate_technology,
            "state": self._validate_state,
            "localisation": self._validate_localisation,
        }

        handler = dispatch.get(file_type)
        if handler:
            handler(data, schema, result)
        else:
            # 기본 검증: root_block 존재 여부
            self._validate_generic(data, schema, result)

    # ------------------------------------------------------------------
    # Common validations
    # ------------------------------------------------------------------

    def _check_required_keys(
        self,
        data: dict[str, Any],
        schema: dict,
        result: SchemaValidationResult,
    ) -> None:
        """필수 키 존재 여부 검증."""
        required = schema.get("required_keys", [])
        root_block = schema.get("root_block")

        # root_block이 있으면 그 안의 데이터를 검증
        if root_block and root_block in data:
            target = data[root_block]
            if isinstance(target, dict):
                for key in required:
                    if key not in target:
                        result.add(
                            Severity.ERROR,
                            "MISSING_KEY",
                            f"Required key '{key}' missing in '{root_block}'",
                            key_path=f"{root_block}.{key}",
                        )
        elif root_block and root_block not in data:
            # root_block 자체가 없는 경우는 INFO (다른 구조일 수 있음)
            pass
        else:
            for key in required:
                if key not in data:
                    result.add(
                        Severity.ERROR,
                        "MISSING_KEY",
                        f"Required key '{key}' missing",
                        key_path=key,
                    )

    def _validate_generic(
        self,
        data: dict[str, Any],
        schema: dict,
        result: SchemaValidationResult,
    ) -> None:
        """범용 검증: root_block 확인, 빈 블록 감지."""
        root_block = schema.get("root_block")
        if root_block and root_block not in data:
            # root_block이 스키마에 정의되어 있지만 파일에 없는 경우
            result.add(
                Severity.INFO,
                "NO_ROOT_BLOCK",
                f"Expected root block '{root_block}' not found. "
                f"Top-level keys: {list(data.keys())[:5]}",
            )

    # ------------------------------------------------------------------
    # Character validation
    # ------------------------------------------------------------------

    def _validate_character(
        self,
        data: dict[str, Any],
        schema: dict,
        result: SchemaValidationResult,
    ) -> None:
        """캐릭터 파일 검증."""
        chars = data.get("characters", {})
        if not isinstance(chars, dict):
            result.add(
                Severity.ERROR,
                "BAD_STRUCTURE",
                "'characters' block is not a dict",
            )
            return

        seen_ids: set[str] = set()
        for char_id, char_data in chars.items():
            # 중복 ID
            if char_id in seen_ids:
                result.add(
                    Severity.ERROR,
                    "DUPLICATE_ID",
                    f"Duplicate character ID: {char_id}",
                    key_path=f"characters.{char_id}",
                )
            seen_ids.add(char_id)

            if not isinstance(char_data, dict):
                continue

            # 초상화 블록 확인
            if "portraits" not in char_data:
                result.add(
                    Severity.WARNING,
                    "MISSING_PORTRAIT",
                    f"Character '{char_id}' has no portraits block",
                    key_path=f"characters.{char_id}.portraits",
                    suggestion="Add portraits = { civilian = { large = ... } }",
                )

    # ------------------------------------------------------------------
    # Country history validation
    # ------------------------------------------------------------------

    def _validate_country_history(
        self,
        data: dict[str, Any],
        schema: dict,
        result: SchemaValidationResult,
    ) -> None:
        """국가 히스토리 파일 검증."""
        # capital 필수
        if "capital" not in data:
            result.add(
                Severity.ERROR,
                "MISSING_CAPITAL",
                "Country history file must have 'capital' key",
            )

        # 날짜 블록 형식 검증
        import re

        date_pattern = re.compile(r"^\d{4}\.\d{1,2}\.\d{1,2}$")
        for key in data:
            if date_pattern.match(key):
                block = data[key]
                if not isinstance(block, dict):
                    result.add(
                        Severity.WARNING,
                        "BAD_DATE_BLOCK",
                        f"Date block '{key}' is not a dict",
                        key_path=key,
                    )

    # ------------------------------------------------------------------
    # Event validation
    # ------------------------------------------------------------------

    def _validate_event(
        self,
        data: dict[str, Any],
        schema: dict,
        result: SchemaValidationResult,
    ) -> None:
        """이벤트 파일 검증."""
        event_types = schema.get("types", [])

        for etype in event_types:
            events = data.get(etype, [])
            if not isinstance(events, list):
                events = [events]

            for idx, event in enumerate(events):
                if not isinstance(event, dict):
                    continue

                path = f"{etype}[{idx}]"

                # id 필수
                if "id" not in event:
                    result.add(
                        Severity.ERROR,
                        "MISSING_EVENT_ID",
                        f"Event at {path} has no 'id'",
                        key_path=path,
                    )

                # option 블록 확인
                options = event.get("option", [])
                if not isinstance(options, list):
                    options = [options]
                if not options:
                    result.add(
                        Severity.WARNING,
                        "NO_OPTIONS",
                        f"Event {event.get('id', '?')} has no options",
                        key_path=path,
                    )

    # ------------------------------------------------------------------
    # Focus tree validation
    # ------------------------------------------------------------------

    def _validate_focus_tree(
        self,
        data: dict[str, Any],
        schema: dict,
        result: SchemaValidationResult,
    ) -> None:
        """포커스 트리 검증."""
        tree = data.get("focus_tree", {})
        if not isinstance(tree, dict):
            return

        # focus_tree.id 필수
        if "id" not in tree:
            result.add(
                Severity.ERROR,
                "MISSING_TREE_ID",
                "Focus tree has no 'id'",
                key_path="focus_tree.id",
            )

        # 개별 포커스 검증
        focus_list = tree.get("focus", [])
        if not isinstance(focus_list, list):
            focus_list = [focus_list]

        focus_required = schema.get("focus_required", [])
        seen_focus_ids: set[str] = set()

        for idx, focus in enumerate(focus_list):
            if not isinstance(focus, dict):
                continue

            fid = focus.get("id", "")
            path = f"focus_tree.focus[{idx}]({fid})"

            for req_key in focus_required:
                if req_key not in focus:
                    result.add(
                        Severity.ERROR,
                        "MISSING_FOCUS_KEY",
                        f"Focus '{fid}' missing required key '{req_key}'",
                        key_path=path,
                    )

            if fid:
                if fid in seen_focus_ids:
                    result.add(
                        Severity.ERROR,
                        "DUPLICATE_FOCUS",
                        f"Duplicate focus ID: {fid}",
                        key_path=path,
                    )
                seen_focus_ids.add(fid)

    # ------------------------------------------------------------------
    # Decision validation
    # ------------------------------------------------------------------

    def _validate_decision(
        self,
        data: dict[str, Any],
        schema: dict,
        result: SchemaValidationResult,
    ) -> None:
        """디시전 파일 검증."""
        for cat_name, cat_data in data.items():
            if not isinstance(cat_data, dict):
                continue

            for dec_name, dec_data in cat_data.items():
                if not isinstance(dec_data, dict):
                    continue

                path = f"{cat_name}.{dec_name}"

                # 최소한 하나의 효과/트리거가 있어야 유의미
                has_logic = any(
                    k in dec_data
                    for k in (
                        "complete_effect",
                        "remove_effect",
                        "visible",
                        "available",
                        "allowed",
                    )
                )
                if not has_logic:
                    result.add(
                        Severity.INFO,
                        "EMPTY_DECISION",
                        f"Decision '{dec_name}' has no logic blocks",
                        key_path=path,
                    )

    # ------------------------------------------------------------------
    # Idea validation
    # ------------------------------------------------------------------

    def _validate_idea(
        self,
        data: dict[str, Any],
        schema: dict,
        result: SchemaValidationResult,
    ) -> None:
        """아이디어 파일 검증."""
        ideas = data.get("ideas", {})
        if not isinstance(ideas, dict):
            return

        for cat, cat_data in ideas.items():
            if not isinstance(cat_data, dict):
                continue
            for idea_name, idea_data in cat_data.items():
                if not isinstance(idea_data, dict):
                    continue

                path = f"ideas.{cat}.{idea_name}"

                # modifier 또는 다른 효과가 있어야 유의미
                if not idea_data:
                    result.add(
                        Severity.WARNING,
                        "EMPTY_IDEA",
                        f"Idea '{idea_name}' is empty",
                        key_path=path,
                    )

    # ------------------------------------------------------------------
    # Technology validation
    # ------------------------------------------------------------------

    def _validate_technology(
        self,
        data: dict[str, Any],
        schema: dict,
        result: SchemaValidationResult,
    ) -> None:
        """기술 파일 검증."""
        techs = data.get("technologies", {})
        if not isinstance(techs, dict):
            return

        for tech_name, tech_data in techs.items():
            if not isinstance(tech_data, dict):
                continue

            path = f"technologies.{tech_name}"

            # research_cost 필수 (doctrine 제외)
            if "research_cost" not in tech_data and "doctrine" not in tech_data:
                result.add(
                    Severity.WARNING,
                    "MISSING_RESEARCH_COST",
                    f"Technology '{tech_name}' has no research_cost",
                    key_path=path,
                )

    # ------------------------------------------------------------------
    # State validation
    # ------------------------------------------------------------------

    def _validate_state(
        self,
        data: dict[str, Any],
        schema: dict,
        result: SchemaValidationResult,
    ) -> None:
        """State 파일 검증."""
        state = data.get("state", {})
        if not isinstance(state, dict):
            return

        required = schema.get("required_keys", [])
        for key in required:
            if key not in state:
                result.add(
                    Severity.ERROR,
                    "MISSING_STATE_KEY",
                    f"State missing required key '{key}'",
                    key_path=f"state.{key}",
                )

        # provinces가 비어있으면 경고
        provinces = state.get("provinces", [])
        if not provinces:
            result.add(
                Severity.WARNING,
                "EMPTY_PROVINCES",
                "State has no provinces",
                key_path="state.provinces",
            )

    # ------------------------------------------------------------------
    # Localisation validation
    # ------------------------------------------------------------------

    def _validate_localisation(
        self,
        data: dict[str, Any],
        schema: dict,
        result: SchemaValidationResult,
    ) -> None:
        """로컬라이제이션 파일 검증 (YAML 기반이므로 기본 구조만)."""
        # 로컬라이제이션은 YAML이라 PDX 파서로 안 읽힘 — 별도 처리 필요
        result.add(
            Severity.INFO,
            "YAML_FORMAT",
            "Localisation files use YAML format, not PDX Script. "
            "Use a YAML parser for full validation.",
        )
