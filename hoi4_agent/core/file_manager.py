"""
HOI4 mod 파일 안전 관리자.
백업, 복원, 변경 로그 기능을 제공한다.
"""
from __future__ import annotations

import difflib
import json
import shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger


@dataclass
class ChangeRecord:
    """단일 파일 변경 기록."""

    timestamp: str
    operation: str  # "add_character", "update_politics", "add_portrait" 등
    file_path: str
    entity_id: str  # char_id, country_tag 등
    old_value: dict | None = None
    new_value: dict | None = None
    source: str = ""  # "wikidata", "wikipedia", "manual" 등
    wiki_url: str = ""


class ChangeLog:
    """변경 로그 관리."""

    def __init__(self, log_path: Path) -> None:
        self.log_path = log_path
        self._records: list[ChangeRecord] = []

    @property
    def records(self) -> list[ChangeRecord]:
        """변경 기록 목록 (읽기 전용)."""
        return list(self._records)

    def add(self, record: ChangeRecord) -> None:
        """변경 기록 추가."""
        self._records.append(record)
        logger.info(
            "Change recorded: {} on {} (entity={})",
            record.operation,
            record.file_path,
            record.entity_id,
        )

    def save(self) -> None:
        """로그를 JSON 파일로 저장."""
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        data = [asdict(r) for r in self._records]
        self.log_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.debug("Change log saved to {}", self.log_path)

    def load(self) -> None:
        """저장된 로그 불러오기."""
        if not self.log_path.exists():
            logger.debug("No change log found at {}", self.log_path)
            return
        data = json.loads(self.log_path.read_text(encoding="utf-8"))
        self._records = [ChangeRecord(**item) for item in data]
        logger.debug("Loaded {} change records", len(self._records))

    def get_by_entity(self, entity_id: str) -> list[ChangeRecord]:
        """특정 엔티티의 변경 기록 조회."""
        return [r for r in self._records if r.entity_id == entity_id]

    def get_by_date(self, date: str) -> list[ChangeRecord]:
        """특정 날짜의 변경 기록 조회.

        Args:
            date: ``YYYY-MM-DD`` 형식의 날짜 문자열.
        """
        return [r for r in self._records if r.timestamp.startswith(date)]

    def generate_report(self) -> str:
        """사람이 읽을 수 있는 변경 보고서 생성."""
        if not self._records:
            return "변경 기록이 없습니다."

        lines: list[str] = []
        lines.append("=" * 60)
        lines.append("변경 보고서")
        lines.append(f"총 {len(self._records)}건의 변경 기록")
        lines.append("=" * 60)

        by_operation: dict[str, list[ChangeRecord]] = {}
        for rec in self._records:
            by_operation.setdefault(rec.operation, []).append(rec)

        for op, recs in by_operation.items():
            lines.append(f"\n[{op}] ({len(recs)}건)")
            for rec in recs:
                lines.append(
                    f"  - {rec.timestamp} | {rec.entity_id} | {rec.file_path}"
                )
                if rec.source:
                    lines.append(f"    출처: {rec.source}")
                if rec.wiki_url:
                    lines.append(f"    위키: {rec.wiki_url}")

        lines.append("\n" + "=" * 60)
        return "\n".join(lines)


class FileManager:
    """MOD 파일 안전 관리자."""

    def __init__(self, mod_root: Path, backup_dir: Path | None = None) -> None:
        self.mod_root = mod_root
        self.backup_dir = backup_dir or (mod_root / "tools" / ".backups")
        self.change_log = ChangeLog(mod_root / "tools" / "change_log.json")

    def read_file(self, path: Path) -> str:
        """파일 읽기 (UTF-8 BOM 처리 포함)."""
        raw = path.read_bytes()
        # UTF-8 BOM(0xEF 0xBB 0xBF) 제거
        if raw.startswith(b"\xef\xbb\xbf"):
            raw = raw[3:]
        return raw.decode("utf-8")

    def write_file(
        self,
        path: Path,
        content: str,
        operation: str = "",
        entity_id: str = "",
    ) -> None:
        """파일 쓰기 (쓰기 전 자동 백업).

        기존 파일이 존재하면 백업을 생성한 뒤 덮어쓴다.
        ``operation`` 과 ``entity_id`` 가 주어지면 변경 로그에 기록한다.
        """
        old_content: str | None = None
        if path.exists():
            old_content = self.read_file(path)
            self.backup_file(path)

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        logger.info("File written: {}", path)

        if operation:
            record = ChangeRecord(
                timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                operation=operation,
                file_path=str(path),
                entity_id=entity_id,
                old_value={"content": old_content} if old_content else None,
                new_value={"content": content},
            )
            self.change_log.add(record)

    def backup_file(self, path: Path) -> Path:
        """파일 백업. 타임스탬프 기반 백업 파일 경로 반환."""
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        backup_name = f"{path.stem}_{timestamp}{path.suffix}"
        backup_path = self.backup_dir / backup_name
        shutil.copy2(path, backup_path)
        logger.debug("Backup created: {}", backup_path)
        return backup_path

    def restore_file(
        self,
        path: Path,
        backup_path: Path | None = None,
    ) -> bool:
        """백업에서 파일 복원. ``backup_path`` 없으면 최신 백업 사용."""
        if backup_path is None:
            backups = self.list_backups(path)
            if not backups:
                logger.warning("No backups found for {}", path)
                return False
            backup_path = backups[0]

        if not backup_path.exists():
            logger.warning("Backup file not found: {}", backup_path)
            return False

        shutil.copy2(backup_path, path)
        logger.info("Restored {} from {}", path, backup_path)
        return True

    def list_backups(self, path: Path) -> list[Path]:
        """특정 파일의 백업 목록 반환 (최신순)."""
        if not self.backup_dir.exists():
            return []
        pattern = f"{path.stem}_*{path.suffix}"
        backups = sorted(
            self.backup_dir.glob(pattern),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        return backups

    def generate_diff(self, old_content: str, new_content: str) -> str:
        """두 파일 내용의 unified diff 생성."""
        old_lines = old_content.splitlines(keepends=True)
        new_lines = new_content.splitlines(keepends=True)
        diff = difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile="before",
            tofile="after",
        )
        return "".join(diff)

    def apply_with_diff_review(
        self,
        path: Path,
        new_content: str,
        operation: str = "",
    ) -> bool:
        """diff를 보여주고 확인 후 파일 쓰기. CLI 환경에서 사용."""
        if path.exists():
            old_content = self.read_file(path)
            diff = self.generate_diff(old_content, new_content)
            if not diff:
                logger.info("No changes detected for {}", path)
                return False
            print(diff)
        else:
            print(f"[NEW FILE] {path}")

        response = input("Apply changes? [y/N]: ").strip().lower()
        if response == "y":
            self.write_file(path, new_content, operation=operation)
            return True

        logger.info("Changes rejected by user for {}", path)
        return False
