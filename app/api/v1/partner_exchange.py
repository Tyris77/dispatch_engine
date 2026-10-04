import os
import uuid
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.models.tenant import Tenant
from app.schemas.partner_exchange import PartnerReferralDispatchPayload, PartnerReferralTrade
from app.services.partner_exchange import partner_exchange_service

router = APIRouter(tags=["Cross-Trade B2B Partner Exchange & Finder Fee Splitter"])

TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "templates")
templates = Jinja2Templates(directory=TEMPLATES_DIR)


@router.get(
    "/partner-exchange/{tenant_slug}",
    response_class=HTMLResponse,
    summary="Cross-Trade B2B Partner Exchange Console",
    description="Interactive B2B trade network console displaying partner roster, active cross-trade referrals, and 10% reciprocal finder fee settlements.",
)
async def get_partner_exchange_view(
    tenant_slug: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    format: Optional[str] = Query(None),
) -> Response:
    tenant = (await db.execute(select(Tenant).where(Tenant.slug == tenant_slug))).scalar_one_or_none()
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Contractor tenant '{tenant_slug}' not found",
        )

    roster = partner_exchange_service.get_partner_network_roster(tenant)
    referrals = partner_exchange_service.get_partner_referrals(tenant)

    # Compute ledger metrics
    total_referred_volume = sum(r.estimated_job_value for r in referrals)
    total_finder_fees = sum(r.finder_fee_due for r in referrals)
    settled_fees = sum(r.finder_fee_due for r in referrals if r.status == "FEE_SETTLED")
    pending_fees = total_finder_fees - settled_fees

    accept_header = request.headers.get("accept", "").lower()
    if format == "json" or "application/json" in accept_header:
        return JSONResponse(
            content={
                "tenant_slug": tenant_slug,
                "partner_count": len(roster),
                "partners": [p.model_dump() for p in roster],
                "referral_count": len(referrals),
                "referrals": [r.model_dump() for r in referrals],
                "total_referred_volume": total_referred_volume,
                "total_finder_fees": total_finder_fees,
                "settled_fees": settled_fees,
                "pending_fees": pending_fees,
            }
        )

    return templates.TemplateResponse(
        request=request,
        name="partner_exchange.html",
        context={
            "tenant": tenant,
            "roster": roster,
            "referrals": referrals,
            "total_referred_volume": total_referred_volume,
            "total_finder_fees": total_finder_fees,
            "settled_fees": settled_fees,
            "pending_fees": pending_fees,
        },
    )


@router.post(
    "/api/v1/partner-exchange/refer/{action_id}",
    response_model=PartnerReferralTrade,
    summary="Dispatch Cross-Trade Referral",
    description="Packages customer contact and diagnostic details into a warm B2B lead dispatched to a trade partner with 10% finder fee tracking.",
)
async def dispatch_partner_referral_api(
    action_id: uuid.UUID,
    payload: PartnerReferralDispatchPayload,
    db: AsyncSession = Depends(get_db),
) -> PartnerReferralTrade:
    from app.models.lead_action import LeadAction

    lead = (await db.execute(select(LeadAction).where(LeadAction.id == action_id))).scalar_one_or_none()
    if not lead:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job record '{action_id}' not found",
        )

    tenant = (await db.execute(select(Tenant).where(Tenant.id == lead.tenant_id))).scalar_one_or_none()
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant for job '{action_id}' not found",
        )

    try:
        referral = await partner_exchange_service.dispatch_cross_trade_referral(
            action_id=action_id,
            target_trade=payload.target_trade,
            referring_tenant=tenant,
            db=db,
            estimated_job_value=payload.estimated_job_value,
            custom_service_needed=payload.service_needed,
            specific_partner_id=payload.recipient_partner_id,
        )
        return referral
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )


@router.post(
    "/api/v1/partner-exchange/settle/{referral_id}",
    summary="Settle 10% Finder Fee",
    description="Records finder fee payment settlement between trade partner shops.",
)
async def settle_finder_fee_api(
    referral_id: str,
    tenant_slug: str = Query(..., description="Tenant slug"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    tenant = (await db.execute(select(Tenant).where(Tenant.slug == tenant_slug))).scalar_one_or_none()
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant '{tenant_slug}' not found",
        )

    settled = await partner_exchange_service.settle_finder_fee(
        referral_id=referral_id,
        tenant=tenant,
        db=db,
    )
    if not settled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Referral '{referral_id}' not found in tenant ledger",
        )

    return {"status": "SUCCESS", "referral_id": referral_id, "fee_status": "FEE_SETTLED"}
