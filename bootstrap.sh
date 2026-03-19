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

echo ""
echo "🎮 HOI4 Modding Agent — 자동 설치"
echo "=================================="
echo ""

command -v git >/dev/null 2>&1 || { echo "[FAIL] git이 필요합니다."; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo "[FAIL] Python 3.11+ 필요. https://python.org/downloads/"; exit 1; }

if [ -d "$DIR" ]; then
    echo "[INFO] 기존 설치 발견 — 업데이트 중..."
    cd "$DIR" && git pull --ff-only
else
    echo "[INFO] 다운로드 중..."
    git clone --depth 1 "$REPO" "$DIR"
fi

cd "$DIR"
chmod +x install.sh
exec ./install.sh
