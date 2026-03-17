"""정당 데이터 교차 검증기. 로컬라이제이션 갭, 충돌, 고아 키를 탐지한다."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from loguru import logger

from tools.shared.constants import (
    COUNTRY_TAGS_DIR,
    HISTORY_COUNTRIES_DIR,
    IDEOLOGIES_FILE,
    LOCALISATION_DIR,
    MAIN_IDEOLOGY_GROUPS,
    PARTIES_LOC_FILE,
)
from tools.shared.validators import Severity, ValidationIssue, ValidationResult


_LOC_ENTRY_RE = re.compile(r"^\s*(\S+?):(?:\d*)?\s+\"(.*)\"", re.MULTILINE)
_COUNTRY_TAG_RE = re.compile(r"^([A-Za-z0-9]+)\s*=\s*\"", re.MULTILINE)
_SET_PARTY_NAME_RE = re.compile(
    r"set_party_name\s*=\s*\{[^}]*ideology\s*=\s*(\w+)[^}]*name\s*=\s*(\w+)",
    re.DOTALL,
)


@dataclass
class CountryCoverage:
    tag: str
    present: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)

    @property
    def ratio(self) -> float:
        total = len(self.present) + len(self.missing)
        return len(self.present) / total if total else 0.0

    @property
    def status(self) -> str:
        if not self.missing:
            return "COMPLETE"
        if not self.present:
            return "NONE"
        return "PARTIAL"


@dataclass
class LocConflict:
    key: str
    sources: dict[str, str] = field(default_factory=dict)


@dataclass
class PartyGapReport:
    total_countries: int = 0
    total_ideologies: int = 0
    complete_count: int = 0
    partial_count: int = 0
    none_count: int = 0
    total_gaps: int = 0
    coverage_pct: float = 0.0
    coverages: list[CountryCoverage] = field(default_factory=list)
    conflicts: list[LocConflict] = field(default_factory=list)
    orphan_loc_keys: list[str] = field(default_factory=list)
    missing_loc_from_history: list[tuple[str, str, str]] = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            "=" * 60,
            "  Party Gap Analysis Report",
            "=" * 60,
            f"  Countries: {self.total_countries}  |  Ideology groups: {self.total_ideologies}",
            f"  Coverage: {self.coverage_pct:.1f}%  ({self.total_countries * self.total_ideologies - self.total_gaps}"
            f" / {self.total_countries * self.total_ideologies})",
            f"  Complete: {self.complete_count}  |  Partial: {self.partial_count}  |  None: {self.none_count}",
            f"  Total gaps: {self.total_gaps}",
            f"  Conflicts: {len(self.conflicts)}",
            f"  Orphan loc keys: {len(self.orphan_loc_keys)}",
            f"  History→loc missing: {len(self.missing_loc_from_history)}",
            "-" * 60,
        ]

        worst = sorted(self.coverages, key=lambda c: len(c.missing), reverse=True)
        lines.append("  Top 20 countries with most gaps:")
        for cov in worst[:20]:
            if not cov.missing:
                break
            lines.append(f"    {cov.tag:6s}  missing {len(cov.missing):2d}: {', '.join(cov.missing[:5])}"
                         + ("..." if len(cov.missing) > 5 else ""))

        if self.conflicts:
            lines.append("")
            lines.append(f"  Conflicts ({len(self.conflicts)}):")
            for c in self.conflicts[:10]:
                lines.append(f"    {c.key}: {c.sources}")

        lines.append("=" * 60)
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_countries": self.total_countries,
            "total_ideologies": self.total_ideologies,
            "coverage_pct": round(self.coverage_pct, 2),
            "complete": self.complete_count,
            "partial": self.partial_count,
            "none": self.none_count,
            "total_gaps": self.total_gaps,
            "conflicts": len(self.conflicts),
            "orphan_keys": len(self.orphan_loc_keys),
            "history_missing_loc": len(self.missing_loc_from_history),
            "per_country": {
                c.tag: {"status": c.status, "missing": c.missing, "present": c.present}
                for c in self.coverages
            },
        }


class PartyValidator:
    """정당 로컬라이제이션 교차 검증기."""

    def __init__(self, mod_root: Path) -> None:
        self.mod_root = mod_root
        self._loc_dir = mod_root / "localisation" / "english"
        self._parties_file = self._loc_dir / "TFR_parties_l_english.yml"
        self._country_tags_dir = mod_root / "common" / "country_tags"
        self._history_dir = mod_root / "history" / "countries"
        self._ideology_groups = list(MAIN_IDEOLOGY_GROUPS)

    def validate_all(self) -> tuple[ValidationResult, PartyGapReport]:
        """전체 정당 교차 검증을 수행한다."""
        result = ValidationResult()

        country_tags = self._collect_country_tags()
        parties_loc = self._read_loc_file(self._parties_file)
        country_locs = self._collect_country_loc_entries()
        all_loc = self._merge_loc(parties_loc, country_locs)
        history_parties = self._collect_history_set_party_names()

        report = self._gap_analysis(country_tags, all_loc, result)
        self._detect_conflicts(parties_loc, country_locs, report, result)
        self._detect_orphans(country_tags, all_loc, report, result)
        self._detect_history_missing_loc(history_parties, all_loc, report, result)

        return result, report

    def validate_country(self, tag: str) -> tuple[ValidationResult, CountryCoverage]:
        """단일 국가의 정당 커버리지를 검증한다."""
        result = ValidationResult()
        parties_loc = self._read_loc_file(self._parties_file)
        country_locs = self._collect_country_loc_entries()
        all_loc = self._merge_loc(parties_loc, country_locs)

        present = []
        missing = []
        for ideo in self._ideology_groups:
            key = f"{tag}_{ideo}_party"
            if key in all_loc:
                present.append(ideo)
            else:
                missing.append(ideo)
                result.add_warning(
                    "MISSING_PARTY_LOC",
                    f"{tag}: missing party loc for '{ideo}'",
                )

        return result, CountryCoverage(tag=tag, present=present, missing=missing)

    def _collect_country_tags(self) -> list[str]:
        tags: list[str] = []
        if not self._country_tags_dir.exists():
            logger.warning(f"Country tags dir not found: {self._country_tags_dir}")
            return tags
        for f in sorted(self._country_tags_dir.glob("*.txt")):
            try:
                content = f.read_text(encoding="utf-8-sig")
            except (OSError, UnicodeDecodeError):
                continue
            for m in _COUNTRY_TAG_RE.finditer(content):
                tag = m.group(1).strip()
                if tag and tag not in tags:
                    tags.append(tag)
        logger.debug(f"Collected {len(tags)} country tags")
        return tags

    def _read_loc_file(self, path: Path) -> dict[str, str]:
        if not path.exists():
            return {}
        try:
            content = path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError):
            return {}
        entries: dict[str, str] = {}
        for m in _LOC_ENTRY_RE.finditer(content):
            entries[m.group(1)] = m.group(2)
        return entries

    def _collect_country_loc_entries(self) -> dict[str, dict[str, str]]:
        """모든 yml 파일에서 _party 키를 수집한다. {filename: {key: value}}"""
        result: dict[str, dict[str, str]] = {}
        if not self._loc_dir.exists():
            return result
        for f in sorted(self._loc_dir.glob("*.yml")):
            if f.name == self._parties_file.name:
                continue
            entries = self._read_loc_file(f)
            party_entries = {k: v for k, v in entries.items() if "_party" in k}
            if party_entries:
                result[f.name] = party_entries
        return result

    @staticmethod
    def _merge_loc(
        parties_loc: dict[str, str],
        country_locs: dict[str, dict[str, str]],
    ) -> dict[str, str]:
        merged: dict[str, str] = dict(parties_loc)
        for entries in country_locs.values():
            for k, v in entries.items():
                if k not in merged:
                    merged[k] = v
        return merged

    def _collect_history_set_party_names(self) -> list[tuple[str, str, str]]:
        """history 파일에서 set_party_name 추출. [(file, ideology, loc_key)]"""
        results: list[tuple[str, str, str]] = []
        if not self._history_dir.exists():
            return results
        for f in sorted(self._history_dir.glob("*.txt")):
            try:
                content = f.read_text(encoding="utf-8-sig")
            except (OSError, UnicodeDecodeError):
                continue
            for m in _SET_PARTY_NAME_RE.finditer(content):
                results.append((f.name, m.group(1), m.group(2)))
        return results

    def _gap_analysis(
        self,
        country_tags: list[str],
        all_loc: dict[str, str],
        result: ValidationResult,
    ) -> PartyGapReport:
        report = PartyGapReport(
            total_countries=len(country_tags),
            total_ideologies=len(self._ideology_groups),
        )

        for tag in country_tags:
            present = []
            missing = []
            for ideo in self._ideology_groups:
                key = f"{tag}_{ideo}_party"
                if key in all_loc:
                    present.append(ideo)
                else:
                    missing.append(ideo)

            cov = CountryCoverage(tag=tag, present=present, missing=missing)
            report.coverages.append(cov)

            if cov.status == "COMPLETE":
                report.complete_count += 1
            elif cov.status == "NONE":
                report.none_count += 1
            else:
                report.partial_count += 1

            report.total_gaps += len(missing)

            for ideo in missing:
                result.add_warning(
                    "MISSING_PARTY_LOC",
                    f"{tag}: no party localisation for ideology '{ideo}'",
                )

        total_cells = report.total_countries * report.total_ideologies
        if total_cells > 0:
            report.coverage_pct = ((total_cells - report.total_gaps) / total_cells) * 100

        return report

    def _detect_conflicts(
        self,
        parties_loc: dict[str, str],
        country_locs: dict[str, dict[str, str]],
        report: PartyGapReport,
        result: ValidationResult,
    ) -> None:
        for filename, entries in country_locs.items():
            for key, value in entries.items():
                if key in parties_loc and parties_loc[key] != value:
                    conflict = LocConflict(
                        key=key,
                        sources={
                            "TFR_parties_l_english.yml": parties_loc[key],
                            filename: value,
                        },
                    )
                    report.conflicts.append(conflict)
                    result.add_warning(
                        "PARTY_LOC_CONFLICT",
                        f"'{key}' defined differently in TFR_parties and {filename}",
                    )

        filenames = list(country_locs.keys())
        for i, fn1 in enumerate(filenames):
            for fn2 in filenames[i + 1:]:
                overlap = set(country_locs[fn1]) & set(country_locs[fn2])
                for key in overlap:
                    if country_locs[fn1][key] != country_locs[fn2][key]:
                        conflict = LocConflict(
                            key=key,
                            sources={fn1: country_locs[fn1][key], fn2: country_locs[fn2][key]},
                        )
                        report.conflicts.append(conflict)
                        result.add_warning(
                            "PARTY_LOC_DUPLICATE_CONFLICT",
                            f"'{key}' differs between {fn1} and {fn2}",
                        )

    def _detect_orphans(
        self,
        country_tags: list[str],
        all_loc: dict[str, str],
        report: PartyGapReport,
        result: ValidationResult,
    ) -> None:
        tag_set = set(country_tags)
        ideo_set = set(self._ideology_groups)
        party_key_re = re.compile(r"^([A-Za-z0-9]+)_(\w+)_party$")

        for key in all_loc:
            if not key.endswith("_party"):
                continue
            if key.endswith("_party_long") or "_party_" in key:
                continue

            m = party_key_re.match(key)
            if not m:
                report.orphan_loc_keys.append(key)
                result.add_warning(
                    "ORPHAN_PARTY_KEY",
                    f"Party loc key '{key}' doesn't match {{TAG}}_{{ideology}}_party pattern",
                )
                continue

            tag, ideo = m.group(1), m.group(2)
            if tag not in tag_set:
                report.orphan_loc_keys.append(key)
                result.add_warning(
                    "ORPHAN_PARTY_KEY_BAD_TAG",
                    f"Party loc key '{key}' references unknown tag '{tag}'",
                )
            elif ideo not in ideo_set:
                report.orphan_loc_keys.append(key)
                result.add_warning(
                    "ORPHAN_PARTY_KEY_BAD_IDEOLOGY",
                    f"Party loc key '{key}' references unknown ideology '{ideo}'",
                )

    def _detect_history_missing_loc(
        self,
        history_parties: list[tuple[str, str, str]],
        all_loc: dict[str, str],
        report: PartyGapReport,
        result: ValidationResult,
    ) -> None:
        for filename, ideology, loc_key in history_parties:
            if loc_key not in all_loc:
                report.missing_loc_from_history.append((filename, ideology, loc_key))
                result.add_warning(
                    "HISTORY_PARTY_MISSING_LOC",
                    f"{filename}: set_party_name references '{loc_key}' but no loc entry found",
                )
