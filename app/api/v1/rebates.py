import os
import uuid
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.models.lead_action import LeadAction
from app.models.tenant import Tenant
from app.schemas.rebates import RebateCalculationResult, RebateClaimDossier
from app.services.rebates import rebates_service

router = APIRouter(tags=["Utility Rebate & Federal IRA Tax Credit Engine"])

TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "templates")
templates = Jinja2Templates(directory=TEMPLATES_DIR)


class CalculateRebatesRequest(BaseModel):
    equipment_type: str = Field(default="Heat Pump", description="Installed equipment category")
    proposal_tier: str = Field(default="Best", description="Proposal tier (Good, Better, Best)")
    gross_price: float = Field(..., description="Quoted contract gross price")
    utility_provider: Optional[str] = Field(None, description="Electric or gas utility provider")


@router.get(
    "/rebate/{action_id}",
    response_class=HTMLResponse,
    summary="Official Utility Rebate & Federal IRA Tax Credit Claim Form",
    description="Renders official printable clean energy rebate claim dossier pre-filled with AHRI certificate, equipment serials, and contractor license.",
)
async def get_rebate_claim_view(
    action_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    format: Optional[str] = Query(None, description="Response format override ('json')"),
) -> Response:
    try:
        action_uuid = uuid.UUID(action_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Invalid action ID format: '{action_id}'",
        )

    # 1. Fetch LeadAction
    stmt = select(LeadAction).where(LeadAction.id == action_uuid)
    lead_action = (await db.execute(stmt)).scalar_one_or_none()
    if not lead_action:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"LeadAction '{action_id}' not found",
        )

    # 2. Fetch Tenant
    tenant_stmt = select(Tenant).where(Tenant.id == lead_action.tenant_id)
    tenant = (await db.execute(tenant_stmt)).scalar_one_or_none()
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant for action '{action_id}' not found",
        )

    # 3. Generate rebate claim dossier
    dossier: RebateClaimDossier = rebates_service.generate_rebate_claim_dossier(
        lead_action=lead_action,
        tenant=tenant,
    )
    await db.commit()

    # 4. Handle JSON response
    accept_header = request.headers.get("accept", "").lower()
    if format == "json" or "application/json" in accept_header:
        return JSONResponse(content=dossier.model_dump())

    # 5. Render HTML claim template
    return templates.TemplateResponse(
        request=request,
        name="rebate_claim.html",
        context={
            "dossier": dossier,
            "tenant": tenant,
        },
    )


@router.post(
    "/api/v1/rebates/calculate",
    response_model=RebateCalculationResult,
    summary="Calculate Applicable Utility Rebates & IRA Tax Credits",
    description="Determines qualifying clean energy incentives and calculates net customer out-of-pocket price.",
)
async def calculate_rebates_api(
    payload: CalculateRebatesRequest,
) -> RebateCalculationResult:
    tenant_settings = {}
    if payload.utility_provider:
        tenant_settings["utility_provider"] = payload.utility_provider

    return rebates_service.calculate_applicable_rebates(
        equipment_type=payload.equipment_type,
        proposal_tier=payload.proposal_tier,
        gross_price=payload.gross_price,
        tenant_settings=tenant_settings,
    )
