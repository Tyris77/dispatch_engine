import os
import uuid
from typing import Optional
from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, Response, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_db
from app.models.lead_action import LeadAction
from app.schemas.legal import LienWaiverDocument
from app.services.legal import lien_waiver_service

router = APIRouter(tags=["Statutory Mechanic's Lien Waiver Engine"])

TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "templates")
templates = Jinja2Templates(directory=TEMPLATES_DIR)


@router.get(
    "/lien-waiver/{action_id}",
    response_class=HTMLResponse,
    summary="Statutory Mechanic's Lien Waiver Document View",
    description="Renders formal, print-ready statutory mechanic's lien waiver and unconditional release with notary public acknowledgment block.",
)
async def get_lien_waiver_view(
    action_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    waiver_type: Optional[str] = Query("FINAL_UNCONDITIONAL_RELEASE"),
    format: Optional[str] = Query(None),
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

    waiver_data = action.lien_waiver_data
    if not waiver_data:
        waiver = lien_waiver_service.generate_lien_waiver(
            lead_action=action,
            tenant=tenant,
            waiver_type=waiver_type or "FINAL_UNCONDITIONAL_RELEASE",
        )
        action.lien_waiver_data = waiver.model_dump()
        await db.commit()
        await db.refresh(action)
    else:
        try:
            waiver = LienWaiverDocument.model_validate(waiver_data)
        except Exception:
            waiver = lien_waiver_service.generate_lien_waiver(
                lead_action=action,
                tenant=tenant,
                waiver_type=waiver_type or "FINAL_UNCONDITIONAL_RELEASE",
            )
            action.lien_waiver_data = waiver.model_dump()
            await db.commit()
            await db.refresh(action)

    accept_header = request.headers.get("accept", "").lower()
    if "application/json" in accept_header or format == "json":
        return JSONResponse(content=waiver.model_dump())

    return templates.TemplateResponse(
        request=request,
        name="lien_waiver.html",
        context={
            "action_id": str(action.id),
            "lead_action": action,
            "tenant": tenant,
            "waiver": waiver,
        },
    )


@router.post(
    "/lien-waiver/{action_id}/generate",
    summary="Generate or Re-Issue Statutory Mechanic's Lien Waiver",
    description="Explicitly generates or modifies a statutory lien waiver document with custom amount or jurisdiction override.",
)
async def generate_lien_waiver_endpoint(
    action_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    waiver_type: Optional[str] = Form("FINAL_UNCONDITIONAL_RELEASE"),
    amount_override: Optional[float] = Form(None),
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

    waiver = lien_waiver_service.generate_lien_waiver(
        lead_action=action,
        tenant=tenant,
        waiver_type=waiver_type or "FINAL_UNCONDITIONAL_RELEASE",
    )

    if amount_override is not None and amount_override >= 0:
        waiver.amount_waived = float(amount_override)

    action.lien_waiver_data = waiver.model_dump()
    await db.commit()
    await db.refresh(action)

    accept_header = request.headers.get("accept", "").lower()
    if "application/json" in accept_header or request.query_params.get("format") == "json":
        return JSONResponse(content=waiver.model_dump())

    return RedirectResponse(
        url=f"/lien-waiver/{action.id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.get(
    "/api/v1/legal/lien-waiver/{action_id}",
    response_model=LienWaiverDocument,
    summary="Get Statutory Lien Waiver JSON",
    description="Returns the structured LienWaiverDocument JSON for the given dispatch action ID.",
)
async def get_lien_waiver_json(
    action_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> LienWaiverDocument:
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

    if not action.lien_waiver_data:
        waiver = lien_waiver_service.generate_lien_waiver(action, tenant)
        action.lien_waiver_data = waiver.model_dump()
        await db.commit()
        await db.refresh(action)
        return waiver

    return LienWaiverDocument.model_validate(action.lien_waiver_data)
