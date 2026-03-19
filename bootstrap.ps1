# ============================================================
# HOI4 Modding Agent — One-Line Bootstrap (Windows PowerShell)
#
# Usage:
#   irm https://raw.githubusercontent.com/peppone-choi/hoi4-modding-agent/main/bootstrap.ps1 | iex
# ============================================================

$ErrorActionPreference = "Stop"
$Repo = "https://github.com/peppone-choi/hoi4-modding-agent.git"
$Dir = "$HOME\hoi4-modding-agent"

Write-Host ""
Write-Host "🎮 HOI4 Modding Agent — 자동 설치" -ForegroundColor Cyan
Write-Host "==================================" -ForegroundColor Cyan
Write-Host ""

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host "[FAIL] git이 필요합니다. https://git-scm.com/download/win" -ForegroundColor Red
    exit 1
}
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Host "[FAIL] Python 3.11+ 필요. https://python.org/downloads/" -ForegroundColor Red
    Write-Host "       설치 시 'Add Python to PATH' 체크 필수!" -ForegroundColor Yellow
    exit 1
}

if (Test-Path $Dir) {
    Write-Host "[INFO] 기존 설치 발견 — 업데이트 중..."
    Set-Location $Dir
    git pull --ff-only
} else {
    Write-Host "[INFO] 다운로드 중..."
    git clone --depth 1 $Repo $Dir
}

Set-Location $Dir
& cmd /c install.bat
