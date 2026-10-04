import uuid
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.schemas.reactivation import ReactivationBatchResult, ReactivationOffer
from app.services.reactivation import reactivation_service

router = APIRouter(prefix="/reactivation", tags=["Reactivation Engines"])


@router.post(
    "/batch-scan",
    response_model=ReactivationBatchResult,
    summary="Trigger Autonomous Dead Lead Reactivation Sweep",
    description="Scans dormant leads for 48-Hour Unsigned Proposals and 6-Month Seasonal Aging Equipment (10+ yr old systems), dispatching route-credit revival SMS campaigns.",
)
async def run_batch_reactivation(
    request: Request,
    tenant_id: Optional[uuid.UUID] = Query(None, description="Optional tenant UUID to filter sweep"),
    force_all: bool = Query(False, description="If true, reactivate eligible leads regardless of timestamps"),
    db: AsyncSession = Depends(get_db),
) -> ReactivationBatchResult:
    base_url = str(request.base_url).rstrip("/")
    result = await reactivation_service.scan_and_reactivate_dead_leads(
        db=db,
        tenant_id=tenant_id,
        force_all=force_all,
        base_url=base_url,
    )
    return result


@router.post(
    "/trigger/{action_id}",
    response_model=ReactivationOffer,
    summary="1-Click Dead Lead Reactivation Trigger",
    description="Instantly generates and dispatches a personalized route-credit reactivation offer for a specific lead.",
)
async def trigger_single_lead_reactivation(
    action_id: uuid.UUID,
    request: Request,
    campaign_type: str = Query("UNSIGNED_PROPOSAL_48H", description="'UNSIGNED_PROPOSAL_48H' or 'SEASONAL_EQUIPMENT_AGE'"),
    custom_credit: float = Query(250.0, description="Route credit promotional discount in USD"),
    db: AsyncSession = Depends(get_db),
) -> ReactivationOffer:
    base_url = str(request.base_url).rstrip("/")
    try:
        offer = await reactivation_service.trigger_lead_reactivation(
            action_id=action_id,
            db=db,
            campaign_type=campaign_type,
            custom_credit=custom_credit,
            base_url=base_url,
        )
        return offer
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )
