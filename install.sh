#!/usr/bin/env bash
# ============================================================
# HOI4 Modding Agent — Install & Run (macOS / Linux)
# Already installed? Just runs. Not installed? Installs then runs.
# ============================================================
set -e

CYAN='\033[0;36m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info()  { echo -e "${CYAN}[INFO]${NC} $1"; }
ok()    { echo -e "${GREEN}[OK]${NC} $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
fail()  { echo -e "${RED}[FAIL]${NC} $1"; exit 1; }

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"
ENV_FILE="$SCRIPT_DIR/.env"
INSTALLED_MARKER="$VENV_DIR/.installed"

# ── Auto-detect mod folder ──
find_mod() {
    local hoi4_docs="$HOME/Documents/Paradox Interactive/Hearts of Iron IV/mod"
    [ ! -d "$hoi4_docs" ] && return 1

    local mods=()
    for d in "$hoi4_docs"/*/; do
        [ -f "$d/descriptor.mod" ] || [ -d "$d/common" ] && mods+=("$d")
    done
    [ ${#mods[@]} -eq 0 ] && return 1

    if [ ${#mods[@]} -eq 1 ]; then
        echo "${mods[0]}"
        return 0
    fi

    echo "" >&2
    echo "사용 가능한 모드:" >&2
    for i in "${!mods[@]}"; do
        echo "  $((i+1))) $(basename "${mods[$i]}")" >&2
    done
    echo "" >&2
    read -p "모드 번호 선택 [1]: " choice
    choice=${choice:-1}
    echo "${mods[$((choice-1))]}"
}

# ── Already installed? Just run ──
if [ -f "$INSTALLED_MARKER" ] && [ -f "$ENV_FILE" ]; then
    source "$VENV_DIR/bin/activate"
    MOD_PATH="${1:-}"
    if [ -z "$MOD_PATH" ]; then
        MOD_PATH=$(find_mod) || MOD_PATH="$SCRIPT_DIR"
    fi
    exec hoi4-agent "$MOD_PATH"
fi

# ── First-time install ──
echo ""
echo "🎮 HOI4 Modding Agent — 설치 및 실행"
echo "======================================"
echo ""

# --- Python check ---
info "Python 확인 중..."
PY=""
for cmd in python3.12 python3.11 python3 python; do
    if command -v "$cmd" &>/dev/null; then
        ver=$("$cmd" --version 2>&1 | grep -oE '[0-9]+\.[0-9]+')
        major=$(echo "$ver" | cut -d. -f1)
        minor=$(echo "$ver" | cut -d. -f2)
        if [ "$major" -ge 3 ] && [ "$minor" -ge 11 ]; then
            PY="$cmd"
            break
        fi
    fi
done
[ -z "$PY" ] && fail "Python 3.11+ 필요. https://python.org/downloads/"
ok "Python $($PY --version 2>&1 | grep -oE '[0-9]+\.[0-9]+\.[0-9]+')"

# --- venv ---
if [ ! -d "$VENV_DIR" ]; then
    info "가상환경 생성 중..."
    $PY -m venv "$VENV_DIR"
fi
source "$VENV_DIR/bin/activate"
ok "가상환경 활성화"

# --- install ---
info "pip 업그레이드..."
pip install --upgrade pip -q
info "의존성 설치 중... (1-2분 소요)"
pip install -e ".[search,portrait,mcp]" -q 2>&1 | tail -3
ok "의존성 설치 완료"

# --- .env setup ---
if [ ! -f "$ENV_FILE" ]; then
    cp "$SCRIPT_DIR/.env.example" "$ENV_FILE"

    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "📝 AI Provider 설정"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    echo "  1) Gemini  — 추천, 가장 저렴 (무료 키 발급)"
    echo "  2) OpenAI  — GPT-4o-mini"
    echo "  3) Claude  — Anthropic"
    echo "  4) Ollama  — 로컬, 무료"
    echo ""
    read -p "선택 [1]: " choice
    choice=${choice:-1}

    case $choice in
        1)
            sed -i.bak "s/^AI_PROVIDER=.*/AI_PROVIDER=gemini/" "$ENV_FILE"
            echo ""
            echo "  Gemini API 키 → https://aistudio.google.com/apikey"
            echo ""
            read -p "  API Key: " key
            [ -n "$key" ] && sed -i.bak "s/^GEMINI_API_KEY=.*/GEMINI_API_KEY=$key/" "$ENV_FILE"
            ;;
        2)
            sed -i.bak "s/^AI_PROVIDER=.*/AI_PROVIDER=openai/" "$ENV_FILE"
            echo ""
            echo "  OpenAI API 키 → https://platform.openai.com/api-keys"
            echo ""
            read -p "  API Key: " key
            [ -n "$key" ] && sed -i.bak "s/^# OPENAI_API_KEY=.*/OPENAI_API_KEY=$key/" "$ENV_FILE"
            ;;
        3)
            sed -i.bak "s/^AI_PROVIDER=.*/AI_PROVIDER=anthropic/" "$ENV_FILE"
            echo ""
            echo "  Anthropic API 키 → https://console.anthropic.com/settings/keys"
            echo ""
            read -p "  API Key: " key
            [ -n "$key" ] && sed -i.bak "s/^# ANTHROPIC_API_KEY=.*/ANTHROPIC_API_KEY=$key/" "$ENV_FILE"
            ;;
        4)
            sed -i.bak "s/^AI_PROVIDER=.*/AI_PROVIDER=ollama/" "$ENV_FILE"
            read -p "  Ollama URL [http://localhost:11434]: " url
            url=${url:-http://localhost:11434}
            read -p "  모델 [qwen3.5:4b]: " model
            model=${model:-qwen3.5:4b}
            sed -i.bak "s|^# OLLAMA_BASE_URL=.*|OLLAMA_BASE_URL=$url|;s|^# OLLAMA_MODEL=.*|OLLAMA_MODEL=$model|" "$ENV_FILE"
            ;;
    esac
    rm -f "$ENV_FILE.bak"
    ok ".env 설정 완료"
fi

# --- Mark installed ---
touch "$INSTALLED_MARKER"

# --- Find mod & run ---
echo ""
ok "설치 완료! 에이전트를 시작합니다..."
echo ""

MOD_PATH="${1:-}"
if [ -z "$MOD_PATH" ]; then
    MOD_PATH=$(find_mod) || MOD_PATH="$SCRIPT_DIR"
fi

exec hoi4-agent "$MOD_PATH"
