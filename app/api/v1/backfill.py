import uuid
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.models.lead_action import LeadAction
from app.models.tenant import Tenant
from app.schemas.backfill import BackfillBroadcastResult
from app.services.backfill import backfill_service

router = APIRouter(tags=["Smart Cancellation Slot Backfill Engine"])


@router.post(
    "/api/v1/backfill/trigger/{action_id}",
    response_model=BackfillBroadcastResult,
    summary="Trigger Smart Cancellation Slot Backfill Broadcast",
    description="Detects appointment cancellation, scans corridor leads, and broadcasts $50 instant route credit SMS offers.",
)
async def trigger_cancellation_backfill_endpoint(
    action_id: uuid.UUID,
    request: Request,
    tenant_slug: Optional[str] = Query(None, description="Optional tenant slug override"),
    db: AsyncSession = Depends(get_db),
) -> BackfillBroadcastResult:
    # 1. Fetch LeadAction to verify existence and tenant
    stmt = select(LeadAction).where(LeadAction.id == action_id)
    lead_action = (await db.execute(stmt)).scalar_one_or_none()
    if not lead_action:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"LeadAction '{action_id}' not found",
        )

    # 2. Fetch Tenant
    tenant: Optional[Tenant] = None
    if tenant_slug:
        t_stmt = select(Tenant).where(Tenant.slug == tenant_slug)
        tenant = (await db.execute(t_stmt)).scalar_one_or_none()
    if not tenant:
        t_stmt = select(Tenant).where(Tenant.id == lead_action.tenant_id)
        tenant = (await db.execute(t_stmt)).scalar_one_or_none()
    if not tenant:
        t_stmt = select(Tenant).where(Tenant.is_active == True)
        tenant = (await db.execute(t_stmt)).scalars().first()

    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active tenant found for slot backfill",
        )

    # 3. Process Cancellation Backfill Broadcast
    result = await backfill_service.process_slot_cancellation(
        canceled_action_id=action_id,
        tenant=tenant,
        db=db,
    )
    return result


@router.post(
    "/api/v1/backfill/claim/{candidate_action_id}",
    response_model=BackfillBroadcastResult,
    summary="Claim Cancellation Backfill Slot",
    description="Books the candidate customer, applies $50 route credit, and confirms the schedule.",
)
async def claim_backfill_slot_endpoint(
    candidate_action_id: uuid.UUID,
    request: Request,
    slot_time: str = Query("Today 2:00 PM - 4:00 PM", description="Appointment time window"),
    db: AsyncSession = Depends(get_db),
) -> BackfillBroadcastResult:
    # 1. Fetch candidate lead
    stmt = select(LeadAction).where(LeadAction.id == candidate_action_id)
    candidate_lead = (await db.execute(stmt)).scalar_one_or_none()
    if not candidate_lead:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Candidate LeadAction '{candidate_action_id}' not found",
        )

    tenant_stmt = select(Tenant).where(Tenant.id == candidate_lead.tenant_id)
    tenant = (await db.execute(tenant_stmt)).scalar_one_or_none()
    if not tenant:
        tenant_stmt = select(Tenant).where(Tenant.is_active == True)
        tenant = (await db.execute(tenant_stmt)).scalars().first()

    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active tenant found",
        )

    result = await backfill_service.claim_backfill_slot(
        candidate_action_id=candidate_action_id,
        slot_time=slot_time,
        tenant=tenant,
        db=db,
    )
    return result
