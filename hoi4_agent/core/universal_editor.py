"""
범용 PDX 에디터 엔진.
hoi4_schema.py의 31개 파일 타입 전부를 읽기/편집/검증/저장하는 단일 에디터.

핵심 아이디어:
    파일 타입 선택 → 디렉토리 스캔 → 파싱 → 트리 표시
    → 스키마 기반 검증/자동완성 → 직렬화기로 저장

사용법:
    from tools.shared.universal_editor import UniversalEditor
    
    editor = UniversalEditor(mod_root)
    
    # 파일 타입 목록
    types = editor.list_file_types()
    
    # 특정 타입의 파일 목록
    files = editor.scan_files("event")
    
    # 파일 로드
    doc = editor.load_file("events/TFR_events_USA.txt", "event")
    
    # 데이터 탐색
    tree = doc.get_tree()
    value = doc.get("country_event[0].id")
    
    # 수정
    doc.set("country_event[0].title", "My Event Title")
    doc.add_entry("country_event", new_event_dict)
    doc.remove_entry("country_event", 0)
    
    # 검증 + 저장
    result = doc.validate()
    if not result.has_errors:
        doc.save()
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

from loguru import logger

from tools.shared.constants import MOD_ROOT
from tools.shared.file_manager import FileManager
from tools.shared.hoi4_parser import HOI4Parser
from tools.shared.hoi4_schema import (
    FILE_SCHEMAS,
    AUTOMATION_TIERS,
    get_schema,
    get_automation_tier,
    get_all_file_types,
)
from tools.shared.pdx_serializer import PDXSerializer
from tools.shared.schema_validator import (
    SchemaValidator,
    SchemaValidationResult,
)


# =====================================================================
# 파일 타입 레지스트리
# =====================================================================


@dataclass
class FileTypeInfo:
    """파일 타입 메타데이터."""

    name: str
    file_path_pattern: str
    wiki_url: str
    automation_tier: str  # full_auto, template_auto, assisted, manual
    root_block: str = ""
    required_keys: list[str] = field(default_factory=list)
    file_count: int = 0  # 스캔된 파일 수


class FileTypeRegistry:
    """31개 파일 타입의 레지스트리.

    hoi4_schema.py의 FILE_SCHEMAS를 래핑하여
    파일 탐색, 메타데이터 조회, 자동완성 데이터 제공.
    """

    def __init__(self, mod_root: Path = MOD_ROOT) -> None:
        self.mod_root = mod_root
        self._cache: dict[str, FileTypeInfo] = {}

    def get_all_types(self) -> list[FileTypeInfo]:
        """모든 파일 타입 정보 반환 (캐시)."""
        if not self._cache:
            for ftype in get_all_file_types():
                self._cache[ftype] = self._build_info(ftype)
        return sorted(self._cache.values(), key=lambda x: x.name)

    def get_type(self, name: str) -> FileTypeInfo | None:
        """단일 파일 타입 정보."""
        if name not in self._cache:
            info = self._build_info(name)
            if info:
                self._cache[name] = info
        return self._cache.get(name)

    def get_types_by_tier(self, tier: str) -> list[FileTypeInfo]:
        """자동화 등급별 파일 타입 목록."""
        return [
            info
            for info in self.get_all_types()
            if info.automation_tier == tier
        ]

    def scan_files(self, file_type: str) -> list[Path]:
        """특정 파일 타입의 모든 파일 경로를 반환."""
        schema = get_schema(file_type)
        if schema is None:
            return []

        pattern = schema.get("file_path", "")
        if not pattern:
            return []

        # glob 패턴으로 변환
        # "common/characters/*.txt" → mod_root / "common/characters/*.txt"
        if "**" in pattern:
            parts = pattern.split("/")
            base = self.mod_root
            for p in parts[:-1]:
                base = base / p
            return sorted(base.rglob(parts[-1])) if base.exists() else []
        elif "*" in pattern:
            full_pattern = self.mod_root / pattern
            parent = full_pattern.parent
            glob_part = full_pattern.name
            return sorted(parent.glob(glob_part)) if parent.exists() else []
        else:
            # 단일 파일
            p = self.mod_root / pattern
            return [p] if p.exists() else []

    def _build_info(self, file_type: str) -> FileTypeInfo | None:
        """FILE_SCHEMAS에서 FileTypeInfo 구축."""
        schema = get_schema(file_type)
        if schema is None:
            return None

        files = self.scan_files(file_type)

        return FileTypeInfo(
            name=file_type,
            file_path_pattern=schema.get("file_path", ""),
            wiki_url=schema.get("wiki_url", ""),
            automation_tier=get_automation_tier(file_type),
            root_block=schema.get("root_block", ""),
            required_keys=schema.get("required_keys", []),
            file_count=len(files),
        )


# =====================================================================
# 문서 (로드된 PDX 파일)
# =====================================================================


@dataclass
class TreeNode:
    """PDX 데이터 트리의 노드. UI에서 트리 표시에 사용."""

    key: str
    value_type: str  # "dict", "list", "str", "int", "float", "bool"
    children_count: int = 0
    preview: str = ""  # 값의 미리보기 (짧은 문자열)
    path: str = ""  # 점 표기법 경로 (예: "characters.USA_trump_char")


class PDXDocument:
    """로드된 단일 PDX 파일을 나타내는 편집 가능 문서.

    파서로 로드한 dict를 래핑하여 CRUD, 검증, 직렬화를 제공한다.
    """

    def __init__(
        self,
        data: dict[str, Any],
        file_type: str,
        file_path: Path,
        mod_root: Path = MOD_ROOT,
    ) -> None:
        self.data = data
        self.file_type = file_type
        self.file_path = file_path
        self._mod_root = mod_root
        self._serializer = PDXSerializer()
        self._validator = SchemaValidator(mod_root)
        self._file_manager = FileManager(mod_root)
        self._dirty = False  # 수정 여부

    @property
    def is_dirty(self) -> bool:
        """수정되었는지."""
        return self._dirty

    # ------------------------------------------------------------------
    # 데이터 탐색
    # ------------------------------------------------------------------

    def get_tree(self, max_depth: int = 3) -> list[TreeNode]:
        """데이터를 트리 노드 목록으로 변환 (UI 표시용)."""
        nodes: list[TreeNode] = []
        self._build_tree(self.data, nodes, "", 0, max_depth)
        return nodes

    def get(self, path: str) -> Any:
        """점 표기법으로 값 조회.

        예: "characters.USA_trump_char.portraits.civilian.large"
        배열 인덱스: "country_event[0].id"
        """
        return self._navigate(self.data, path)

    def get_keys(self, path: str = "") -> list[str]:
        """특정 경로의 하위 키 목록."""
        if not path:
            target = self.data
        else:
            target = self._navigate(self.data, path)

        if isinstance(target, dict):
            return list(target.keys())
        if isinstance(target, list):
            return [str(i) for i in range(len(target))]
        return []

    def get_entities(self) -> list[dict[str, str]]:
        """파일의 최상위 엔티티(캐릭터, 이벤트 등) 목록.

        반환: [{"id": "...", "type": "...", "preview": "..."}, ...]
        """
        schema = get_schema(self.file_type)
        if schema is None:
            return []

        root_block = schema.get("root_block", "")
        entities: list[dict[str, str]] = []

        if root_block and root_block in self.data:
            container = self.data[root_block]
            if isinstance(container, dict):
                for key, val in container.items():
                    entities.append({
                        "id": key,
                        "type": root_block,
                        "preview": self._preview(val),
                    })
            elif isinstance(container, list):
                for i, item in enumerate(container):
                    eid = item.get("id", f"[{i}]") if isinstance(item, dict) else f"[{i}]"
                    entities.append({
                        "id": str(eid),
                        "type": root_block,
                        "preview": self._preview(item),
                    })
        else:
            # root_block이 없는 타입 (event, decision 등)
            for key, val in self.data.items():
                if isinstance(val, dict):
                    entities.append({
                        "id": key,
                        "type": "block",
                        "preview": self._preview(val),
                    })
                elif isinstance(val, list):
                    for i, item in enumerate(val):
                        eid = item.get("id", f"{key}[{i}]") if isinstance(item, dict) else f"{key}[{i}]"
                        entities.append({
                            "id": str(eid),
                            "type": key,
                            "preview": self._preview(item),
                        })

        return entities

    # ------------------------------------------------------------------
    # 데이터 수정
    # ------------------------------------------------------------------

    def set(self, path: str, value: Any) -> bool:
        """점 표기법으로 값 설정. 성공 시 True."""
        parts = self._parse_path(path)
        if not parts:
            return False

        target = self.data
        for part in parts[:-1]:
            target = self._step_into(target, part)
            if target is None:
                return False

        last = parts[-1]
        key, idx = self._parse_part(last)

        if idx is not None and isinstance(target, dict) and key in target:
            lst = target[key]
            if isinstance(lst, list) and 0 <= idx < len(lst):
                lst[idx] = value
                self._dirty = True
                return True
        elif isinstance(target, dict):
            target[key] = value
            self._dirty = True
            return True

        return False

    def add_entry(
        self,
        container_path: str,
        entry: dict[str, Any] | Any,
        entry_id: str = "",
    ) -> bool:
        """컨테이너에 새 엔트리 추가.

        container가 dict면 entry_id를 키로 추가.
        container가 list면 append.
        """
        target = self._navigate(self.data, container_path) if container_path else self.data

        if isinstance(target, dict) and entry_id:
            if entry_id in target:
                logger.warning("이미 존재하는 ID: {}", entry_id)
                return False
            target[entry_id] = entry
            self._dirty = True
            return True
        elif isinstance(target, list):
            target.append(entry)
            self._dirty = True
            return True

        return False

    def remove_entry(
        self,
        container_path: str,
        entry_id: str | int,
    ) -> bool:
        """컨테이너에서 엔트리 제거."""
        target = self._navigate(self.data, container_path) if container_path else self.data

        if isinstance(target, dict) and isinstance(entry_id, str):
            if entry_id in target:
                del target[entry_id]
                self._dirty = True
                return True
        elif isinstance(target, list) and isinstance(entry_id, int):
            if 0 <= entry_id < len(target):
                target.pop(entry_id)
                self._dirty = True
                return True

        return False

    def update_entry(
        self,
        path: str,
        updates: dict[str, Any],
    ) -> bool:
        """특정 경로의 dict에 여러 키를 업데이트."""
        target = self._navigate(self.data, path)
        if not isinstance(target, dict):
            return False

        target.update(updates)
        self._dirty = True
        return True

    # ------------------------------------------------------------------
    # 검증
    # ------------------------------------------------------------------

    def validate(self) -> SchemaValidationResult:
        """현재 데이터를 스키마 기반 검증."""
        return self._validator.validate_data(
            self.data,
            self.file_type,
            file_path=str(self.file_path),
        )

    # ------------------------------------------------------------------
    # 저장
    # ------------------------------------------------------------------

    def serialize(self) -> str:
        """현재 데이터를 PDX Script 문자열로 직렬화."""
        return self._serializer.serialize(self.data)

    def save(self, backup: bool = True) -> Path:
        """파일로 저장. backup=True면 기존 파일 백업."""
        content = self.serialize()
        self._file_manager.write_file(
            self.file_path,
            content,
            operation=f"edit_{self.file_type}",
            entity_id=str(self.file_path.name),
        )
        self._dirty = False
        logger.info("저장 완료: {}", self.file_path)
        return self.file_path

    def save_as(self, new_path: Path) -> Path:
        """새 경로로 저장."""
        content = self.serialize()
        new_path.parent.mkdir(parents=True, exist_ok=True)
        new_path.write_text(content, encoding="utf-8")
        self._dirty = False
        logger.info("다른 이름으로 저장: {}", new_path)
        return new_path

    def get_diff(self) -> str:
        """원본 파일과의 차이점 (unified diff)."""
        if not self.file_path.exists():
            return "[New file]"
        original = self.file_path.read_text(encoding="utf-8-sig")
        new_content = self.serialize()
        return self._file_manager.generate_diff(original, new_content)

    # ------------------------------------------------------------------
    # Navigation helpers
    # ------------------------------------------------------------------

    def _navigate(self, data: Any, path: str) -> Any:
        """점 표기법 경로로 데이터 탐색."""
        if not path:
            return data

        parts = self._parse_path(path)
        current = data
        for part in parts:
            current = self._step_into(current, part)
            if current is None:
                return None
        return current

    def _step_into(self, data: Any, part: str) -> Any:
        """한 단계 내려가기."""
        key, idx = self._parse_part(part)

        if isinstance(data, dict):
            val = data.get(key)
            if val is None:
                return None
            if idx is not None:
                if isinstance(val, list) and 0 <= idx < len(val):
                    return val[idx]
                return None
            return val
        elif isinstance(data, list):
            try:
                return data[int(key)]
            except (ValueError, IndexError):
                return None
        return None

    @staticmethod
    def _parse_path(path: str) -> list[str]:
        """점 표기법 경로를 파트 리스트로 파싱.

        "characters.USA_trump_char.portraits" → ["characters", "USA_trump_char", "portraits"]
        "country_event[0].id" → ["country_event[0]", "id"]
        """
        return path.split(".")

    @staticmethod
    def _parse_part(part: str) -> tuple[str, int | None]:
        """파트에서 키와 인덱스 분리.

        "country_event[0]" → ("country_event", 0)
        "characters" → ("characters", None)
        """
        m = re.match(r"^(.+?)\[(\d+)]$", part)
        if m:
            return m.group(1), int(m.group(2))
        return part, None

    def _build_tree(
        self,
        data: Any,
        nodes: list[TreeNode],
        parent_path: str,
        depth: int,
        max_depth: int,
    ) -> None:
        """재귀적 트리 노드 빌드."""
        if depth >= max_depth:
            return

        if isinstance(data, dict):
            for key, val in data.items():
                path = f"{parent_path}.{key}" if parent_path else key
                node = TreeNode(
                    key=key,
                    value_type=type(val).__name__,
                    children_count=(
                        len(val) if isinstance(val, (dict, list)) else 0
                    ),
                    preview=self._preview(val),
                    path=path,
                )
                nodes.append(node)
                if isinstance(val, (dict, list)):
                    self._build_tree(val, nodes, path, depth + 1, max_depth)
        elif isinstance(data, list):
            for i, item in enumerate(data):
                path = f"{parent_path}[{i}]"
                node = TreeNode(
                    key=f"[{i}]",
                    value_type=type(item).__name__,
                    children_count=(
                        len(item) if isinstance(item, (dict, list)) else 0
                    ),
                    preview=self._preview(item),
                    path=path,
                )
                nodes.append(node)
                if isinstance(item, (dict, list)):
                    self._build_tree(
                        item, nodes, path, depth + 1, max_depth
                    )

    @staticmethod
    def _preview(value: Any, max_len: int = 60) -> str:
        """값의 짧은 미리보기 문자열."""
        if isinstance(value, dict):
            keys = list(value.keys())[:4]
            extra = f"... +{len(value) - 4}" if len(value) > 4 else ""
            return "{" + ", ".join(keys) + extra + "}"
        if isinstance(value, list):
            return f"[{len(value)} items]"
        s = str(value)
        return s[:max_len] + "..." if len(s) > max_len else s


# =====================================================================
# 범용 에디터
# =====================================================================


class UniversalEditor:
    """범용 PDX 에디터 — 31개 파일 타입 전체를 하나의 인터페이스로 관리.

    Parameters
    ----------
    mod_root : Path
        모드 루트 경로.
    """

    def __init__(self, mod_root: Path = MOD_ROOT) -> None:
        self.mod_root = mod_root
        self._parser = HOI4Parser()
        self._serializer = PDXSerializer()
        self._validator = SchemaValidator(mod_root)
        self._registry = FileTypeRegistry(mod_root)

    # ------------------------------------------------------------------
    # 파일 타입 관리
    # ------------------------------------------------------------------

    def list_file_types(self) -> list[FileTypeInfo]:
        """모든 파일 타입 목록."""
        return self._registry.get_all_types()

    def get_file_type(self, name: str) -> FileTypeInfo | None:
        """단일 파일 타입 정보."""
        return self._registry.get_type(name)

    def list_types_by_tier(self, tier: str) -> list[FileTypeInfo]:
        """자동화 등급별 파일 타입."""
        return self._registry.get_types_by_tier(tier)

    # ------------------------------------------------------------------
    # 파일 탐색
    # ------------------------------------------------------------------

    def scan_files(self, file_type: str) -> list[Path]:
        """특정 파일 타입의 모든 파일."""
        return self._registry.scan_files(file_type)

    def scan_all(self) -> dict[str, list[Path]]:
        """모든 파일 타입의 파일을 스캔."""
        result: dict[str, list[Path]] = {}
        for ftype in get_all_file_types():
            files = self.scan_files(ftype)
            if files:
                result[ftype] = files
        return result

    # ------------------------------------------------------------------
    # 문서 로드/생성
    # ------------------------------------------------------------------

    def load_file(
        self, file_path: Path | str, file_type: str
    ) -> PDXDocument:
        """파일을 로드하여 PDXDocument 반환."""
        path = (
            Path(file_path)
            if Path(file_path).is_absolute()
            else self.mod_root / file_path
        )

        data = self._parser.parse_file(path)
        return PDXDocument(
            data=data,
            file_type=file_type,
            file_path=path,
            mod_root=self.mod_root,
        )

    def create_document(
        self,
        file_type: str,
        file_path: Path | str,
        initial_data: dict[str, Any] | None = None,
    ) -> PDXDocument:
        """새 PDX 문서 생성."""
        path = (
            Path(file_path)
            if Path(file_path).is_absolute()
            else self.mod_root / file_path
        )

        schema = get_schema(file_type)
        if initial_data is None:
            initial_data = {}
            # root_block이 있으면 빈 블록 생성
            if schema and schema.get("root_block"):
                initial_data[schema["root_block"]] = {}

        return PDXDocument(
            data=initial_data,
            file_type=file_type,
            file_path=path,
            mod_root=self.mod_root,
        )

    # ------------------------------------------------------------------
    # 검증
    # ------------------------------------------------------------------

    def validate_file(
        self, file_path: Path | str, file_type: str
    ) -> SchemaValidationResult:
        """단일 파일 검증."""
        return self._validator.validate_file(
            Path(file_path)
            if Path(file_path).is_absolute()
            else self.mod_root / file_path,
            file_type,
        )

    def validate_type(self, file_type: str) -> SchemaValidationResult:
        """특정 파일 타입의 모든 파일 검증."""
        files = self.scan_files(file_type)
        combined = SchemaValidationResult(file_type=file_type)
        for fpath in files:
            result = self._validator.validate_file(fpath, file_type)
            combined.merge(result)
        return combined

    def validate_all(self) -> dict[str, SchemaValidationResult]:
        """모든 파일 타입 검증."""
        results: dict[str, SchemaValidationResult] = {}
        for ftype in get_all_file_types():
            results[ftype] = self.validate_type(ftype)
        return results

    # ------------------------------------------------------------------
    # 자동완성
    # ------------------------------------------------------------------

    def get_valid_keys(self, file_type: str) -> list[str]:
        """파일 타입에 유효한 키 목록 (자동완성용)."""
        return self._validator.get_valid_keys(file_type)

    def get_valid_values(
        self, file_type: str, key: str
    ) -> list[str] | None:
        """특정 키의 유효 값 목록."""
        return self._validator.get_valid_values(file_type, key)

    # ------------------------------------------------------------------
    # 통계
    # ------------------------------------------------------------------

    def get_mod_stats(self) -> dict[str, Any]:
        """모드 전체 통계."""
        all_files = self.scan_all()
        total_files = sum(len(f) for f in all_files.values())

        tier_stats: dict[str, int] = {}
        for tier_name, tier_data in AUTOMATION_TIERS.items():
            count = sum(
                len(all_files.get(ft, []))
                for ft in tier_data["file_types"]
            )
            tier_stats[tier_name] = count

        return {
            "mod_root": str(self.mod_root),
            "total_file_types": len(all_files),
            "total_files": total_files,
            "files_by_type": {
                ft: len(files) for ft, files in all_files.items()
            },
            "files_by_tier": tier_stats,
        }
