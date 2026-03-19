#!/usr/bin/env bash
# ============================================================
# HOI4 Modding Agent — One-Line Bootstrap (macOS / Linux)
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/peppone-choi/hoi4-modding-agent/main/bootstrap.sh | bash
# ============================================================
set -e

REPO="https://github.com/peppone-choi/hoi4-modding-agent.git"
DIR="$HOME/hoi4-modding-agent"
NEED_PY="3.11"

info()  { echo -e "\033[0;36m[INFO]\033[0m $1"; }
ok()    { echo -e "\033[0;32m[OK]\033[0m $1"; }
warn()  { echo -e "\033[1;33m[WARN]\033[0m $1"; }
fail()  { echo -e "\033[0;31m[FAIL]\033[0m $1"; exit 1; }

echo ""
echo "🎮 HOI4 Modding Agent — 자동 설치"
echo "=================================="
echo ""

# ── Git ──
if command -v git &>/dev/null; then
    ok "Git $(git --version | grep -oE '[0-9]+\.[0-9]+\.[0-9]+')"
else
    info "Git 설치 중..."
    if [[ "$OSTYPE" == darwin* ]]; then
        if command -v brew &>/dev/null; then
            brew install git
        else
            info "Xcode Command Line Tools 설치 (Git 포함)..."
            xcode-select --install 2>/dev/null || true
            echo "설치 팝업이 뜨면 '설치'를 누르세요. 완료 후 이 스크립트를 다시 실행하세요."
            exit 0
        fi
    elif command -v apt-get &>/dev/null; then
        sudo apt-get update -qq && sudo apt-get install -y -qq git
    elif command -v dnf &>/dev/null; then
        sudo dnf install -y git
    elif command -v pacman &>/dev/null; then
        sudo pacman -Sy --noconfirm git
    else
        fail "Git 자동 설치 불가. 수동 설치: https://git-scm.com/downloads"
    fi
    ok "Git 설치 완료"
fi

# ── Python ──
find_python() {
    for cmd in python3.12 python3.11 python3 python; do
        if command -v "$cmd" &>/dev/null; then
            local ver
            ver=$("$cmd" --version 2>&1 | grep -oE '[0-9]+\.[0-9]+')
            local major minor
            major=$(echo "$ver" | cut -d. -f1)
            minor=$(echo "$ver" | cut -d. -f2)
            if [ "$major" -ge 3 ] && [ "$minor" -ge 11 ]; then
                echo "$cmd"
                return 0
            fi
        fi
    done
    return 1
}

PY=$(find_python) && ok "Python $($PY --version 2>&1 | grep -oE '[0-9]+\.[0-9]+\.[0-9]+')" || {
    info "Python ${NEED_PY}+ 설치 중..."
    if [[ "$OSTYPE" == darwin* ]]; then
        if command -v brew &>/dev/null; then
            brew install python@3.12
        else
            info "Homebrew 설치 중..."
            /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
            eval "$(/opt/homebrew/bin/brew shellenv 2>/dev/null || /usr/local/bin/brew shellenv 2>/dev/null)"
            brew install python@3.12
        fi
    elif command -v apt-get &>/dev/null; then
        sudo apt-get update -qq
        sudo apt-get install -y -qq software-properties-common
        sudo add-apt-repository -y ppa:deadsnakes/ppa
        sudo apt-get update -qq
        sudo apt-get install -y -qq python3.12 python3.12-venv python3.12-dev
    elif command -v dnf &>/dev/null; then
        sudo dnf install -y python3.12
    elif command -v pacman &>/dev/null; then
        sudo pacman -Sy --noconfirm python
    else
        fail "Python 자동 설치 불가. 수동 설치: https://python.org/downloads/"
    fi

    PY=$(find_python) || fail "Python ${NEED_PY}+ 설치 실패. https://python.org/downloads/"
    ok "Python 설치 완료: $($PY --version 2>&1)"
}

# ── Clone / Update ──
if [ -d "$DIR" ]; then
    info "기존 설치 발견 — 업데이트 중..."
    cd "$DIR" && git pull --ff-only
else
    info "다운로드 중..."
    git clone --depth 1 "$REPO" "$DIR"
fi

cd "$DIR"
chmod +x install.sh
exec ./install.sh
