@echo off
setlocal enabledelayedexpansion

echo ============================================================
echo  Local AI Assistant – Dev Mode
echo ============================================================

REM ── Check deps ────────────────────────────────────────────────
if not exist "server\main.py" (
    echo ERROR: Run this script from the repo root.
    pause & exit /b 1
)

REM ── FastAPI server ────────────────────────────────────────────
echo [1/4] Starting FastAPI server...
start "FastAPI" /B python server\main.py
echo       FastAPI started on http://localhost:8000

REM ── Frontend dev server ───────────────────────────────────────
echo [2/4] Starting Vue dev server...
if not exist "apps\frontend\node_modules" (
    echo       Installing frontend dependencies...
    cd apps\frontend && npm install && cd ..\..
)
start "Vite" /B cmd /c "cd apps\frontend && npm run dev"
echo       Vite started on http://localhost:5173

REM ── Install Electron deps if needed ──────────────────────────
if not exist "apps\desktop\node_modules" (
    echo [3/4] Installing Electron dependencies...
    cd apps\desktop && npm install && cd ..\..
) else (
    echo [3/4] Electron dependencies OK
)

REM ── Wait for servers to be ready ─────────────────────────────
echo [4/4] Waiting 5 seconds for servers to initialise...
timeout /t 5 /nobreak >nul

REM ── Electron ─────────────────────────────────────────────────
echo       Launching Electron...
cd apps\desktop
npx electron . --dev
cd ..\..

echo.
echo All processes stopped.
endlocal
