import uuid
from typing import Any, Dict, Optional
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.core.logging import logger
from app.models.lead_action import LeadAction
from app.models.tenant import Tenant
from app.schemas.reputation import (
    ReviewOutcome,
    ReviewRatingSubmission,
    ReviewRequestTriggerResponse,
)
from app.services.reputation import (
    process_review_reply,
    trigger_post_job_review_request,
)

router = APIRouter()


@router.post(
    "/reputation/trigger/{action_id}",
    response_model=ReviewRequestTriggerResponse,
    summary="Trigger Post-Job Review Request",
    description="Sends SMS to customer prompting 1-5 star feedback after job/contract completion.",
)
async def trigger_review_request(
    action_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> ReviewRequestTriggerResponse:
    # 1. Fetch LeadAction
    query = select(LeadAction).where(LeadAction.id == action_id)
    lead_action = (await db.execute(query)).scalar_one_or_none()

    if not lead_action:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Lead action '{action_id}' not found",
        )

    # 2. Fetch associated Tenant
    tenant_query = select(Tenant).where(Tenant.id == lead_action.tenant_id)
    tenant = (await db.execute(tenant_query)).scalar_one_or_none()

    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Associated tenant not found",
        )

    result = await trigger_post_job_review_request(
        lead_action=lead_action,
        tenant=tenant,
        db=db,
    )

    if not result.get("success"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result.get("error", "Failed to trigger review request"),
        )

    return ReviewRequestTriggerResponse(
        action_id=str(lead_action.id),
        tenant_slug=tenant.slug,
        status="PROMPTED",
        sms_sent=result.get("sms_sent", False),
        customer_phone=result.get("customer_phone"),
    )


@router.post(
    "/reputation/reply/{action_id}",
    response_model=ReviewOutcome,
    summary="Submit Review Rating & Feedback",
    description="Processes customer 1-5 star rating: routes 4-5 stars to Google, or shields 1-3 stars with owner SMS alert.",
)
async def submit_review_reply(
    action_id: uuid.UUID,
    submission: ReviewRatingSubmission,
    db: AsyncSession = Depends(get_db),
) -> ReviewOutcome:
    # 1. Fetch LeadAction
    query = select(LeadAction).where(LeadAction.id == action_id)
    lead_action = (await db.execute(query)).scalar_one_or_none()

    if not lead_action:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Lead action '{action_id}' not found",
        )

    # 2. Fetch associated Tenant
    tenant_query = select(Tenant).where(Tenant.id == lead_action.tenant_id)
    tenant = (await db.execute(tenant_query)).scalar_one_or_none()

    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Associated tenant not found",
        )

    outcome = await process_review_reply(
        rating=submission.rating,
        feedback=submission.feedback or "",
        lead_action=lead_action,
        tenant=tenant,
        db=db,
    )
    return outcome
