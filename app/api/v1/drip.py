from typing import Optional
from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.schemas.drip import (
    DripCampaignStatus,
    DripLeadStatus,
    DripTriggerResponse,
)
from app.services.drip import drip_service

router = APIRouter(prefix="/drip", tags=["Autonomous B2B Drip & Territory Follow-Up Engine"])


@router.get(
    "/pipeline",
    response_model=DripCampaignStatus,
    summary="Get Active B2B Contractor Drip Pipeline",
    description="Returns enrolled DMV target contractors, current qualification stages, missed call leaks, and scheduled touches.",
)
async def get_drip_pipeline() -> DripCampaignStatus:
    return drip_service.get_pipeline()


@router.post(
    "/trigger",
    response_model=DripTriggerResponse,
    summary="Trigger B2B Drip Follow-Up Evaluation Cycle",
    description="Manually triggers scheduled 48h Audit and Day 5 Onboard follow-up evaluations across the contractor portfolio.",
)
async def trigger_drip_cycle(
    force_all: bool = Query(False, description="Force dispatch of follow-up messages regardless of time gates"),
    db: AsyncSession = Depends(get_db),
) -> DripTriggerResponse:
    return await drip_service.evaluate_drip_schedules(db=db, force_all=force_all)


@router.patch(
    "/leads/{contractor_id}/status",
    summary="Update Contractor Lead Drip Status",
    description="Transitions contractor lead stage (CONTACTED, FOLLOWUP_1_DUE, FOLLOWUP_2_DUE, REPLIED, CLOSED).",
)
async def update_contractor_status(
    contractor_id: str,
    new_status: DripLeadStatus = Query(..., description="Target status"),
    notes: Optional[str] = Query(None, description="Optional transition notes"),
):
    lead = drip_service.update_lead_status(contractor_id, new_status, notes)
    if not lead:
        return {"status": "NOT_FOUND", "contractor_id": contractor_id}
    return {"status": "UPDATED", "lead": lead}
