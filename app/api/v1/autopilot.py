from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.schemas.autopilot import AutopilotRunNowResponse, AutopilotStatusReport
from app.services.autopilot import autopilot_service

router = APIRouter(prefix="/autopilot", tags=["24/7 Autonomous Autopilot Worker"])


@router.get(
    "/status",
    response_model=AutopilotStatusReport,
    summary="24/7 Autonomous Autopilot Status & Telemetry",
    description="Returns live background worker status, active task registry, last cycle timestamp, and recent task execution logs.",
)
async def get_autopilot_status() -> AutopilotStatusReport:
    return autopilot_service.get_status_report()


@router.post(
    "/run-now",
    response_model=AutopilotRunNowResponse,
    summary="Trigger Immediate Autonomous Cycle",
    description="Operator override to execute a manual autonomous operations pass across all 5 core tasks immediately.",
)
async def run_autopilot_now(
    force_all: bool = Query(True, description="Force execution of time-gated tasks (Fleet routing and ROI digests)"),
) -> AutopilotRunNowResponse:
    result = await autopilot_service.execute_autonomous_cycle(force_all=force_all)
    return result

