"""
ModScanner — 아무 HOI4 모드 폴더를 자동 스캔하여 전체 구조를 파악한다.

descriptor.mod 위치를 기준으로 모드 루트를 결정하고,
캐릭터·국가·이벤트·포커스·이념 등 모든 엔티티를 경량 regex로 빠르게 수집한다.
결과는 ModContext에 담겨 동적 시스템 프롬프트 생성에 쓰인다.
"""
from __future__ import annotations

import os
import re
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from loguru import logger


# =====================================================================
# ModContext — 스캔 결과 전체를 담는 컨테이너
# =====================================================================

@dataclass
class CharacterInfo:
    char_id: str
    file: str
    country_tag: str = ""
    roles: list[str] = field(default_factory=list)      # country_leader, corps_commander, advisor …
    ideology: str = ""
    portrait: str = ""


@dataclass
class CountryInfo:
    tag: str
    name: str = ""
    history_file: str = ""
    capital: str = ""
    ruling_ideology: str = ""
    characters: list[str] = field(default_factory=list)  # recruit_character 에서 수집
    oob: str = ""


@dataclass
class EventInfo:
    event_id: str
    event_type: str  # country_event, news_event …
    file: str
    has_title: bool = False
    option_count: int = 0


@dataclass
class FocusTreeInfo:
    tree_id: str
    file: str
    country: str = ""
    focus_count: int = 0


@dataclass
class ModContext:
    """모드 전체 컨텍스트. 스캔 결과를 담는다."""
    root: Path = field(default_factory=Path)

    # 메타
    mod_name: str = ""
    mod_version: str = ""
    supported_version: str = ""
    mod_tags: list[str] = field(default_factory=list)
    replace_paths: list[str] = field(default_factory=list)

    # 엔티티
    countries: dict[str, CountryInfo] = field(default_factory=dict)
    characters: dict[str, CharacterInfo] = field(default_factory=dict)
    events: list[EventInfo] = field(default_factory=list)
    focus_trees: list[FocusTreeInfo] = field(default_factory=list)
    ideas: list[str] = field(default_factory=list)
    decisions: list[str] = field(default_factory=list)
    ideology_groups: dict[str, list[str]] = field(default_factory=dict)  # group → [sub_ideologies]
    loc_languages: list[str] = field(default_factory=list)
    loc_key_count: int = 0
    gfx_sprites: int = 0

    # 파일 조직
    file_counts: dict[str, int] = field(default_factory=dict)  # category → count
    naming_prefix: str = ""           # 파일 접두사 (예: TFR_, KR_ 등)
    naming_conventions: dict[str, str] = field(default_factory=dict)  # 파일 타입 → 패턴
    directory_map: dict[str, dict] = field(default_factory=dict)

    # 통계
    total_files: int = 0
    scan_time_sec: float = 0.0

    # ----- 프롬프트 생성 -----

    def to_prompt(self) -> str:
        """동적 시스템 프롬프트 조각을 생성한다."""
        lines: list[str] = []

        lines.append(f"모드명: {self.mod_name or '(알 수 없음)'}")
        lines.append(f"모드 루트: {self.root}")
        if self.mod_version:
            lines.append(f"버전: {self.mod_version}")
        if self.supported_version:
            lines.append(f"HOI4 지원 버전: {self.supported_version}")

        lines.append("")
        lines.append(f"국가: {len(self.countries)}개")
        if self.countries:
            sample_tags = sorted(self.countries.keys())[:30]
            lines.append(f"  태그 예시: {', '.join(sample_tags)}")

        lines.append(f"캐릭터: {len(self.characters)}개")
        lines.append(f"이벤트: {len(self.events)}개")
        lines.append(f"포커스 트리: {len(self.focus_trees)}개")
        lines.append(f"아이디어: {len(self.ideas)}개")
        lines.append(f"디시전: {len(self.decisions)}개")

        if self.ideology_groups:
            lines.append("")
            lines.append("이념 구조:")
            for group, subs in sorted(self.ideology_groups.items()):
                lines.append(f"  {group}: {', '.join(subs[:8])}")

        if self.naming_prefix:
            lines.append(f"\n파일 접두사: {self.naming_prefix}")
        if self.naming_conventions:
            lines.append("네이밍 컨벤션:")
            for ftype, pattern in sorted(self.naming_conventions.items()):
                lines.append(f"  {ftype}: {pattern}")

        lines.append("")
        lines.append(f"로컬라이제이션: {self.loc_key_count}개 키, 언어 {self.loc_languages}")
        lines.append(f"GFX 스프라이트: {self.gfx_sprites}개")
        lines.append(f"총 모드 파일: {self.total_files}개")

        if self.file_counts:
            lines.append("\n파일 분포:")
            for cat, cnt in sorted(self.file_counts.items(), key=lambda x: -x[1])[:15]:
                lines.append(f"  {cat}: {cnt}개")

        if self.directory_map:
            lines.append("\n디렉토리 구조 (표준 HOI4 폴더):")
            for dir_path in sorted(self.directory_map.keys()):
                dir_data = self.directory_map[dir_path]
                purpose = dir_data.get("purpose", "")
                file_count = dir_data.get("file_count", 0)
                content_type = dir_data.get("content_type", "")
                if purpose:
                    lines.append(f"  {dir_path} → {purpose} ({file_count}개 파일, 타입: {content_type})")

        return "\n".join(lines)

    def to_stats_dict(self) -> dict[str, Any]:
        """사이드바용 통계 딕셔너리."""
        return {
            "모드명": self.mod_name or "(알 수 없음)",
            "국가": len(self.countries),
            "캐릭터": len(self.characters),
            "이벤트": len(self.events),
            "포커스 트리": len(self.focus_trees),
            "이념 그룹": len(self.ideology_groups),
            "로컬 키": self.loc_key_count,
            "총 파일": self.total_files,
            "스캔 시간": f"{self.scan_time_sec:.1f}s",
        }


# =====================================================================
# ModScanner
# =====================================================================

class ModScanner:
    """모드 폴더를 빠르게 스캔하여 ModContext를 구축한다."""

    def scan(self, mod_root: Path) -> ModContext:
        """전체 스캔 실행."""
        t0 = time.time()
        ctx = ModContext(root=mod_root)

        self._scan_descriptor(ctx)
        self._scan_country_tags(ctx)
        self._scan_country_history(ctx)
        self._scan_characters(ctx)
        self._scan_ideologies(ctx)
        self._scan_events(ctx)
        self._scan_focuses(ctx)
        self._scan_ideas(ctx)
        self._scan_decisions(ctx)
        self._scan_localisation(ctx)
        self._scan_gfx(ctx)
        self._scan_directories(ctx)
        self._count_files(ctx)
        self._detect_naming(ctx)

        ctx.scan_time_sec = time.time() - t0
        logger.info(
            "모드 스캔 완료: {} — {}개 국가, {}개 캐릭터, {}개 이벤트 ({:.1f}s)",
            ctx.mod_name, len(ctx.countries), len(ctx.characters),
            len(ctx.events), ctx.scan_time_sec,
        )
        return ctx

    # ------------------------------------------------------------------
    # descriptor.mod
    # ------------------------------------------------------------------

    def _scan_descriptor(self, ctx: ModContext) -> None:
        desc = ctx.root / "descriptor.mod"
        if not desc.exists():
            # 루트에 없으면 *.mod 찾기
            mods = list(ctx.root.glob("*.mod"))
            if mods:
                desc = mods[0]
            else:
                return

        text = desc.read_text(encoding="utf-8-sig", errors="replace")
        m = re.search(r'name\s*=\s*"([^"]+)"', text)
        if m:
            ctx.mod_name = m.group(1)
        m = re.search(r'version\s*=\s*"([^"]+)"', text)
        if m:
            ctx.mod_version = m.group(1)
        m = re.search(r'supported_version\s*=\s*"([^"]+)"', text)
        if m:
            ctx.supported_version = m.group(1)

        tags_match = re.search(r'tags\s*=\s*\{([^}]+)\}', text, re.DOTALL)
        ctx.mod_tags = re.findall(r'"([^"]+)"', tags_match.group(1)) if tags_match else []
        ctx.replace_paths = re.findall(r'replace_path\s*=\s*"([^"]+)"', text)

    # ------------------------------------------------------------------
    # common/country_tags/*.txt — 국가 태그 수집
    # ------------------------------------------------------------------

    def _scan_country_tags(self, ctx: ModContext) -> None:
        tag_dir = ctx.root / "common" / "country_tags"
        if not tag_dir.is_dir():
            return
        for fpath in sorted(tag_dir.glob("*.txt")):
            text = self._read(fpath)
            for m in re.finditer(r'^([A-Z0-9]{3})\s*=\s*"countries/([^"]+)"', text, re.MULTILINE):
                tag, name_file = m.group(1), m.group(2)
                name = name_file.replace(".txt", "")
                if tag not in ctx.countries:
                    ctx.countries[tag] = CountryInfo(tag=tag, name=name)
                else:
                    ctx.countries[tag].name = ctx.countries[tag].name or name

    # ------------------------------------------------------------------
    # history/countries/*.txt — 국가 히스토리
    # ------------------------------------------------------------------

    def _scan_country_history(self, ctx: ModContext) -> None:
        hist_dir = ctx.root / "history" / "countries"
        if not hist_dir.is_dir():
            return
        for fpath in sorted(hist_dir.glob("*.txt")):
            text = self._read(fpath)
            rel = str(fpath.relative_to(ctx.root))

            # 파일명에서 태그 추출: "USA - United States.txt" → "USA"
            tag_m = re.match(r"^([A-Z0-9]{2,4})\s*-", fpath.stem)
            if not tag_m:
                continue
            tag = tag_m.group(1)

            if tag not in ctx.countries:
                ctx.countries[tag] = CountryInfo(tag=tag)
            ci = ctx.countries[tag]
            ci.history_file = rel

            # capital
            cm = re.search(r'capital\s*=\s*(\d+)', text)
            if cm:
                ci.capital = cm.group(1)

            # ruling ideology
            im = re.search(r'ruling_party\s*=\s*(\w+)', text)
            if im:
                ci.ruling_ideology = im.group(1)

            # oob
            om = re.search(r'(?:set_)?oob\s*=\s*"([^"]+)"', text)
            if om:
                ci.oob = om.group(1)

            # recruit_character
            for rm in re.finditer(r'recruit_character\s*=\s*(\w+)', text):
                ci.characters.append(rm.group(1))

    # ------------------------------------------------------------------
    # common/characters/*.txt — 캐릭터
    # ------------------------------------------------------------------

    def _scan_characters(self, ctx: ModContext) -> None:
        char_dir = ctx.root / "common" / "characters"
        if not char_dir.is_dir():
            return
        for fpath in sorted(char_dir.glob("*.txt")):
            text = self._read(fpath)
            rel = str(fpath.relative_to(ctx.root))

            # 파일명에서 국가 태그 추출 시도
            file_tag = self._guess_tag_from_filename(fpath.stem)

            # 캐릭터 ID 패턴: TAG_name_char = { 또는 최상위 블록 내 ID = {
            for m in re.finditer(r'^\t(\w+)\s*=\s*\{', text, re.MULTILINE):
                cid = m.group(1)
                if cid in ("characters", "portraits", "civilian", "army", "navy"):
                    continue

                char = CharacterInfo(char_id=cid, file=rel)
                char.country_tag = file_tag or cid.split("_")[0] if "_" in cid else ""

                # 블록 내용 추출 (경량)
                block = self._extract_block(text, m.start())

                # 역할 탐지
                if "country_leader" in block:
                    char.roles.append("country_leader")
                if "corps_commander" in block:
                    char.roles.append("corps_commander")
                if "field_marshal" in block:
                    char.roles.append("field_marshal")
                if "navy_leader" in block:
                    char.roles.append("navy_leader")
                if "advisor" in block:
                    char.roles.append("advisor")

                # ideology
                ideo_m = re.search(r'ideology\s*=\s*(\w+)', block)
                if ideo_m:
                    char.ideology = ideo_m.group(1)

                # portrait
                port_m = re.search(r'large\s*=\s*"([^"]+)"', block)
                if port_m:
                    char.portrait = port_m.group(1)

                ctx.characters[cid] = char

    # ------------------------------------------------------------------
    # common/ideologies/*.txt — 이념 그룹 + 하위 이념
    # ------------------------------------------------------------------

    def _scan_ideologies(self, ctx: ModContext) -> None:
        ideo_dir = ctx.root / "common" / "ideologies"
        if not ideo_dir.is_dir():
            return
        for fpath in sorted(ideo_dir.glob("*.txt")):
            text = self._read(fpath)
            # 최상위: ideologies = { group = { types = { sub = { ... } } } }
            # 단순화: 들여쓰기 1탭 = 그룹, types 내부 = 서브이념
            current_group = ""
            in_types = False
            for line in text.splitlines():
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue

                # 그룹 레벨 (탭 1개)
                gm = re.match(r'^\t(\w+)\s*=\s*\{', line)
                if gm and gm.group(1) not in ("ideologies",):
                    current_group = gm.group(1)
                    if current_group not in ctx.ideology_groups:
                        ctx.ideology_groups[current_group] = []
                    in_types = False
                    continue

                if "types" in stripped and "=" in stripped and "{" in stripped:
                    in_types = True
                    continue

                # 서브이념 (탭 3개 안쪽)
                if in_types and current_group:
                    sm = re.match(r'^\t{3}(\w+)\s*=\s*\{', line)
                    if sm:
                        ctx.ideology_groups[current_group].append(sm.group(1))

                if stripped == "}" and in_types:
                    # types 블록 끝일 수도
                    pass

    # ------------------------------------------------------------------
    # events/*.txt — 이벤트
    # ------------------------------------------------------------------

    def _scan_events(self, ctx: ModContext) -> None:
        ev_dir = ctx.root / "events"
        if not ev_dir.is_dir():
            return
        for fpath in sorted(ev_dir.glob("*.txt")):
            text = self._read(fpath)
            rel = str(fpath.relative_to(ctx.root))

            for m in re.finditer(
                r'(country_event|news_event|state_event|unit_leader_event)\s*=\s*\{',
                text,
            ):
                etype = m.group(1)
                block = self._extract_block(text, m.start())
                eid_m = re.search(r'id\s*=\s*([\w.]+)', block)
                if not eid_m:
                    continue
                opts = len(re.findall(r'option\s*=\s*\{', block))
                ctx.events.append(EventInfo(
                    event_id=eid_m.group(1),
                    event_type=etype,
                    file=rel,
                    has_title="title" in block,
                    option_count=opts,
                ))

    # ------------------------------------------------------------------
    # common/national_focus/*.txt — 포커스 트리
    # ------------------------------------------------------------------

    def _scan_focuses(self, ctx: ModContext) -> None:
        foc_dir = ctx.root / "common" / "national_focus"
        if not foc_dir.is_dir():
            return
        for fpath in sorted(foc_dir.glob("*.txt")):
            text = self._read(fpath)
            rel = str(fpath.relative_to(ctx.root))

            for m in re.finditer(r'focus_tree\s*=\s*\{', text):
                block = self._extract_block(text, m.start())
                tid_m = re.search(r'\bid\s*=\s*(\w+)', block)
                country_m = re.search(r'country\s*=\s*\{[^}]*tag\s*=\s*(\w+)', block, re.DOTALL)
                fcount = len(re.findall(r'^\t\tfocus\s*=\s*\{', block, re.MULTILINE))
                if not fcount:
                    fcount = len(re.findall(r'\bfocus\s*=\s*\{', block))
                ctx.focus_trees.append(FocusTreeInfo(
                    tree_id=tid_m.group(1) if tid_m else fpath.stem,
                    file=rel,
                    country=country_m.group(1) if country_m else "",
                    focus_count=fcount,
                ))

    # ------------------------------------------------------------------
    # common/ideas/*.txt — 아이디어
    # ------------------------------------------------------------------

    def _scan_ideas(self, ctx: ModContext) -> None:
        idea_dir = ctx.root / "common" / "ideas"
        if not idea_dir.is_dir():
            return
        for fpath in sorted(idea_dir.glob("*.txt")):
            text = self._read(fpath)
            # idea 토큰: 탭2 레벨의 ID = {
            for m in re.finditer(r'^\t{2}(\w+)\s*=\s*\{', text, re.MULTILINE):
                token = m.group(1)
                if token not in ("modifier", "targeted_modifier", "research_bonus",
                                 "equipment_bonus", "on_add", "on_remove", "rule",
                                 "cancel", "allowed", "available", "visible"):
                    ctx.ideas.append(token)

    # ------------------------------------------------------------------
    # common/decisions/*.txt — 디시전
    # ------------------------------------------------------------------

    def _scan_decisions(self, ctx: ModContext) -> None:
        dec_dir = ctx.root / "common" / "decisions"
        if not dec_dir.is_dir():
            return
        for fpath in sorted(dec_dir.glob("**/*.txt")):
            text = self._read(fpath)
            for m in re.finditer(r'^\t(\w+)\s*=\s*\{', text, re.MULTILINE):
                token = m.group(1)
                if token not in ("icon", "allowed", "available", "visible",
                                 "complete_effect", "remove_effect", "modifier",
                                 "ai_will_do", "cost", "fire_only_once", "cancel_trigger"):
                    ctx.decisions.append(token)

    # ------------------------------------------------------------------
    # localisation/ — 로컬라이제이션
    # ------------------------------------------------------------------

    def _scan_localisation(self, ctx: ModContext) -> None:
        loc_root = ctx.root / "localisation"
        if not loc_root.is_dir():
            return

        langs: set[str] = set()
        key_count = 0

        # languages.yml 확인
        lang_file = loc_root / "languages.yml"
        if lang_file.exists():
            for m in re.finditer(r'^\s*l_(\w+):', lang_file.read_text(errors="replace"), re.MULTILINE):
                langs.add(m.group(1))

        for fpath in loc_root.rglob("*.yml"):
            text = self._read(fpath)
            # 언어 헤더
            lm = re.search(r'l_(\w+):', text)
            if lm:
                langs.add(lm.group(1))
            # 키 카운트 (key:0 "value" 패턴)
            key_count += len(re.findall(r'^\s*\w+:\d+\s+"', text, re.MULTILINE))

        ctx.loc_languages = sorted(langs)
        ctx.loc_key_count = key_count

    # ------------------------------------------------------------------
    # interface/*.gfx — GFX 스프라이트
    # ------------------------------------------------------------------

    def _scan_gfx(self, ctx: ModContext) -> None:
        iface_dir = ctx.root / "interface"
        if not iface_dir.is_dir():
            return
        count = 0
        for fpath in iface_dir.glob("*.gfx"):
            text = self._read(fpath)
            count += len(re.findall(r'spriteType\s*=\s*\{', text, re.IGNORECASE))
        ctx.gfx_sprites = count

    # ------------------------------------------------------------------
    # 파일 수 집계
    # ------------------------------------------------------------------

    def _count_files(self, ctx: ModContext) -> None:
        total = 0
        counts: dict[str, int] = defaultdict(int)
        skip = {".git", ".venv", "__pycache__", "tools", ".omc", ".omx", ".claude", ".cache"}

        for fpath in ctx.root.rglob("*"):
            if fpath.is_dir():
                continue
            parts = set(fpath.relative_to(ctx.root).parts)
            if parts & skip:
                continue
            total += 1
            # 카테고리: 첫 번째 디렉토리
            rel_parts = fpath.relative_to(ctx.root).parts
            if len(rel_parts) >= 2:
                cat = f"{rel_parts[0]}/{rel_parts[1]}"
            else:
                cat = rel_parts[0] if rel_parts else "(root)"
            counts[cat] += 1

        ctx.total_files = total
        ctx.file_counts = dict(counts)

    # ------------------------------------------------------------------
    # 네이밍 컨벤션 자동 탐지
    # ------------------------------------------------------------------

    def _detect_naming(self, ctx: ModContext) -> None:
        # 캐릭터 파일 접두사 탐지
        char_dir = ctx.root / "common" / "characters"
        if char_dir.is_dir():
            prefixes = Counter()
            for f in char_dir.glob("*.txt"):
                parts = f.stem.split("_")
                if len(parts) >= 2:
                    prefixes[parts[0]] += 1
            if prefixes:
                top_prefix = prefixes.most_common(1)[0][0]
                ctx.naming_prefix = top_prefix
                ctx.naming_conventions["characters"] = f"{top_prefix}_characters_TAG.txt"

        # 이벤트 파일 패턴
        ev_dir = ctx.root / "events"
        if ev_dir.is_dir():
            ev_prefixes = Counter()
            for f in ev_dir.glob("*.txt"):
                parts = f.stem.split("_")
                if len(parts) >= 2:
                    ev_prefixes[parts[0]] += 1
            if ev_prefixes:
                top = ev_prefixes.most_common(1)[0][0]
                ctx.naming_conventions["events"] = f"{top}_events_TAG.txt"

        # 포커스 파일 패턴
        foc_dir = ctx.root / "common" / "national_focus"
        if foc_dir.is_dir():
            foc_prefixes = Counter()
            for f in foc_dir.glob("*.txt"):
                parts = f.stem.split("_")
                if len(parts) >= 2:
                    foc_prefixes[parts[0]] += 1
            if foc_prefixes:
                top = foc_prefixes.most_common(1)[0][0]
                ctx.naming_conventions["focuses"] = f"{top}_focus_TAG.txt"

    def _scan_directories(self, ctx: ModContext) -> None:
        from hoi4_agent.core.hoi4_schema import get_directory_info
        
        for dirpath, dirnames, filenames in os.walk(ctx.root):
            rel_path = Path(dirpath).relative_to(ctx.root)
            
            if rel_path == Path("."):
                continue
            
            dir_key = str(rel_path).replace("\\", "/") + "/"
            
            dir_info = get_directory_info(dir_key)
            if dir_info:
                ctx.directory_map[dir_key] = {
                    "path": dir_key,
                    "purpose": dir_info.get("purpose", ""),
                    "description": dir_info.get("description", ""),
                    "content_type": dir_info.get("content_type", ""),
                    "file_pattern": dir_info.get("file_pattern", ""),
                    "file_count": len(filenames),
                    "subdir_count": len(dirnames),
                }

    # ------------------------------------------------------------------
    # 유틸리티
    # ------------------------------------------------------------------

    @staticmethod
    def _read(fpath: Path, limit: int = 500_000) -> str:
        """파일을 빠르게 읽되 너무 큰 파일은 자른다."""
        try:
            text = fpath.read_text(encoding="utf-8-sig", errors="replace")
            return text[:limit]
        except Exception:
            return ""

    @staticmethod
    def _extract_block(text: str, start: int, max_len: int = 50_000) -> str:
        """start 위치의 { 부터 매칭되는 } 까지 추출."""
        brace_pos = text.find("{", start)
        if brace_pos == -1:
            return ""
        depth = 0
        i = brace_pos
        end = min(len(text), brace_pos + max_len)
        while i < end:
            ch = text[i]
            if ch == "#":
                # 주석 건너뛰기
                nl = text.find("\n", i)
                i = nl + 1 if nl != -1 else end
                continue
            if ch == '"':
                # 문자열 건너뛰기
                i += 1
                while i < end and text[i] != '"':
                    if text[i] == "\\":
                        i += 1
                    i += 1
                i += 1
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start:i + 1]
            i += 1
        return text[start:end]

    @staticmethod
    def _guess_tag_from_filename(stem: str) -> str:
        """파일명에서 국가 태그를 추측한다. 예: TFR_characters_USA → USA"""
        parts = stem.split("_")
        for part in reversed(parts):
            if re.match(r'^[A-Z]{3}$', part):
                return part
        return ""


# =====================================================================
# 편의 함수
# =====================================================================

def find_mod_root(start: Path | None = None) -> Path | None:
    """
    descriptor.mod 를 찾아서 모드 루트를 결정한다.
    start 가 None 이면 CWD 부터 위로 탐색.
    """
    if start is None:
        start = Path.cwd()

    # 현재 디렉토리에 descriptor.mod 가 있으면 바로 반환
    if (start / "descriptor.mod").exists():
        return start

    # *.mod 파일이 있으면 반환
    mods = list(start.glob("*.mod"))
    if mods:
        return start

    # 상위로 탐색 (최대 5단계)
    current = start
    for _ in range(5):
        current = current.parent
        if (current / "descriptor.mod").exists():
            return current
        if list(current.glob("*.mod")):
            return current

    return None


    def _scan_directories(self, ctx: ModContext) -> None:
        from hoi4_agent.core.hoi4_schema import get_directory_info
        
        for dirpath, dirnames, filenames in os.walk(ctx.root):
            rel_path = Path(dirpath).relative_to(ctx.root)
            
            if rel_path == Path("."):
                continue
            
            dir_key = str(rel_path).replace("\\", "/") + "/"
            
            dir_info = get_directory_info(dir_key)
            if dir_info:
                ctx.directory_map[dir_key] = {
                    "path": dir_key,
                    "purpose": dir_info.get("purpose", ""),
                    "description": dir_info.get("description", ""),
                    "content_type": dir_info.get("content_type", ""),
                    "file_pattern": dir_info.get("file_pattern", ""),
                    "file_count": len(filenames),
                    "subdir_count": len(dirnames),
                }
