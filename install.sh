#!/usr/bin/env bash
# ============================================================
# HOI4 Modding Agent — macOS / Linux Installer
# ============================================================
set -e

CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

info()  { echo -e "${CYAN}[INFO]${NC} $1"; }
ok()    { echo -e "${GREEN}[OK]${NC} $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
fail()  { echo -e "${RED}[FAIL]${NC} $1"; exit 1; }

echo ""
echo "🎮 HOI4 Modding Agent Installer"
echo "================================"
echo ""

# --- Python check ---
info "Python 확인 중..."
if command -v python3 &>/dev/null; then
    PY=python3
elif command -v python &>/dev/null; then
    PY=python
else
    fail "Python이 설치되어 있지 않습니다. https://www.python.org/downloads/ 에서 설치하세요."
fi

PY_VER=$($PY --version 2>&1 | grep -oE '[0-9]+\.[0-9]+')
PY_MAJOR=$(echo "$PY_VER" | cut -d. -f1)
PY_MINOR=$(echo "$PY_VER" | cut -d. -f2)

if [ "$PY_MAJOR" -lt 3 ] || ([ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 11 ]); then
    fail "Python 3.11+ 필요 (현재: $PY_VER). https://www.python.org/downloads/"
fi
ok "Python $PY_VER"

# --- venv ---
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"

if [ ! -d "$VENV_DIR" ]; then
    info "가상환경 생성 중..."
    $PY -m venv "$VENV_DIR"
    ok "가상환경 생성 완료"
else
    ok "가상환경 이미 존재"
fi

source "$VENV_DIR/bin/activate"
ok "가상환경 활성화"

# --- pip upgrade ---
info "pip 업그레이드..."
pip install --upgrade pip -q

# --- install ---
info "의존성 설치 중... (1-2분 소요)"
pip install -e ".[search,portrait,mcp]" -q 2>&1 | tail -3
ok "의존성 설치 완료"

# --- .env setup ---
ENV_FILE="$SCRIPT_DIR/.env"
if [ ! -f "$ENV_FILE" ]; then
    info ".env 파일 생성 중..."
    cp "$SCRIPT_DIR/.env.example" "$ENV_FILE"

    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "📝 API 키 설정"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    echo "AI Provider를 선택하세요:"
    echo "  1) Gemini (추천 — 가장 저렴)"
    echo "  2) OpenAI GPT"
    echo "  3) Anthropic Claude"
    echo "  4) Ollama (로컬 — 무료)"
    echo ""
    read -p "선택 [1-4, 기본값 1]: " provider_choice
    provider_choice=${provider_choice:-1}

    case $provider_choice in
        1)
            sed -i.bak "s/^AI_PROVIDER=.*/AI_PROVIDER=gemini/" "$ENV_FILE"
            echo ""
            echo "Gemini API 키가 필요합니다."
            echo "  → https://aistudio.google.com/apikey 에서 무료 발급"
            echo ""
            read -p "Gemini API Key: " gemini_key
            if [ -n "$gemini_key" ]; then
                sed -i.bak "s/^GEMINI_API_KEY=.*/GEMINI_API_KEY=$gemini_key/" "$ENV_FILE"
            fi
            ;;
        2)
            sed -i.bak "s/^AI_PROVIDER=.*/AI_PROVIDER=openai/" "$ENV_FILE"
            echo ""
            echo "OpenAI API 키가 필요합니다."
            echo "  → https://platform.openai.com/api-keys 에서 발급"
            echo ""
            read -p "OpenAI API Key: " openai_key
            if [ -n "$openai_key" ]; then
                sed -i.bak "s/^# OPENAI_API_KEY=.*/OPENAI_API_KEY=$openai_key/" "$ENV_FILE"
            fi
            ;;
        3)
            sed -i.bak "s/^AI_PROVIDER=.*/AI_PROVIDER=anthropic/" "$ENV_FILE"
            echo ""
            echo "Anthropic API 키가 필요합니다."
            echo "  → https://console.anthropic.com/settings/keys 에서 발급"
            echo ""
            read -p "Anthropic API Key: " anthropic_key
            if [ -n "$anthropic_key" ]; then
                sed -i.bak "s/^# ANTHROPIC_API_KEY=.*/ANTHROPIC_API_KEY=$anthropic_key/" "$ENV_FILE"
            fi
            ;;
        4)
            sed -i.bak "s/^AI_PROVIDER=.*/AI_PROVIDER=ollama/" "$ENV_FILE"
            echo ""
            read -p "Ollama 서버 URL [http://localhost:11434]: " ollama_url
            ollama_url=${ollama_url:-http://localhost:11434}
            read -p "Ollama 모델 [qwen3.5:4b]: " ollama_model
            ollama_model=${ollama_model:-qwen3.5:4b}
            sed -i.bak "s|^# OLLAMA_BASE_URL=.*|OLLAMA_BASE_URL=$ollama_url|" "$ENV_FILE"
            sed -i.bak "s|^# OLLAMA_MODEL=.*|OLLAMA_MODEL=$ollama_model|" "$ENV_FILE"
            ;;
    esac

    rm -f "$ENV_FILE.bak"
    ok ".env 설정 완료"
else
    ok ".env 이미 존재 — 건너뜀"
fi

# --- MOD_ROOT auto-detect ---
info "모드 폴더 탐색 중..."
HOI4_DOCS="$HOME/Documents/Paradox Interactive/Hearts of Iron IV/mod"
if [ -d "$HOI4_DOCS" ]; then
    ok "HOI4 모드 폴더 발견: $HOI4_DOCS"
    echo ""
    echo "사용 가능한 모드:"
    i=1
    mods=()
    for d in "$HOI4_DOCS"/*/; do
        if [ -f "$d/descriptor.mod" ] || [ -d "$d/common" ]; then
            mod_name=$(basename "$d")
            echo "  $i) $mod_name"
            mods+=("$d")
            i=$((i+1))
        fi
    done
    if [ ${#mods[@]} -gt 0 ]; then
        echo ""
        read -p "모드 번호 선택 (Enter로 건너뛰기): " mod_choice
        if [ -n "$mod_choice" ] && [ "$mod_choice" -le ${#mods[@]} ] 2>/dev/null; then
            selected="${mods[$((mod_choice-1))]}"
            echo "선택: $(basename "$selected")"
        fi
    fi
else
    warn "HOI4 모드 폴더를 찾지 못했습니다."
fi

# --- Done ---
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ 설치 완료!"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "실행 방법:"
echo ""
echo "  source .venv/bin/activate"
if [ -n "$selected" ]; then
    echo "  hoi4-agent \"$selected\""
else
    echo "  hoi4-agent /path/to/your/mod"
fi
echo ""
echo "웹 브라우저에서 http://localhost:8501 로 접속하세요."
echo ""
