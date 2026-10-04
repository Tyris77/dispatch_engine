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
from app.schemas.supply_arbitrage import SupplyArbitrageComparison
from app.services.supply_arbitrage import supply_arbitrage_service

router = APIRouter(tags=["Multi-Distributor Supply Arbitrage Comparator"])

TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "templates")
templates = Jinja2Templates(directory=TEMPLATES_DIR)


@router.get(
    "/supply-compare/{action_id}",
    response_class=HTMLResponse,
    summary="Wholesale Supply House Arbitrage Comparison View",
    description="Side-by-side pricing matrix comparing Ferguson, Johnstone, ABC Supply, and Hajoca.",
)
async def get_supply_compare_view(
    action_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    format: Optional[str] = Query(None, description="Response format override ('json')"),
    message: Optional[str] = Query(None, description="Status update message"),
) -> Response:
    # 1. Fetch LeadAction
    stmt = select(LeadAction).where(LeadAction.id == action_id)
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
        tenant_stmt = select(Tenant).where(Tenant.is_active == True)
        tenant = (await db.execute(tenant_stmt)).scalars().first()

    if not tenant:
        tenant = Tenant(
            id=lead_action.tenant_id,
            name="Pro Services",
            slug="pro-services",
            api_key_hash="x",
            webhook_secret="y",
            is_active=True,
        )

    # 3. Generate or retrieve multi-distributor pricing comparison
    comparison = supply_arbitrage_service.compare_distributor_pricing(
        lead_action=lead_action,
        tenant=tenant,
    )

    if format == "json" or "application/json" in request.headers.get("accept", ""):
        return JSONResponse(content=comparison.model_dump())

    return templates.TemplateResponse(
        request=request,
        name="supply_compare.html",
        context={
            "comparison": comparison,
            "lead": lead_action,
            "tenant": tenant,
            "message": message,
        },
    )


@router.post(
    "/api/v1/supply-compare/switch/{action_id}",
    response_model=SupplyArbitrageComparison,
    summary="Switch Will-Call PO Distributor Destination",
    description="Updates the active purchase order destination, branch counter, and navigation link.",
)
async def switch_po_distributor_endpoint(
    action_id: uuid.UUID,
    request: Request,
    target_distributor: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
) -> Response:
    # Handle JSON or Form body
    chosen_distributor = target_distributor
    is_json = False

    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        is_json = True
        body = await request.json()
        chosen_distributor = body.get("target_distributor", chosen_distributor)

    if not chosen_distributor:
        chosen_distributor = "Johnstone Supply"

    comparison = await supply_arbitrage_service.switch_po_distributor(
        action_id=action_id,
        target_distributor=chosen_distributor,
        db=db,
    )

    if is_json or "application/json" in request.headers.get("accept", ""):
        return JSONResponse(content=comparison.model_dump())

    return RedirectResponse(
        url=f"/supply-compare/{action_id}?message=Successfully+switched+will-call+PO+to+{chosen_distributor}",
        status_code=status.HTTP_303_SEE_OTHER,
    )
