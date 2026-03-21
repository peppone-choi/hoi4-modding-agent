@echo off
chcp 65001 >nul
title HoI4 포트레잇 관리자 v6

echo ======================================
echo   HoI4 포트레잇 관리자 v6
echo ======================================

set SCRIPT_DIR=%~dp0
set VENV=%SCRIPT_DIR%.venv\Scripts\python.exe
set PORT=5555

:: Check venv
if not exist "%VENV%" (
    echo 오류: .venv가 없습니다. install.bat을 먼저 실행하세요.
    pause
    exit /b 1
)

:: Find mod directory
set MOD_DIR=
for /d %%d in ("%SCRIPT_DIR%..\*") do (
    if exist "%%d\descriptor.mod" (
        set MOD_DIR=%%d
        goto :found
    )
)

:found
if "%MOD_DIR%"=="" (
    echo 오류: 모드 폴더를 찾을 수 없습니다.
    echo 사용법: portrait_manager.bat --mod "경로"
    pause
    exit /b 1
)

echo 모드: %MOD_DIR%
echo.
echo 브라우저에서 열기: http://localhost:%PORT%
echo 종료: Ctrl+C
echo.

:: Open browser after delay
start "" cmd /c "timeout /t 2 /nobreak >nul & start http://localhost:%PORT%"

:: Launch
cd /d "%SCRIPT_DIR%"
"%VENV%" portrait_selector.py --mod "%MOD_DIR%" --port %PORT%

pause
