"""
HOI4 mod 파일 검증기.
중복 ID, 잘못된 날짜, 누락된 초상화 GFX 참조 등을 검사한다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from loguru import logger


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class Severity(Enum):
    ERROR = "ERROR"        # 쓰기 차단 (중복 ID 등)
    WARNING = "WARNING"    # 경고만 (누락 초상화 등)
    INFO = "INFO"


@dataclass
class ValidationIssue:
    severity: Severity
    code: str              # 예: "DUPLICATE_CHAR_ID"
    message: str
    file_path: str = ""
    line_number: int = 0
    char_id: str = ""


@dataclass
class ValidationResult:
    issues: list[ValidationIssue] = field(default_factory=list)

    # -- predicates -----------------------------------------------------------

    @property
    def has_errors(self) -> bool:
        return any(i.severity == Severity.ERROR for i in self.issues)

    @property
    def errors(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == Severity.ERROR]

    @property
    def warnings(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == Severity.WARNING]

    # -- mutators -------------------------------------------------------------

    def add_error(self, code: str, message: str, **kwargs: Any) -> None:
        self.issues.append(
            ValidationIssue(severity=Severity.ERROR, code=code, message=message, **kwargs)
        )

    def add_warning(self, code: str, message: str, **kwargs: Any) -> None:
        self.issues.append(
            ValidationIssue(severity=Severity.WARNING, code=code, message=message, **kwargs)
        )

    def merge(self, other: ValidationResult) -> None:
        """다른 ValidationResult 의 이슈를 병합한다."""
        self.issues.extend(other.issues)

    # -- reporting ------------------------------------------------------------

    def summary(self) -> str:
        error_count = len(self.errors)
        warning_count = len(self.warnings)
        total = len(self.issues)
        lines = [
            f"Validation: {total} issue(s) ({error_count} error(s), {warning_count} warning(s))"
        ]
        for issue in self.issues:
            prefix = f"[{issue.severity.value}]"
            loc = ""
            if issue.file_path:
                loc += f" {issue.file_path}"
            if issue.line_number:
                loc += f":{issue.line_number}"
            lines.append(f"  {prefix}{loc} {issue.code}: {issue.message}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Character ID regex
# TAG: 2-4 uppercase letters/digits, starting with a letter
# name: lowercase letters, digits, underscores (at least one char)
# suffix: _char
# ---------------------------------------------------------------------------
_CHAR_ID_PATTERN = re.compile(r"^[A-Z][A-Z0-9]{1,3}_[a-z][a-z0-9_]*_char$")


# ---------------------------------------------------------------------------
# CharacterValidator
# ---------------------------------------------------------------------------


class CharacterValidator:
    """캐릭터 파일 검증."""

    def validate_char_id(self, char_id: str) -> ValidationResult:
        """캐릭터 ID 형식 검증. 패턴: {TAG}_{name}_char"""
        result = ValidationResult()
        if not _CHAR_ID_PATTERN.match(char_id):
            result.add_error(
                "INVALID_CHAR_ID",
                f"Character ID '{char_id}' does not match pattern {{TAG}}_{{name}}_char",
                char_id=char_id,
            )
        return result

    def validate_no_duplicate_ids(self, characters_dir: Path) -> ValidationResult:
        """모든 캐릭터 파일에서 중복 ID 검사. 중복 시 ERROR."""
        result = ValidationResult()
        seen: dict[str, str] = {}  # char_id -> first file path

        if not characters_dir.exists():
            result.add_warning(
                "DIR_NOT_FOUND",
                f"Characters directory not found: {characters_dir}",
            )
            return result

        for txt_file in sorted(characters_dir.glob("*.txt")):
            char_ids = self._extract_char_ids(txt_file)
            for char_id, line_num in char_ids:
                if char_id in seen:
                    result.add_error(
                        "DUPLICATE_CHAR_ID",
                        f"Duplicate character ID '{char_id}' "
                        f"(first defined in {Path(seen[char_id]).name})",
                        file_path=str(txt_file),
                        line_number=line_num,
                        char_id=char_id,
                    )
                else:
                    seen[char_id] = str(txt_file)

        return result

    def validate_portrait_references(
        self,
        char_data: dict[str, Any],
        gfx_sprites: dict[str, str],
        gfx_dir: Path,
    ) -> ValidationResult:
        """초상화 GFX 참조 검증. 파일이 없으면 WARNING."""
        result = ValidationResult()

        char_id = char_data.get("id", "")
        portraits = char_data.get("portraits", {})

        for _category, paths in portraits.items():
            if isinstance(paths, dict):
                for _size, path in paths.items():
                    self._check_portrait(result, char_id, str(path), gfx_sprites, gfx_dir)
            elif isinstance(paths, str):
                self._check_portrait(result, char_id, paths, gfx_sprites, gfx_dir)

        return result

    def validate_ideology(self, ideology: str, valid_ideologies: set[str]) -> ValidationResult:
        """이념 코드 유효성 검증."""
        result = ValidationResult()
        if ideology not in valid_ideologies:
            result.add_error(
                "INVALID_IDEOLOGY",
                f"Unknown ideology: '{ideology}'",
            )
        return result

    # -- internal helpers -----------------------------------------------------

    def _check_portrait(
        self,
        result: ValidationResult,
        char_id: str,
        portrait_path: str,
        gfx_sprites: dict[str, str],
        gfx_dir: Path,
    ) -> None:
        """하나의 초상화 경로가 디스크에 존재하는지 검사한다."""
        if not portrait_path:
            return

        # portrait_path 는 "gfx/leaders/USA/Donald_Trump.png" 형태.
        # gfx_dir 는 모드 루트의 gfx 디렉터리.
        # 모드 루트 = gfx_dir.parent
        mod_root = gfx_dir.parent if gfx_dir.name == "gfx" else gfx_dir
        resolved = mod_root / portrait_path

        # GFX 스프라이트 사전에도 없고 파일도 없으면 WARNING
        if portrait_path not in gfx_sprites and not resolved.exists():
            result.add_warning(
                "MISSING_PORTRAIT",
                f"Portrait file not found: {portrait_path}",
                char_id=char_id,
            )

    @staticmethod
    def _extract_char_ids(file_path: Path) -> list[tuple[str, int]]:
        """캐릭터 파일에서 캐릭터 ID 와 줄 번호를 추출한다."""
        ids: list[tuple[str, int]] = []
        try:
            content = file_path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError) as exc:
            logger.warning(f"Failed to read {file_path}: {exc}")
            return ids

        depth = 0
        inside_characters = False

        for line_num, line in enumerate(content.splitlines(), 1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue

            # characters 블록 진입
            if not inside_characters and re.match(r"characters\s*=?\s*\{", stripped):
                inside_characters = True
                depth = stripped.count("{") - stripped.count("}")
                continue

            if inside_characters:
                # depth 1 == characters 블록 바로 아래 → 캐릭터 ID
                if depth == 1:
                    m = re.match(r"(\w+)\s*=\s*\{", stripped)
                    if m:
                        ids.append((m.group(1), line_num))

                depth += stripped.count("{") - stripped.count("}")
                if depth <= 0:
                    inside_characters = False
                    depth = 0

        return ids


# ---------------------------------------------------------------------------
# HistoryValidator
# ---------------------------------------------------------------------------

_DATE_RE = re.compile(r"^\d{4}\.\d{1,2}\.\d{1,2}$")


class HistoryValidator:
    """history/countries/*.txt 파일 검증."""

    def validate_date_format(self, date_str: str) -> ValidationResult:
        """날짜 형식 검증. 포맷: YYYY.M.D"""
        result = ValidationResult()
        if not _DATE_RE.match(date_str):
            result.add_error(
                "INVALID_DATE_FORMAT",
                f"Invalid date format: '{date_str}' (expected YYYY.M.D)",
            )
            return result

        parts = date_str.split(".")
        year, month, day = int(parts[0]), int(parts[1]), int(parts[2])

        if year < 1:
            result.add_error("INVALID_DATE_YEAR", f"Invalid year {year} in date '{date_str}'")
        if month < 1 or month > 12:
            result.add_error("INVALID_DATE_MONTH", f"Invalid month {month} in date '{date_str}'")
        if day < 1 or day > 31:
            result.add_error("INVALID_DATE_DAY", f"Invalid day {day} in date '{date_str}'")

        return result

    def validate_recruited_characters_exist(
        self,
        history_data: dict[str, Any],
        all_char_ids: set[str],
    ) -> ValidationResult:
        """recruit_character 참조가 실제로 존재하는지 검증. 없으면 WARNING."""
        result = ValidationResult()

        recruited: list[str] = history_data.get("recruit_characters", [])
        file_path: str = history_data.get("file_path", "")

        for char_id in recruited:
            if char_id not in all_char_ids:
                result.add_warning(
                    "MISSING_RECRUIT_CHARACTER",
                    f"recruit_character '{char_id}' not found in any character file",
                    file_path=file_path,
                    char_id=char_id,
                )

        return result

    def validate_ruling_party_ideology(
        self,
        ideology: str,
        valid_ideologies: set[str],
    ) -> ValidationResult:
        """집권당 이념이 유효한지 검증."""
        result = ValidationResult()
        if ideology not in valid_ideologies:
            result.add_error(
                "INVALID_RULING_PARTY",
                f"Invalid ruling party ideology: '{ideology}'",
            )
        return result


# ---------------------------------------------------------------------------
# ModValidator  –  전체 모드 검증 오케스트레이터
# ---------------------------------------------------------------------------


class ModValidator:
    """전체 모드 검증 오케스트레이터."""

    def __init__(self, mod_root: Path):
        self.mod_root = mod_root
        self.char_validator = CharacterValidator()
        self.history_validator = HistoryValidator()

    # -- public API -----------------------------------------------------------

    def validate_all(self) -> ValidationResult:
        """전체 모드 검증 실행."""
        result = ValidationResult()

        logger.info("Starting full mod validation...")

        result.merge(self.validate_characters())
        result.merge(self.validate_histories())
        result.merge(self.validate_parties())

        logger.info(result.summary())
        return result

    def validate_parties(self) -> ValidationResult:
        """정당 로컬라이제이션 교차 검증."""
        from tools.shared.party_validator import PartyValidator

        pv = PartyValidator(self.mod_root)
        result, report = pv.validate_all()
        logger.info(report.summary())
        return result

    def validate_characters(self) -> ValidationResult:
        """모든 캐릭터 파일 검증."""
        result = ValidationResult()
        characters_dir = self.mod_root / "common" / "characters"

        dup_result = self.char_validator.validate_no_duplicate_ids(characters_dir)
        result.merge(dup_result)

        return result

    def validate_histories(self) -> ValidationResult:
        """모든 히스토리 파일 검증."""
        result = ValidationResult()
        history_dir = self.mod_root / "history" / "countries"

        if not history_dir.exists():
            result.add_warning(
                "DIR_NOT_FOUND",
                f"History directory not found: {history_dir}",
            )
            return result

        all_char_ids = self.get_all_char_ids()

        for txt_file in sorted(history_dir.glob("*.txt")):
            hist_data = self._parse_history_file(txt_file)
            recruit_result = self.history_validator.validate_recruited_characters_exist(
                hist_data, all_char_ids,
            )
            result.merge(recruit_result)

        return result

    def get_all_char_ids(self) -> set[str]:
        """모든 캐릭터 ID 수집."""
        characters_dir = self.mod_root / "common" / "characters"
        ids: set[str] = set()

        if not characters_dir.exists():
            return ids

        for txt_file in sorted(characters_dir.glob("*.txt")):
            for char_id, _ in CharacterValidator._extract_char_ids(txt_file):
                ids.add(char_id)

        return ids

    def get_valid_ideologies(self) -> set[str]:
        """유효한 이념 코드 목록 반환."""
        ideology_file = self.mod_root / "common" / "ideologies" / "TFR_ideologies.txt"
        return self._parse_ideologies(ideology_file)

    # -- internal helpers -----------------------------------------------------

    @staticmethod
    def _parse_ideologies(file_path: Path) -> set[str]:
        """이념 파일을 파싱하여 모든 하위 유형 이름을 반환한다."""
        ideologies: set[str] = set()

        if not file_path.exists():
            logger.warning(f"Ideology file not found: {file_path}")
            return ideologies

        try:
            content = file_path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError) as exc:
            logger.warning(f"Failed to read {file_path}: {exc}")
            return ideologies

        depth = 0
        in_types_block = False
        types_base_depth = 0

        for line in content.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                # 빈 줄 / 주석은 무시하되 brace 가 포함된 주석은 거의 없음
                continue

            # types = { 블록 진입
            if not in_types_block and re.match(r"types\s*=\s*\{", stripped):
                in_types_block = True
                types_base_depth = depth + 1
                depth += stripped.count("{") - stripped.count("}")
                continue

            if in_types_block:
                # types 블록 바로 아래 depth 에서 하위 유형 이름 추출
                if depth == types_base_depth:
                    m = re.match(r"(\w+)\s*=\s*\{", stripped)
                    if m:
                        ideologies.add(m.group(1))

                depth += stripped.count("{") - stripped.count("}")
                if depth < types_base_depth:
                    in_types_block = False
            else:
                depth += stripped.count("{") - stripped.count("}")

        # 최상위 이념 그룹 이름도 추가 (ruling_party 에서 참조됨)
        # ideologies = { 바로 아래 블록 이름: totalitarian_socialist, communist, …
        top_level = re.compile(r"^\t(\w+)\s*=\s*\{", re.MULTILINE)
        for m in top_level.finditer(content):
            name = m.group(1)
            if name not in ("ideologies", "types"):
                ideologies.add(name)

        return ideologies

    @staticmethod
    def _parse_history_file(file_path: Path) -> dict[str, Any]:
        """히스토리 파일에서 recruit_character 참조를 추출한다."""
        data: dict[str, Any] = {
            "file_path": str(file_path),
            "recruit_characters": [],
        }

        try:
            content = file_path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError) as exc:
            logger.warning(f"Failed to read {file_path}: {exc}")
            return data

        pattern = re.compile(r"^\s*recruit_character\s*=\s*(\w+)", re.MULTILINE)
        for m in pattern.finditer(content):
            data["recruit_characters"].append(m.group(1))

        return data
