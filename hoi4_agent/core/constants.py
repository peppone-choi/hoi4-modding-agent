"""
프로젝트 전체 상수 정의.
"""
from pathlib import Path

# ===== 모드 경로 =====
MOD_ROOT = Path("/Users/apple/Documents/Paradox Interactive/Hearts of Iron IV/mod/Breaking-Point")
CHARACTERS_DIR = MOD_ROOT / "common" / "characters"
HISTORY_COUNTRIES_DIR = MOD_ROOT / "history" / "countries"
HISTORY_STATES_DIR = MOD_ROOT / "history" / "states"
IDEOLOGIES_FILE = MOD_ROOT / "common" / "ideologies" / "TFR_ideologies.txt"
INTERFACE_DIR = MOD_ROOT / "interface"
GFX_LEADERS_DIR = MOD_ROOT / "gfx" / "leaders"
PORTRAITS_DEF_DIR = MOD_ROOT / "portraits"

# tools 경로
TOOLS_DIR = MOD_ROOT / "tools"
CACHE_DIR = TOOLS_DIR / ".cache"
BACKUPS_DIR = TOOLS_DIR / ".backups"
CHANGE_LOG_FILE = TOOLS_DIR / "change_log.json"
OUTPUT_DIR = TOOLS_DIR / "output"

# ===== TFR 초상화 스펙 =====
PORTRAIT_WIDTH = 156
PORTRAIT_HEIGHT = 210
PORTRAIT_FORMAT = "PNG"
ADVISOR_WIDTH = 65
ADVISOR_HEIGHT = 67

# TFR 컬러라이제이션 값 (Idenn 튜토리얼 기준)
SKIN_COLOR_HEX = "#936F60"      # R147 G111 B96 - 피부 기본
LIP_COLOR_HEX = "#936B60"       # R147 G107 B96 - 입술/볼
JAW_COLOR_HEX = "#706560"       # R112 G101 B96 - 아래 턱
EYE_COLOR_HEX = "#898989"       # R137 G137 B137 - 흰 눈
NOSE_COLOR_HEX = "#936258"      # R147 G98 B88 - 코

# TFR 배경색 (환경변수에서 로드, 기본값은 여기 정의)
BG_COLOR_HEX = "#3D2B50"           # 어두운 보라 배경 (기본값)
BG_COLOR_LIGHT_HEX = "#6B4C7A"     # 밝은 보라 (가장자리, 기본값)

# TFR 포트레잇 얼굴 기준 (842장 분석 평균)
FACE_WIDTH_RATIO = 0.584            # 프레임 대비 얼굴 너비 58%
FACE_HEIGHT_RATIO = 0.492           # 프레임 대비 얼굴 높이 49%
FACE_CENTER_X_RATIO = 0.496         # 얼굴 중심 X 50%
FACE_CENTER_Y_RATIO = 0.508         # 얼굴 중심 Y 51%
FACE_TOP_Y_RATIO = 0.262            # 이마 시작 Y 26%

# 가우시안 블러 설정
GAUSSIAN_BLUR_RADIUS_1 = 10.0   # Layer 1
GAUSSIAN_BLUR_RADIUS_3 = 2.0    # Layer 3
GAUSSIAN_BLUR_OPACITY_3 = 0.9   # Layer 3 opacity 90%

# ===== Wiki API 설정 =====
WIKIPEDIA_API_URL = "https://en.wikipedia.org/w/api.php"
WIKIPEDIA_KO_API_URL = "https://ko.wikipedia.org/w/api.php"
WIKIDATA_SPARQL_URL = "https://query.wikidata.org/sparql"
WIKIMEDIA_COMMONS_API_URL = "https://commons.wikimedia.org/w/api.php"
NAMUWIKI_DUMP_URL = "https://namu.wiki/mirror/dump"

WIKI_USER_AGENT = "BreakingPointHOI4Updater/1.0 (HOI4 mod automation; https://github.com/user/breaking-point)"
WIKI_RATE_LIMIT_DELAY = 0.5     # 초 단위 요청 간격
WIKI_MAX_CONCURRENT = 3
WIKI_CACHE_TTL_DAYS = 30

# 허용 라이선스
ALLOWED_LICENSES = {
    "CC BY-SA 4.0",
    "CC BY-SA 3.0",
    "CC BY 4.0",
    "CC BY 3.0",
    "Public Domain",
    "CC0",
    "CC BY-SA 2.0",
    "CC BY 2.0",
}

# ===== HOI4 이념 목록 (기본값, 실제는 파일에서 로드) =====
DEFAULT_IDEOLOGIES = {
    # 민주주의 계열
    "liberalism", "conservatism", "neoliberalism", "social_democracy",
    "progressivism", "right_populism", "left_populism",
    # 공산주의 계열
    "marxism", "marxism_leninism", "stalinism", "maoism", "trotskyism",
    # 파시즘 계열
    "fascism", "nazism", "ultranationalism",
    # 중립
    "despotism", "centrism", "theocracy",
}

# ===== 날짜 =====
TARGET_DATE = "2026.1.1"
TARGET_YEAR = 2026

# ===== 로컬라이제이션 =====
LOCALISATION_DIR = MOD_ROOT / "localisation" / "english"
PARTIES_LOC_FILE = LOCALISATION_DIR / "TFR_parties_l_english.yml"
COUNTRY_TAGS_DIR = MOD_ROOT / "common" / "country_tags"

# ===== HOI4 주요 이념 그룹 (정당 검증용) =====
MAIN_IDEOLOGY_GROUPS: list[str] = [
    "totalitarian_socialist",
    "communist",
    "libertarian_socialist",
    "social_democrat",
    "social_liberal",
    "market_liberal",
    "conservative",
    "authoritarian_democrat",
    "nationalist",
    "fascist",
    "national_socialist",
]

# ===== 캐릭터 ID 패턴 =====
CHAR_ID_PATTERN = r'^[A-Z0-9_]+_[a-zA-Z0-9_]+_char$'
