# ============================================================
# HOI4 Modding Agent — One-Line Bootstrap (Windows PowerShell)
#
# Usage:
#   irm https://raw.githubusercontent.com/peppone-choi/hoi4-modding-agent/main/bootstrap.ps1 | iex
# ============================================================

$ErrorActionPreference = "Stop"
$Repo = "https://github.com/peppone-choi/hoi4-modding-agent.git"
$Dir = "$HOME\hoi4-modding-agent"
$NeedPy = "3.11"

Write-Host ""
Write-Host "🎮 HOI4 Modding Agent — 자동 설치" -ForegroundColor Cyan
Write-Host "==================================" -ForegroundColor Cyan
Write-Host ""

# ── Git ──
if (Get-Command git -ErrorAction SilentlyContinue) {
    $gitVer = (git --version) -replace 'git version ',''
    Write-Host "[OK] Git $gitVer" -ForegroundColor Green
} else {
    Write-Host "[INFO] Git 설치 중..." -ForegroundColor Cyan

    if (Get-Command winget -ErrorAction SilentlyContinue) {
        winget install --id Git.Git -e --accept-source-agreements --accept-package-agreements
    } else {
        $gitUrl = "https://github.com/git-for-windows/git/releases/latest/download/Git-2.47.1-64-bit.exe"
        $gitInstaller = "$env:TEMP\git-installer.exe"
        Write-Host "[INFO] Git 다운로드 중..." -ForegroundColor Cyan
        Invoke-WebRequest -Uri $gitUrl -OutFile $gitInstaller -UseBasicParsing
        Start-Process -Wait -FilePath $gitInstaller -ArgumentList "/VERYSILENT","/NORESTART","/SP-"
        Remove-Item $gitInstaller -ErrorAction SilentlyContinue
    }

    $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        Write-Host "[FAIL] Git 설치 실패. https://git-scm.com/download/win 에서 수동 설치하세요." -ForegroundColor Red
        exit 1
    }
    Write-Host "[OK] Git 설치 완료" -ForegroundColor Green
}

# ── Python ──
function Find-Python {
    foreach ($cmd in @("python3", "python", "py")) {
        $exe = Get-Command $cmd -ErrorAction SilentlyContinue
        if ($exe) {
            try {
                $ver = & $exe.Source --version 2>&1 | Select-String -Pattern '\d+\.\d+' | ForEach-Object { $_.Matches[0].Value }
                $parts = $ver -split '\.'
                if ([int]$parts[0] -ge 3 -and [int]$parts[1] -ge 11) {
                    return $exe.Source
                }
            } catch {}
        }
    }
    return $null
}

$pyExe = Find-Python
if ($pyExe) {
    $pyVer = & $pyExe --version 2>&1
    Write-Host "[OK] $pyVer" -ForegroundColor Green
} else {
    Write-Host "[INFO] Python ${NeedPy}+ 설치 중..." -ForegroundColor Cyan

    if (Get-Command winget -ErrorAction SilentlyContinue) {
        winget install --id Python.Python.3.12 -e --accept-source-agreements --accept-package-agreements
    } else {
        $pyUrl = "https://www.python.org/ftp/python/3.12.8/python-3.12.8-amd64.exe"
        $pyInstaller = "$env:TEMP\python-installer.exe"
        Write-Host "[INFO] Python 다운로드 중..." -ForegroundColor Cyan
        Invoke-WebRequest -Uri $pyUrl -OutFile $pyInstaller -UseBasicParsing
        Start-Process -Wait -FilePath $pyInstaller -ArgumentList "/quiet","InstallAllUsers=0","PrependPath=1","Include_pip=1"
        Remove-Item $pyInstaller -ErrorAction SilentlyContinue
    }

    $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
    $pyExe = Find-Python
    if (-not $pyExe) {
        Write-Host "[FAIL] Python 설치 실패. https://python.org/downloads/ 에서 수동 설치하세요." -ForegroundColor Red
        Write-Host "       'Add Python to PATH' 반드시 체크!" -ForegroundColor Yellow
        exit 1
    }
    Write-Host "[OK] Python 설치 완료" -ForegroundColor Green
}

# ── Clone / Update ──
if (Test-Path $Dir) {
    Write-Host "[INFO] 기존 설치 발견 — 업데이트 중..." -ForegroundColor Cyan
    Set-Location $Dir
    git pull --ff-only
} else {
    Write-Host "[INFO] 다운로드 중..." -ForegroundColor Cyan
    git clone --depth 1 $Repo $Dir
}

Set-Location $Dir
& cmd /c install.bat
