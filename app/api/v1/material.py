import os
import uuid
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.core.logging import logger
from app.models.lead_action import LeadAction
from app.models.tenant import Tenant
from app.schemas.material import JobProfitability, PurchaseOrder
from app.services.material import dispatch_po_to_supplier, generate_material_purchase_order

router = APIRouter(tags=["Material & Will-Call PO"])

TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "templates")
templates = Jinja2Templates(directory=TEMPLATES_DIR)


@router.get(
    "/po/{action_id}",
    response_class=HTMLResponse,
    summary="View Material Purchase Order & Job Profitability",
    description="Renders printable/mobile Will-Call PO and real-time profitability matrix or returns structured JSON.",
)
async def get_purchase_order_view(
    action_id: uuid.UUID,
    request: Request,
    supplier: Optional[str] = Query(None, description="Optional supply house override"),
    format: Optional[str] = Query(None, description="'json' for structured Pydantic payload"),
    db: AsyncSession = Depends(get_db),
) -> Response:
    # 1. Fetch LeadAction
    query = select(LeadAction).where(LeadAction.id == action_id)
    lead_action = (await db.execute(query)).scalar_one_or_none()
    if not lead_action:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Lead action '{action_id}' not found",
        )

    # 2. Fetch Tenant
    tenant_query = select(Tenant).where(Tenant.id == lead_action.tenant_id)
    tenant = (await db.execute(tenant_query)).scalar_one_or_none()
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant for lead action '{action_id}' not found",
        )

    # 3. Generate or retrieve PO and Profitability
    if not lead_action.material_po or not lead_action.profitability_data or supplier:
        po, profitability = generate_material_purchase_order(
            lead_action=lead_action,
            tenant=tenant,
            supplier_name=supplier,
        )
        await db.commit()
        await db.refresh(lead_action)
    else:
        po = PurchaseOrder.model_validate(lead_action.material_po)
        profitability = JobProfitability.model_validate(lead_action.profitability_data)

    # 4. JSON Mode Support
    accept_header = request.headers.get("accept", "").lower()
    if format == "json" or "application/json" in accept_header:
        return JSONResponse(
            content={
                "purchase_order": po.model_dump(),
                "profitability": profitability.model_dump(),
            }
        )

    # 5. Render HTML Template
    return templates.TemplateResponse(
        request=request,
        name="po_order.html",
        context={
            "po": po,
            "profitability": profitability,
            "tenant": tenant,
            "action_id": str(action_id),
        },
    )


@router.post(
    "/po/{action_id}/dispatch",
    summary="Dispatch Will-Call PO to Supply House",
    description="Marks PO as ORDERED and sends SMS notification with Google Maps link to on-call technician.",
)
async def dispatch_purchase_order_endpoint(
    action_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Response:
    try:
        updated_po = await dispatch_po_to_supplier(action_id=action_id, db=db)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))

    content_type = request.headers.get("content-type", "").lower()
    accept_header = request.headers.get("accept", "").lower()

    if "application/json" in content_type or "application/json" in accept_header or request.query_params.get("format") == "json":
        return JSONResponse(
            content={
                "success": True,
                "status": "ORDERED",
                "po": updated_po.model_dump(),
            }
        )

    return RedirectResponse(
        url=f"/po/{action_id}?dispatched=true",
        status_code=status.HTTP_303_SEE_OTHER,
    )
