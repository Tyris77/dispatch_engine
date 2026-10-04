#!/usr/bin/env bash
# ==============================================================================
# 🚀 DISPATCH ENGINE: 24/7 AUTONOMOUS AUTOPILOT 1-CLICK LAUNCHER
# ==============================================================================
set -euo pipefail

echo -e "\033[1;36m==================================================================\033[0m"
echo -e "\033[1;32m 🚀 DISPATCH ENGINE: 24/7 AUTONOMOUS AUTOPILOT LAUNCHER \033[0m"
echo -e "\033[1;36m==================================================================\033[0m"

# 1. Verify Database Schema
echo -e "\n\033[1;33m[1/3] Verifying Database Schema...\033[0m"
python3 -c "
import asyncio
from app.db.base import Base
from app.db.session import async_engine
from app.core.config import settings

async def init():
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print(f'✅ Database schema synchronized.')

asyncio.run(init())
"

# 2. Launch Uvicorn in Background
echo -e "\n\033[1;33m[2/3] Launching Uvicorn Worker Service...\033[0m"
python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --log-level info &
UVICORN_PID=$!
trap "kill -9 $UVICORN_PID 2>/dev/null || true" EXIT

sleep 2

# 3. Check and Launch Cloudflare Tunnel
echo -e "\n\033[1;33m[3/3] Establishing Cloudflare Secure Edge Tunnel...\033[0m"
if command -v cloudflared &> /dev/null; then
    echo -e "\033[1;36m🌐 Starting cloudflared tunnel to http://localhost:8000...\033[0m"
    cloudflared tunnel --url http://localhost:8000
else
    echo -e "\033[1;33mℹ️  'cloudflared' CLI not found in PATH.\033[0m"
    echo -e "👉 Install via: brew install cloudflared / apt install cloudflared"
    echo -e "\n\033[1;32m==================================================================\033[0m"
    echo -e "\033[1;32m 🟢 24/7 AUTONOMOUS AUTOPILOT IS ACTIVE LOCALLY\033[0m"
    echo -e "\033[1;32m==================================================================\033[0m"
    echo -e " Operator Console: http://127.0.0.1:8000/dashboard"
    echo -e " Telemetry API:    http://127.0.0.1:8000/api/v1/autopilot/status"
    echo -e " Trigger Cycle:    curl -X POST http://127.0.0.1:8000/api/v1/autopilot/run-now"
    echo -e "\nPress Ctrl+C to terminate..."
    wait $UVICORN_PID
fi
