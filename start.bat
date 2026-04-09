@echo off
setlocal enabledelayedexpansion

echo ============================================================
echo  Local AI Assistant – Dev Mode
echo  PowerShell 버전 권장: start.ps1
echo ============================================================

if not exist "server\main.py" (
    echo [ERROR] 프로젝트 루트에서 실행하세요.
    pause & exit /b 1
)

REM ── FastAPI ────────────────────────────────────────────────────
echo [1/4] FastAPI 서버 시작...
start "FastAPI" cmd /k "python server\main.py"
echo       http://localhost:8000

REM ── Vue dev server ─────────────────────────────────────────────
echo [2/4] Vue 개발 서버 시작...
if not exist "apps\frontend\node_modules" (
    echo       의존성 설치 중...
    cd apps\frontend && npm install && cd ..\..
)
start "Vite" cmd /k "cd apps\frontend && npm run dev"
echo       http://localhost:5173

REM ── Electron deps ──────────────────────────────────────────────
if not exist "apps\desktop\node_modules" (
    echo [3/4] Electron 의존성 설치 중...
    cd apps\desktop && npm install && cd ..\..
) else (
    echo [3/4] Electron 의존성 OK
)

REM ── 대기 ───────────────────────────────────────────────────────
echo [4/4] 서버 초기화 대기 (5초)...
timeout /t 5 /nobreak >nul

REM ── Electron ───────────────────────────────────────────────────
echo       Electron 시작...
cd apps\desktop
npx electron . --dev
cd ..\..

echo.
echo 종료되었습니다.
endlocal
