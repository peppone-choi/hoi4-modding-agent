"""정당→이념 매핑 엔진. 다층 신뢰도 기반 매핑을 제공한다."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from loguru import logger

from tools.shared.constants import MAIN_IDEOLOGY_GROUPS


@dataclass
class PartyMapping:
    party_name: str
    country_tag: str = ""
    ideology_group: str = ""
    sub_ideology: str = ""
    confidence: float = 0.0
    source: str = ""
    needs_review: bool = False
    alternatives: list[dict[str, Any]] = field(default_factory=list)


# =====================================================================
# Layer 1: Exact match table
# =====================================================================

EXACT_MATCH: dict[str, tuple[str, str, str]] = {
    # === Americas === (group, sub_ideology, country_tag)
    "Republican Party": ("conservative", "right_populism", "USA"),
    "Democratic Party": ("social_liberal", "progressivism", "USA"),
    "Libertarian Party": ("market_liberal", "libertarianism", "USA"),
    "Democratic Socialists of America": ("libertarian_socialist", "reformist_socialism", "USA"),
    "Green Party": ("social_democrat", "green_politics", "USA"),
    "Constitution Party": ("authoritarian_democrat", "classical_conservatism", "USA"),
    "Party for Socialism and Liberation": ("communist", "marxism_leninism", "USA"),
    "Communist Party USA": ("communist", "marxism_leninism", "USA"),
    "America First Party": ("nationalist", "civic_nationalism", "USA"),
    "Patriot Front": ("fascist", "fascism", "USA"),
    "National Socialist Movement": ("national_socialist", "neonazism", "USA"),
    "Workers World Party": ("communist", "marxism_leninism", "USA"),
    "Socialist Workers Party": ("totalitarian_socialist", "trotskyism", "USA"),
    "Liberal Party of Canada": ("social_liberal", "liberalism", "CAN"),
    "Conservative Party of Canada": ("conservative", "conservatism", "CAN"),
    "New Democratic Party": ("social_democrat", "social_democracy", "CAN"),
    "Bloc Québécois": ("social_democrat", "left_populism", "CAN"),
    "People's Party of Canada": ("market_liberal", "libertarianism", "CAN"),
    "Green Party of Canada": ("social_democrat", "green_politics", "CAN"),
    "Morena": ("social_democrat", "left_populism", "MEX"),
    "National Action Party": ("conservative", "christian_democracy", "MEX"),
    "Institutional Revolutionary Party": ("authoritarian_democrat", "auth_populism", "MEX"),
    "Citizens' Movement": ("social_liberal", "liberalism", "MEX"),
    "Workers' Party": ("social_democrat", "left_populism", "BRA"),
    "Liberal Party": ("conservative", "right_populism", "BRA"),
    "Brazilian Social Democracy Party": ("social_liberal", "liberalism", "BRA"),
    "Progressistas": ("conservative", "conservatism", "BRA"),
    "Brazilian Communist Party": ("communist", "marxism_leninism", "BRA"),
    "Socialism and Liberty Party": ("libertarian_socialist", "eco_socialism", "BRA"),
    "Peronist Party": ("social_democrat", "left_populism", "ARG"),
    "Justicialist Party": ("social_democrat", "left_populism", "ARG"),
    "Radical Civic Union": ("social_liberal", "liberalism", "ARG"),
    "Republican Proposal": ("conservative", "conservatism", "ARG"),
    "La Libertad Avanza": ("market_liberal", "libertarianism", "ARG"),
    "Independent Democratic Union": ("conservative", "conservatism", "CHL"),
    "Socialist Party of Chile": ("social_democrat", "social_democracy", "CHL"),
    "Chile Vamos": ("conservative", "conservatism", "CHL"),
    "Broad Front": ("social_democrat", "social_democracy", "CHL"),
    "United Socialist Party of Venezuela": ("totalitarian_socialist", "bolivarianism", "VEN"),
    "Democratic Unity Roundtable": ("social_liberal", "liberalism", "VEN"),
    "Communist Party of Cuba": ("totalitarian_socialist", "marxism_leninism", "CUB"),
    "Historic Pact": ("social_democrat", "left_populism", "COL"),
    "Democratic Center": ("conservative", "conservatism", "COL"),
    "Free Peru": ("communist", "marxism_leninism", "PRU"),
    "Popular Force": ("conservative", "right_populism", "PRU"),
    "Citizens' Revolution": ("social_democrat", "left_populism", "ECU"),
    "Movement for Socialism": ("libertarian_socialist", "eco_socialism", "BOL"),
    # === Europe - Western ===
    "Labour Party": ("social_democrat", "social_democracy", "ENG"),
    "Conservative Party": ("conservative", "conservatism", "ENG"),
    "Liberal Democrats": ("social_liberal", "liberalism", "ENG"),
    "Scottish National Party": ("social_democrat", "left_populism", "ENG"),
    "Reform UK": ("authoritarian_democrat", "right_populism", "ENG"),
    "Sinn Féin": ("libertarian_socialist", "left_populism", "IRE"),
    "Democratic Unionist Party": ("conservative", "conservatism", "ENG"),
    "Plaid Cymru": ("social_democrat", "left_populism", "ENG"),
    "UK Independence Party": ("nationalist", "civic_nationalism", "ENG"),
    "British National Party": ("fascist", "fascism", "ENG"),
    "Social Democratic Party of Germany": ("social_democrat", "social_democracy", "GER"),
    "Christian Democratic Union of Germany": ("conservative", "christian_democracy", "GER"),
    "Christian Social Union in Bavaria": ("conservative", "christian_democracy", "GER"),
    "Alliance 90/The Greens": ("social_democrat", "green_politics", "GER"),
    "Free Democratic Party": ("market_liberal", "liberalism", "GER"),
    "Alternative for Germany": ("nationalist", "radical_nationalism", "GER"),
    "The Left": ("libertarian_socialist", "reformist_socialism", "GER"),
    "Sahra Wagenknecht Alliance": ("social_democrat", "left_populism", "GER"),
    "National Democratic Party of Germany": ("national_socialist", "neonazism", "GER"),
    "Renaissance": ("social_liberal", "liberalism", "FRA"),
    "National Rally": ("nationalist", "radical_nationalism", "FRA"),
    "La France Insoumise": ("libertarian_socialist", "left_populism", "FRA"),
    "Les Républicains": ("conservative", "conservatism", "FRA"),
    "Reconquête": ("fascist", "identitarianism", "FRA"),
    "French Communist Party": ("communist", "marxism_leninism", "FRA"),
    "Rassemblement National": ("nationalist", "radical_nationalism", "FRA"),
    "Socialist Party": ("social_democrat", "social_democracy", "FRA"),
    "Europe Ecology – The Greens": ("social_democrat", "green_politics", "FRA"),
    "New Popular Front": ("libertarian_socialist", "left_populism", "FRA"),
    "People's Party for Freedom and Democracy": ("market_liberal", "liberalism", "HOL"),
    "Party for Freedom": ("nationalist", "radical_nationalism", "HOL"),
    "GreenLeft": ("social_democrat", "green_politics", "HOL"),
    "Democrats 66": ("social_liberal", "liberalism", "HOL"),
    "Christian Democratic Appeal": ("conservative", "christian_democracy", "HOL"),
    "Forum for Democracy": ("fascist", "identitarianism", "HOL"),
    "New Flemish Alliance": ("conservative", "conservatism", "BEL"),
    "Vlaams Belang": ("nationalist", "radical_nationalism", "BEL"),
    "Open Flemish Liberals and Democrats": ("market_liberal", "liberalism", "BEL"),
    "Swiss People's Party": ("nationalist", "civic_nationalism", "SWI"),
    "Social Democratic Party of Switzerland": ("social_democrat", "social_democracy", "SWI"),
    "FDP.The Liberals": ("market_liberal", "liberalism", "SWI"),
    "Austrian People's Party": ("conservative", "christian_democracy", "AUS"),
    "Freedom Party of Austria": ("nationalist", "radical_nationalism", "AUS"),
    "Social Democratic Party of Austria": ("social_democrat", "social_democracy", "AUS"),
    "NEOS": ("market_liberal", "liberalism", "AUS"),
    # === Europe - Nordic ===
    "Swedish Social Democratic Party": ("social_democrat", "social_democracy", "SWE"),
    "Moderate Party": ("conservative", "conservatism", "SWE"),
    "Sweden Democrats": ("nationalist", "civic_nationalism", "SWE"),
    "Left Party": ("libertarian_socialist", "reformist_socialism", "SWE"),
    "Centre Party": ("market_liberal", "centrism", "SWE"),
    "Norwegian Labour Party": ("social_democrat", "social_democracy", "NOR"),
    "Conservative Party of Norway": ("conservative", "conservatism", "NOR"),
    "Progress Party": ("market_liberal", "libertarianism", "NOR"),
    "Social Democrats": ("social_democrat", "social_democracy", "DEN"),
    "Danish People's Party": ("nationalist", "civic_nationalism", "DEN"),
    "Venstre": ("market_liberal", "liberalism", "DEN"),
    "Red-Green Alliance": ("libertarian_socialist", "eco_socialism", "DEN"),
    "National Coalition Party": ("conservative", "conservatism", "FIN"),
    "Social Democratic Party of Finland": ("social_democrat", "social_democracy", "FIN"),
    "Finns Party": ("nationalist", "civic_nationalism", "FIN"),
    "Green League": ("social_democrat", "green_politics", "FIN"),
    "Left Alliance": ("libertarian_socialist", "reformist_socialism", "FIN"),
    # === Europe - Southern ===
    "Brothers of Italy": ("nationalist", "civic_nationalism", "ITA"),
    "Lega": ("authoritarian_democrat", "right_populism", "ITA"),
    "Five Star Movement": ("social_democrat", "left_populism", "ITA"),
    "Forza Italia": ("conservative", "conservatism", "ITA"),
    "Democratic Party": ("social_democrat", "social_democracy", "ITA"),
    "CasaPound": ("fascist", "fascism", "ITA"),
    "Spanish Socialist Workers' Party": ("social_democrat", "social_democracy", "SPR"),
    "People's Party": ("conservative", "conservatism", "SPR"),
    "Vox": ("nationalist", "radical_nationalism", "SPR"),
    "Sumar": ("libertarian_socialist", "left_populism", "SPR"),
    "Podemos": ("libertarian_socialist", "eco_socialism", "SPR"),
    "Ciudadanos": ("market_liberal", "liberalism", "SPR"),
    "Esquerra Republicana de Catalunya": ("social_democrat", "left_populism", "SPR"),
    "Socialist Party of Portugal": ("social_democrat", "social_democracy", "POR"),
    "Social Democratic Party of Portugal": ("conservative", "conservatism", "POR"),
    "Chega": ("nationalist", "radical_nationalism", "POR"),
    "Portuguese Communist Party": ("communist", "marxism_leninism", "POR"),
    "Left Bloc": ("libertarian_socialist", "eco_socialism", "POR"),
    "Syriza": ("libertarian_socialist", "reformist_socialism", "GRE"),
    "New Democracy": ("conservative", "conservatism", "GRE"),
    "Communist Party of Greece": ("communist", "marxism_leninism", "GRE"),
    "Golden Dawn": ("national_socialist", "neonazism", "GRE"),
    "Greek Solution": ("nationalist", "civic_nationalism", "GRE"),
    # === Europe - Eastern ===
    "United Russia": ("authoritarian_democrat", "sovereign_democracy", "SOV"),
    "Communist Party of the Russian Federation": ("communist", "marxism_leninism", "SOV"),
    "Liberal Democratic Party of Russia": ("nationalist", "radical_nationalism", "SOV"),
    "A Just Russia": ("social_democrat", "social_democracy", "SOV"),
    "New People": ("market_liberal", "liberalism", "SOV"),
    "Yabloko": ("social_liberal", "liberalism", "SOV"),
    "Servant of the People": ("social_liberal", "liberalism", "UKR"),
    "European Solidarity": ("conservative", "conservatism", "UKR"),
    "Opposition Platform — For Life": ("authoritarian_democrat", "sovereign_democracy", "UKR"),
    "Batkivshchyna": ("conservative", "conservatism", "UKR"),
    "Svoboda": ("nationalist", "radical_nationalism", "UKR"),
    "Right Sector": ("fascist", "fascism", "UKR"),
    "Azov Movement": ("national_socialist", "neonazism", "UKR"),
    "Law and Justice": ("authoritarian_democrat", "auth_populism", "POL"),
    "Civic Platform": ("social_liberal", "liberalism", "POL"),
    "Confederation Liberty and Independence": ("nationalist", "civic_nationalism", "POL"),
    "Belaya Rus": ("authoritarian_democrat", "sovereign_democracy", "BLR"),
    "Fidesz": ("authoritarian_democrat", "auth_populism", "HUN"),
    "Jobbik": ("nationalist", "radical_nationalism", "HUN"),
    "Democratic Coalition": ("social_liberal", "liberalism", "HUN"),
    "Mi Hazánk": ("fascist", "fascism", "HUN"),
    "ANO 2011": ("market_liberal", "centrism", "CZE"),
    "Civic Democratic Party": ("conservative", "conservatism", "CZE"),
    "Freedom and Direct Democracy": ("nationalist", "civic_nationalism", "CZE"),
    "Social Democracy Party": ("social_democrat", "social_democracy", "ROM"),
    "Alliance for the Union of Romanians": ("nationalist", "radical_nationalism", "ROM"),
    "Serbian Progressive Party": ("authoritarian_democrat", "sovereign_democracy", "SER"),
    "Serbian Radical Party": ("nationalist", "radical_nationalism", "SER"),
    "Croatian Democratic Union": ("conservative", "christian_democracy", "CRO"),
    "Social Democratic Party of Croatia": ("social_democrat", "social_democracy", "CRO"),
    "GERB": ("conservative", "conservatism", "BUL"),
    "Revival": ("nationalist", "radical_nationalism", "BUL"),
    "Bulgarian Socialist Party": ("social_democrat", "social_democracy", "BUL"),
    # === East Asia ===
    "Chinese Communist Party": ("totalitarian_socialist", "maoism", "PRC"),
    "Communist Party of China": ("totalitarian_socialist", "maoism", "PRC"),
    "Kuomintang": ("conservative", "conservatism", "CHI"),
    "Workers' Party of Korea": ("totalitarian_socialist", "jucheism", "PRK"),
    "Korean Workers' Party": ("totalitarian_socialist", "jucheism", "PRK"),
    "People Power Party": ("conservative", "conservatism", "KOR"),
    "Democratic Party of Korea": ("social_liberal", "liberalism", "KOR"),
    "Rebuilding Korea Party": ("conservative", "right_populism", "KOR"),
    "Reform Party": ("market_liberal", "liberalism", "KOR"),
    "Justice Party": ("social_democrat", "progressivism", "KOR"),
    "Liberal Democratic Party": ("conservative", "conservatism", "JAP"),
    "Constitutional Democratic Party": ("social_democrat", "social_democracy", "JAP"),
    "Nippon Ishin no Kai": ("market_liberal", "liberalism", "JAP"),
    "Japanese Communist Party": ("communist", "marxism_leninism", "JAP"),
    "Komeito": ("conservative", "christian_democracy", "JAP"),
    "Reiwa Shinsengumi": ("social_democrat", "left_populism", "JAP"),
    "Democratic Progressive Party": ("social_liberal", "liberalism", "CHI"),
    "Communist Party of Vietnam": ("totalitarian_socialist", "marxism_leninism", "VIN"),
    "Lao People's Revolutionary Party": ("totalitarian_socialist", "marxism_leninism", "LAO"),
    "Cambodian People's Party": ("authoritarian_democrat", "autocracy", "CAM"),
    "Myanmar's National League for Democracy": ("social_liberal", "liberalism", "MYA"),
    "Union Solidarity and Development Party": ("authoritarian_democrat", "autocracy", "MYA"),
    # === South/Southeast Asia ===
    "Bharatiya Janata Party": ("nationalist", "civic_nationalism", "RAJ"),
    "Indian National Congress": ("social_liberal", "liberalism", "RAJ"),
    "Communist Party of India (Marxist)": ("communist", "marxism_leninism", "RAJ"),
    "Communist Party of India": ("communist", "marxism_leninism", "RAJ"),
    "Aam Aadmi Party": ("social_democrat", "left_populism", "RAJ"),
    "Bahujan Samaj Party": ("social_democrat", "social_democracy", "RAJ"),
    "Rashtriya Swayamsevak Sangh": ("fascist", "hindutva", "RAJ"),
    "Pakistan Tehreek-e-Insaf": ("conservative", "right_populism", "PAK"),
    "Pakistan Muslim League (N)": ("conservative", "conservatism", "PAK"),
    "Pakistan Peoples Party": ("social_democrat", "social_democracy", "PAK"),
    "Jamaat-e-Islami": ("nationalist", "wahhabism", "PAK"),
    "Awami League": ("social_democrat", "social_democracy", "BAN"),
    "Bangladesh Nationalist Party": ("conservative", "conservatism", "BAN"),
    "Pheu Thai Party": ("social_democrat", "left_populism", "SIA"),
    "Move Forward Party": ("social_liberal", "liberalism", "SIA"),
    "Palang Pracharath Party": ("authoritarian_democrat", "autocracy", "SIA"),
    "Gerindra": ("conservative", "right_populism", "INS"),
    "PDI-P": ("social_democrat", "left_populism", "INS"),
    "Golkar": ("authoritarian_democrat", "sovereign_democracy", "INS"),
    "Prosperous Justice Party": ("nationalist", "wahhabism", "INS"),
    "Barisan Nasional": ("conservative", "conservatism", "MAL"),
    "Pakatan Harapan": ("social_liberal", "liberalism", "MAL"),
    "Malaysian Islamic Party": ("nationalist", "wahhabism", "MAL"),
    "People's Action Party": ("authoritarian_democrat", "sovereign_democracy", "SIN"),
    "Workers' Party of Singapore": ("social_democrat", "social_democracy", "SIN"),
    "Marcos Coalition": ("authoritarian_democrat", "auth_populism", "PHI"),
    "Liberal Party of the Philippines": ("social_liberal", "liberalism", "PHI"),
    "Aksyon Demokratiko": ("social_liberal", "liberalism", "PHI"),
    # === Middle East ===
    "Justice and Development Party": ("authoritarian_democrat", "conservative_democracy", "TUR"),
    "Republican People's Party": ("social_democrat", "social_democracy", "TUR"),
    "Peoples' Democratic Party": ("libertarian_socialist", "reformist_socialism", "TUR"),
    "Nationalist Movement Party": ("nationalist", "radical_nationalism", "TUR"),
    "Good Party": ("conservative", "conservatism", "TUR"),
    "Grey Wolves": ("fascist", "fascism", "TUR"),
    "Combatant Clergy Association": ("authoritarian_democrat", "theocracy", "PER"),
    "Society of Seminary Teachers of Qom": ("authoritarian_democrat", "theocracy", "PER"),
    "Mojahedin-e Khalq": ("libertarian_socialist", "eco_socialism", "PER"),
    "Tudeh Party of Iran": ("communist", "marxism_leninism", "PER"),
    "House of Saud": ("authoritarian_democrat", "monarchy", "SAU"),
    "Hezbollah": ("nationalist", "wahhabism", "LEB"),
    "Amal Movement": ("authoritarian_democrat", "theocracy", "LEB"),
    "Hamas": ("nationalist", "wahhabism", "PAL"),
    "Fatah": ("authoritarian_democrat", "auth_populism", "PAL"),
    "Palestinian Islamic Jihad": ("fascist", "wahhabism", "PAL"),
    "Taliban": ("fascist", "wahhabism", "AFG"),
    "Baath Party": ("authoritarian_democrat", "left_baathism", "SYR"),
    "Arab Socialist Ba'ath Party": ("authoritarian_democrat", "left_baathism", "SYR"),
    "Iraqi Baath Party": ("authoritarian_democrat", "left_baathism", "IRQ"),
    "Syrian Social Nationalist Party": ("fascist", "fascism", "SYR"),
    "Kurdistan Workers' Party": ("libertarian_socialist", "eco_socialism", "TUR"),
    "Peshmerga": ("conservative", "conservatism", "IRQ"),
    "Houthis": ("nationalist", "wahhabism", "YEM"),
    "Ansar Allah": ("nationalist", "wahhabism", "YEM"),
    "Al-Shabaab": ("fascist", "salafism", "SOM"),
    "Islamic State": ("fascist", "salafism", "SYR"),
    "Hayat Tahrir al-Sham": ("fascist", "salafism", "SYR"),
    "Free Syrian Army": ("conservative", "conservatism", "SYR"),
    "Syrian Democratic Forces": ("libertarian_socialist", "eco_socialism", "SYR"),
    "Likud": ("conservative", "right_populism", "ISR"),
    "Yesh Atid": ("social_liberal", "liberalism", "ISR"),
    "National Unity": ("conservative", "conservatism", "ISR"),
    "Shas": ("conservative", "theocracy", "ISR"),
    "Religious Zionism": ("nationalist", "civic_nationalism", "ISR"),
    "Israel Beiteinu": ("nationalist", "civic_nationalism", "ISR"),
    "Hadash": ("communist", "marxism_leninism", "ISR"),
    "Islah Party": ("conservative", "wahhabism", "YEM"),
    "General People's Congress": ("authoritarian_democrat", "auth_populism", "YEM"),
    # === Africa ===
    "African National Congress": ("social_democrat", "social_democracy", "SAF"),
    "Democratic Alliance": ("market_liberal", "liberalism", "SAF"),
    "Economic Freedom Fighters": ("libertarian_socialist", "left_populism", "SAF"),
    "uMkhonto weSizwe": ("social_democrat", "left_populism", "SAF"),
    "Inkatha Freedom Party": ("conservative", "conservatism", "SAF"),
    "All Progressives Congress": ("conservative", "conservatism", "NGA"),
    "People's Democratic Party": ("social_liberal", "liberalism", "NGA"),
    "Labour Party of Nigeria": ("social_democrat", "social_democracy", "NGA"),
    "Boko Haram": ("fascist", "salafism", "NGA"),
    "Prosperity Party": ("authoritarian_democrat", "sovereign_democracy", "ETH"),
    "Oromo Liberation Front": ("libertarian_socialist", "eco_socialism", "ETH"),
    "Tigray People's Liberation Front": ("communist", "marxism_leninism", "ETH"),
    "Jubilee Party": ("conservative", "conservatism", "KEN"),
    "Orange Democratic Movement": ("social_democrat", "social_democracy", "KEN"),
    "Chama Cha Mapinduzi": ("authoritarian_democrat", "sovereign_democracy", "TAN"),
    "National Resistance Movement": ("authoritarian_democrat", "sovereign_democracy", "UGA"),
    "Rwandan Patriotic Front": ("authoritarian_democrat", "sovereign_democracy", "RWA"),
    "ZANU-PF": ("authoritarian_democrat", "sovereign_democracy", "ZIM"),
    "Movement for Democratic Change": ("social_liberal", "liberalism", "ZIM"),
    "MPLA": ("authoritarian_democrat", "sovereign_democracy", "ANG"),
    "UNITA": ("conservative", "conservatism", "ANG"),
    "FRELIMO": ("authoritarian_democrat", "sovereign_democracy", "MOZ"),
    "Rassemblement National pour la Démocratie": ("authoritarian_democrat", "sovereign_democracy", "ALG"),
    "National Democratic Rally": ("authoritarian_democrat", "sovereign_democracy", "ALG"),
    "Ennahda": ("conservative", "wahhabism", "TUN"),
    "Neo-Destour": ("authoritarian_democrat", "auth_populism", "TUN"),
    "National Congress Party": ("authoritarian_democrat", "theocracy", "SUD"),
    "Rapid Support Forces": ("fascist", "warlordism", "SUD"),
    "Libyan National Army": ("authoritarian_democrat", "autocracy", "LBA"),
    "Government of National Unity": ("social_liberal", "liberalism", "LBA"),
    # === Oceania ===
    "Australian Labor Party": ("social_democrat", "social_democracy", "AST"),
    "Liberal Party of Australia": ("conservative", "conservatism", "AST"),
    "Australian Greens": ("social_democrat", "green_politics", "AST"),
    "One Nation": ("nationalist", "right_populism", "AST"),
    "New Zealand Labour Party": ("social_democrat", "social_democracy", "NZL"),
    "New Zealand National Party": ("conservative", "conservatism", "NZL"),
    "ACT New Zealand": ("market_liberal", "libertarianism", "NZL"),
    "Green Party of Aotearoa New Zealand": ("social_democrat", "green_politics", "NZL"),
    # === Central Asia / Caucasus ===
    "Nur Otan": ("authoritarian_democrat", "sovereign_democracy", "KAZ"),
    "Liberal Democratic Party of Uzbekistan": ("authoritarian_democrat", "sovereign_democracy", "UZB"),
    "Democratic Party of Turkmenistan": ("authoritarian_democrat", "sovereign_democracy", "TMS"),
    "People's Democratic Party of Tajikistan": ("authoritarian_democrat", "sovereign_democracy", "TAJ"),
    "Social Democratic Party of Kyrgyzstan": ("social_democrat", "social_democracy", "KYR"),
    "Georgian Dream": ("authoritarian_democrat", "sovereign_democracy", "GEO"),
    "United National Movement": ("social_liberal", "liberalism", "GEO"),
    "New Azerbaijan Party": ("authoritarian_democrat", "sovereign_democracy", "AZR"),
    "Republican Party of Armenia": ("conservative", "conservatism", "ARM"),
    "Civil Contract": ("social_liberal", "liberalism", "ARM"),
}


# =====================================================================
# Layer 2: Keyword patterns (longest-first order)
# =====================================================================

KEYWORD_PATTERNS: list[tuple[str, str, str, float]] = [
    # (keyword, ideology_group, sub_ideology, confidence)
    # --- specific first ---
    ("christian democrat", "conservative", "christian_democracy", 0.75),
    ("social democrat", "social_democrat", "social_democracy", 0.75),
    ("national socialist", "national_socialist", "neonazism", 0.85),
    ("marxist-leninist", "communist", "marxism_leninism", 0.8),
    ("marxism-leninism", "communist", "marxism_leninism", 0.8),
    ("united russia", "authoritarian_democrat", "sovereign_democracy", 0.9),
    ("people power", "conservative", "conservatism", 0.7),
    ("baath", "authoritarian_democrat", "left_baathism", 0.8),
    # --- left spectrum ---
    ("communist", "communist", "marxism_leninism", 0.8),
    ("marxist", "communist", "marxism_leninism", 0.75),
    ("trotskyist", "totalitarian_socialist", "trotskyism", 0.8),
    ("maoist", "totalitarian_socialist", "maoism", 0.8),
    ("socialist", "libertarian_socialist", "eco_socialism", 0.55),
    ("labour", "social_democrat", "social_democracy", 0.7),
    ("labor", "social_democrat", "social_democracy", 0.7),
    ("workers", "communist", "marxism_leninism", 0.65),
    ("green", "social_democrat", "green_politics", 0.7),
    ("progressive", "social_democrat", "progressivism", 0.65),
    ("left", "libertarian_socialist", "reformist_socialism", 0.45),
    # --- center ---
    ("liberal", "social_liberal", "liberalism", 0.5),
    ("democratic", "social_liberal", "liberalism", 0.35),
    ("centrist", "market_liberal", "centrism", 0.6),
    ("libertarian", "market_liberal", "libertarianism", 0.7),
    # --- right spectrum ---
    ("conservative", "conservative", "conservatism", 0.7),
    ("republican", "conservative", "conservatism", 0.4),
    ("patriot", "nationalist", "civic_nationalism", 0.5),
    ("national", "nationalist", "civic_nationalism", 0.4),
    # --- far right ---
    ("fascist", "fascist", "fascism", 0.85),
    ("falangist", "fascist", "fascism", 0.85),
    ("nazi", "national_socialist", "neonazism", 0.9),
    ("identitarian", "fascist", "identitarianism", 0.8),
    # --- religious ---
    ("islamic", "nationalist", "wahhabism", 0.55),
    ("salafi", "fascist", "salafism", 0.75),
    ("jihad", "fascist", "wahhabism", 0.7),
    ("christian", "conservative", "christian_democracy", 0.5),
    # --- authoritarian ---
    ("junta", "authoritarian_democrat", "autocracy", 0.7),
    ("military", "authoritarian_democrat", "autocracy", 0.45),
    ("monarchist", "authoritarian_democrat", "monarchy", 0.7),
    ("royal", "authoritarian_democrat", "monarchy", 0.6),
]


# =====================================================================
# Layer 3: Wikidata political position → ideology
# =====================================================================

POLITICAL_POSITION_MAP: dict[str, tuple[str, str]] = {
    "far-left": ("totalitarian_socialist", "maoism"),
    "left-wing": ("communist", "marxism_leninism"),
    "centre-left": ("social_democrat", "social_democracy"),
    "centre": ("social_liberal", "liberalism"),
    "center": ("social_liberal", "liberalism"),
    "centre-right": ("conservative", "conservatism"),
    "right-wing": ("authoritarian_democrat", "right_populism"),
    "far-right": ("nationalist", "radical_nationalism"),
}


class PartyMapper:
    """다층 신뢰도 기반 정당→이념 매핑 엔진."""

    def __init__(
        self,
        review_threshold: float = 0.6,
        extra_exact: dict[str, tuple[str, str, str]] | None = None,
    ) -> None:
        self._threshold = review_threshold
        self._exact = dict(EXACT_MATCH)
        if extra_exact:
            self._exact.update(extra_exact)
        self._unmapped: list[str] = []

    def map_party(
        self,
        party_name: str,
        country_tag: str = "",
        political_position: str = "",
    ) -> PartyMapping:
        if not party_name:
            return PartyMapping(party_name="", needs_review=True)

        result = PartyMapping(party_name=party_name, country_tag=country_tag)
        alternatives: list[dict[str, Any]] = []

        if party_name in self._exact:
            group, sub, tag = self._exact[party_name]
            result.ideology_group = group
            result.sub_ideology = sub
            result.country_tag = result.country_tag or tag
            result.confidence = 1.0
            result.source = "exact_match"
            result.needs_review = False
            return result

        name_lower = party_name.lower()
        best_exact_score = 0.0
        for known, (group, sub, tag) in self._exact.items():
            known_lower = known.lower()
            if known_lower in name_lower or name_lower in known_lower:
                overlap = len(set(known_lower.split()) & set(name_lower.split()))
                score = 0.85 + (overlap * 0.02)
                if score > best_exact_score:
                    best_exact_score = score
                    result.ideology_group = group
                    result.sub_ideology = sub
                    result.country_tag = result.country_tag or tag
                    result.confidence = min(score, 0.95)
                    result.source = "exact_substring"

        if best_exact_score > 0:
            result.needs_review = result.confidence < self._threshold
            return result

        # Layer 2: keyword patterns
        best_kw: tuple[str, str, float] | None = None
        for keyword, group, sub, conf in KEYWORD_PATTERNS:
            if keyword in name_lower:
                if best_kw is None or conf > best_kw[2]:
                    if best_kw is not None:
                        alternatives.append({
                            "ideology_group": best_kw[0],
                            "sub_ideology": best_kw[1],
                            "confidence": best_kw[2],
                        })
                    best_kw = (group, sub, conf)
                else:
                    alternatives.append({
                        "ideology_group": group,
                        "sub_ideology": sub,
                        "confidence": conf,
                    })

        if best_kw:
            result.ideology_group = best_kw[0]
            result.sub_ideology = best_kw[1]
            result.confidence = best_kw[2]
            result.source = "keyword"
            result.alternatives = alternatives
            result.needs_review = result.confidence < self._threshold
            return result

        # Layer 3: political position from Wikidata
        if political_position:
            pos_lower = political_position.lower().strip()
            sorted_positions = sorted(POLITICAL_POSITION_MAP.keys(), key=len, reverse=True)
            for pos_key in sorted_positions:
                group, sub = POLITICAL_POSITION_MAP[pos_key]
                if pos_key in pos_lower:
                    result.ideology_group = group
                    result.sub_ideology = sub
                    result.confidence = 0.55
                    result.source = "wikidata_position"
                    result.needs_review = True
                    return result

        # Layer 4: fallback
        result.confidence = 0.0
        result.source = "unmapped"
        result.needs_review = True
        self._unmapped.append(party_name)
        return result

    def map_parties_batch(
        self, parties: list[tuple[str, str]],
    ) -> list[PartyMapping]:
        return [self.map_party(name, tag) for name, tag in parties]

    def get_unmapped(self) -> list[str]:
        return list(set(self._unmapped))

    def export_mapping_table(self) -> dict[str, dict[str, str]]:
        return {
            name: {"ideology_group": g, "sub_ideology": s, "country_tag": t}
            for name, (g, s, t) in self._exact.items()
        }
