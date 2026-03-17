"""
풀 파이프라인 프로세서.
게임 시작 날짜를 받아 국가별로 전체 인물/정당/군부/비국가 행위자를
자동 발견 → 생성 → 검증하는 end-to-end 파이프라인.

캐릭터 한 명당 처리 흐름:
  1. 위키 검색 → 이름/생년/직위/정당/이념/군사계급
  2. 모드에 없으면 → 캐릭터 자동 추가 (common/characters/)
  3. 초상화 없으면 → Wikimedia → TFR 스타일 → gfx/leaders/
  4. GFX 미등록 → interface/*.gfx
  5. 로컬라이제이션 없으면 → localisation/english/*.yml
  6. 히스토리에 recruit 없으면 → history/countries/
  7. 정당/이념 변경 → set_politics / set_party_name 업데이트

사용법:
    from tools.wiki_updater.core.full_pipeline import FullPipeline

    pipeline = FullPipeline(mod_root, game_start_date="2026.1.1")
    result = pipeline.process_country("USA")
    result = pipeline.process_all()
"""
from __future__ import annotations

import re as _re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from loguru import logger

from tools.shared.constants import MOD_ROOT, TARGET_DATE
from tools.shared.hoi4_parser import HOI4Parser, CharacterParser, CountryHistoryParser
from tools.shared.localisation_generator import LocalisationGenerator
from tools.wiki_updater.cache.sqlite_cache import WikiCache
from tools.wiki_updater.core.data_extractor import (
    DataExtractor,
    ExtractedPersonData,
    COUNTRY_NAME_TO_TAG,
    PARTY_TO_IDEOLOGY,
)
from tools.wiki_updater.core.wikidata_client import WikidataClient, WikidataEntityData


# =====================================================================
# 이데올로기 매핑
# =====================================================================

# Wikidata 정치이념(P1142) → 이 모드의 이데올로기 그룹
# 대폭 보강: 모호한 매핑(libertarianism→conservative 등) 수정
WIKIDATA_IDEOLOGY_TO_MOD_GROUP: dict[str, str] = {
    # --- conservative ---
    "conservatism": "conservative",
    "liberal conservatism": "conservative",
    "national conservatism": "conservative",
    "fiscal conservatism": "conservative",
    "Christian democracy": "conservative",
    "Christian democratic": "conservative",
    "right-wing populism": "conservative",
    "neoconservatism": "conservative",
    "paleoconservatism": "conservative",
    "traditionalist conservatism": "conservative",
    "one-nation conservatism": "conservative",
    # --- social_liberal ---
    "liberalism": "social_liberal",
    "social liberalism": "social_liberal",
    "centrism": "social_liberal",
    "radical centrism": "social_liberal",
    "green liberalism": "social_liberal",
    "third way": "social_liberal",
    "liberal democracy": "social_liberal",
    # --- market_liberal ---
    "classical liberalism": "market_liberal",
    "libertarianism": "market_liberal",
    "right-libertarianism": "market_liberal",
    "neoliberalism": "market_liberal",
    "economic liberalism": "market_liberal",
    "minarchism": "market_liberal",
    "laissez-faire": "market_liberal",
    "free-market environmentalism": "market_liberal",
    # --- social_democrat ---
    "social democracy": "social_democrat",
    "democratic socialism": "social_democrat",
    "progressivism": "social_democrat",
    "left-wing populism": "social_democrat",
    "green politics": "social_democrat",
    "left-wing nationalism": "social_democrat",
    "Nordic model": "social_democrat",
    "welfare state": "social_democrat",
    "labour movement": "social_democrat",
    # --- libertarian_socialist ---
    "socialism": "libertarian_socialist",
    "ecosocialism": "libertarian_socialist",
    "anarchism": "libertarian_socialist",
    "left-libertarianism": "libertarian_socialist",
    "libertarian socialism": "libertarian_socialist",
    "anarcho-communism": "libertarian_socialist",
    "syndicalism": "libertarian_socialist",
    "council communism": "libertarian_socialist",
    "Luxemburgism": "libertarian_socialist",
    # --- communist ---
    "communism": "communist",
    "Marxism–Leninism": "communist",
    "Marxism-Leninism": "communist",
    "Marxism": "communist",
    "Trotskyism": "communist",
    "left communism": "communist",
    "anti-revisionism": "communist",
    # --- totalitarian_socialist ---
    "Maoism": "totalitarian_socialist",
    "Stalinism": "totalitarian_socialist",
    "Juche": "totalitarian_socialist",
    "Hoxhaism": "totalitarian_socialist",
    "Guevarism": "totalitarian_socialist",
    # --- authoritarian_democrat ---
    "authoritarianism": "authoritarian_democrat",
    "populism": "authoritarian_democrat",
    "illiberal democracy": "authoritarian_democrat",
    "dominant-party system": "authoritarian_democrat",
    "Bonapartism": "authoritarian_democrat",
    "Peronism": "authoritarian_democrat",
    "Kemalism": "authoritarian_democrat",
    "guided democracy": "authoritarian_democrat",
    "managed democracy": "authoritarian_democrat",
    "competitive authoritarianism": "authoritarian_democrat",
    # --- nationalist ---
    "nationalism": "nationalist",
    "ultranationalism": "nationalist",
    "Islamism": "nationalist",
    "theocracy": "nationalist",
    "religious fundamentalism": "nationalist",
    "Islamic fundamentalism": "nationalist",
    "irredentism": "nationalist",
    "Zionism": "nationalist",
    "Hindu nationalism": "nationalist",
    "pan-Arabism": "nationalist",
    "Baathism": "nationalist",
    "militarism": "nationalist",
    "absolute monarchy": "nationalist",
    # --- fascist ---
    "fascism": "fascist",
    "neo-fascism": "fascist",
    "Falangism": "fascist",
    "clerical fascism": "fascist",
    "Italian fascism": "fascist",
    "proto-fascism": "fascist",
    "Third Position": "fascist",
    # --- national_socialist ---
    "National Socialism": "national_socialist",
    "Nazism": "national_socialist",
    "neo-Nazism": "national_socialist",
    "Strasserism": "national_socialist",
    "esoteric Nazism": "national_socialist",
    "white supremacy": "national_socialist",
    "white nationalism": "national_socialist",
}

# 정당 이름 키워드 → 이데올로기 그룹 매핑 (fallback)
# WIKIDATA_IDEOLOGY_TO_MOD_GROUP에서 못 찾을 때 정당 이름 자체의 키워드로 매핑
PARTY_NAME_KEYWORD_TO_GROUP: dict[str, str] = {
    # social_democrat
    "social democrat": "social_democrat",
    "labour": "social_democrat",
    "labor": "social_democrat",
    "workers' party": "social_democrat",
    "workers party": "social_democrat",
    "green party": "social_democrat",
    "progressive": "social_democrat",
    # social_liberal
    "liberal democrat": "social_liberal",
    "centrist": "social_liberal",
    "radical party": "social_liberal",
    # market_liberal
    "libertarian": "market_liberal",
    "free democrat": "market_liberal",
    "liberal party": "market_liberal",
    # conservative
    "conservative": "conservative",
    "republican party": "conservative",
    "christian democrat": "conservative",
    "people's party": "conservative",
    "peoples party": "conservative",
    "popular party": "conservative",
    "tory": "conservative",
    # authoritarian_democrat
    "united russia": "authoritarian_democrat",
    "people power": "authoritarian_democrat",
    # libertarian_socialist
    "socialist party": "libertarian_socialist",
    "democratic socialist": "libertarian_socialist",
    # communist
    "communist": "communist",
    "marxist": "communist",
    # totalitarian_socialist
    "workers' party of korea": "totalitarian_socialist",
    # nationalist
    "national front": "nationalist",
    "national rally": "nationalist",
    "patriot": "nationalist",
    "independence party": "nationalist",
    # fascist
    "fascist": "fascist",
    "falange": "fascist",
    "golden dawn": "fascist",
    # national_socialist
    "national socialist": "national_socialist",
    "nazi": "national_socialist",
    "neo-nazi": "national_socialist",
}

# =====================================================================
# 모드 로케일 기반 정당 레지스트리
# =====================================================================


class ModPartyRegistry:
    """모드의 로케일 파일에서 TAG_group_party 패턴을 파싱하여 정당 레지스트리 구축.

    모드에 이미 정의된 정당을 기준으로 위키 정당을 매핑할 때 사용한다.
    Wikidata SPARQL보다 이 레지스트리가 항상 우선한다.

    데이터 구조:
        _registry[TAG][ideology_group] = {
            "short": "GOP (C)",
            "long": "Republican Party (Conservative)",
            "variants": {"nlp": "NLP(Po)", "nlp_long": "National Liberty Party (Populists)"},
        }

    역매핑 구조:
        _name_to_group[TAG] = {
            "republican party": "conservative",
            "democratic party": "social_democrat",
            ...
        }
    """

    def __init__(self, mod_root: Path, ideology_groups: list[str]) -> None:
        self.mod_root = mod_root
        self._ideology_groups = set(ideology_groups)
        self._registry: dict[str, dict[str, dict[str, Any]]] = {}
        # 정확 매칭용: TAG → {정당이름(소문자) → ideology_group}
        # 약칭 + 전체 이름 모두 포함
        self._name_to_group: dict[str, dict[str, str]] = {}
        # fuzzy 매칭용: TAG → {전체이름(소문자) → ideology_group}
        # 약칭 제외, 전체 이름(long name)만 포함
        self._long_name_to_group: dict[str, dict[str, str]] = {}
        # 전역 정확 매칭 (TAG 무관): {정당이름(소문자) → ideology_group}
        self._global_name_to_group: dict[str, str] = {}
        # 전역 fuzzy 매칭 (TAG 무관): {전체이름(소문자) → ideology_group}
        self._global_long_to_group: dict[str, str] = {}
        self._load_all()

    def _load_all(self) -> None:
        """모든 영어 로케일 파일에서 정당 키를 파싱."""
        loc_dir = self.mod_root / "localisation" / "english"
        if not loc_dir.exists():
            return

        # TAG_group_party 패턴
        # 그룹 이름: totalitarian_socialist, communist, ..., national_socialist
        groups_pattern = "|".join(_re.escape(g) for g in sorted(self._ideology_groups, key=len, reverse=True))
        # 패턴: TAG_group_party (base), TAG_group_party_long, TAG_group_party_SUFFIX
        party_re = _re.compile(
            rf'^(\S+?)_({groups_pattern})_party(?:_([\w]+))?',
        )

        for yml_file in loc_dir.glob("*.yml"):
            self._parse_loc_file(yml_file, party_re)

        # 역매핑 구축
        self._build_reverse_maps()

        total_parties = sum(len(groups) for groups in self._registry.values())
        total_countries = len(self._registry)
        logger.info(
            "ModPartyRegistry: {}개국 {}개 정당 슬롯 로드 (역매핑 {}건)",
            total_countries, total_parties, len(self._global_name_to_group),
        )

    def _parse_loc_file(self, yml_file: Path, party_re: _re.Pattern) -> None:
        """단일 로케일 파일에서 정당 항목 파싱."""
        try:
            content = yml_file.read_text(encoding="utf-8-sig")
        except Exception:
            return

        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("l_"):
                continue

            # KEY:0 "Value" 또는 KEY: "Value"
            m = _re.match(r'^(\S+?):(?:\d*)?\s+"(.*)"', line)
            if not m:
                continue

            key = m.group(1)
            value = m.group(2)

            # TAG_group_party 패턴 매칭
            pm = party_re.match(key)
            if not pm:
                continue

            tag = pm.group(1)
            group = pm.group(2)
            suffix = pm.group(3)  # None(base), "long", or variant suffix

            if tag not in self._registry:
                self._registry[tag] = {}
            if group not in self._registry[tag]:
                self._registry[tag][group] = {"short": "", "long": "", "variants": {}}

            slot = self._registry[tag][group]
            if suffix is None:
                # base: TAG_group_party → short name
                slot["short"] = value
            elif suffix == "long":
                # TAG_group_party_long → long name
                slot["long"] = value
            else:
                # TAG_group_party_SUFFIX → variant
                slot["variants"][suffix] = value

    def _build_reverse_maps(self) -> None:
        """정당 이름 → ideology_group 역매핑 구축.

        - 정확 매칭용(_name_to_group): 약칭 + 전체 이름 모두 포함
        - fuzzy 매칭용(_long_name_to_group): 전체 이름(long)만 포함.
          약칭("PA", "SP", "GOP (C)" 등)으로 fuzzy하면
          "party", "spain" 등에 false positive가 발생하므로 제외.
        """
        for tag, groups in self._registry.items():
            if tag not in self._name_to_group:
                self._name_to_group[tag] = {}
            if tag not in self._long_name_to_group:
                self._long_name_to_group[tag] = {}

            for group, info in groups.items():
                # short name → 정확 매칭만
                if info["short"]:
                    name_lower = info["short"].lower().strip()
                    self._name_to_group[tag][name_lower] = group
                    if name_lower not in self._global_name_to_group:
                        self._global_name_to_group[name_lower] = group

                # long name → 정확 매칭 + fuzzy 매칭
                if info["long"]:
                    name_lower = info["long"].lower().strip()
                    self._name_to_group[tag][name_lower] = group
                    self._long_name_to_group[tag][name_lower] = group
                    if name_lower not in self._global_name_to_group:
                        self._global_name_to_group[name_lower] = group
                    if name_lower not in self._global_long_to_group:
                        self._global_long_to_group[name_lower] = group

                # variants → 정확 매칭만
                for _vsuffix, vname in info.get("variants", {}).items():
                    if vname:
                        name_lower = vname.lower().strip()
                        self._name_to_group[tag][name_lower] = group

    # ------------------------------------------------------------------
    # 조회 API
    # ------------------------------------------------------------------

    def get_country_slots(self, tag: str) -> dict[str, dict[str, Any]]:
        """국가의 전체 정당 슬롯 반환."""
        return self._registry.get(tag, {})

    def get_all_countries(self) -> list[str]:
        """레지스트리에 있는 모든 국가 태그."""
        return sorted(self._registry.keys())

    def get_party_group_for_country(self, tag: str, party_name: str) -> str:
        """국가 컨텍스트에서 정당 이름 → ideology_group.

        1. 정확 매칭 (약칭 + 전체 이름)
        2. fuzzy 매칭 (전체 이름만 — 약칭은 절대 사용 안 함)
        3. 글로벌 정확 매칭
        4. 글로벌 fuzzy 매칭 (전체 이름만)
        """
        name_lower = party_name.lower().strip()

        # 1. 국가별 정확 매칭 (약칭 + 전체 이름)
        tag_map = self._name_to_group.get(tag, {})
        if name_lower in tag_map:
            return tag_map[name_lower]

        # 2. 국가별 fuzzy — 전체 이름(long)에서만
        long_map = self._long_name_to_group.get(tag, {})
        for registered_long, group in long_map.items():
            if name_lower in registered_long or registered_long in name_lower:
                return group

        # 3. 글로벌 정확 매칭
        if name_lower in self._global_name_to_group:
            return self._global_name_to_group[name_lower]

        # 4. 글로벌 fuzzy — 전체 이름(long)에서만
        for registered_long, group in self._global_long_to_group.items():
            if name_lower in registered_long or registered_long in name_lower:
                return group

        return ""

    def match_wiki_party(
        self, tag: str, wiki_party_name: str, wiki_ideology: str = "",
    ) -> tuple[str, str]:
        """위키 정당을 모드 정당에 매핑.

        반환: (ideology_group, match_source)
        match_source: "mod_exact", "mod_fuzzy", "mod_global",
                      "keyword", "wikidata_dict", "unmapped"

        fuzzy 매칭은 전체 이름(long name)에서만 수행.
        약칭으로 fuzzy하지 않음 (PA→party 같은 false positive 방지).
        """
        name_lower = wiki_party_name.lower().strip()

        # 1. 국가별 정확 매칭 (약칭 + 전체 이름)
        tag_map = self._name_to_group.get(tag, {})
        if name_lower in tag_map:
            return tag_map[name_lower], "mod_exact"

        # 2. 국가별 fuzzy — 전체 이름(long)에서만
        long_map = self._long_name_to_group.get(tag, {})
        for registered_long, group in long_map.items():
            if name_lower in registered_long or registered_long in name_lower:
                return group, "mod_fuzzy"

        # 3. 글로벌 정확 매칭
        if name_lower in self._global_name_to_group:
            return self._global_name_to_group[name_lower], "mod_global"

        # 4. 글로벌 fuzzy — 전체 이름(long)에서만
        for registered_long, group in self._global_long_to_group.items():
            if name_lower in registered_long or registered_long in name_lower:
                return group, "mod_global"

        # 5. 정당 이름 키워드 매칭
        for keyword, group in PARTY_NAME_KEYWORD_TO_GROUP.items():
            if keyword in name_lower:
                return group, "keyword"

        # 6. Wikidata 이데올로기 딕셔너리 fallback
        if wiki_ideology:
            ideo_lower = wiki_ideology.lower()
            for wd_ideo, mod_group in WIKIDATA_IDEOLOGY_TO_MOD_GROUP.items():
                if wd_ideo.lower() in ideo_lower or ideo_lower in wd_ideo.lower():
                    return mod_group, "wikidata_dict"

        return "", "unmapped"

    def has_empty_slots(self, tag: str) -> list[str]:
        """국가에서 정당이 정의되지 않은 이데올로기 그룹 목록."""
        existing = set(self._registry.get(tag, {}).keys())
        return [g for g in self._ideology_groups if g not in existing]


# 모드 이데올로기 그룹 → 기본 서브이데올로기 (캐릭터에 사용)
MOD_GROUP_DEFAULT_SUB: dict[str, str] = {
    "totalitarian_socialist": "marxism_leninism",
    "communist": "marxism_leninism",
    "libertarian_socialist": "reformist_socialism",
    "social_democrat": "social_democracy",
    "social_liberal": "centrist",
    "market_liberal": "classical_liberalism",
    "conservative": "right_centrist",
    "authoritarian_democrat": "hybrid_regime",
    "nationalist": "autocrat",
    "fascist": "classical_fascism",
    "national_socialist": "neonazism",
}

# Wikidata 군사계급 → HOI4 역할
MILITARY_RANK_TO_ROLE: dict[str, str] = {
    "general": "corps_commander",
    "lieutenant general": "corps_commander",
    "major general": "corps_commander",
    "brigadier general": "corps_commander",
    "general of the army": "field_marshal",
    "field marshal": "field_marshal",
    "marshal": "field_marshal",
    "admiral": "navy_leader",
    "vice admiral": "navy_leader",
    "rear admiral": "navy_leader",
    "fleet admiral": "navy_leader",
    "admiral of the fleet": "navy_leader",
}

# Wikidata 국가 QID → HOI4 TAG (주요 국가)
COUNTRY_QID_TO_TAG: dict[str, str] = {
    "Q30": "USA", "Q145": "ENG", "Q142": "FRA", "Q183": "GER",
    "Q159": "SOV", "Q148": "PRC", "Q17": "JAP", "Q38": "ITA",
    "Q29": "SPR", "Q184": "BLR", "Q212": "UKR", "Q884": "KOR",
    "Q423": "PRK", "Q668": "RAJ", "Q817": "KUW", "Q851": "SAU",
    "Q79": "EGY", "Q43": "TUR", "Q794": "PER", "Q801": "ISR",
    "Q155": "BRA", "Q96": "MEX", "Q414": "ARM", "Q227": "AZR",
    "Q232": "KAZ", "Q813": "KYR", "Q863": "PAK", "Q889": "AFG",
    "Q16": "CAN", "Q298": "SER", "Q45": "POR", "Q218": "ROM",
    "Q36": "PLD", "Q213": "CZE", "Q28": "HUN", "Q55": "HOL",
    "Q31": "BEL", "Q39": "SWI", "Q34": "SWE", "Q20": "NOR",
    "Q33": "FIN", "Q35": "DEN", "Q37": "LIT", "Q211": "LAT",
    "Q191": "EST", "Q230": "GEO", "Q219": "BUL", "Q41": "GRE",
    "Q40": "AUS", "Q408": "AST", "Q334": "LOS",
    "Q865": "CHI", "Q902": "BAN", "Q836": "BRM",
}


# =====================================================================
# 발견된 인물 모델
# =====================================================================


@dataclass
class DiscoveredPerson:
    """위키에서 발견된 인물."""

    qid: str = ""
    name: str = ""
    country_tag: str = ""
    birth_date: str = ""
    death_date: str = ""

    # 역할 분류
    category: str = ""  # government, military, party_leader, opposition, radical, activist, rebel
    role: str = ""  # country_leader, advisor, corps_commander, field_marshal, navy_leader

    # 정치
    ideology_group: str = ""  # 모드의 11개 그룹 중 하나
    sub_ideology: str = ""  # 모드의 ~150개 서브이데올로기 중 하나
    party_name: str = ""  # 실제 정당 이름
    position_title: str = ""  # 직위명 (예: "President of the United States")

    # 군사
    military_rank: str = ""

    # 생성용
    char_id: str = ""  # 생성될 캐릭터 ID
    has_portrait: bool = False
    portrait_url: str = ""  # Wikimedia Commons URL


@dataclass
class CountryPipelineResult:
    """국가 1개 파이프라인 결과."""

    country_tag: str = ""
    country_name: str = ""
    game_date: str = ""

    # 발견
    discovered: list[DiscoveredPerson] = field(default_factory=list)
    existing_chars: int = 0

    # 생성
    chars_added: int = 0
    chars_updated: int = 0
    portraits_generated: int = 0
    loc_entries_added: int = 0
    history_updated: bool = False
    parties_updated: int = 0

    # 에러
    errors: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"[{self.country_tag}] {self.country_name} @ {self.game_date}\n"
            f"  발견: {len(self.discovered)}명 | 기존: {self.existing_chars}명\n"
            f"  추가: {self.chars_added} | 업데이트: {self.chars_updated}\n"
            f"  초상화: {self.portraits_generated} | 로컬라이제이션: {self.loc_entries_added}\n"
            f"  정당 업데이트: {self.parties_updated} | 히스토리: {'✓' if self.history_updated else '✗'}\n"
            f"  에러: {len(self.errors)}건"
        )


# =====================================================================
# 이데올로기 해석기
# =====================================================================


class IdeologyResolver:
    """모드의 이데올로기 구조를 파싱하고, Wikidata 정보를 매핑.

    ModPartyRegistry와 연동하여 모드 로케일에 정의된 정당을
    기준으로 위키 정보를 매핑한다.
    """

    def __init__(self, mod_root: Path = MOD_ROOT) -> None:
        self.mod_root = mod_root
        self._groups: dict[str, list[str]] = {}  # group → [sub_ideologies]
        self._party_registry: ModPartyRegistry | None = None
        self._load_ideologies()

    def _load_ideologies(self) -> None:
        """common/ideologies/*.txt에서 이데올로기 구조 로드."""
        parser = HOI4Parser()
        ideo_dir = self.mod_root / "common" / "ideologies"
        if not ideo_dir.exists():
            return

        for f in ideo_dir.glob("*.txt"):
            data = parser.parse_file(f)
            ideologies = data.get("ideologies", data)
            for group_name, group_data in ideologies.items():
                if isinstance(group_data, dict):
                    types = group_data.get("types", {})
                    if isinstance(types, dict):
                        self._groups[group_name] = list(types.keys())

    def _ensure_party_registry(self) -> ModPartyRegistry:
        """ModPartyRegistry 지연 초기화."""
        if self._party_registry is None:
            self._party_registry = ModPartyRegistry(self.mod_root, self.groups)
        return self._party_registry

    @property
    def party_registry(self) -> ModPartyRegistry:
        """정당 레지스트리 접근자."""
        return self._ensure_party_registry()

    @property
    def groups(self) -> list[str]:
        return list(self._groups.keys())

    def get_sub_ideologies(self, group: str) -> list[str]:
        return self._groups.get(group, [])

    def is_valid_group(self, group: str) -> bool:
        return group in self._groups

    def is_valid_sub(self, sub: str) -> bool:
        return any(sub in subs for subs in self._groups.values())

    def get_group_for_sub(self, sub: str) -> str:
        for group, subs in self._groups.items():
            if sub in subs:
                return group
        return ""

    def map_wikidata_ideology(
        self,
        wikidata_ideology: str,
        country_tag: str = "",
        party_name: str = "",
    ) -> tuple[str, str]:
        """Wikidata 정치이념 → (모드 그룹, 기본 서브이데올로기).

        매핑 우선순위:
        1. 모드 레지스트리에서 country_tag + party_name으로 매칭
        2. 정당 이름 키워드 매칭
        3. WIKIDATA_IDEOLOGY_TO_MOD_GROUP 딕셔너리
        4. 기본값 (빈 문자열 — 호출자가 처리)
        """
        registry = self._ensure_party_registry()

        # 1. 모드 레지스트리 우선 (정당 이름으로)
        if party_name and country_tag:
            group, source = registry.match_wiki_party(
                country_tag, party_name, wikidata_ideology,
            )
            if group:
                sub = MOD_GROUP_DEFAULT_SUB.get(group, "")
                logger.debug(
                    "이데올로기 매핑: {} → {} ({})", party_name, group, source,
                )
                return group, sub

        # 2. 정당 이름만으로 (country_tag 없는 경우)
        if party_name:
            group, source = registry.match_wiki_party("", party_name, wikidata_ideology)
            if group:
                sub = MOD_GROUP_DEFAULT_SUB.get(group, "")
                return group, sub

        # 3. Wikidata 이데올로기 딕셔너리 (보강된 버전)
        if wikidata_ideology:
            ideology_lower = wikidata_ideology.lower()
            for wd_ideo, mod_group in WIKIDATA_IDEOLOGY_TO_MOD_GROUP.items():
                if wd_ideo.lower() in ideology_lower or ideology_lower in wd_ideo.lower():
                    sub = MOD_GROUP_DEFAULT_SUB.get(mod_group, "")
                    return mod_group, sub

        # 4. 기본값 — conservative fallback 제거, 빈 문자열 반환
        # 호출자가 명시적으로 처리하도록 변경
        return "", ""

    def map_party_to_ideology(
        self,
        party_name: str,
        country_tag: str = "",
    ) -> tuple[str, str]:
        """정당 이름 → (모드 그룹, 서브이데올로기).

        모드 레지스트리 우선, PARTY_TO_IDEOLOGY fallback.
        """
        registry = self._ensure_party_registry()

        # 1. 모드 레지스트리
        if country_tag:
            group = registry.get_party_group_for_country(country_tag, party_name)
            if group:
                sub = MOD_GROUP_DEFAULT_SUB.get(group, "")
                return group, sub

        # 2. 글로벌 레지스트리
        group = registry.get_party_group_for_country("", party_name)
        if group:
            sub = MOD_GROUP_DEFAULT_SUB.get(group, "")
            return group, sub

        # 3. 기존 PARTY_TO_IDEOLOGY fallback
        if party_name in PARTY_TO_IDEOLOGY:
            sub = PARTY_TO_IDEOLOGY[party_name]
            group = self.get_group_for_sub(sub)
            if group:
                return group, sub

        # 4. 정당 이름 키워드 매칭
        name_lower = party_name.lower()
        for keyword, group in PARTY_NAME_KEYWORD_TO_GROUP.items():
            if keyword in name_lower:
                sub = MOD_GROUP_DEFAULT_SUB.get(group, "")
                return group, sub

        return "", ""

    def map_military_rank(self, rank: str) -> str:
        """군사 계급 → HOI4 역할."""
        rank_lower = rank.lower()
        for keyword, role in MILITARY_RANK_TO_ROLE.items():
            if keyword in rank_lower:
                return role
        if "general" in rank_lower or "marshal" in rank_lower:
            return "corps_commander"
        if "admiral" in rank_lower:
            return "navy_leader"
        return "corps_commander"


# =====================================================================
# 풀 파이프라인
# =====================================================================


class FullPipeline:
    """국가별 전체 인물 자동 발견 + 생성 파이프라인.

    Parameters
    ----------
    mod_root : Path
        모드 루트 경로.
    game_start_date : str
        게임 시작 날짜 (YYYY.M.D 또는 YYYY-MM-DD).
    use_cache : bool
        SQLite 캐시 사용 여부.
    generate_portraits : bool
        초상화 자동 생성 여부.
    dry_run : bool
        True면 파일 수정 없이 발견만.
    """

    def __init__(
        self,
        mod_root: Path = MOD_ROOT,
        game_start_date: str = TARGET_DATE,
        use_cache: bool = True,
        generate_portraits: bool = True,
        dry_run: bool = False,
    ) -> None:
        self.mod_root = mod_root
        self.game_date = game_start_date.replace(".", "-") if "." in game_start_date else game_start_date
        self.game_date_pdx = game_start_date.replace("-", ".") if "-" in game_start_date else game_start_date
        self.dry_run = dry_run
        self.generate_portraits = generate_portraits

        self._cache = WikiCache() if use_cache else None
        self._wikidata = WikidataClient()
        self._extractor = DataExtractor(cache=self._cache)
        self._ideology = IdeologyResolver(mod_root)
        self._char_parser = CharacterParser()
        self._hist_parser = CountryHistoryParser()
        self._loc_gen = LocalisationGenerator(mod_root)
        self._parser = HOI4Parser()

        # 로컬라이제이션 캐시
        self._loc_names = self._loc_gen.read_file()

        # 기존 캐릭터 ID 세트
        chars_dir = mod_root / "common" / "characters"
        self._existing_chars = set(
            self._char_parser.parse_all_characters(chars_dir).keys()
        )

        # TAG ↔ name 매핑
        self._tag_to_name = {v: k for k, v in COUNTRY_NAME_TO_TAG.items()}
        self._qid_to_tag = COUNTRY_QID_TO_TAG

    # ------------------------------------------------------------------
    # 메인 API
    # ------------------------------------------------------------------

    def process_country(
        self,
        country_tag: str,
        progress_callback: Callable[[str, int, int], None] | None = None,
    ) -> CountryPipelineResult:
        """국가 1개에 대해 풀 파이프라인 실행."""
        country_name = self._tag_to_name.get(country_tag, country_tag)
        result = CountryPipelineResult(
            country_tag=country_tag,
            country_name=country_name,
            game_date=self.game_date_pdx,
        )

        logger.info("=== {} ({}) 파이프라인 시작 @ {} ===", country_tag, country_name, self.game_date_pdx)

        # 1. 기존 캐릭터 수
        result.existing_chars = sum(
            1 for cid in self._existing_chars
            if self._char_parser.get_character_country(cid) == country_tag
        )

        # 2. 위키에서 인물 발견
        try:
            discovered = self._discover_all_persons(country_tag, country_name)
            result.discovered = discovered
            logger.info("{}: {}명 발견 (기존 {}명)", country_tag, len(discovered), result.existing_chars)
        except Exception as exc:
            result.errors.append(f"Discovery failed: {exc}")
            logger.error("{} 인물 발견 실패: {}", country_tag, exc)
            return result

        if self.dry_run:
            return result

        # 3. 각 인물에 대해 생성
        total = len(discovered)
        for idx, person in enumerate(discovered):
            try:
                added = self._process_single_person(person, country_tag, result)
                if progress_callback:
                    progress_callback(
                        f"{'✓' if added else '⏭'} {person.name} ({person.category})",
                        idx + 1,
                        total,
                    )
            except Exception as exc:
                result.errors.append(f"{person.name}: {exc}")
                logger.error("인물 처리 실패 {}: {}", person.name, exc)

        # 4. 정당/정치 자동 업데이트 (추가 + 수정 + 집권당 판단)
        try:
            party_results = self.sync_parties_from_wiki(country_tag)
            result.parties_updated = sum(1 for r in party_results if r["action"] not in ("skipped (same)", "unmapped"))
        except Exception as exc:
            result.errors.append(f"Party sync failed: {exc}")

        # 5. recruit_character 히스토리 업데이트
        try:
            self._update_politics(country_tag, discovered, result)
        except Exception as exc:
            result.errors.append(f"History update failed: {exc}")

        logger.info(result.summary())
        return result

    def process_all(
        self,
        country_tags: list[str] | None = None,
        progress_callback: Callable[[str, int, int], None] | None = None,
    ) -> list[CountryPipelineResult]:
        """여러 국가 풀 파이프라인. None이면 모드의 모든 국가."""
        if country_tags is None:
            hist_dir = self.mod_root / "history" / "countries"
            histories = self._hist_parser.parse_all_histories(hist_dir)
            country_tags = sorted(histories.keys())

        results: list[CountryPipelineResult] = []
        total = len(country_tags)

        for idx, tag in enumerate(country_tags):
            if progress_callback:
                progress_callback(f"Processing {tag}...", idx + 1, total)

            result = self.process_country(tag)
            results.append(result)

        return results

    # ------------------------------------------------------------------
    # 인물 발견 (Wikidata SPARQL + REST)
    # ------------------------------------------------------------------

    def _discover_all_persons(
        self, country_tag: str, country_name: str,
    ) -> list[DiscoveredPerson]:
        """국가의 모든 핵심 인물을 위키에서 발견."""
        persons: list[DiscoveredPerson] = []
        country_qid = self._get_country_qid(country_tag)

        # 1. 국가원수 + 정부수반
        persons.extend(self._discover_government(country_tag, country_qid))

        # 2. 정당 지도자들 (여러 정당)
        if country_qid:
            persons.extend(self._discover_party_leaders(country_tag, country_qid))

        # 3. 군부
        if country_qid:
            persons.extend(self._discover_military(country_tag, country_qid))

        # 4. 중복 제거 (같은 QID)
        seen_qids: set[str] = set()
        unique: list[DiscoveredPerson] = []
        for p in persons:
            key = p.qid or p.name
            if key not in seen_qids:
                seen_qids.add(key)
                # char_id 생성
                if not p.char_id:
                    safe_name = p.name.lower().replace(" ", "_").replace("-", "_").replace(".", "")
                    p.char_id = f"{country_tag}_{safe_name}_char"
                unique.append(p)

        # 5. 이미 모드에 있는 캐릭터 제외
        new_only = [p for p in unique if p.char_id not in self._existing_chars]

        return new_only

    def _discover_government(
        self, country_tag: str, country_qid: str,
    ) -> list[DiscoveredPerson]:
        """국가원수 + 정부수반 발견."""
        persons: list[DiscoveredPerson] = []

        # 국가원수
        heads_of_state = self._wikidata.get_current_heads_of_state()
        for h in heads_of_state:
            h_tag = self._qid_to_tag.get(h.get("country_qid", ""), "")
            if h_tag == country_tag:
                entity = self._wikidata.get_entity_by_qid(h["qid"])
                p = self._entity_to_person(entity, country_tag, "government", "country_leader")
                if p:
                    p.position_title = "Head of State"
                    persons.append(p)

        # 정부수반
        heads_of_gov = self._wikidata.get_current_heads_of_government()
        for h in heads_of_gov:
            h_tag = self._qid_to_tag.get(h.get("country_qid", ""), "")
            if h_tag == country_tag:
                entity = self._wikidata.get_entity_by_qid(h["qid"])
                p = self._entity_to_person(entity, country_tag, "government", "advisor")
                if p:
                    p.position_title = "Head of Government"
                    persons.append(p)

        return persons

    def _discover_party_leaders(
        self, country_tag: str, country_qid: str,
    ) -> list[DiscoveredPerson]:
        """국가의 정당들 + 각 지도자 발견."""
        persons: list[DiscoveredPerson] = []

        parties = self._wikidata.get_political_parties_by_country(country_qid)
        logger.info("{}: {}개 정당 발견", country_tag, len(parties))

        for party in parties[:20]:
            party_name = party.get("name", "")
            party_qid = party.get("qid", "")
            wd_ideology = party.get("ideology", "")

            # 정당 → 모드 이데올로기 매핑 (모드 레지스트리 우선)
            mod_group, sub_ideo = self._ideology.map_party_to_ideology(
                party_name, country_tag=country_tag,
            )
            if not mod_group and wd_ideology:
                mod_group, sub_ideo = self._ideology.map_wikidata_ideology(
                    wd_ideology, country_tag=country_tag, party_name=party_name,
                )

            # 정당 지도자 찾기 (SPARQL: P488 chairperson)
            leader = self._find_party_leader(party_qid, party_name)
            if leader:
                leader.country_tag = country_tag
                leader.category = "party_leader"
                leader.role = "country_leader"
                leader.party_name = party_name
                leader.ideology_group = mod_group
                leader.sub_ideology = sub_ideo or MOD_GROUP_DEFAULT_SUB.get(mod_group, "")
                persons.append(leader)

        return persons

    def _find_party_leader(self, party_qid: str, party_name: str) -> DiscoveredPerson | None:
        """정당의 현재 지도자를 찾는다."""
        if not party_qid:
            return None

        query = f"""
SELECT ?leader ?leaderLabel ?birthDate ?deathDate
WHERE {{
  wd:{party_qid} wdt:P488 ?leader .
  OPTIONAL {{ ?leader wdt:P569 ?birthDate }}
  OPTIONAL {{ ?leader wdt:P570 ?deathDate }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en" . }}
}}
LIMIT 5
"""
        try:
            rows = self._wikidata._sparql_query(query)
        except Exception:
            return None

        for row in rows:
            name = self._wikidata._extract_value(row, "leaderLabel")
            qid = self._wikidata._qid_from_uri(self._wikidata._extract_value(row, "leader"))
            birth = self._wikidata._extract_value(row, "birthDate")
            death = self._wikidata._extract_value(row, "deathDate")

            # 사망자 제외
            if death and death[:4].isdigit() and int(death[:4]) < 2026:
                continue

            return DiscoveredPerson(
                qid=qid,
                name=name,
                birth_date=birth[:10] if birth else "",
                death_date=death[:10] if death else "",
            )

        return None

    def _discover_military(
        self, country_tag: str, country_qid: str,
    ) -> list[DiscoveredPerson]:
        """군 사령관들 발견."""
        persons: list[DiscoveredPerson] = []

        commanders = self._wikidata.get_military_commanders(country_qid)
        logger.info("{}: {}명 군인 발견", country_tag, len(commanders))

        for cmd in commanders[:30]:
            # 사망자 제외
            if cmd.death_date and cmd.death_date[:4].isdigit():
                if int(cmd.death_date[:4]) < 2020:
                    continue

            # 계급 → 역할
            role = "corps_commander"
            for rank in cmd.military_ranks:
                mapped = self._ideology.map_military_rank(rank)
                if mapped == "field_marshal":
                    role = "field_marshal"
                    break
                if mapped == "navy_leader":
                    role = "navy_leader"
                    break

            p = DiscoveredPerson(
                qid=cmd.qid,
                name=cmd.label,
                country_tag=country_tag,
                birth_date=cmd.birth_date,
                death_date=cmd.death_date,
                category="military",
                role=role,
                military_rank=", ".join(cmd.military_ranks[:2]),
            )
            persons.append(p)

        return persons

    # ------------------------------------------------------------------
    # 인물 처리 (생성)
    # ------------------------------------------------------------------

    def _process_single_person(
        self,
        person: DiscoveredPerson,
        country_tag: str,
        result: CountryPipelineResult,
    ) -> bool:
        """발견된 인물 1명을 모드에 추가."""
        # 위키에서 상세 데이터 가져오기
        extracted = self._extractor.extract_person(
            person.char_id, person.name, country_tag
        )
        if extracted is None:
            return False

        # 이데올로기 오버라이드 (파이프라인에서 결정한 값 우선)
        if person.ideology_group and person.sub_ideology:
            extracted.ideology = person.sub_ideology

        # 캐릭터 파일 생성
        from tools.wiki_updater.generators.character_generator import WikiCharacterGenerator
        gen = WikiCharacterGenerator(self.mod_root)

        if person.char_id in self._existing_chars:
            gen.update_character_in_mod(extracted, self.mod_root)
            result.chars_updated += 1
        else:
            gen.add_character_to_mod(extracted, self.mod_root)
            result.chars_added += 1
            self._existing_chars.add(person.char_id)

        # 초상화 생성
        if self.generate_portraits and not person.has_portrait:
            try:
                from tools.portrait_generator.pipeline.portrait_pipeline import PortraitPipeline
                portrait = PortraitPipeline()
                portrait_path = portrait.process_from_wiki(
                    person.name, person.char_id, country_tag, self.mod_root
                )
                if portrait_path:
                    result.portraits_generated += 1
                    person.has_portrait = True
            except Exception as exc:
                logger.debug("초상화 생성 실패 {}: {}", person.name, exc)

        # 로컬라이제이션
        name_key = person.char_id.replace("_char", "")
        if name_key not in self._loc_names:
            self._loc_gen.add_character_loc(person.char_id, person.name)
            result.loc_entries_added += 1

        return True

    # ------------------------------------------------------------------
    # 정치 업데이트
    # ------------------------------------------------------------------

    def _update_politics(
        self,
        country_tag: str,
        discovered: list[DiscoveredPerson],
        result: CountryPipelineResult,
    ) -> int:
        """국가의 정당/이데올로기 업데이트.

        히스토리 파일에 set_party_name, set_popularities,
        recruit_character를 업데이트한다.
        """
        hist_dir = self.mod_root / "history" / "countries"
        hist_files = list(hist_dir.glob(f"{country_tag} - *.txt"))
        if not hist_files:
            return 0

        hist_file = hist_files[0]
        content = hist_file.read_text(encoding="utf-8-sig")

        updated_count = 0

        # recruit_character 추가
        for person in discovered:
            if person.char_id not in content:
                recruit_line = f'\trecruit_character = {person.char_id}\n'
                # 마지막 recruit_character 뒤에 삽입
                import re
                last_recruit = list(re.finditer(r'recruit_character\s*=\s*\S+', content))
                if last_recruit:
                    pos = last_recruit[-1].end()
                    content = content[:pos] + "\n" + recruit_line + content[pos:]
                else:
                    # recruit가 없으면 set_technology 앞에 삽입
                    tech_pos = content.find("set_technology")
                    if tech_pos > 0:
                        content = content[:tech_pos] + recruit_line + "\n" + content[tech_pos:]
                updated_count += 1

        if updated_count > 0 and not self.dry_run:
            hist_file.write_text(content, encoding="utf-8")
            result.history_updated = True

        return updated_count

    # ------------------------------------------------------------------
    # 유틸리티
    # ------------------------------------------------------------------

    def _get_country_qid(self, tag: str) -> str:
        """HOI4 TAG → Wikidata QID."""
        for qid, t in self._qid_to_tag.items():
            if t == tag:
                return qid
        return ""

    def _entity_to_person(
        self,
        entity: WikidataEntityData | None,
        country_tag: str,
        category: str,
        role: str,
    ) -> DiscoveredPerson | None:
        """WikidataEntityData → DiscoveredPerson 변환."""
        if entity is None or not entity.label:
            return None

        # 이데올로기 결정 (모드 레지스트리 우선)
        mod_group, sub_ideo = "", ""
        if entity.parties:
            for party in entity.parties:
                mod_group, sub_ideo = self._ideology.map_party_to_ideology(
                    party, country_tag=country_tag,
                )
                if mod_group:
                    break

        return DiscoveredPerson(
            qid=entity.qid,
            name=entity.label,
            country_tag=country_tag,
            birth_date=entity.birth_date,
            death_date=entity.death_date,
            category=category,
            role=role,
            ideology_group=mod_group,
            sub_ideology=sub_ideo,
            party_name=entity.parties[0] if entity.parties else "",
            portrait_url=entity.image or "",
        )

    # ------------------------------------------------------------------
    # 정당 슬롯 시스템
    # ------------------------------------------------------------------

    def get_country_party_slots(self, country_tag: str) -> dict[str, dict[str, Any]]:
        """국가의 이데올로기 슬롯별 정당 정보.

        ModPartyRegistry를 우선 사용하고, 없으면 직접 로케일을 파싱한다.

        반환:
        {
            "conservative": {
                "short": "GOP (C)",
                "long": "Republican Party (Conservative)",
                "variants": {"nlp": "NLP(Po)", "nlp_long": "National Liberty Party (Populists)"},
            },
            ...
        }
        """
        # ModPartyRegistry를 통해 가져오기
        registry = self._ideology.party_registry
        slots = registry.get_country_slots(country_tag)
        if slots:
            return slots

        # fallback: 직접 로케일 파싱 (레지스트리에 없는 경우)
        loc_dir = self.mod_root / "localisation" / "english"
        loc_files = list(loc_dir.glob(f"TFR_country_localisation_{country_tag}*_l_english.yml"))

        all_entries: dict[str, str] = {}
        for lf in loc_files:
            entries = self._loc_gen.read_file(lf)
            all_entries.update(entries)

        result: dict[str, dict[str, Any]] = {}
        for group in self._ideology.groups:
            key_short = f"{country_tag}_{group}_party"
            key_long = f"{country_tag}_{group}_party_long"

            short_name = all_entries.get(key_short, "")
            long_name = all_entries.get(key_long, "")

            if short_name or long_name:
                variants: dict[str, str] = {}
                prefix = f"{country_tag}_{group}_party_"
                for k, v in all_entries.items():
                    if k.startswith(prefix) and k != key_long:
                        suffix = k[len(prefix):]
                        if suffix and suffix != "long":
                            variants[suffix] = v

                result[group] = {
                    "short": short_name,
                    "long": long_name,
                    "variants": variants,
                }

        return result

    def update_party_slot(
        self,
        country_tag: str,
        ideology_group: str,
        short_name: str,
        long_name: str = "",
    ) -> bool:
        """국가의 특정 이데올로기 슬롯 정당 이름 업데이트."""
        loc_dir = self.mod_root / "localisation" / "english"
        loc_file = loc_dir / f"TFR_country_localisation_{country_tag}_l_english.yml"

        entries = {
            f"{country_tag}_{ideology_group}_party": short_name,
        }
        if long_name:
            entries[f"{country_tag}_{ideology_group}_party_long"] = long_name

        return self._loc_gen.add_entries(entries, loc_file)

    def sync_parties_from_wiki(
        self, country_tag: str, force_overwrite: bool = False,
    ) -> list[dict[str, str]]:
        """위키에서 국가의 정당을 가져와 자동 추가/수정 + 집권당 판단.

        핵심 원칙: 모드에 이미 정의된 정당이 항상 우선.
        위키는 빈 슬롯만 채우는 보조 역할.

        동작:
        1. 모드 레지스트리에서 기존 정당 슬롯 확인
        2. 위키 정당 → 모드 이데올로기 슬롯 매핑 (레지스트리 우선)
        3. 빈 슬롯만 → 자동 추가 (로케일)
        4. force_overwrite=True일 때만 기존 정당 덮어쓰기
        5. 국가원수의 정당으로 집권당 판단 → set_politics 업데이트

        반환: [{"group": ..., "party": ..., "action": ..., "source": ...}, ...]
        """
        country_qid = self._get_country_qid(country_tag)
        if not country_qid:
            return []

        existing_slots = self.get_country_party_slots(country_tag)
        wiki_parties = self._wikidata.get_political_parties_by_country(country_qid)
        registry = self._ideology.party_registry

        results: list[dict[str, str]] = []
        ruling_group = ""

        # --- 국가원수의 정당으로 집권당 판단 ---
        heads = self._wikidata.get_current_heads_of_state()
        for h in heads:
            h_tag = self._qid_to_tag.get(h.get("country_qid", ""), "")
            if h_tag == country_tag:
                entity = self._wikidata.get_entity_by_qid(h["qid"])
                if entity and entity.parties:
                    for party in entity.parties:
                        group, _ = self._ideology.map_party_to_ideology(
                            party, country_tag=country_tag,
                        )
                        if group:
                            ruling_group = group
                            results.append({
                                "group": group,
                                "party": party,
                                "action": f"ruling (head of state: {entity.label})",
                                "source": "wikidata",
                            })
                            break
                break

        # --- 정당별 슬롯 처리 (모드 레지스트리 우선 매핑) ---
        best_per_group: dict[str, tuple[str, str]] = {}  # group → (party_name, source)

        for party in wiki_parties:
            party_name = party.get("name", "")
            wd_ideology = party.get("ideology", "")

            # 레지스트리 우선 매핑
            mod_group, source = registry.match_wiki_party(
                country_tag, party_name, wd_ideology,
            )

            if not mod_group:
                results.append({
                    "group": "?",
                    "party": party_name,
                    "action": "unmapped",
                    "source": "none",
                })
                continue

            # 같은 그룹에 여러 정당이면 첫 번째만 (주요 정당)
            if mod_group in best_per_group:
                continue
            best_per_group[mod_group] = (party_name, source)

        for mod_group, (party_name, source) in best_per_group.items():
            short = self._make_party_short(party_name)

            if mod_group in existing_slots and existing_slots[mod_group].get("short") and not force_overwrite:
                results.append({
                    "group": mod_group, "party": party_name,
                    "action": f"kept (existing: {existing_slots[mod_group]['short']})",
                    "source": source,
                })
            elif mod_group in existing_slots and existing_slots[mod_group].get("short") and force_overwrite:
                if not self.dry_run:
                    self._update_party_loc(country_tag, mod_group, short, party_name)
                results.append({
                    "group": mod_group, "party": party_name,
                    "action": f"overwritten ({existing_slots[mod_group]['short']} → {short})",
                    "source": source,
                })
            else:
                # 빈 슬롯 → 위키 정당으로 추가
                if not self.dry_run:
                    self.update_party_slot(country_tag, mod_group, short, party_name)
                existing_slots[mod_group] = {"short": short, "long": party_name, "variants": {}}
                results.append({
                    "group": mod_group, "party": party_name,
                    "action": "added",
                    "source": source,
                })

        # --- 집권당 히스토리 업데이트 ---
        if ruling_group and not self.dry_run:
            self._update_ruling_party(country_tag, ruling_group)

        return results

    def _make_party_short(self, party_name: str) -> str:
        """정당 전체 이름 → 약칭 생성."""
        if len(party_name) <= 20:
            return party_name
        words = party_name.split()
        abbr = "".join(w[0] for w in words if w[0].isupper())
        return abbr if len(abbr) >= 2 else party_name[:20]

    def _update_party_loc(
        self, country_tag: str, group: str, short: str, long: str,
    ) -> None:
        """로케일에서 정당 이름 수정 (기존 값 업데이트)."""
        loc_dir = self.mod_root / "localisation" / "english"
        loc_file = loc_dir / f"TFR_country_localisation_{country_tag}_l_english.yml"

        short_key = f"{country_tag}_{group}_party"
        long_key = f"{country_tag}_{group}_party_long"

        self._loc_gen.update_entry(short_key, short, loc_file)
        if long:
            self._loc_gen.update_entry(long_key, long, loc_file)

        # update가 실패하면 (키가 없으면) add로 fallback
        if not self._loc_gen.has_key(short_key, loc_file):
            self._loc_gen.add_entries({short_key: short, long_key: long}, loc_file)

    def _update_ruling_party(self, country_tag: str, ideology_group: str) -> None:
        """히스토리 파일의 set_politics.ruling_party를 업데이트."""
        import re

        hist_dir = self.mod_root / "history" / "countries"
        hist_files = list(hist_dir.glob(f"{country_tag} - *.txt"))
        if not hist_files:
            return

        content = hist_files[0].read_text(encoding="utf-8-sig")

        # ruling_party = XXX 교체
        new_content, count = re.subn(
            r'(ruling_party\s*=\s*)\S+',
            rf'\g<1>{ideology_group}',
            content,
            count=1,
        )

        if count > 0:
            hist_files[0].write_text(new_content, encoding="utf-8")
            logger.info("{}: ruling_party → {}", country_tag, ideology_group)

    # ------------------------------------------------------------------
    # 정보 조회 API
    # ------------------------------------------------------------------

    def get_ideology_info(self) -> dict[str, list[str]]:
        """모드의 이데올로기 구조: {그룹: [서브이데올로기들]}."""
        return {g: self._ideology.get_sub_ideologies(g) for g in self._ideology.groups}

    def get_country_politics(self, country_tag: str) -> dict[str, Any]:
        """국가의 현재 정치 상태 종합."""
        hist_dir = self.mod_root / "history" / "countries"
        histories = self._hist_parser.parse_all_histories(hist_dir)
        data = histories.get(country_tag, {})

        return {
            "ruling_party": data.get("set_politics", {}).get("ruling_party", ""),
            "popularities": data.get("set_popularities", {}),
            "elections": data.get("set_politics", {}).get("elections_allowed", False),
            "recruited": self._hist_parser.get_recruited_characters(data),
            "party_slots": self.get_country_party_slots(country_tag),
        }
