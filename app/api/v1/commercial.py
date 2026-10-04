import os
from typing import Optional
from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, Response, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.models.lead_action import LeadAction
from app.models.tenant import Tenant
from app.schemas.commercial import (
    CommercialTenantRequestSubmission,
    CommercialWorkOrder,
    ConsolidatedMonthlyStatement,
    PropertyPortfolio,
)
from app.services.commercial import commercial_service

router = APIRouter(tags=["Commercial Property Manager Multi-Unit Portal"])

TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "templates")
templates = Jinja2Templates(directory=TEMPLATES_DIR)


@router.get(
    "/commercial/{tenant_slug}",
    response_class=HTMLResponse,
    summary="Commercial Property Manager Multi-Unit Portal",
    description="Multi-unit building portfolio dashboard with 1-tap approval queue and monthly consolidated statements.",
)
async def get_commercial_portal_view(
    tenant_slug: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    approve: Optional[str] = Query(None, description="Optional 1-tap approval work order ID query trigger"),
    message: Optional[str] = Query(None, description="Optional banner message"),
    format: Optional[str] = Query(None, description="Response format override ('json')"),
) -> Response:
    # 1. Fetch Tenant
    stmt = select(Tenant).where(Tenant.slug == tenant_slug)
    tenant = (await db.execute(stmt)).scalar_one_or_none()
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant '{tenant_slug}' not found",
        )

    # 2. Check for instant 1-tap approval link trigger in query params
    if approve:
        approved_order = await commercial_service.approve_commercial_work_order(
            order_id=approve,
            tenant=tenant,
            db=db,
        )
        if approved_order:
            message = f"Work Order {approve} successfully approved for priority dispatch."

    # 3. Retrieve Portfolios
    portfolios = commercial_service.get_tenant_portfolios(tenant)
    total_units = sum(p.unit_count for p in portfolios)

    # 4. Retrieve Work Orders
    work_orders = await commercial_service.get_portfolio_work_orders(tenant=tenant, db=db)
    pending_count = sum(1 for wo in work_orders if wo.approval_status == "PENDING_PM_APPROVAL")
    auto_approved_count = sum(1 for wo in work_orders if wo.approval_status == "APPROVED_AUTO")

    # 5. Generate Statement for Primary Portfolio
    primary_portfolio_id = portfolios[0].portfolio_id if portfolios else "meridian-pentagon"
    statement = await commercial_service.generate_consolidated_statement(
        portfolio_id=primary_portfolio_id,
        billing_period="October 2026",
        db=db,
        tenant=tenant,
    )

    if format == "json" or "application/json" in request.headers.get("accept", ""):
        return JSONResponse(
            content={
                "tenant_slug": tenant.slug,
                "tenant_name": tenant.name,
                "total_units": total_units,
                "pending_count": pending_count,
                "auto_approved_count": auto_approved_count,
                "portfolios": [p.model_dump() for p in portfolios],
                "work_orders": [wo.model_dump() for wo in work_orders],
                "statement": statement.model_dump(),
            }
        )

    return templates.TemplateResponse(
        request=request,
        name="commercial_portal.html",
        context={
            "tenant": tenant,
            "portfolios": portfolios,
            "total_units": total_units,
            "work_orders": work_orders,
            "pending_count": pending_count,
            "auto_approved_count": auto_approved_count,
            "statement": statement,
            "message": message,
        },
    )


@router.post(
    "/api/v1/commercial/approve/{order_id}",
    summary="1-Tap Property Manager Work Order Approval",
    description="Approves a pending commercial work order and triggers immediate dispatch.",
)
async def post_commercial_approve(
    order_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Response:
    # Locate target LeadAction with this work order
    stmt = select(LeadAction)
    result = await db.execute(stmt)
    leads = result.scalars().all()

    target_lead: Optional[LeadAction] = None
    for lead in leads:
        cdata = lead.commercial_data or {}
        if cdata.get("order_id") == order_id:
            target_lead = lead
            break

    if not target_lead:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Work order '{order_id}' not found",
        )

    # Fetch Tenant
    tenant_stmt = select(Tenant).where(Tenant.id == target_lead.tenant_id)
    tenant = (await db.execute(tenant_stmt)).scalar_one_or_none()
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant associated with work order not found",
        )

    approved_order = await commercial_service.approve_commercial_work_order(
        order_id=order_id,
        tenant=tenant,
        db=db,
    )

    if not approved_order:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Could not approve work order '{order_id}'",
        )

    if "application/json" in request.headers.get("accept", "") or request.headers.get("content-type") == "application/json":
        return JSONResponse(
            content={
                "status": "APPROVED",
                "order_id": order_id,
                "work_order": approved_order.model_dump(),
            }
        )

    return RedirectResponse(
        url=f"/commercial/{tenant.slug}?message=Work+Order+{order_id}+Approved+Successfully",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post(
    "/api/v1/commercial/request",
    summary="Submit Commercial Tenant Request",
    description="Submits a maintenance request for a unit in a managed commercial portfolio.",
)
async def post_commercial_request(
    request: Request,
    portfolio_id: str = Form(...),
    unit_number: str = Form(...),
    tenant_name: str = Form(...),
    issue_description: str = Form(...),
    db: AsyncSession = Depends(get_db),
) -> Response:
    # Find any active tenant
    stmt = select(Tenant).where(Tenant.is_active == True)
    tenant = (await db.execute(stmt)).scalars().first()
    if not tenant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No active tenant found")

    portfolios = commercial_service.get_tenant_portfolios(tenant)
    target_p = next((p for p in portfolios if p.portfolio_id == portfolio_id), portfolios[0])

    work_order = await commercial_service.process_commercial_tenant_request(
        portfolio=target_p,
        unit_number=unit_number,
        tenant_name=tenant_name,
        issue_text=issue_description,
        tenant=tenant,
        db=db,
    )

    if "application/json" in request.headers.get("accept", ""):
        return JSONResponse(content={"status": "created", "work_order": work_order.model_dump()})

    msg = f"Work Order {work_order.order_id} created: {work_order.approval_status}"
    return RedirectResponse(
        url=f"/commercial/{tenant.slug}?message={msg}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.get(
    "/api/v1/commercial/statement/{portfolio_id}",
    response_model=ConsolidatedMonthlyStatement,
    summary="Consolidated Monthly Statement JSON API",
)
async def get_commercial_statement_api(
    portfolio_id: str,
    billing_period: Optional[str] = Query("October 2026"),
    db: AsyncSession = Depends(get_db),
) -> ConsolidatedMonthlyStatement:
    stmt = select(Tenant).where(Tenant.is_active == True)
    tenant = (await db.execute(stmt)).scalars().first()
    return await commercial_service.generate_consolidated_statement(
        portfolio_id=portfolio_id,
        billing_period=billing_period or "October 2026",
        db=db,
        tenant=tenant,
    )
