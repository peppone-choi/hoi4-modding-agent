#!/bin/bash
# HoI4 포트레잇 관리자 — 더블클릭으로 실행
# Double-click to launch HoI4 Portrait Manager

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV="$SCRIPT_DIR/.venv/bin/python"
PORT=5555

echo "======================================"
echo "  HoI4 포트레잇 관리자 v6"
echo "======================================"

# Check venv
if [ ! -f "$VENV" ]; then
    echo "오류: .venv가 없습니다. install.sh를 먼저 실행하세요."
    read -p "아무 키나 눌러 종료..."
    exit 1
fi

# Find mod directory
MOD_DIR=""
for d in "$SCRIPT_DIR"/../*/; do
    if [ -f "$d/descriptor.mod" ]; then
        MOD_DIR="$d"
        break
    fi
done

if [ -z "$MOD_DIR" ]; then
    echo "오류: 모드 폴더를 찾을 수 없습니다."
    echo "사용법: portrait_manager.command --mod /path/to/mod"
    read -p "아무 키나 눌러 종료..."
    exit 1
fi

echo "모드: $(basename "$MOD_DIR")"
echo "경로: $MOD_DIR"
echo ""
echo "브라우저에서 열기: http://localhost:$PORT"
echo "종료: Ctrl+C"
echo ""

# Open browser
sleep 2 && open "http://localhost:$PORT" &

# Launch
cd "$SCRIPT_DIR"
"$VENV" portrait_selector.py --mod "$MOD_DIR" --port $PORT
