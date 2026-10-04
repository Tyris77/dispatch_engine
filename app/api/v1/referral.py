import os
import uuid
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.models.lead_action import LeadAction
from app.models.tenant import Tenant
from app.schemas.referral import (
    ReferralClaimResponse,
    ReferralClaimSubmission,
    ReferralVoucher,
)
from app.services.referral import referral_service

router = APIRouter(tags=["Customer Neighbor Referral Engine"])

TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "templates")
templates = Jinja2Templates(directory=TEMPLATES_DIR)


@router.get(
    "/refer/{action_id}",
    response_class=HTMLResponse,
    summary="Customer Neighbor Referral Voucher Page",
    description="Branded #0B0F19 voucher page with 1-tap emergency booking and camera quote form.",
)
async def get_referral_voucher_view(
    action_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    format: Optional[str] = Query(None),
) -> Response:
    # 1. Resolve lead action
    try:
        action_uuid = uuid.UUID(action_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Invalid referral voucher ID: '{action_id}'",
        )

    stmt = select(LeadAction).where(LeadAction.id == action_uuid)
    lead = (await db.execute(stmt)).scalar_one_or_none()
    if not lead:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Referral voucher '{action_id}' not found",
        )

    # 2. Resolve tenant
    tenant_stmt = select(Tenant).where(Tenant.id == lead.tenant_id)
    tenant = (await db.execute(tenant_stmt)).scalar_one_or_none()
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Contractor tenant not found for this voucher",
        )

    # 3. Resolve or generate voucher
    base_url = str(request.base_url).rstrip("/")
    if lead.referral_data and "referral_code" in lead.referral_data:
        try:
            voucher = ReferralVoucher(**lead.referral_data)
        except Exception:
            voucher = referral_service.generate_referral_voucher(lead, tenant, base_url=base_url)
            await db.commit()
    else:
        voucher = referral_service.generate_referral_voucher(lead, tenant, base_url=base_url)
        await db.commit()

    # 4. JSON content negotiation
    accept_header = request.headers.get("accept", "").lower()
    if format == "json" or "application/json" in accept_header:
        return JSONResponse(content=voucher.model_dump())

    # 5. Render HTML
    return templates.TemplateResponse(
        request=request,
        name="referral_voucher.html",
        context={
            "voucher": voucher,
            "tenant": tenant,
            "lead": lead,
        },
    )


@router.post(
    "/refer/{action_id}/claim",
    response_model=ReferralClaimResponse,
    summary="Process Neighbor Referral Claim & Instant Dispatch",
    description="Processes referred neighbor booking, applies $150 discount, and credits referring customer $100.",
)
async def claim_referral_voucher(
    action_id: str,
    submission: ReferralClaimSubmission,
    db: AsyncSession = Depends(get_db),
) -> ReferralClaimResponse:
    try:
        action_uuid = uuid.UUID(action_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Invalid referral voucher ID: '{action_id}'",
        )

    stmt = select(LeadAction).where(LeadAction.id == action_uuid)
    lead = (await db.execute(stmt)).scalar_one_or_none()
    if not lead:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Referral voucher '{action_id}' not found",
        )

    tenant_stmt = select(Tenant).where(Tenant.id == lead.tenant_id)
    tenant = (await db.execute(tenant_stmt)).scalar_one_or_none()
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Contractor tenant not found for this voucher",
        )

    response = await referral_service.process_referral_claim(
        submission=submission,
        tenant=tenant,
        db=db,
    )
    return response


@router.get(
    "/api/v1/referral/{action_id}",
    response_model=ReferralVoucher,
    summary="Get Referral Voucher JSON",
    description="Fetches referral voucher metadata, share link, and rewards earned.",
)
async def get_referral_voucher_api(
    action_id: str,
    db: AsyncSession = Depends(get_db),
) -> ReferralVoucher:
    try:
        action_uuid = uuid.UUID(action_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Invalid referral voucher ID: '{action_id}'",
        )

    stmt = select(LeadAction).where(LeadAction.id == action_uuid)
    lead = (await db.execute(stmt)).scalar_one_or_none()
    if not lead:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Referral voucher '{action_id}' not found",
        )

    tenant_stmt = select(Tenant).where(Tenant.id == lead.tenant_id)
    tenant = (await db.execute(tenant_stmt)).scalar_one_or_none()
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Contractor tenant not found for this voucher",
        )

    voucher = await referral_service.get_referral_voucher_by_action_id(
        action_id=action_id,
        tenant=tenant,
        db=db,
    )
    if not voucher:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Failed to resolve referral voucher for '{action_id}'",
        )
    return voucher
