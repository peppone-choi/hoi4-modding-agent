"""
검색 쿼리 확장기.
인물명 + 국적/직함 기반으로 다양한 검색 쿼리를 생성한다.
현지어 변환, 직함 추가, 맥락 키워드 등으로 검색 커버리지를 극대화.
"""
from __future__ import annotations

# 국가 태그 → 현지어 스크립트 매핑
# HOI4 태그 기준으로 검색어를 생성하기 위함
TAG_TO_LANGUAGES: dict[str, list[str]] = {
    # 동아시아
    "CHI": ["zh"], "PRC": ["zh"], "TAI": ["zh"],
    "JAP": ["ja"], "KOR": ["ko"], "PRK": ["ko"],
    # 중앙/서아시아
    "AFG": ["fa", "ps"],  # 다리어, 파슈토
    "IRN": ["fa"], "IRQ": ["ar"], "SYR": ["ar"],
    "TUR": ["tr"], "SAU": ["ar"], "YEM": ["ar"],
    "ISR": ["he", "ar"], "PAL": ["ar"],
    "KAZ": ["kk", "ru"], "UZB": ["uz", "ru"],
    "TKM": ["tk", "ru"], "KYR": ["ky", "ru"],
    "TAJ": ["tg", "ru"],
    # 남아시아
    "RAJ": ["hi", "ur"], "IND": ["hi"], "PAK": ["ur"],
    "BAN": ["bn"], "SRL": ["si", "ta"],
    # 동남아시아
    "SIA": ["th"], "VIE": ["vi"], "INS": ["id"],
    "MAL": ["ms"], "PHI": ["tl"], "MYA": ["my"],
    # 러시아/구소련
    "SOV": ["ru"], "RUS": ["ru"], "UKR": ["uk"],
    "BLR": ["be", "ru"], "GEO": ["ka"], "ARM": ["hy"],
    "AZR": ["az"],
    # 유럽
    "FRA": ["fr"], "GER": ["de"], "ITA": ["it"],
    "SPR": ["es"], "POR": ["pt"], "POL": ["pl"],
    "ROM": ["ro"], "HUN": ["hu"], "CZE": ["cs"],
    "BUL": ["bg"], "SER": ["sr"], "CRO": ["hr"],
    "GRE": ["el"], "NOR": ["no"], "SWE": ["sv"],
    "FIN": ["fi"], "DEN": ["da"], "HOL": ["nl"],
    "BEL": ["nl", "fr"],
    # 아프리카
    "ETH": ["am"], "EGY": ["ar"], "LBY": ["ar"],
    "ALG": ["ar", "fr"], "MOR": ["ar", "fr"],
    "NGA": ["en", "ha"], "GHA": ["en"],
    "KEN": ["sw", "en"], "TAN": ["sw"],
    "SAF": ["af", "zu", "en"],
    # 아메리카
    "USA": ["en"], "CAN": ["en", "fr"],
    "MEX": ["es"], "BRA": ["pt"],
    "ARG": ["es"], "CHL": ["es"], "COL": ["es"],
    "VEN": ["es"], "CUB": ["es"], "PER": ["es"],
    # 미국 내전 태그
    "APA": ["en"], "USB": ["en"], "USC": ["en"],
    "ATW": ["en"],
}

# 맥락 키워드 (포즈/상황별)
CONTEXT_KEYWORDS_EN = [
    "portrait", "official photo", "speech",
    "press conference", "meeting",
]

# 직함 키워드
TITLE_KEYWORDS = {
    "en": ["president", "prime minister", "general", "minister", "leader", "commander"],
    "ko": ["대통령", "총리", "장군", "장관", "지도자", "사령관"],
}


def expand_queries(
    person_name: str,
    native_name: str | None = None,
    title: str | None = None,
    country_tag: str | None = None,
    max_queries: int = 15,
) -> list[str]:
    """인물명 기반으로 다양한 검색 쿼리를 생성한다.

    Args:
        person_name: 영문 인물명 (예: "Abdul Rashid Dostum").
        native_name: 현지어 인물명 (예: "عبدالرشید دوستم").
        title: 직함 (예: "general", "president").
        country_tag: HOI4 국가 태그 (예: "AFG").
        max_queries: 최대 쿼리 수.

    Returns:
        검색 쿼리 리스트 (중복 제거).
    """
    queries: list[str] = []

    # 1. 기본: 영문 이름
    queries.append(person_name)

    # 2. 현지어 이름
    if native_name:
        queries.append(native_name)

    # 3. 직함 추가
    if title:
        queries.append(f"{person_name} {title}")

    # 4. 맥락 키워드 추가
    for kw in CONTEXT_KEYWORDS_EN:
        queries.append(f"{person_name} {kw}")

    # 5. 성만 사용 (짧은 검색)
    parts = person_name.split()
    if len(parts) >= 2:
        last_name = parts[-1]
        queries.append(f"{last_name} {title or 'politician'}")

    # 6. 이름 변형 (하이픈, 언더스코어 등)
    if "-" in person_name:
        queries.append(person_name.replace("-", " "))
    if "_" in person_name:
        queries.append(person_name.replace("_", " "))

    # 중복 제거 + 최대 수 제한
    seen: set[str] = set()
    unique: list[str] = []
    for q in queries:
        q_lower = q.strip().lower()
        if q_lower and q_lower not in seen:
            seen.add(q_lower)
            unique.append(q.strip())
    return unique[:max_queries]


def get_search_languages(country_tag: str) -> list[str]:
    """국가 태그에 해당하는 검색 언어 코드 리스트를 반환한다."""
    langs = TAG_TO_LANGUAGES.get(country_tag, [])
    if "en" not in langs:
        langs = langs + ["en"]
    return langs
