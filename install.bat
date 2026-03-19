@echo off
chcp 65001 >nul 2>&1
setlocal EnableDelayedExpansion

:: ============================================================
:: HOI4 Modding Agent — Install & Run (Windows)
:: Already installed? Just runs. Not installed? Installs then runs.
:: ============================================================

set "SCRIPT_DIR=%~dp0"
set "VENV_DIR=%SCRIPT_DIR%.venv"
set "ENV_FILE=%SCRIPT_DIR%.env"
set "MARKER=%VENV_DIR%\.installed"

:: ── Already installed? Just run ──
if exist "%MARKER%" if exist "%ENV_FILE%" (
    call "%VENV_DIR%\Scripts\activate.bat"

    set "MOD_PATH=%~1"
    if "!MOD_PATH!"=="" call :find_mod
    if "!MOD_PATH!"=="" set "MOD_PATH=%SCRIPT_DIR%"

    hoi4-agent "!MOD_PATH!"
    goto :eof
)

:: ── First-time install ──
echo.
echo 🎮 HOI4 Modding Agent — 설치 및 실행
echo ======================================
echo.

:: --- Python check ---
echo [INFO] Python 확인 중...
where python >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [FAIL] Python이 설치되어 있지 않습니다.
    echo        https://www.python.org/downloads/
    echo        "Add Python to PATH" 반드시 체크!
    pause
    exit /b 1
)
for /f "tokens=2 delims= " %%v in ('python --version 2^>^&1') do set PY_VER=%%v
echo [OK] Python %PY_VER%

:: --- venv ---
if not exist "%VENV_DIR%" (
    echo [INFO] 가상환경 생성 중...
    python -m venv "%VENV_DIR%"
)
call "%VENV_DIR%\Scripts\activate.bat"
echo [OK] 가상환경 활성화

:: --- install ---
echo [INFO] pip 업그레이드...
pip install --upgrade pip -q >nul 2>&1
echo [INFO] 의존성 설치 중... (1-2분 소요)
pip install -e ".[search,portrait,mcp]" -q 2>&1
echo [OK] 의존성 설치 완료

:: --- .env setup ---
if not exist "%ENV_FILE%" (
    copy "%SCRIPT_DIR%.env.example" "%ENV_FILE%" >nul

    echo.
    echo ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    echo 📝 AI Provider 설정
    echo ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    echo.
    echo   1^) Gemini  — 추천, 가장 저렴 (무료 키 발급^)
    echo   2^) OpenAI  — GPT-4o-mini
    echo   3^) Claude  — Anthropic
    echo   4^) Ollama  — 로컬, 무료
    echo.
    set /p "CHOICE=선택 [1]: "
    if "!CHOICE!"=="" set CHOICE=1

    if "!CHOICE!"=="1" (
        echo.
        echo   Gemini API 키 → https://aistudio.google.com/apikey
        echo.
        set /p "API_KEY=  API Key: "
        powershell -Command "(Get-Content '%ENV_FILE%') -replace '^AI_PROVIDER=.*','AI_PROVIDER=gemini' -replace '^GEMINI_API_KEY=.*','GEMINI_API_KEY=!API_KEY!' | Set-Content '%ENV_FILE%'"
    )
    if "!CHOICE!"=="2" (
        echo.
        echo   OpenAI API 키 → https://platform.openai.com/api-keys
        echo.
        set /p "API_KEY=  API Key: "
        powershell -Command "(Get-Content '%ENV_FILE%') -replace '^AI_PROVIDER=.*','AI_PROVIDER=openai' -replace '^# OPENAI_API_KEY=.*','OPENAI_API_KEY=!API_KEY!' | Set-Content '%ENV_FILE%'"
    )
    if "!CHOICE!"=="3" (
        echo.
        echo   Anthropic API 키 → https://console.anthropic.com/settings/keys
        echo.
        set /p "API_KEY=  API Key: "
        powershell -Command "(Get-Content '%ENV_FILE%') -replace '^AI_PROVIDER=.*','AI_PROVIDER=anthropic' -replace '^# ANTHROPIC_API_KEY=.*','ANTHROPIC_API_KEY=!API_KEY!' | Set-Content '%ENV_FILE%'"
    )
    if "!CHOICE!"=="4" (
        set /p "OLL_URL=  Ollama URL [http://localhost:11434]: "
        if "!OLL_URL!"=="" set OLL_URL=http://localhost:11434
        set /p "OLL_MDL=  모델 [qwen3.5:4b]: "
        if "!OLL_MDL!"=="" set OLL_MDL=qwen3.5:4b
        powershell -Command "(Get-Content '%ENV_FILE%') -replace '^AI_PROVIDER=.*','AI_PROVIDER=ollama' -replace '^# OLLAMA_BASE_URL=.*','OLLAMA_BASE_URL=!OLL_URL!' -replace '^# OLLAMA_MODEL=.*','OLLAMA_MODEL=!OLL_MDL!' | Set-Content '%ENV_FILE%'"
    )
    echo [OK] .env 설정 완료
)

:: --- Mark installed ---
echo. > "%MARKER%"

:: --- Find mod & run ---
echo.
echo [OK] 설치 완료! 에이전트를 시작합니다...
echo.

set "MOD_PATH=%~1"
if "!MOD_PATH!"=="" call :find_mod
if "!MOD_PATH!"=="" set "MOD_PATH=%SCRIPT_DIR%"

hoi4-agent "!MOD_PATH!"
goto :eof

:: ── Subroutine: find HOI4 mod folder ──
:find_mod
set "HOI4_DOCS=%USERPROFILE%\Documents\Paradox Interactive\Hearts of Iron IV\mod"
if not exist "%HOI4_DOCS%" exit /b 1

set MOD_COUNT=0
for /d %%d in ("%HOI4_DOCS%\*") do (
    set /a MOD_COUNT+=1
    set "MOD_!MOD_COUNT!=%%d"
)
if !MOD_COUNT! equ 0 exit /b 1
if !MOD_COUNT! equ 1 (
    set "MOD_PATH=!MOD_1!"
    exit /b 0
)

echo.
echo 사용 가능한 모드:
for /L %%i in (1,1,!MOD_COUNT!) do (
    for %%p in ("!MOD_%%i!") do echo   %%i^) %%~nxp
)
echo.
set /p "MC=모드 번호 선택 [1]: "
if "!MC!"=="" set MC=1
set "MOD_PATH=!MOD_%MC%!"
exit /b 0
