import os
from typing import Any, Dict, List, Optional
import uuid

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, Response, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_db
from app.core.logging import logger
from app.models.lead_action import LeadAction
from app.models.tenant import Tenant
from app.schemas.crew_surge import (
    CrewBidClaimRequest,
    CrewBidClaimResponse,
    CrewSubcontractor,
    SurgeBidBroadcast,
    SurgeBidCreateRequest,
)
from app.services.crew_surge import crew_surge_service

router = APIRouter(tags=["Autonomous 1099 Crew Surge Dispatch & Shift Bidding Engine"])

TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "templates")
templates = Jinja2Templates(directory=TEMPLATES_DIR)


@router.post(
    "/api/v1/crew-surge/trigger-bid/{action_id}",
    response_model=SurgeBidBroadcast,
    summary="Trigger On-Demand Crew Surge Bid Broadcast",
    description="Calculates 65/35 contractor margin, sets 15-minute countdown, and broadcasts to DMV 1099 trade network.",
)
@router.post(
    "/crew-surge/trigger-bid/{action_id}",
    response_model=SurgeBidBroadcast,
    include_in_schema=False,
)
async def trigger_surge_bid_endpoint(
    action_id: str,
    request: Request,
    payload: Optional[SurgeBidCreateRequest] = None,
    db: AsyncSession = Depends(get_db),
) -> SurgeBidBroadcast:
    try:
        action_uuid = uuid.UUID(str(action_id))
    except (ValueError, AttributeError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Dispatch lead '{action_id}' not found",
        )

    stmt = (
        select(LeadAction)
        .options(selectinload(LeadAction.tenant))
        .where(LeadAction.id == action_uuid)
    )
    action = (await db.execute(stmt)).scalar_one_or_none()
    if not action:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Dispatch lead '{action_id}' not found",
        )

    # Read optional JSON request body if present
    ticket_val: Optional[float] = None
    split_pct: float = 0.65
    sla_mins: int = 45

    if payload is not None:
        ticket_val = payload.ticket_value
        if payload.split_percentage is not None:
            split_pct = payload.split_percentage
        if payload.arrival_sla_minutes is not None:
            sla_mins = payload.arrival_sla_minutes
    else:
        # Check query params as fallback
        query_ticket = request.query_params.get("ticket_value")
        if query_ticket:
            try:
                ticket_val = float(query_ticket)
            except ValueError:
                pass

    base_url = str(request.base_url).rstrip("/")
    broadcast = await crew_surge_service.create_surge_bid(
        action=action,
        ticket_value=ticket_val,
        split_percentage=split_pct,
        arrival_sla_minutes=sla_mins,
        base_url=base_url,
        db=db,
    )
    return broadcast


@router.get(
    "/crew-bid/{bid_id}",
    summary="View Surge Shift Bid Portal",
    description="Renders mobile-first luxury 1-tap claim view with 15-min countdown, pays banner, and compliance checks.",
)
@router.get(
    "/api/v1/crew-surge/bid/{bid_id}",
    response_model=SurgeBidBroadcast,
    summary="Get Surge Shift Bid Details (JSON)",
)
async def get_surge_bid_portal(
    bid_id: str,
    request: Request,
    format: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
) -> Response:
    lookup = await crew_surge_service.get_bid_and_action(bid_id, db)
    if not lookup:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Surge bid '{bid_id}' not found",
        )

    broadcast, action = lookup
    tenant = action.tenant if action else None

    accept_header = request.headers.get("accept", "").lower()
    if format == "json" or "application/json" in accept_header:
        return JSONResponse(content=broadcast.model_dump())

    # Get sample pre-filled enrolled subcontractor for quick demo testing
    sample_sub = crew_surge_service.get_subcontractor("sub-dmv-mendez")

    return templates.TemplateResponse(
        request=request,
        name="crew_bid.html",
        context={
            "bid": broadcast,
            "action": action,
            "tenant": tenant,
            "sample_sub": sample_sub,
            "all_subs": crew_surge_service.get_all_subcontractors(),
        },
    )


@router.post(
    "/api/v1/crew-surge/claim/{bid_id}",
    response_model=CrewBidClaimResponse,
    summary="Claim On-Demand Surge Shift",
    description="Validates W-9 & COI compliance gates, locks job against race conditions, and generates 1099 voucher.",
)
@router.post(
    "/crew-bid/{bid_id}/claim",
    response_model=CrewBidClaimResponse,
    include_in_schema=False,
)
async def claim_surge_bid_endpoint(
    bid_id: str,
    request: Request,
    claim_payload: Optional[CrewBidClaimRequest] = None,
    subcontractor_id: Optional[str] = Form(None),
    subcontractor_phone: Optional[str] = Form(None),
    estimated_eta_minutes: Optional[int] = Form(None),
    db: AsyncSession = Depends(get_db),
) -> Response:
    content_type = request.headers.get("content-type", "").lower()

    if claim_payload is not None:
        req = claim_payload
    elif "application/json" in content_type:
        try:
            body = await request.json()
            req = CrewBidClaimRequest.model_validate(body)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid claim JSON payload: {exc}",
            )
    else:
        # Form submission
        sub_id = subcontractor_id or "sub-dmv-mendez"
        sub_phone = subcontractor_phone or "+17035550191"
        eta = estimated_eta_minutes if estimated_eta_minutes is not None else 35
        req = CrewBidClaimRequest(
            subcontractor_id=sub_id,
            subcontractor_phone=sub_phone,
            estimated_eta_minutes=eta,
        )

    base_url = str(request.base_url).rstrip("/")
    result = await crew_surge_service.claim_surge_bid(
        bid_id=bid_id,
        claim_data=req,
        db=db,
        base_url=base_url,
    )

    accept_header = request.headers.get("accept", "").lower()
    if "application/json" in accept_header or "application/json" in content_type:
        return JSONResponse(content=result.model_dump())

    # If submitted from browser form on /crew-bid/{bid_id}
    if result.status == "ACCEPTED":
        return RedirectResponse(
            url=f"/crew-bid/{bid_id}?status=ACCEPTED",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    elif result.status == "REJECTED_COMPLIANCE":
        return RedirectResponse(
            url=f"/crew-bid/{bid_id}?status=REJECTED_COMPLIANCE&w9_url={result.w9_portal_url}",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    elif result.status == "ALREADY_CLAIMED":
        return RedirectResponse(
            url=f"/crew-bid/{bid_id}?status=ALREADY_CLAIMED",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    else:
        return RedirectResponse(
            url=f"/crew-bid/{bid_id}?status=EXPIRED",
            status_code=status.HTTP_303_SEE_OTHER,
        )


@router.get(
    "/crew-network/{tenant_slug}",
    summary="Surge Crew Roster & Bidding Dashboard",
    description="Renders multi-crew roster with compliance statuses (W-9 & COI), active bids, and contractor margin analytics.",
)
async def crew_network_dashboard(
    tenant_slug: str,
    request: Request,
    format: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
) -> Response:
    stmt = select(Tenant).where(Tenant.slug == tenant_slug)
    tenant = (await db.execute(stmt)).scalar_one_or_none()
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Contractor tenant '{tenant_slug}' not found",
        )

    subcontractors = crew_surge_service.get_all_subcontractors()
    bids = await crew_surge_service.get_active_bids_for_tenant(tenant_slug, db)

    total_crews = len(subcontractors)
    w9_ok = sum(1 for s in subcontractors if s.w9_verified)
    coi_ok = sum(1 for s in subcontractors if s.coi_verified)
    compliance_rate = round((w9_ok / total_crews * 100) if total_crews else 100.0, 1)

    open_bids = [b for b in bids if b.status == "OPEN"]
    claimed_bids = [b for b in bids if b.status == "CLAIMED"]
    total_payout = round(sum(b.subcontractor_payout for b in claimed_bids), 2)
    total_margin = round(sum(b.contractor_margin for b in claimed_bids), 2)

    metrics = {
        "total_crews": total_crews,
        "w9_verified_count": w9_ok,
        "coi_verified_count": coi_ok,
        "compliance_rate": compliance_rate,
        "open_bids_count": len(open_bids),
        "claimed_bids_count": len(claimed_bids),
        "total_subcontractor_payout": total_payout,
        "total_contractor_margin": total_margin,
    }

    accept_header = request.headers.get("accept", "").lower()
    if format == "json" or "application/json" in accept_header:
        return JSONResponse(
            content={
                "tenant": tenant.slug,
                "metrics": metrics,
                "subcontractors": [s.model_dump() for s in subcontractors],
                "bids": [b.model_dump() for b in bids],
            }
        )

    return templates.TemplateResponse(
        request=request,
        name="crew_network.html",
        context={
            "tenant": tenant,
            "subcontractors": subcontractors,
            "bids": bids,
            "open_bids": open_bids,
            "claimed_bids": claimed_bids,
            "metrics": metrics,
        },
    )


@router.get(
    "/api/v1/crew-surge/active-bids/{tenant_slug}",
    response_model=List[SurgeBidBroadcast],
    summary="Fetch Active Surge Bids for Tenant",
    description="Returns JSON array of open and claimed surge bids for contractor fleet operations.",
)
async def get_active_bids_endpoint(
    tenant_slug: str,
    db: AsyncSession = Depends(get_db),
) -> List[SurgeBidBroadcast]:
    stmt = select(Tenant).where(Tenant.slug == tenant_slug)
    tenant = (await db.execute(stmt)).scalar_one_or_none()
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant '{tenant_slug}' not found",
        )
    return await crew_surge_service.get_active_bids_for_tenant(tenant_slug, db)


@router.get(
    "/api/v1/crew-surge/subcontractors",
    response_model=List[CrewSubcontractor],
    summary="Fetch Enrolled 1099 Subcontractors",
    description="Returns verified DMV 1099 subcontractors across plumbing, HVAC, roofing, water, and electrical.",
)
async def list_subcontractors_endpoint() -> List[CrewSubcontractor]:
    return crew_surge_service.get_all_subcontractors()
