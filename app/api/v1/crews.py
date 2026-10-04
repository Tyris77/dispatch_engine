import os
from typing import Any, Dict, Optional
import uuid

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, Response, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_db
from app.models.lead_action import LeadAction
from app.models.tenant import Tenant
from app.schemas.crew import CrewVoucherData
from app.services.crews import crew_settlement_service

router = APIRouter(tags=["Subcontractor Crew & 1099 Settlement Ledger"])

TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "templates")
templates = Jinja2Templates(directory=TEMPLATES_DIR)


@router.post(
    "/api/v1/crews/assign/{action_id}",
    response_model=CrewVoucherData,
    summary="Assign Subcontractor Crew to Job",
    description="Assigns 1099 trade crew, computes labor payout, and generates labor settlement voucher.",
)
async def assign_crew_endpoint(
    action_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    crew_name: Optional[str] = Form(None),
    foreman_name: Optional[str] = Form(None),
    foreman_phone: Optional[str] = Form(None),
    trade_specialty: Optional[str] = Form(None),
    payout_type: Optional[str] = Form(None),
    rate_amount: Optional[float] = Form(None),
    unit_quantity: Optional[float] = Form(None),
    scope_summary: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
) -> Response:
    content_type = request.headers.get("content-type", "").lower()
    payload: Dict[str, Any] = {}

    if "application/json" in content_type:
        try:
            payload = await request.json()
        except Exception:
            payload = {}
    else:
        payload = {
            "crew_name": crew_name,
            "foreman_name": foreman_name,
            "foreman_phone": foreman_phone,
            "trade_specialty": trade_specialty,
            "payout_type": payout_type,
            "rate_amount": rate_amount,
            "unit_quantity": unit_quantity,
            "scope_summary": scope_summary,
            "notes": notes,
        }
        payload = {k: v for k, v in payload.items() if v is not None}

    try:
        voucher = await crew_settlement_service.assign_crew_to_job(
            action_id=action_id,
            crew_payload=payload,
            db=db,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )

    accept_header = request.headers.get("accept", "").lower()
    if "application/json" in accept_header or "application/json" in content_type:
        return JSONResponse(content=voucher.model_dump())

    return RedirectResponse(
        url=f"/crew-voucher/{action_id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.get(
    "/crew-voucher/{action_id}",
    response_class=HTMLResponse,
    summary="Subcontractor 1099 Labor Settlement Voucher View",
    description="Renders official printable 1099 labor settlement voucher with scope checklist and sign-off blocks.",
)
async def get_crew_voucher_view(
    action_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Response:
    stmt = (
        select(LeadAction)
        .options(selectinload(LeadAction.tenant))
        .where(LeadAction.id == action_id)
    )
    action = (await db.execute(stmt)).scalar_one_or_none()
    if not action:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Dispatch lead '{action_id}' not found",
        )

    tenant = action.tenant
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant association missing for lead",
        )

    # If crew voucher not yet generated, auto-generate standard crew voucher
    voucher_data = action.crew_data
    if not voucher_data:
        trade_spec = action.action_type or "General Mechanical & Restoration"
        default_payload = {
            "crew_name": f"{tenant.name} Specialized Trade Crew Alpha",
            "foreman_name": "Carlos Mendez",
            "foreman_phone": "+12025550188",
            "trade_specialty": trade_spec,
            "payout_type": "PERCENTAGE",
            "rate_amount": 28.0,
            "scope_summary": action.qualification_summary or "Full trade repair and installation per customer agreement.",
            "notes": "Standard 1099 labor agreement. Final release upon homeowner signature.",
        }
        voucher = await crew_settlement_service.assign_crew_to_job(
            action_id=action.id,
            crew_payload=default_payload,
            db=db,
        )
    else:
        voucher = CrewVoucherData.model_validate(voucher_data)

    accept_header = request.headers.get("accept", "").lower()
    if "application/json" in accept_header or request.query_params.get("format") == "json":
        return JSONResponse(content=voucher.model_dump())

    return templates.TemplateResponse(
        request=request,
        name="crew_voucher.html",
        context={
            "action_id": str(action.id),
            "tenant": tenant,
            "voucher": voucher,
        },
    )


@router.get(
    "/api/v1/crews/voucher/{action_id}",
    response_model=CrewVoucherData,
    summary="Fetch Crew Settlement Voucher (JSON)",
    description="Returns structured 1099 settlement voucher data and contractor net profit margins.",
)
async def get_crew_voucher_json(
    action_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> CrewVoucherData:
    stmt = (
        select(LeadAction)
        .options(selectinload(LeadAction.tenant))
        .where(LeadAction.id == action_id)
    )
    action = (await db.execute(stmt)).scalar_one_or_none()
    if not action:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Dispatch lead '{action_id}' not found",
        )

    if not action.crew_data:
        default_payload = {
            "crew_name": f"{action.tenant.name if action.tenant else 'Apex'} Trade Crew",
            "foreman_name": "Carlos Mendez",
            "foreman_phone": "+12025550188",
            "trade_specialty": action.action_type or "General Restoration",
            "payout_type": "PERCENTAGE",
            "rate_amount": 25.0,
        }
        voucher = await crew_settlement_service.assign_crew_to_job(
            action_id=action.id,
            crew_payload=default_payload,
            db=db,
        )
        return voucher

    return CrewVoucherData.model_validate(action.crew_data)
