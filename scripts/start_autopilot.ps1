<#
.SYNOPSIS
    1-Click Hands-Off Launcher for Dispatch Engine with 24/7 Autonomous Autopilot & Cloudflare Tunnel
.DESCRIPTION
    Verifies database tables, boots the FastAPI uvicorn daemon, launches Cloudflare Tunnel,
    and displays operator telemetry.
#>

$ErrorActionPreference = "Stop"

Write-Host "==================================================================" -ForegroundColor Cyan
Write-Host " 🚀 DISPATCH ENGINE: 24/7 AUTONOMOUS AUTOPILOT LAUNCHER" -ForegroundColor Green
Write-Host "==================================================================" -ForegroundColor Cyan

# 1. Verify Python & Database Schema
Write-Host "`n[1/3] Verifying Database Schema..." -ForegroundColor Yellow
python -c "
import asyncio
from app.db.base import Base
from app.db.session import async_engine
from app.core.config import settings

async def init():
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print(f'✅ Database schema synchronized ({settings.DATABASE_URL.split(\"@\")[-1]}).')

asyncio.run(init())
"
if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ Database schema initialization failed." -ForegroundColor Red
    exit 1
}

# 2. Start Uvicorn Server in Background
Write-Host "`n[2/3] Launching Uvicorn Worker Service..." -ForegroundColor Yellow
$UvicornProc = Start-Process python -ArgumentList "-m uvicorn app.main:app --host 127.0.0.1 --port 8000 --log-level info" -PassThru -NoNewWindow
Start-Sleep -Seconds 3

# Test local health endpoint
try {
    $health = Invoke-RestMethod -Uri "http://127.0.0.1:8000/health" -Method Get -TimeoutSec 5
    Write-Host "✅ FastAPI Server is ONLINE on PID $($UvicornProc.Id) (Status: $($health.status))" -ForegroundColor Green
} catch {
    Write-Host "⚠️ Warning: Server is still warming up or health check timed out." -ForegroundColor Yellow
}

# 3. Check and Launch Cloudflare Tunnel
Write-Host "`n[3/3] Establishing Cloudflare Secure Edge Tunnel..." -ForegroundColor Yellow
$cloudflaredCmd = Get-Command cloudflared -ErrorAction SilentlyContinue

if ($cloudflaredCmd) {
    Write-Host "🌐 Starting cloudflared tunnel to http://localhost:8000..." -ForegroundColor Cyan
    Write-Host "Press Ctrl+C at any time to gracefully stop.`n" -ForegroundColor DarkGray
    & cloudflared tunnel --url http://localhost:8000
} else {
    Write-Host "ℹ️  'cloudflared' CLI was not found in PATH." -ForegroundColor Yellow
    Write-Host "👉 Install via: winget install --id Cloudflare.cloudflared" -ForegroundColor Gray
    Write-Host "👉 Or download from: https://github.com/cloudflare/cloudflared/releases" -ForegroundColor Gray
    Write-Host "`n==================================================================" -ForegroundColor Green
    Write-Host " 🟢 24/7 AUTONOMOUS AUTOPILOT IS ACTIVE LOCALLY" -ForegroundColor Green
    Write-Host "==================================================================" -ForegroundColor Green
    Write-Host " Operator Console: http://127.0.0.1:8000/dashboard" -ForegroundColor White
    Write-Host " Telemetry API:    http://127.0.0.1:8000/api/v1/autopilot/status" -ForegroundColor White
    Write-Host " Trigger Cycle:    curl -X POST http://127.0.0.1:8000/api/v1/autopilot/run-now" -ForegroundColor White
    Write-Host " Press Enter to stop server..." -ForegroundColor DarkGray
    Read-Host
    Stop-Process -Id $UvicornProc.Id -Force
}
