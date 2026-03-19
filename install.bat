@echo off
chcp 65001 >nul 2>&1
setlocal EnableDelayedExpansion

echo.
echo 🎮 HOI4 Modding Agent Installer (Windows)
echo ==========================================
echo.

:: --- Python check ---
echo [INFO] Python 확인 중...
where python >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [FAIL] Python이 설치되어 있지 않습니다.
    echo        https://www.python.org/downloads/ 에서 설치하세요.
    echo        설치 시 "Add Python to PATH" 체크 필수!
    pause
    exit /b 1
)

for /f "tokens=2 delims= " %%v in ('python --version 2^>^&1') do set PY_VER=%%v
echo [OK] Python %PY_VER%

:: --- venv ---
set "SCRIPT_DIR=%~dp0"
set "VENV_DIR=%SCRIPT_DIR%.venv"

if not exist "%VENV_DIR%" (
    echo [INFO] 가상환경 생성 중...
    python -m venv "%VENV_DIR%"
    echo [OK] 가상환경 생성 완료
) else (
    echo [OK] 가상환경 이미 존재
)

call "%VENV_DIR%\Scripts\activate.bat"
echo [OK] 가상환경 활성화

:: --- pip upgrade ---
echo [INFO] pip 업그레이드...
pip install --upgrade pip -q >nul 2>&1

:: --- install ---
echo [INFO] 의존성 설치 중... (1-2분 소요)
pip install -e ".[search,portrait,mcp]" -q 2>&1
echo [OK] 의존성 설치 완료

:: --- .env setup ---
set "ENV_FILE=%SCRIPT_DIR%.env"
if not exist "%ENV_FILE%" (
    echo [INFO] .env 파일 생성 중...
    copy "%SCRIPT_DIR%.env.example" "%ENV_FILE%" >nul

    echo.
    echo ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    echo 📝 API 키 설정
    echo ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    echo.
    echo AI Provider를 선택하세요:
    echo   1^) Gemini (추천 — 가장 저렴^)
    echo   2^) OpenAI GPT
    echo   3^) Anthropic Claude
    echo   4^) Ollama (로컬 — 무료^)
    echo.
    set /p "PROVIDER_CHOICE=선택 [1-4, 기본값 1]: "
    if "!PROVIDER_CHOICE!"=="" set PROVIDER_CHOICE=1

    if "!PROVIDER_CHOICE!"=="1" (
        echo.
        echo Gemini API 키가 필요합니다.
        echo   → https://aistudio.google.com/apikey 에서 무료 발급
        echo.
        set /p "API_KEY=Gemini API Key: "
        
        powershell -Command "(Get-Content '%ENV_FILE%') -replace '^AI_PROVIDER=.*', 'AI_PROVIDER=gemini' -replace '^GEMINI_API_KEY=.*', 'GEMINI_API_KEY=!API_KEY!' | Set-Content '%ENV_FILE%'"
    )
    if "!PROVIDER_CHOICE!"=="2" (
        echo.
        echo OpenAI API 키가 필요합니다.
        echo   → https://platform.openai.com/api-keys 에서 발급
        echo.
        set /p "API_KEY=OpenAI API Key: "
        
        powershell -Command "(Get-Content '%ENV_FILE%') -replace '^AI_PROVIDER=.*', 'AI_PROVIDER=openai' -replace '^# OPENAI_API_KEY=.*', 'OPENAI_API_KEY=!API_KEY!' | Set-Content '%ENV_FILE%'"
    )
    if "!PROVIDER_CHOICE!"=="3" (
        echo.
        echo Anthropic API 키가 필요합니다.
        echo   → https://console.anthropic.com/settings/keys 에서 발급
        echo.
        set /p "API_KEY=Anthropic API Key: "
        
        powershell -Command "(Get-Content '%ENV_FILE%') -replace '^AI_PROVIDER=.*', 'AI_PROVIDER=anthropic' -replace '^# ANTHROPIC_API_KEY=.*', 'ANTHROPIC_API_KEY=!API_KEY!' | Set-Content '%ENV_FILE%'"
    )
    if "!PROVIDER_CHOICE!"=="4" (
        echo.
        set /p "OLLAMA_URL=Ollama 서버 URL [http://localhost:11434]: "
        if "!OLLAMA_URL!"=="" set OLLAMA_URL=http://localhost:11434
        set /p "OLLAMA_MDL=Ollama 모델 [qwen3.5:4b]: "
        if "!OLLAMA_MDL!"=="" set OLLAMA_MDL=qwen3.5:4b
        
        powershell -Command "(Get-Content '%ENV_FILE%') -replace '^AI_PROVIDER=.*', 'AI_PROVIDER=ollama' -replace '^# OLLAMA_BASE_URL=.*', 'OLLAMA_BASE_URL=!OLLAMA_URL!' -replace '^# OLLAMA_MODEL=.*', 'OLLAMA_MODEL=!OLLAMA_MDL!' | Set-Content '%ENV_FILE%'"
    )
    echo [OK] .env 설정 완료
) else (
    echo [OK] .env 이미 존재 — 건너뜀
)

:: --- MOD_ROOT auto-detect ---
echo [INFO] 모드 폴더 탐색 중...
set "HOI4_DOCS=%USERPROFILE%\Documents\Paradox Interactive\Hearts of Iron IV\mod"
if exist "%HOI4_DOCS%" (
    echo [OK] HOI4 모드 폴더 발견
    echo.
    echo 사용 가능한 모드:
    set MOD_COUNT=0
    for /d %%d in ("%HOI4_DOCS%\*") do (
        set /a MOD_COUNT+=1
        echo   !MOD_COUNT!^) %%~nxd
        set "MOD_!MOD_COUNT!=%%d"
    )
    if !MOD_COUNT! gtr 0 (
        echo.
        set /p "MOD_CHOICE=모드 번호 선택 (Enter로 건너뛰기): "
        if defined MOD_CHOICE (
            set "SELECTED_MOD=!MOD_!MOD_CHOICE!!"
        )
    )
) else (
    echo [WARN] HOI4 모드 폴더를 찾지 못했습니다.
)

:: --- Done ---
echo.
echo ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo ✅ 설치 완료!
echo ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo.
echo 실행 방법:
echo.
echo   .venv\Scripts\activate
if defined SELECTED_MOD (
    echo   hoi4-agent "!SELECTED_MOD!"
) else (
    echo   hoi4-agent "경로\모드폴더"
)
echo.
echo 웹 브라우저에서 http://localhost:8501 로 접속하세요.
echo.
pause
