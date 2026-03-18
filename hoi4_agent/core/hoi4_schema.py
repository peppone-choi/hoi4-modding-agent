"""
HOI4 PDX Script 스키마 데이터베이스.
hoi4.paradoxwikis.com/Modding 에서 수집한 공식 레퍼런스 기반.

용도:
- validator가 유효 키/값 검증에 사용
- generator가 파일 생성 시 필수 키 확인에 사용
- web UI가 자동완성 및 도움말에 사용
"""
from __future__ import annotations


# =====================================================================
# 파일 타입별 스키마
# =====================================================================
# 각 파일 타입에 대해:
# - file_path: 해당 파일이 위치하는 경로 패턴
# - wiki_url: 공식 레퍼런스 URL
# - required_keys / optional_keys: 필수/선택 키
# - nested_blocks: 중첩 블록 구조

FILE_SCHEMAS: dict[str, dict] = {
    "character": {
        "file_path": "common/characters/*.txt",
        "wiki_url": "https://hoi4.paradoxwikis.com/Character_modding",
        "root_block": "characters",
        "required_keys": [],
        "entity_keys": {
            "portraits": {
                "civilian": {"large": "str", "small": "str"},
                "army": {"large": "str", "small": "str"},
                "navy": {"large": "str", "small": "str"},
            },
            "gender": ["male", "female", "undefined"],
            "country_leader": {
                "ideology": "str",
                "traits": "list",
                "desc": "str",
                "expire": "str",
            },
            "corps_commander": {
                "skill": "int",
                "attack_skill": "int",
                "defense_skill": "int",
                "planning_skill": "int",
                "logistics_skill": "int",
                "traits": "list",
                "legacy_id": "int",
            },
            "field_marshal": {
                "skill": "int",
                "attack_skill": "int",
                "defense_skill": "int",
                "planning_skill": "int",
                "logistics_skill": "int",
                "traits": "list",
                "legacy_id": "int",
            },
            "navy_leader": {
                "skill": "int",
                "attack_skill": "int",
                "defense_skill": "int",
                "maneuvering_skill": "int",
                "coordination_skill": "int",
                "traits": "list",
                "legacy_id": "int",
            },
            "advisor": {
                "slot": "str",
                "idea_token": "str",
                "traits": "list",
                "cost": "int",
                "allowed": "block",
                "visible": "block",
                "available": "block",
                "ai_will_do": "block",
                "on_add": "block",
                "on_remove": "block",
            },
        },
    },
    "country_history": {
        "file_path": "history/countries/*.txt",
        "wiki_url": "https://hoi4.paradoxwikis.com/Country_creation",
        "required_keys": ["capital"],
        "optional_keys": [
            "oob", "set_oob", "set_naval_oob", "set_air_oob",
            "set_research_slots", "set_stability", "set_war_support",
            "set_convoys", "starting_train_buffer",
            "recruit_character", "add_ideas", "set_technology",
            "set_politics", "set_popularities",
            "create_faction", "add_to_faction",
            "give_guarantee", "diplomatic_relation",
            "set_autonomy", "puppet",
            "add_equipment_to_stockpile",
        ],
        "date_block": True,
    },
    "event": {
        "file_path": "events/*.txt",
        "wiki_url": "https://hoi4.paradoxwikis.com/Event_modding",
        "types": ["country_event", "news_event", "state_event", "unit_leader_event"],
        "required_keys": ["id"],
        "optional_keys": [
            "title", "desc", "picture", "trigger",
            "mean_time_to_happen", "is_triggered_only",
            "fire_only_once", "major", "hidden",
            "immediate", "after", "timeout_days", "show_major",
        ],
        "nested_blocks": {
            "option": {
                "name": "str",
                "trigger": "block",
                "ai_chance": "block",
            },
        },
    },
    "national_focus": {
        "file_path": "common/national_focus/*.txt",
        "wiki_url": "https://hoi4.paradoxwikis.com/National_focus_modding",
        "root_block": "focus_tree",
        "tree_keys": [
            "id", "country", "default",
            "continuous_focus_position", "initial_show_position",
        ],
        "focus_required": ["id", "icon", "x", "y", "cost"],
        "focus_optional": [
            "prerequisite", "mutually_exclusive",
            "available", "bypass", "cancel_if_not_visible",
            "cancel", "ai_will_do", "completion_reward",
            "select_effect", "search_filters",
            "relative_position_id", "dynamic",
        ],
    },
    "decision": {
        "file_path": "common/decisions/*.txt",
        "wiki_url": "https://hoi4.paradoxwikis.com/Decision_modding",
        "category_keys": [
            "allowed", "visible", "available", "icon",
            "priority", "highlight_states", "on_map_area",
            "picture", "scripted_gui",
        ],
        "decision_keys": [
            "allowed", "visible", "available", "icon", "cost",
            "custom_cost_trigger", "custom_cost_text",
            "fire_only_once", "days_re_enable",
            "complete_effect", "remove_effect", "remove_trigger",
            "cancel_trigger", "cancel_effect",
            "modifier", "targeted_modifier",
            "days_remove", "ai_will_do",
            "war_with_on_remove", "war_with_on_complete",
        ],
        "targeted_keys": [
            "targets", "target_trigger",
            "target_array", "target_root_trigger",
        ],
    },
    "idea": {
        "file_path": "common/ideas/*.txt",
        "wiki_url": "https://hoi4.paradoxwikis.com/Idea_modding",
        "root_block": "ideas",
        "categories": ["country", "hidden_ideas"],
        "spirit_keys": [
            "picture", "name", "modifier", "targeted_modifier",
            "research_bonus", "equipment_bonus", "rule",
            "on_add", "on_remove", "cancel",
            "allowed_civil_war", "do_effect",
        ],
        "slot_keys": [
            "allowed", "allowed_to_remove", "visible",
            "available", "cost", "removal_cost",
            "level", "traits", "ledger",
        ],
    },
    "ideology": {
        "file_path": "common/ideologies/*.txt",
        "wiki_url": "https://hoi4.paradoxwikis.com/Ideology_modding",
        "root_block": "ideologies",
        "ideology_keys": [
            "types", "dynamic_faction_names", "color",
            "rules", "war_impact_on_world_tension",
            "faction_impact_on_world_tension",
            "modifiers", "can_be_boosted",
            "can_collaborate", "faction_modifiers",
        ],
    },
    "technology": {
        "file_path": "common/technologies/*.txt",
        "wiki_url": "https://hoi4.paradoxwikis.com/Technology_modding",
        "root_block": "technologies",
        "tech_keys": [
            "research_cost", "start_year", "folder",
            "path", "dependencies", "XOR",
            "sub_technologies", "categories", "doctrine",
            "allow", "allow_branch",
            "on_research_complete", "ai_will_do",
            "enable_equipments", "enable_subunits",
            "enable_equipment_modules", "enable_building",
        ],
    },
    "equipment": {
        "file_path": "common/units/equipment/*.txt",
        "wiki_url": "https://hoi4.paradoxwikis.com/Equipment_modding",
        "root_block": "equipments",
        "archetype_keys": [
            "is_archetype", "is_buildable", "active",
            "year", "type", "group_by",
            "interface_category", "picture", "resources",
        ],
        "equipment_keys": ["archetype", "parent", "priority", "visual_level"],
    },
    "unit": {
        "file_path": "common/units/*.txt",
        "wiki_url": "https://hoi4.paradoxwikis.com/Unit_modding",
        "root_block": "sub_units",
        "unit_keys": [
            "sprite", "map_icon_category", "priority",
            "ai_priority", "active", "group", "type",
            "categories", "essential", "need",
            "transport", "special_forces",
            "marines", "mountaineers", "can_be_parachuted",
        ],
    },
    "building": {
        "file_path": "common/buildings/*.txt",
        "wiki_url": "https://hoi4.paradoxwikis.com/Building_modding",
        "root_block": "buildings",
        "building_keys": [
            "base_cost", "per_level_extra_cost", "icon_frame",
            "value", "show_on_map",
            "infrastructure", "military_production",
            "general_production", "naval_production",
            "air_base", "is_port", "land_fort", "naval_fort",
            "refinery", "nuclear_reactor",
            "level_cap", "damage_factor", "only_costal",
        ],
    },
    "state": {
        "file_path": "history/states/*.txt",
        "wiki_url": "https://hoi4.paradoxwikis.com/State_modding",
        "root_block": "state",
        "required_keys": ["id", "name", "manpower", "state_category", "provinces"],
        "optional_keys": [
            "impassable", "resources",
            "local_supplies", "buildings_max_level_factor",
        ],
        "history_keys": [
            "owner", "controller", "victory_points",
            "buildings", "add_core_of", "add_claim_by",
        ],
    },
    "localisation": {
        "file_path": "localisation/**/*_l_*.yml",
        "wiki_url": "https://hoi4.paradoxwikis.com/Localisation",
        "format": "YAML",
        "encoding": "UTF-8-BOM",
        "structure": 'l_<language>:\\n key:version "value"',
        "special_chars": {
            "§": "color (§R=red §G=green §Y=yellow §B=blue §!=end)",
            "£": "text icon (£GFX_name)",
            "$": "nested string ($loc_key$)",
            "\\n": "newline",
            "[": "scripted localisation / namespace",
        },
    },
    "on_actions": {
        "file_path": "common/on_actions/*.txt",
        "wiki_url": "https://hoi4.paradoxwikis.com/On_actions",
        "root_block": "on_actions",
        "general": ["on_startup", "on_daily", "on_weekly", "on_monthly"],
        "politics": [
            "on_government_change",
            "on_ruling_party_change",
            "on_new_term_election",
        ],
        "diplomacy": [
            "on_declare_war", "on_war", "on_peace",
            "on_capitulation", "on_annex", "on_puppet",
            "on_liberate", "on_civil_war_end",
        ],
        "faction": ["on_create_faction", "on_join_faction", "on_leave_faction"],
        "states": ["on_state_control_changed"],
        "military": ["on_nuke_drop", "on_naval_invasion", "on_paradrop"],
    },
    "ai_modding": {
        "file_path": "common/ai_strategy/*.txt",
        "wiki_url": "https://hoi4.paradoxwikis.com/AI_modding",
        "strategy_types": {
            "diplomatic": [
                "alliance", "antagonize", "befriend",
                "conquer", "contain", "declare_war",
                "ignore", "protect", "support",
            ],
            "military": [
                "invade", "prepare_for_war", "front_control",
                "front_unit_request", "garrison",
                "put_unit_buffers", "area_priority",
            ],
            "naval": [
                "naval_avoid_region",
                "naval_convoy_raid_region",
                "naval_mission_threshold",
            ],
            "production": [
                "build_building", "unit_ratio",
                "equipment_variant_production_factor",
                "production_upgrade_desire_offset",
            ],
        },
    },
    "scripted_gui": {
        "file_path": "common/scripted_guis/*.txt",
        "wiki_url": "https://hoi4.paradoxwikis.com/Scripted_GUI_modding",
        "context_types": [
            "player_context", "selected_country_context",
            "selected_state_context", "decision_category",
            "country_mapicon", "state_mapicon",
        ],
        "blocks": [
            "window_name", "parent_window_token",
            "parent_window_name", "visible",
            "effects", "triggers", "properties",
            "dynamic_lists", "ai_enabled",
            "ai_check", "ai_weights",
        ],
    },
    "portrait": {
        "file_path": "portraits/*.txt",
        "wiki_url": "https://hoi4.paradoxwikis.com/Portrait_modding",
        "size": "156x210",
        "advisor_size": "65x67",
        "gfx_file": "interface/_random_portraits.gfx",
        "roles": ["army", "navy", "political"],
        "gender": ["male", "female"],
    },
    "bookmark": {
        "file_path": "common/bookmarks/*.txt",
        "wiki_url": "https://hoi4.paradoxwikis.com/Bookmark_modding",
        "bookmark_keys": [
            "name", "desc", "date", "picture",
            "default", "default_country", "effect",
        ],
        "country_entry_keys": [
            "history", "ideology", "minor",
            "available", "ideas", "focuses",
        ],
    },
    "autonomous_state": {
        "file_path": "common/autonomous_states/*.txt",
        "wiki_url": "https://hoi4.paradoxwikis.com/Autonomy_state_modding",
        "keys": [
            "id", "default", "is_puppet",
            "use_overlord_color", "min_freedom_level",
            "manpower_influence", "rule", "modifier",
            "allowed", "can_take_level", "can_lose_level",
            "allowed_levels_filter",
        ],
    },
    "balance_of_power": {
        "file_path": "common/bop/*.txt",
        "wiki_url": "https://hoi4.paradoxwikis.com/Balance_of_power_modding",
        "bop_keys": [
            "initial_value", "left_side",
            "right_side", "decision_category",
        ],
        "side_keys": ["id", "icon"],
        "range_keys": [
            "id", "min", "max", "modifier",
            "rule", "on_activate", "on_deactivate",
        ],
    },
    "mio": {
        "file_path": "common/military_industrial_organization/organizations/*.txt",
        "wiki_url": "https://hoi4.paradoxwikis.com/Military_industrial_organization_modding",
        "mio_keys": [
            "name", "icon", "equipment_type",
            "research_categories", "allowed",
            "visible", "available",
            "research_bonus", "task_capacity",
        ],
        "trait_keys": [
            "token", "name", "icon", "position",
            "parent", "any_parent", "all_parents",
            "mutually_exclusive", "available", "visible",
            "equipment_bonus", "production_bonus",
            "organization_modifier",
        ],
    },
    "faction": {
        "file_path": "common/factions/**/*.txt",
        "wiki_url": "https://hoi4.paradoxwikis.com/Faction_modding",
        "effects": [
            "create_faction_from_template",
            "add_to_faction", "remove_from_faction",
            "set_faction_leader", "set_faction_name",
            "add_faction_goal",
        ],
    },
    "doctrine": {
        "file_path": "common/doctrines/**/*.txt",
        "wiki_url": "https://hoi4.paradoxwikis.com/Doctrine_modding",
        "structure": ["folders", "grand_doctrines", "tracks", "subdoctrines"],
    },
    "division": {
        "file_path": "history/units/*.txt",
        "wiki_url": "https://hoi4.paradoxwikis.com/Division_modding",
        "template_keys": [
            "name", "regiments", "support",
            "division_names_group", "is_locked",
            "force_allow_recruiting",
            "division_cap", "priority",
        ],
        "division_keys": [
            "name", "division_name", "location",
            "division_template", "start_experience_factor",
            "start_equipment_factor", "force_equipment_variants",
        ],
    },
    "resource": {
        "file_path": "common/resources/*.txt",
        "wiki_url": "https://hoi4.paradoxwikis.com/Resources_modding",
        "root_block": "resources",
        "keys": ["icon_frame", "cic", "convoys"],
    },
    "map": {
        "file_path": "map/*",
        "wiki_url": "https://hoi4.paradoxwikis.com/Map_modding",
        "files": {
            "provinces.bmp": "24-bit RGB province borders",
            "definition.csv": "Province ID;R;G;B;type;coastal;terrain;continent",
            "terrain.bmp": "8-bit indexed terrain textures",
            "heightmap.bmp": "8-bit greyscale height",
            "buildings.txt": "Building model positions",
            "adjacencies.csv": "Province adjacencies",
            "supply_nodes.txt": "Supply node positions",
            "railways.txt": "Railway connections",
        },
    },
    "strategic_region": {
        "file_path": "map/strategicregions/*.txt",
        "wiki_url": "https://hoi4.paradoxwikis.com/Strategic_region_modding",
        "keys": ["id", "name", "provinces", "naval_terrain"],
        "weather_keys": [
            "between", "temperature", "no_phenomenon",
            "rain_light", "rain_heavy", "snow",
            "blizzard", "mud", "sandstorm", "min_snow_level",
        ],
    },
    "interface": {
        "file_path": "interface/*.gui",
        "wiki_url": "https://hoi4.paradoxwikis.com/Interface_modding",
        "elements": [
            "containerWindowType", "iconType",
            "instantTextBoxType", "buttonType",
            "smoothListboxType", "checkboxType",
            "editBoxType", "OverlappingElementsBoxType",
        ],
        "gfx_types": [
            "spriteType", "frameAnimatedSpriteType",
            "progressbartype", "corneredTileSpriteType",
            "maskedShieldType",
        ],
    },
    "cosmetic_tag": {
        "file_path": "common/countries/cosmetic.txt",
        "wiki_url": "https://hoi4.paradoxwikis.com/Cosmetic_tag_modding",
        "effects": ["set_cosmetic_tag", "drop_cosmetic_tag"],
        "localisation_pattern": 'COSMETICTAG_ideology: "Name"',
    },
    "achievement": {
        "file_path": "common/achievements/*.txt",
        "wiki_url": "https://hoi4.paradoxwikis.com/Achievement_modding",
        "keys": ["unique_id", "possible", "happened"],
        "types": ["custom_achievement", "custom_ribbon"],
    },
    "mod_structure": {
        "file_path": "*.mod",
        "wiki_url": "https://hoi4.paradoxwikis.com/Mod_structure",
        "mod_keys": [
            "name", "path", "tags", "picture",
            "supported_version", "version", "dependencies",
        ],
    },
}


# =====================================================================
# 스코프 시스템
# =====================================================================

SCOPES: dict[str, dict | list] = {
    "dual": [
        "TAG", "state_id", "character_id",
        "ROOT", "THIS", "PREV", "FROM",
        "PREV.PREV", "PREV.PREV.PREV",
        "FROM.FROM", "FROM.FROM.FROM",
        "overlord", "faction_leader",
        "owner", "controller", "capital_scope",
        "event_target:", "var:", "mio:", "sp:",
    ],
    "trigger_only": {
        "country": [
            "all_country", "any_country",
            "all_other_country", "any_other_country",
            "all_neighbor_country", "any_neighbor_country",
            "all_allied_country", "any_allied_country",
            "all_enemy_country", "any_enemy_country",
            "all_subject_countries", "any_subject_country",
            "all_guaranteed_country", "any_guaranteed_country",
        ],
        "state": [
            "all_state", "any_state",
            "all_neighbor_state", "any_neighbor_state",
            "all_owned_state", "any_owned_state",
            "all_core_state", "any_core_state",
            "all_controlled_state", "any_controlled_state",
        ],
        "character": [
            "all_character", "any_character",
            "all_unit_leader", "any_unit_leader",
            "all_army_leader", "any_army_leader",
            "all_navy_leader", "any_navy_leader",
        ],
    },
    "effect_only": {
        "country": [
            "every_country", "random_country",
            "every_other_country", "random_other_country",
            "every_neighbor_country", "random_neighbor_country",
            "every_enemy_country", "random_enemy_country",
            "every_allied_country", "random_allied_country",
        ],
        "state": [
            "every_state", "random_state",
            "every_neighbor_state", "random_neighbor_state",
            "every_owned_state", "random_owned_state",
            "every_core_state", "random_core_state",
            "every_controlled_state", "random_controlled_state",
            "random_owned_controlled_state",
        ],
        "character": [
            "every_character", "random_character",
            "every_unit_leader", "random_unit_leader",
            "every_army_leader", "random_army_leader",
            "every_navy_leader", "random_navy_leader",
        ],
    },
    "flow_control": [
        "AND", "OR", "NOT",
        "if", "else_if", "else",
        "hidden_trigger", "hidden_effect",
        "custom_trigger_tooltip", "custom_effect_tooltip",
        "count_triggers", "random_list",
    ],
}


# =====================================================================
# Modifier 카테고리
# =====================================================================

MODIFIER_CATEGORIES: dict[str, list[str]] = {
    "politics": [
        "political_power_gain", "political_power_factor",
        "political_power_cost", "stability_factor",
        "stability_weekly", "war_support_factor",
        "war_support_weekly", "drift_defence_factor",
        "command_power_gain", "command_power_gain_mult",
    ],
    "military_general": [
        "army_org", "army_org_factor",
        "army_morale", "army_morale_factor",
        "army_attack_factor", "army_defence_factor",
        "army_speed_factor", "max_planning",
        "planning_speed", "supply_consumption_factor",
        "training_time_factor", "max_dig_in",
        "recon_factor", "experience_gain_factor",
    ],
    "production": [
        "production_speed_buildings_factor",
        "consumer_goods_factor", "research_speed_factor",
        "industrial_capacity_factory",
        "industrial_capacity_dockyard",
        "line_change_production_efficiency_factor",
        "production_factory_max_efficiency_factor",
    ],
    "diplomacy": [
        "trade_opinion_factor", "justify_war_goal_time",
        "send_volunteer_size", "guarantee_cost",
        "improve_relations_maintain_cost_factor",
        "opinion_gain_monthly_factor",
    ],
    "air": [
        "air_attack_factor", "air_defence_factor",
        "air_agility_factor", "air_range_factor",
        "air_bombing_targetting", "air_superiority_efficiency",
        "air_ace_generation_chance_factor",
    ],
    "naval": [
        "naval_speed_factor", "naval_damage_factor",
        "naval_defense_factor", "navy_org_factor",
        "submarine_attack", "convoy_escort_efficiency",
        "convoy_raiding_efficiency_factor",
    ],
    "conscription": [
        "conscription", "conscription_factor",
        "recruitable_population", "weekly_manpower",
        "monthly_population",
    ],
    "intelligence": [
        "operative_slot", "intel_from_operatives_factor",
        "decryption_factor", "encryption_factor",
        "crypto_department_enabled",
    ],
}


# =====================================================================
# Defines 카테고리
# =====================================================================

DEFINE_CATEGORIES: list[str] = [
    "NGame", "NGeography", "NDiplomacy", "NCountry", "NResistance",
    "NProduction", "NMarket", "NTechnology", "NPolitics", "NBuildings",
    "NDeployment", "NMilitary", "NAir", "NNavy", "NTrade", "NAI",
    "NFocus", "NOperatives", "NIntel", "NCharacter", "NSupply",
    "NIndustrialOrganisation", "NProject", "NGraphics", "NInterface",
]


# =====================================================================
# 자동화 가능성 등급
# =====================================================================

AUTOMATION_TIERS: dict[str, dict] = {
    "full_auto": {
        "description": "완전 자동화 — 파서/생성기로 읽고 쓸 수 있음",
        "file_types": [
            "character", "country_history", "localisation",
            "state", "ideology", "portrait",
            "bookmark", "cosmetic_tag",
            "resource", "autonomous_state", "mod_structure",
        ],
    },
    "template_auto": {
        "description": "템플릿 기반 자동화 — 구조가 반복적이므로 템플릿으로 생성 가능",
        "file_types": [
            "event", "decision", "idea", "on_actions",
            "scripted_gui", "balance_of_power", "achievement",
            "ai_modding", "faction", "doctrine", "division",
        ],
    },
    "assisted": {
        "description": "AI 보조 편집 — 복잡한 의존성이 있어 사람의 판단이 필요",
        "file_types": [
            "national_focus", "technology", "equipment",
            "unit", "building", "mio", "strategic_region",
        ],
    },
    "manual": {
        "description": "수동이 나음 — 바이너리 또는 비주얼 데이터",
        "file_types": ["map", "interface"],
    },
}


# =====================================================================
# 유틸리티 함수
# =====================================================================

def get_schema(file_type: str) -> dict | None:
    """파일 타입의 스키마 반환."""
    return FILE_SCHEMAS.get(file_type)


def get_wiki_url(file_type: str) -> str:
    """파일 타입의 공식 위키 URL 반환."""
    schema = FILE_SCHEMAS.get(file_type, {})
    return schema.get("wiki_url", "")


def get_automation_tier(file_type: str) -> str:
    """파일 타입의 자동화 가능성 등급 반환."""
    for tier_name, tier_data in AUTOMATION_TIERS.items():
        if file_type in tier_data["file_types"]:
            return tier_name
    return "unknown"


def get_all_file_types() -> list[str]:
    """모든 파일 타입 이름 목록."""
    return sorted(FILE_SCHEMAS.keys())


def get_full_auto_types() -> list[str]:
    """완전 자동화 가능한 파일 타입 목록."""
    return AUTOMATION_TIERS["full_auto"]["file_types"]


def get_template_auto_types() -> list[str]:
    """템플릿 자동화 가능한 파일 타입 목록."""
    return AUTOMATION_TIERS["template_auto"]["file_types"]


DIRECTORY_SCHEMA = {
    "common/": {
        "purpose": "Game rules, definitions, and static data",
        "description": "Common game elements like ideologies, focuses, decisions, modifiers",
        "subdirs": {
            "characters/": {
                "purpose": "Character definitions",
                "description": "Leader, general, admiral, and advisor definitions",
                "file_pattern": "*.txt",
                "content_type": "character",
                "example_keys": ["portraits", "country_leader", "corps_commander", "advisor"],
            },
            "national_focus/": {
                "purpose": "National focus trees",
                "description": "Country-specific focus tree definitions",
                "file_pattern": "*.txt",
                "content_type": "focus",
                "example_keys": ["focus_tree", "id", "icon", "prerequisite", "mutually_exclusive"],
            },
            "ideologies/": {
                "purpose": "Political ideology definitions",
                "description": "Ideology types, groups, and modifiers",
                "file_pattern": "*.txt",
                "content_type": "ideology",
                "example_keys": ["ideologies", "types", "modifiers"],
            },
            "ideas/": {
                "purpose": "National spirits and advisors",
                "description": "Country-specific ideas, buffs, and debuffs",
                "file_pattern": "*.txt",
                "content_type": "idea",
                "example_keys": ["ideas", "cost", "removal_cost", "modifier"],
            },
            "decisions/": {
                "purpose": "Decision categories and actions",
                "description": "Player decisions, missions, and one-time actions",
                "file_pattern": "*.txt",
                "content_type": "decision",
                "example_keys": ["decisions", "available", "visible", "complete_effect"],
            },
            "country_tags/": {
                "purpose": "Country tag definitions",
                "description": "Maps country tags (USA, SOV) to country files",
                "file_pattern": "*.txt",
                "content_type": "country_tag",
                "example_keys": ["USA", "SOV", "GER"],
            },
            "on_actions/": {
                "purpose": "Event triggers on game events",
                "description": "Scripts that fire when specific game events occur",
                "file_pattern": "*.txt",
                "content_type": "on_action",
                "example_keys": ["on_startup", "on_war", "on_capitulation"],
            },
        },
    },
    "events/": {
        "purpose": "Event definitions",
        "description": "Country events, news events, and story-driven content",
        "file_pattern": "*.txt",
        "content_type": "event",
        "example_keys": ["country_event", "news_event", "id", "title", "desc", "option"],
    },
    "history/": {
        "purpose": "Initial game state and historical data",
        "description": "Starting conditions for countries, states, and units",
        "subdirs": {
            "countries/": {
                "purpose": "Country starting conditions",
                "description": "Initial politics, technology, leaders, and resources",
                "file_pattern": "*.txt",
                "content_type": "country_history",
                "example_keys": ["capital", "oob", "set_politics", "set_technology", "recruit_character"],
            },
            "states/": {
                "purpose": "State (province) definitions",
                "description": "State borders, resources, buildings, and ownership",
                "file_pattern": "*.txt",
                "content_type": "state",
                "example_keys": ["id", "name", "provinces", "manpower", "buildings"],
            },
            "units/": {
                "purpose": "Order of battle (OOB) files",
                "description": "Starting military unit positions and compositions",
                "file_pattern": "*.txt",
                "content_type": "oob",
                "example_keys": ["division_template", "units", "instant_effect"],
            },
        },
    },
    "gfx/": {
        "purpose": "Graphics and visual assets",
        "description": "Portraits, flags, UI elements, and sprites",
        "subdirs": {
            "leaders/": {
                "purpose": "Leader portraits",
                "description": "PNG/TGA files for leaders and advisors",
                "file_pattern": "*.png, *.tga, *.dds",
                "content_type": "image",
            },
            "flags/": {
                "purpose": "Country flags",
                "description": "Small, medium, and large flag variants",
                "file_pattern": "*.tga",
                "content_type": "image",
            },
            "interface/": {
                "purpose": "UI graphics",
                "description": "Buttons, backgrounds, and interface elements",
                "file_pattern": "*.dds, *.png",
                "content_type": "image",
            },
        },
    },
    "localisation/": {
        "purpose": "Localized text strings",
        "description": "Translations for events, names, and UI elements",
        "subdirs": {
            "english/": {
                "purpose": "English localization",
                "description": "English text strings",
                "file_pattern": "*_l_english.yml",
                "content_type": "localisation",
                "example_keys": ["l_english:", "KEY:0"],
            },
        },
    },
    "interface/": {
        "purpose": "UI layout definitions",
        "description": "GFX sprite definitions and GUI layouts",
        "file_pattern": "*.gfx, *.gui",
        "content_type": "interface",
        "example_keys": ["spriteTypes", "guiTypes", "containerWindowType"],
    },
    "portraits/": {
        "purpose": "Portrait assignment",
        "description": "Links character IDs to portrait files",
        "file_pattern": "*.txt",
        "content_type": "portrait_definition",
        "example_keys": ["character", "small", "large", "army", "navy"],
    },
    "music/": {
        "purpose": "Music and sound files",
        "description": "Background music, sound effects",
        "file_pattern": "*.ogg, *.mp3",
        "content_type": "audio",
    },
}


def get_directory_info(path: str) -> dict | None:
    """Get metadata about a HOI4 mod directory.
    
    Args:
        path: Relative path like "events/" or "common/characters/"
        
    Returns:
        Directory metadata dict or None if not found
    """
    normalized = path.rstrip("/") + "/"
    
    if normalized in DIRECTORY_SCHEMA:
        return DIRECTORY_SCHEMA[normalized]
    
    for parent, data in DIRECTORY_SCHEMA.items():
        if "subdirs" in data and normalized in data["subdirs"]:
            return data["subdirs"][normalized]
    
    return None


def get_all_known_directories() -> list[str]:
    """Get all known HOI4 mod directory paths."""
    dirs = list(DIRECTORY_SCHEMA.keys())
    
    for parent_data in DIRECTORY_SCHEMA.values():
        if "subdirs" in parent_data:
            dirs.extend(parent_data["subdirs"].keys())
    
    return sorted(dirs)
