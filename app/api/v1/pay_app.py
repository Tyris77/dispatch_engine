import os
import uuid
from typing import Optional
from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, Response, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.models.lead_action import LeadAction
from app.models.tenant import Tenant
from app.schemas.pay_app import AIAContractProgressPayment, PayAppGenerateRequest
from app.services.pay_app import pay_app_service

router = APIRouter(tags=["Commercial AIA G702/G703 Progress Billing Engine"])

TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "templates")
templates = Jinja2Templates(directory=TEMPLATES_DIR)


@router.get(
    "/pay-app/{action_id}",
    response_class=HTMLResponse,
    summary="Commercial AIA Document G702/G703 Progress Payment Application",
    description="Printable commercial application and certificate for payment with Schedule of Values (SOV), architect certification, and contractor notary block.",
)
async def get_pay_app_view(
    action_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    format: Optional[str] = Query(None),
) -> Response:
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

    pay_app: AIAContractProgressPayment = await pay_app_service.get_or_create_pay_app(
        lead_action=lead,
        tenant=tenant,
        db=db,
    )

    accept_header = request.headers.get("accept", "").lower()
    if format == "json" or "application/json" in accept_header:
        return JSONResponse(content=pay_app.model_dump())

    return templates.TemplateResponse(
        request=request,
        name="pay_app.html",
        context={
            "pay_app": pay_app,
            "lead": lead,
            "tenant": tenant,
        },
    )


@router.post(
    "/pay-app/{action_id}/generate",
    summary="Recalculate or Update AIA G702 Progress Billing Parameters",
    description="Recalculates line-item work completed, stored materials, retainage escrow, and net draw due.",
)
async def generate_pay_app_endpoint(
    action_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Response:
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

    content_type = request.headers.get("content-type", "").lower()
    if "application/json" in content_type:
        payload = await request.json()
        req_model = PayAppGenerateRequest.model_validate(payload)
    else:
        form = await request.form()
        req_model = PayAppGenerateRequest(
            progress_pct=float(form.get("progress_pct") or 65.0),
            retainage_pct=float(form.get("retainage_pct") or 10.0),
            application_number=int(form.get("application_number") or 1),
            architect_name=form.get("architect_name") or None,
        )

    pay_app = pay_app_service.generate_aia_payment_application(
        lead_action=lead,
        tenant=tenant,
        progress_pct=req_model.progress_pct,
        retainage_pct=req_model.retainage_pct,
        application_number=req_model.application_number,
        architect_name=req_model.architect_name or "Studio Architecture & Engineering P.C.",
    )

    lead.pay_app_data = pay_app.model_dump()
    await db.commit()

    accept_header = request.headers.get("accept", "").lower()
    if "application/json" in content_type or "application/json" in accept_header or request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JSONResponse(content=pay_app.model_dump())

    return RedirectResponse(
        url=f"/pay-app/{action_id}?updated=1",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.get(
    "/api/v1/pay-app/{action_id}",
    response_model=AIAContractProgressPayment,
    summary="Get AIA G702 Progress Billing Data JSON",
    description="Direct API endpoint returning complete AIA Document G702 & G703 dataset.",
)
async def get_pay_app_data(
    action_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> AIAContractProgressPayment:
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

    return await pay_app_service.get_or_create_pay_app(
        lead_action=lead,
        tenant=tenant,
        db=db,
    )
