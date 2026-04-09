# ============================================================
#  Local AI Assistant – Dev Launcher (PowerShell)
#  실행: powershell -ExecutionPolicy Bypass -File start.ps1
# ============================================================

$Root = $PSScriptRoot

# ── 루트 디렉토리 확인 ─────────────────────────────────────────
if (-not (Test-Path "$Root\server\main.py")) {
    Write-Host "[ERROR] server\main.py not found. 프로젝트 루트에서 실행하세요." -ForegroundColor Red
    exit 1
}

# ── 자식 프로세스 추적 (스크립트 종료 시 정리) ───────────────────
$Procs = @()

function Stop-All {
    Write-Host "`n[Cleanup] 실행 중인 프로세스를 종료합니다..." -ForegroundColor Yellow
    foreach ($p in $Procs) {
        if (-not $p.HasExited) {
            try {
                # 자식 프로세스 트리까지 종료
                taskkill /PID $p.Id /T /F 2>$null | Out-Null
            } catch {}
        }
    }
}

# Ctrl+C 또는 스크립트 종료 시 정리
Register-EngineEvent PowerShell.Exiting -Action { Stop-All } | Out-Null
try {

# ── 1. FastAPI 서버 ────────────────────────────────────────────
Write-Host "[1/4] FastAPI 서버 시작..." -ForegroundColor Cyan
$api = Start-Process -FilePath "python" `
    -ArgumentList "main.py" `
    -WorkingDirectory "$Root\server" `
    -PassThru -WindowStyle Minimized
$Procs += $api
Write-Host "      PID $($api.Id) → http://localhost:8000"

# ── 2. Vue 개발 서버 ───────────────────────────────────────────
Write-Host "[2/4] Vue 개발 서버 시작..." -ForegroundColor Cyan
if (-not (Test-Path "$Root\apps\frontend\node_modules")) {
    Write-Host "      frontend 의존성 설치 중..."
    npm install --prefix "$Root\apps\frontend" | Out-Null
}
$vite = Start-Process -FilePath "cmd" `
    -ArgumentList "/c npm run dev" `
    -WorkingDirectory "$Root\apps\frontend" `
    -PassThru -WindowStyle Minimized
$Procs += $vite
Write-Host "      PID $($vite.Id) → http://localhost:5173"

# ── 3. Electron 의존성 확인 ────────────────────────────────────
Write-Host "[3/4] Electron 의존성 확인..." -ForegroundColor Cyan
if (-not (Test-Path "$Root\apps\desktop\node_modules")) {
    Write-Host "      desktop 의존성 설치 중..."
    npm install --prefix "$Root\apps\desktop" | Out-Null
}
Write-Host "      OK"

# ── 4. 서버 준비 대기 (HTTP 폴링) ─────────────────────────────
Write-Host "[4/4] 서버 준비 대기 중..." -ForegroundColor Cyan
$Timeout = 30
$Interval = 1

function Wait-For-Port {
    param([string]$Url, [string]$Name)
    $elapsed = 0
    while ($elapsed -lt $Timeout) {
        try {
            $res = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 1 -ErrorAction Stop
            if ($res.StatusCode -lt 500) {
                Write-Host "      $Name ready ($($elapsed)s)" -ForegroundColor Green
                return $true
            }
        } catch {}
        Start-Sleep -Seconds $Interval
        $elapsed += $Interval
        Write-Host "      $Name 대기 중... ($($elapsed)s)" -NoNewline
        Write-Host "`r" -NoNewline
    }
    Write-Host "      [WARN] $Name 응답 없음 — 계속 진행합니다." -ForegroundColor Yellow
    return $false
}

Wait-For-Port "http://localhost:8000/api/health" "FastAPI" | Out-Null
Wait-For-Port "http://localhost:5173"            "Vite   " | Out-Null

# ── Electron 실행 ──────────────────────────────────────────────
Write-Host ""
Write-Host "  Electron 시작..." -ForegroundColor Green
$electron = Start-Process -FilePath "npx" `
    -ArgumentList "electron . --dev" `
    -WorkingDirectory "$Root\apps\desktop" `
    -PassThru -WindowStyle Normal
$Procs += $electron

Write-Host "  PID $($electron.Id)"
Write-Host ""
Write-Host "  [실행 중] Electron 창을 닫거나 이 창에서 Ctrl+C 를 누르면 모든 프로세스가 종료됩니다." -ForegroundColor DarkGray

# Electron 종료될 때까지 대기
$electron.WaitForExit()

} finally {
    Stop-All
    Write-Host "[Done]" -ForegroundColor Green
}
