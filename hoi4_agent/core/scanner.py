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


def detect_mod_prefix(mod_root: Path) -> str:
    """모드 파일 접두사를 감지한다."""
    all_prefixes = Counter()
    
    for file_path in mod_root.rglob("*"):
        if file_path.is_file() and file_path.suffix in {".txt", ".yml", ".gfx"}:
            parts = file_path.stem.split("_")
            if len(parts) >= 2 and parts[0].isupper() and len(parts[0]) <= 6:
                all_prefixes[parts[0]] += 1
    
    if all_prefixes:
        return all_prefixes.most_common(1)[0][0]
    
    return "MOD"


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
class ProvinceInfo:
    province_id: int
    rgb: tuple[int, int, int]
    terrain: str  # desert, forest, plains, mountain, hills, marsh, ocean, etc.
    is_coastal: bool
    province_type: str  # land, sea


@dataclass
class StateInfo:
    state_id: int
    name: str
    file: str
    owner: str = ""
    manpower: int = 0
    provinces: list[int] = field(default_factory=list)
    victory_points: dict[int, int] = field(default_factory=dict)  # province_id -> vp_value
    infrastructure: int = 0
    state_category: str = ""


@dataclass
class TechnologyInfo:
    tech_id: str
    file: str
    research_cost: float = 0.0
    start_year: int = 0
    prerequisites: list[str] = field(default_factory=list)  # leads_to_tech
    folder: str = ""
    categories: list[str] = field(default_factory=list)


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
    ideology_groups: dict[str, list[str]] = field(default_factory=dict)
    provinces: dict[int, ProvinceInfo] = field(default_factory=dict)
    states: dict[int, StateInfo] = field(default_factory=dict)
    technologies: list[TechnologyInfo] = field(default_factory=list)
    loc_languages: list[str] = field(default_factory=list)
    loc_key_count: int = 0
    gfx_sprites: int = 0

    # Phase 1: 최우선 (모드/맵/인터페이스/히스토리)
    game_rules: list[str] = field(default_factory=list)
    difficulty_settings: list[str] = field(default_factory=list)
    map_modes: list[str] = field(default_factory=list)
    bookmarks: list[str] = field(default_factory=list)
    scripted_effects: list[str] = field(default_factory=list)
    scripted_triggers: list[str] = field(default_factory=list)
    history_units: dict[str, int] = field(default_factory=dict)  # country_tag -> unit_count
    history_generals: list[str] = field(default_factory=list)
    map_strategic_regions: int = 0
    map_buildings: dict = field(default_factory=dict)  # {"file_size": ..., "line_count": ...}
    map_railways: dict = field(default_factory=dict)
    map_supply_areas: int = 0
    interface_gui: list[str] = field(default_factory=list)
    portraits_data: list[str] = field(default_factory=list)
    
    # Phase 2: 중요 (common/ 나머지)
    scripted_localisation: list[str] = field(default_factory=list)
    scripted_guis: list[str] = field(default_factory=list)
    units: list[str] = field(default_factory=list)
    ai_strategy_plans: list[str] = field(default_factory=list)
    ai_strategy: list[str] = field(default_factory=list)
    on_actions: list[str] = field(default_factory=list)
    dynamic_modifiers: list[str] = field(default_factory=list)
    factions: list[str] = field(default_factory=list)
    ai_equipment: list[str] = field(default_factory=list)
    doctrines: list[str] = field(default_factory=list)
    military_industrial_organization: list[str] = field(default_factory=list)
    ai_templates: list[str] = field(default_factory=list)
    autonomous_states: list[str] = field(default_factory=list)
    scripted_diplomatic_actions: list[str] = field(default_factory=list)
    
    # Phase 3: 표준 (통합 스캔)
    generic_common_scans: dict[str, dict] = field(default_factory=dict)  # folder_name -> {count, sample_keys}
    map_other_files: dict[str, dict] = field(default_factory=dict)  # filename -> metadata

    # 파일 조직
    file_counts: dict[str, int] = field(default_factory=dict)  # category → count
    naming_prefix: str = ""           # 파일 접두사 (예: TFR_, KR_ 등)
    naming_conventions: dict[str, str] = field(default_factory=dict)  # 파일 타입 → 패턴
    directory_map: dict[str, dict] = field(default_factory=dict)

    # 통계
    total_files: int = 0
    scan_time_sec: float = 0.0

    # ----- 프롬프트 생성 -----
    _cached_prompt: str | None = None
    
    def cached_to_prompt(self) -> str:
        """캐싱된 프롬프트 반환. 파일 쓰기 시 cache_clear() 호출."""
        if self._cached_prompt is None:
            self._cached_prompt = self.to_prompt()
        return self._cached_prompt
    
    def cache_clear(self) -> None:
        """프롬프트 캐시 무효화 (파일 쓰기 후 호출)."""
        self._cached_prompt = None

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
        lines.append(f"프로빈스: {len(self.provinces)}개")
        lines.append(f"스테이트: {len(self.states)}개")
        lines.append(f"테크놀로지: {len(self.technologies)}개")
        
        if self.game_rules:
            lines.append(f"게임 룰: {len(self.game_rules)}개")
        if self.difficulty_settings:
            lines.append(f"난이도 설정: {len(self.difficulty_settings)}개")
        if self.map_modes:
            lines.append(f"맵 모드: {len(self.map_modes)}개")
        if self.bookmarks:
            lines.append(f"북마크: {len(self.bookmarks)}개")
        if self.scripted_effects:
            lines.append(f"스크립트 효과: {len(self.scripted_effects)}개")
        if self.scripted_triggers:
            lines.append(f"스크립트 트리거: {len(self.scripted_triggers)}개")
        if self.history_units:
            lines.append(f"히스토리 부대: {sum(self.history_units.values())}개 (국가 {len(self.history_units)}개)")
        if self.map_strategic_regions > 0:
            lines.append(f"전략 지역: {self.map_strategic_regions}개")
        if self.interface_gui:
            lines.append(f"GUI 윈도우: {len(self.interface_gui)}개")
        if self.portraits_data:
            lines.append(f"포트레잇 타입: {len(self.portraits_data)}개")
        
        if self.scripted_localisation:
            lines.append(f"스크립트 지역화: {len(self.scripted_localisation)}개")
        if self.scripted_guis:
            lines.append(f"스크립트 GUI: {len(self.scripted_guis)}개")
        if self.units:
            lines.append(f"유닛 타입: {len(self.units)}개")
        if self.ai_strategy_plans:
            lines.append(f"AI 전략 계획: {len(self.ai_strategy_plans)}개")
        if self.factions:
            lines.append(f"팩션: {len(self.factions)}개")
        
        if self.generic_common_scans:
            lines.append(f"\n기타 common/ 폴더: {len(self.generic_common_scans)}개")
            for folder, data in sorted(self.generic_common_scans.items())[:10]:
                lines.append(f"  {folder}: {data['file_count']}개 파일")

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
        self._scan_map_provinces(ctx)
        self._scan_states(ctx)
        self._scan_technologies(ctx)
        self._scan_localisation(ctx)
        self._scan_gfx(ctx)
        
        # Phase 1: 최우선
        self._scan_game_rules(ctx)
        self._scan_difficulty_settings(ctx)
        self._scan_map_modes(ctx)
        self._scan_bookmarks(ctx)
        self._scan_scripted_effects(ctx)
        self._scan_scripted_triggers(ctx)
        self._scan_history_units(ctx)
        self._scan_history_generals(ctx)
        self._scan_map_strategic_regions(ctx)
        self._scan_map_buildings(ctx)
        self._scan_map_railways(ctx)
        self._scan_map_supply_areas(ctx)
        self._scan_interface_gui(ctx)
        self._scan_portraits(ctx)
        
        # Phase 2: 중요
        self._scan_scripted_localisation(ctx)
        self._scan_scripted_guis(ctx)
        self._scan_units(ctx)
        self._scan_ai_strategy_plans(ctx)
        self._scan_ai_strategy(ctx)
        self._scan_on_actions(ctx)
        self._scan_dynamic_modifiers(ctx)
        self._scan_factions(ctx)
        self._scan_ai_equipment(ctx)
        self._scan_doctrines(ctx)
        self._scan_military_industrial_organization(ctx)
        self._scan_ai_templates(ctx)
        self._scan_autonomous_states(ctx)
        self._scan_scripted_diplomatic_actions(ctx)
        
        # Phase 3: 표준
        self._scan_generic_common_folders(ctx)
        self._scan_map_other_files(ctx)
        
        self._scan_directories(ctx)
        self._count_files(ctx)
        self._detect_naming(ctx)

        ctx.scan_time_sec = time.time() - t0
        logger.info(
            "모드 스캔 완료: {} — {}개 국가, {}개 캐릭터, {}개 이벤트, {}개 프로빈스, {}개 스테이트, {}개 테크 ({:.1f}s)",
            ctx.mod_name, len(ctx.countries), len(ctx.characters),
            len(ctx.events), len(ctx.provinces), len(ctx.states), len(ctx.technologies), ctx.scan_time_sec,
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
        for fpath in sorted(tag_dir.rglob("*.txt")):
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
        for fpath in sorted(hist_dir.rglob("*.txt")):
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
        for fpath in sorted(char_dir.rglob("*.txt")):
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
        for fpath in sorted(ideo_dir.rglob("*.txt")):
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
        for fpath in sorted(ev_dir.rglob("*.txt")):
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
        for fpath in sorted(foc_dir.rglob("*.txt")):
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
        for fpath in sorted(idea_dir.rglob("*.txt")):
            text = self._read(fpath)
            # idea 토큰: 탭2 레벨의 ID = {
            for m in re.finditer(r'^\t{2}(\w+)\s*=\s*\{', text, re.MULTILINE):
                token = m.group(1)
                if token not in ("modifier", "targeted_modifier", "research_bonus",
                                 "equipment_bonus", "on_add", "on_remove", "rule",
                                 "cancel", "allowed", "available", "visible"):
                    ctx.ideas.append(token)

    # ------------------------------------------------------------------
    # decisions
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
    # map/definition.csv — province definitions
    # ------------------------------------------------------------------

    def _scan_map_provinces(self, ctx: ModContext) -> None:
        def_csv = ctx.root / "map" / "definition.csv"
        if not def_csv.exists():
            return
        
        try:
            text = def_csv.read_text(encoding="utf-8-sig", errors="replace")
            for line in text.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                
                parts = line.split(";")
                if len(parts) < 6:
                    continue
                
                try:
                    prov_id = int(parts[0])
                    r, g, b = int(parts[1]), int(parts[2]), int(parts[3])
                    prov_type = parts[4] if len(parts) > 4 else "land"
                    coastal = parts[5].lower() == "true" if len(parts) > 5 else False
                    terrain = parts[6] if len(parts) > 6 else "unknown"
                    
                    ctx.provinces[prov_id] = ProvinceInfo(
                        province_id=prov_id,
                        rgb=(r, g, b),
                        terrain=terrain,
                        is_coastal=coastal,
                        province_type=prov_type,
                    )
                except (ValueError, IndexError):
                    continue
        except Exception as e:
            logger.warning(f"map/definition.csv 읽기 실패: {e}")

    # ------------------------------------------------------------------
    # history/states/*.txt — state definitions
    # ------------------------------------------------------------------

    def _scan_states(self, ctx: ModContext) -> None:
        states_dir = ctx.root / "history" / "states"
        if not states_dir.is_dir():
            return
        
        for fpath in sorted(states_dir.rglob("*.txt")):
            text = self._read(fpath)
            rel = str(fpath.relative_to(ctx.root))
            
            id_m = re.search(r'\bid\s*=\s*(\d+)', text)
            if not id_m:
                continue
            
            state_id = int(id_m.group(1))
            name_m = re.search(r'name\s*=\s*"([^"]+)"', text)
            owner_m = re.search(r'owner\s*=\s*(\w+)', text)
            manpower_m = re.search(r'manpower\s*=\s*(\d+)', text)
            category_m = re.search(r'state_category\s*=\s*(\w+)', text)
            
            provinces_m = re.search(r'provinces\s*=\s*\{([^\}]+)\}', text)
            provinces_list = []
            if provinces_m:
                provinces_list = [int(p) for p in provinces_m.group(1).split() if p.isdigit()]
            
            vp_dict = {}
            for vp_m in re.finditer(r'victory_points\s*=\s*\{\s*(\d+)\s+(\d+)\s*\}', text):
                vp_dict[int(vp_m.group(1))] = int(vp_m.group(2))
            
            infra_m = re.search(r'infrastructure\s*=\s*(\d+)', text)
            
            ctx.states[state_id] = StateInfo(
                state_id=state_id,
                name=name_m.group(1) if name_m else f"STATE_{state_id}",
                file=rel,
                owner=owner_m.group(1) if owner_m else "",
                manpower=int(manpower_m.group(1)) if manpower_m else 0,
                provinces=provinces_list,
                victory_points=vp_dict,
                infrastructure=int(infra_m.group(1)) if infra_m else 0,
                state_category=category_m.group(1) if category_m else "",
            )

    # ------------------------------------------------------------------
    # common/technologies/*.txt — technology trees
    # ------------------------------------------------------------------

    def _scan_technologies(self, ctx: ModContext) -> None:
        tech_dir = ctx.root / "common" / "technologies"
        if not tech_dir.is_dir():
            return
        
        for fpath in sorted(tech_dir.rglob("*.txt")):
            text = self._read(fpath)
            rel = str(fpath.relative_to(ctx.root))
            
            for m in re.finditer(r'^\t(\w+)\s*=\s*\{', text, re.MULTILINE):
                tech_id = m.group(1)
                if tech_id in ("technologies", "folder", "categories", "path", 
                               "enable_equipments", "enable_subunits"):
                    continue
                
                block = self._extract_block(text, m.start())
                
                cost_m = re.search(r'research_cost\s*=\s*([\d.]+)', block)
                year_m = re.search(r'start_year\s*=\s*(\d+)', block)
                folder_m = re.search(r'folder\s*=\s*\{[^}]*name\s*=\s*(\w+)', block, re.DOTALL)
                
                prereqs = []
                for path_m in re.finditer(r'leads_to_tech\s*=\s*(\w+)', block):
                    prereqs.append(path_m.group(1))
                
                categories = []
                cat_block_m = re.search(r'categories\s*=\s*\{([^\}]+)\}', block)
                if cat_block_m:
                    categories = [c.strip() for c in cat_block_m.group(1).split() if c.strip()]
                
                ctx.technologies.append(TechnologyInfo(
                    tech_id=tech_id,
                    file=rel,
                    research_cost=float(cost_m.group(1)) if cost_m else 0.0,
                    start_year=int(year_m.group(1)) if year_m else 0,
                    prerequisites=prereqs,
                    folder=folder_m.group(1) if folder_m else "",
                    categories=categories,
                ))

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
        for fpath in iface_dir.rglob("*.gfx"):
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
        top_prefix = detect_mod_prefix(ctx.root)
        ctx.naming_prefix = top_prefix
        logger.info(f"모드 접두사 감지: {top_prefix}")
        
        ctx.naming_conventions["characters"] = f"{top_prefix}_characters_TAG.txt"
        ctx.naming_conventions["events"] = f"{top_prefix}_events_TAG.txt"
        ctx.naming_conventions["focuses"] = f"{top_prefix}_focus_TAG.txt"
        ctx.naming_conventions["ideologies"] = f"{top_prefix}_ideologies.txt"
        ctx.naming_conventions["parties"] = f"{top_prefix}_parties_l_english.yml"
        ctx.naming_conventions["portraits_gfx"] = f"{top_prefix}_portraits.gfx"

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
        parts = stem.split("_")
        for part in reversed(parts):
            if re.match(r'^[A-Z]{3}$', part):
                return part
        return ""

    def _scan_game_rules(self, ctx: ModContext) -> None:
        rule_dir = ctx.root / "common" / "game_rules"
        if not rule_dir.is_dir():
            return
        for fpath in sorted(rule_dir.rglob("*.txt")):
            text = self._read(fpath)
            for m in re.finditer(r'^(\w+)\s*=\s*\{', text, re.MULTILINE):
                token = m.group(1)
                if token not in ("ideologies",):
                    ctx.game_rules.append(token)

    def _scan_difficulty_settings(self, ctx: ModContext) -> None:
        diff_dir = ctx.root / "common" / "difficulty_settings"
        if not diff_dir.is_dir():
            return
        for fpath in sorted(diff_dir.rglob("*.txt")):
            text = self._read(fpath)
            for m in re.finditer(r'difficulty_setting\s*=\s*\{', text):
                block = self._extract_block(text, m.start())
                key_m = re.search(r'key\s*=\s*"([^"]+)"', block)
                if key_m:
                    ctx.difficulty_settings.append(key_m.group(1))

    def _scan_map_modes(self, ctx: ModContext) -> None:
        mode_dir = ctx.root / "common" / "map_modes"
        if not mode_dir.is_dir():
            return
        for fpath in sorted(mode_dir.rglob("*.txt")):
            text = self._read(fpath)
            for m in re.finditer(r'^\t(\w+)\s*=\s*\{', text, re.MULTILINE):
                ctx.map_modes.append(m.group(1))

    def _scan_bookmarks(self, ctx: ModContext) -> None:
        bm_dir = ctx.root / "common" / "bookmarks"
        if not bm_dir.is_dir():
            return
        for fpath in sorted(bm_dir.rglob("*.txt")):
            text = self._read(fpath)
            for m in re.finditer(r'bookmark\s*=\s*\{', text):
                block = self._extract_block(text, m.start())
                name_m = re.search(r'name\s*=\s*"([^"]+)"', block)
                if name_m:
                    ctx.bookmarks.append(name_m.group(1))

    def _scan_scripted_effects(self, ctx: ModContext) -> None:
        eff_dir = ctx.root / "common" / "scripted_effects"
        if not eff_dir.is_dir():
            return
        for fpath in sorted(eff_dir.rglob("*.txt")):
            text = self._read(fpath)
            for m in re.finditer(r'^(\w+)\s*=\s*\{', text, re.MULTILINE):
                ctx.scripted_effects.append(m.group(1))

    def _scan_scripted_triggers(self, ctx: ModContext) -> None:
        trig_dir = ctx.root / "common" / "scripted_triggers"
        if not trig_dir.is_dir():
            return
        for fpath in sorted(trig_dir.rglob("*.txt")):
            text = self._read(fpath)
            for m in re.finditer(r'^(\w+)\s*=\s*\{', text, re.MULTILINE):
                ctx.scripted_triggers.append(m.group(1))

    def _scan_history_units(self, ctx: ModContext) -> None:
        units_dir = ctx.root / "history" / "units"
        if not units_dir.is_dir():
            return
        for fpath in sorted(units_dir.rglob("*.txt")):
            tag = self._guess_tag_from_filename(fpath.stem)
            if not tag:
                continue
            text = self._read(fpath)
            unit_count = len(re.findall(r'division\s*=\s*\{', text))
            if tag not in ctx.history_units:
                ctx.history_units[tag] = 0
            ctx.history_units[tag] += unit_count

    def _scan_history_generals(self, ctx: ModContext) -> None:
        gen_dir = ctx.root / "history" / "general"
        if not gen_dir.is_dir():
            return
        for fpath in sorted(gen_dir.rglob("*.txt")):
            text = self._read(fpath)
            for m in re.finditer(r'^\t(\w+)\s*=\s*\{', text, re.MULTILINE):
                ctx.history_generals.append(m.group(1))

    def _scan_map_strategic_regions(self, ctx: ModContext) -> None:
        sr_dir = ctx.root / "map" / "strategicregions"
        if not sr_dir.is_dir():
            return
        ctx.map_strategic_regions = len(list(sr_dir.glob("*.txt")))

    def _scan_map_buildings(self, ctx: ModContext) -> None:
        bldg = ctx.root / "map" / "buildings.txt"
        if not bldg.exists():
            return
        ctx.map_buildings["file_size"] = bldg.stat().st_size
        text = self._read(bldg, limit=100_000)
        ctx.map_buildings["line_count"] = len(text.splitlines())

    def _scan_map_railways(self, ctx: ModContext) -> None:
        rail = ctx.root / "map" / "railways.txt"
        if not rail.exists():
            return
        ctx.map_railways["file_size"] = rail.stat().st_size
        text = self._read(rail)
        ctx.map_railways["line_count"] = len(text.splitlines())

    def _scan_map_supply_areas(self, ctx: ModContext) -> None:
        sa_dir = ctx.root / "map" / "supplyareas"
        if not sa_dir.is_dir():
            return
        ctx.map_supply_areas = len(list(sa_dir.glob("*.txt")))

    def _scan_interface_gui(self, ctx: ModContext) -> None:
        iface_dir = ctx.root / "interface"
        if not iface_dir.is_dir():
            return
        for fpath in sorted(iface_dir.rglob("*.gui")):
            text = self._read(fpath)
            for m in re.finditer(r'containerWindowType\s*=\s*\{', text):
                block = self._extract_block(text, m.start())
                name_m = re.search(r'name\s*=\s*"([^"]+)"', block)
                if name_m:
                    ctx.interface_gui.append(name_m.group(1))

    def _scan_portraits(self, ctx: ModContext) -> None:
        port_dir = ctx.root / "portraits"
        if not port_dir.is_dir():
            return
        for fpath in sorted(port_dir.rglob("*.txt")):
            text = self._read(fpath)
            for m in re.finditer(r'^\t(\w+)\s*=\s*\{', text, re.MULTILINE):
                token = m.group(1)
                if token not in ("portraits", "male", "female"):
                    ctx.portraits_data.append(token)

    def _scan_scripted_localisation(self, ctx: ModContext) -> None:
        loc_dir = ctx.root / "common" / "scripted_localisation"
        if not loc_dir.is_dir():
            return
        for fpath in sorted(loc_dir.rglob("*.txt")):
            text = self._read(fpath)
            for m in re.finditer(r'defined_text\s*=\s*\{', text):
                block = self._extract_block(text, m.start())
                name_m = re.search(r'name\s*=\s*(\w+)', block)
                if name_m:
                    ctx.scripted_localisation.append(name_m.group(1))

    def _scan_scripted_guis(self, ctx: ModContext) -> None:
        gui_dir = ctx.root / "common" / "scripted_guis"
        if not gui_dir.is_dir():
            return
        for fpath in sorted(gui_dir.rglob("*.txt")):
            text = self._read(fpath)
            for m in re.finditer(r'scripted_gui\s*=\s*\{', text):
                block = self._extract_block(text, m.start())
                name_m = re.search(r'name\s*=\s*(\w+)', block)
                if name_m:
                    ctx.scripted_guis.append(name_m.group(1))

    def _scan_units(self, ctx: ModContext) -> None:
        units_dir = ctx.root / "common" / "units"
        if not units_dir.is_dir():
            return
        for fpath in sorted(units_dir.rglob("*.txt")):
            text = self._read(fpath)
            for m in re.finditer(r'^\t(sub_unit|equipment|unit)\s*=\s*\{', text, re.MULTILINE):
                block = self._extract_block(text, m.start())
                type_m = re.search(r'type\s*=\s*(\w+)', block)
                if type_m:
                    ctx.units.append(type_m.group(1))

    def _scan_ai_strategy_plans(self, ctx: ModContext) -> None:
        ai_dir = ctx.root / "common" / "ai_strategy_plans"
        if not ai_dir.is_dir():
            return
        for fpath in sorted(ai_dir.rglob("*.txt")):
            text = self._read(fpath)
            for m in re.finditer(r'ai_strategy_plan\s*=\s*\{', text):
                block = self._extract_block(text, m.start())
                name_m = re.search(r'name\s*=\s*(\w+)', block)
                if name_m:
                    ctx.ai_strategy_plans.append(name_m.group(1))

    def _scan_ai_strategy(self, ctx: ModContext) -> None:
        ai_dir = ctx.root / "common" / "ai_strategy"
        if not ai_dir.is_dir():
            return
        for fpath in sorted(ai_dir.rglob("*.txt")):
            text = self._read(fpath)
            for m in re.finditer(r'ai_strategy\s*=\s*\{', text):
                block = self._extract_block(text, m.start())
                id_m = re.search(r'id\s*=\s*"?(\w+)"?', block)
                if id_m:
                    ctx.ai_strategy.append(id_m.group(1))

    def _scan_on_actions(self, ctx: ModContext) -> None:
        on_dir = ctx.root / "common" / "on_actions"
        if not on_dir.is_dir():
            return
        for fpath in sorted(on_dir.rglob("*.txt")):
            text = self._read(fpath)
            for m in re.finditer(r'^(\w+)\s*=\s*\{', text, re.MULTILINE):
                ctx.on_actions.append(m.group(1))

    def _scan_dynamic_modifiers(self, ctx: ModContext) -> None:
        dyn_dir = ctx.root / "common" / "dynamic_modifiers"
        if not dyn_dir.is_dir():
            return
        for fpath in sorted(dyn_dir.rglob("*.txt")):
            text = self._read(fpath)
            for m in re.finditer(r'^(\w+)\s*=\s*\{', text, re.MULTILINE):
                ctx.dynamic_modifiers.append(m.group(1))

    def _scan_factions(self, ctx: ModContext) -> None:
        fac_dir = ctx.root / "common" / "factions"
        if not fac_dir.is_dir():
            return
        for fpath in sorted(fac_dir.rglob("*.txt")):
            text = self._read(fpath)
            for m in re.finditer(r'faction\s*=\s*\{', text):
                block = self._extract_block(text, m.start())
                name_m = re.search(r'name\s*=\s*"([^"]+)"', block)
                if name_m:
                    ctx.factions.append(name_m.group(1))

    def _scan_ai_equipment(self, ctx: ModContext) -> None:
        eq_dir = ctx.root / "common" / "ai_equipment"
        if not eq_dir.is_dir():
            return
        for fpath in sorted(eq_dir.rglob("*.txt")):
            text = self._read(fpath)
            for m in re.finditer(r'^\t(\w+)\s*=\s*\{', text, re.MULTILINE):
                ctx.ai_equipment.append(m.group(1))

    def _scan_doctrines(self, ctx: ModContext) -> None:
        doc_dir = ctx.root / "common" / "technologies"
        if not doc_dir.is_dir():
            return
        for fpath in sorted(doc_dir.rglob("*doctrines*.txt")):
            text = self._read(fpath)
            for m in re.finditer(r'^\t(\w+)\s*=\s*\{', text, re.MULTILINE):
                ctx.doctrines.append(m.group(1))

    def _scan_military_industrial_organization(self, ctx: ModContext) -> None:
        mio_dir = ctx.root / "common" / "military_industrial_organization"
        if not mio_dir.is_dir():
            return
        for fpath in sorted(mio_dir.rglob("*.txt")):
            text = self._read(fpath)
            for m in re.finditer(r'^\t(\w+)\s*=\s*\{', text, re.MULTILINE):
                ctx.military_industrial_organization.append(m.group(1))

    def _scan_ai_templates(self, ctx: ModContext) -> None:
        tmpl_dir = ctx.root / "common" / "ai_templates"
        if not tmpl_dir.is_dir():
            return
        for fpath in sorted(tmpl_dir.rglob("*.txt")):
            text = self._read(fpath)
            for m in re.finditer(r'^\t(\w+)\s*=\s*\{', text, re.MULTILINE):
                ctx.ai_templates.append(m.group(1))

    def _scan_autonomous_states(self, ctx: ModContext) -> None:
        auto_dir = ctx.root / "common" / "autonomous_states"
        if not auto_dir.is_dir():
            return
        for fpath in sorted(auto_dir.rglob("*.txt")):
            text = self._read(fpath)
            for m in re.finditer(r'autonomy_state\s*=\s*\{', text):
                block = self._extract_block(text, m.start())
                id_m = re.search(r'id\s*=\s*(\w+)', block)
                if id_m:
                    ctx.autonomous_states.append(id_m.group(1))

    def _scan_scripted_diplomatic_actions(self, ctx: ModContext) -> None:
        dip_dir = ctx.root / "common" / "scripted_diplomatic_actions"
        if not dip_dir.is_dir():
            return
        for fpath in sorted(dip_dir.rglob("*.txt")):
            text = self._read(fpath)
            for m in re.finditer(r'^\t(\w+)\s*=\s*\{', text, re.MULTILINE):
                ctx.scripted_diplomatic_actions.append(m.group(1))

    def _scan_generic_common_folders(self, ctx: ModContext) -> None:
        common_dir = ctx.root / "common"
        if not common_dir.is_dir():
            return
        
        scanned = {
            "country_tags", "characters", "ideologies", "national_focus", "ideas", "decisions",
            "technologies", "game_rules", "difficulty_settings", "map_modes", "bookmarks",
            "scripted_effects", "scripted_triggers", "scripted_localisation", "scripted_guis",
            "units", "ai_strategy_plans", "ai_strategy", "on_actions", "dynamic_modifiers",
            "factions", "ai_equipment", "doctrines", "military_industrial_organization",
            "ai_templates", "autonomous_states", "scripted_diplomatic_actions", "countries"
        }
        
        for subdir in sorted(common_dir.iterdir()):
            if not subdir.is_dir():
                continue
            if subdir.name in scanned:
                continue
            
            file_count = len(list(subdir.rglob("*.txt")))
            if file_count == 0:
                continue
            
            sample_keys = []
            for fpath in list(subdir.rglob("*.txt"))[:3]:
                text = self._read(fpath, limit=50_000)
                for m in re.finditer(r'^\t?(\w+)\s*=\s*\{', text, re.MULTILINE):
                    sample_keys.append(m.group(1))
                    if len(sample_keys) >= 10:
                        break
            
            ctx.generic_common_scans[subdir.name] = {
                "file_count": file_count,
                "sample_keys": sample_keys[:10]
            }

    def _scan_map_other_files(self, ctx: ModContext) -> None:
        map_dir = ctx.root / "map"
        if not map_dir.is_dir():
            return
        
        important_files = [
            "adjacencies.csv", "adjacency_rules.txt", "ambient_object.txt",
            "cities.txt", "colors.txt", "continent.txt", "default.map",
            "seasons.txt", "supply_nodes.txt", "unitstacks.txt", "weatherpositions.txt"
        ]
        
        for filename in important_files:
            fpath = map_dir / filename
            if fpath.exists():
                ctx.map_other_files[filename] = {
                    "exists": True,
                    "size": fpath.stat().st_size
                }


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
