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
from app.models.tenant import Tenant
from app.schemas.insurance import InsuranceClaimDossier
from app.services.insurance import insurance_service

router = APIRouter(tags=["Insurance Claim Dossier"])

TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "templates")
templates = Jinja2Templates(directory=TEMPLATES_DIR)


@router.get(
    "/insurance/{action_id}",
    response_class=HTMLResponse,
    summary="Insurance Claim Support Dossier View",
    description="Renders official, print-ready insurance adjuster dossier with NOAA weather correlation and building code citations.",
)
async def get_insurance_dossier_view(
    action_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    date_of_loss: Optional[str] = Query(None),
    insurer: Optional[str] = Query(None),
    policy_num: Optional[str] = Query(None),
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

    # If dossier not yet generated or forced update requested, generate it
    dossier_data = action.insurance_data
    if not dossier_data or date_of_loss or insurer:
        dossier = insurance_service.generate_insurance_dossier(
            lead_action=action,
            tenant=tenant,
            insurer_name=insurer,
            policy_number=policy_num,
            date_of_loss=date_of_loss,
        )
        await db.commit()
        await db.refresh(action)
        dossier_data = action.insurance_data
    else:
        dossier = InsuranceClaimDossier.model_validate(dossier_data)

    accept_header = request.headers.get("accept", "").lower()
    if "application/json" in accept_header or request.query_params.get("format") == "json":
        return JSONResponse(content=dossier.model_dump())

    return templates.TemplateResponse(
        request=request,
        name="insurance.html",
        context={
            "action_id": str(action.id),
            "tenant": tenant,
            "dossier": dossier,
        },
    )


@router.post(
    "/insurance/{action_id}/generate",
    summary="Generate or Regenerate Insurance Claim Dossier",
    description="Forces regeneration of the NOAA-correlated insurance dossier with building code citations and Xactimate line items.",
)
async def generate_insurance_dossier_endpoint(
    action_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    insurer: Optional[str] = Form(None),
    policy_num: Optional[str] = Form(None),
    date_of_loss: Optional[str] = Form(None),
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

    dossier = insurance_service.generate_insurance_dossier(
        lead_action=action,
        tenant=action.tenant,
        insurer_name=insurer,
        policy_number=policy_num,
        date_of_loss=date_of_loss,
    )
    await db.commit()

    accept_header = request.headers.get("accept", "").lower()
    if "application/json" in accept_header:
        return JSONResponse(content=dossier.model_dump())

    return RedirectResponse(
        url=f"/insurance/{action.id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.get(
    "/api/v1/insurance/{action_id}",
    response_model=InsuranceClaimDossier,
    summary="Fetch Insurance Claim Dossier (JSON)",
    description="Returns structured insurance dossier including NOAA weather telemetry, IRC citations, and Xactimate items.",
)
async def get_insurance_dossier_json(
    action_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> InsuranceClaimDossier:
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

    if not action.insurance_data:
        dossier = insurance_service.generate_insurance_dossier(
            lead_action=action,
            tenant=action.tenant,
        )
        await db.commit()
        return dossier

    return InsuranceClaimDossier.model_validate(action.insurance_data)
