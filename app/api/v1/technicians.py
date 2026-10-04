import os
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.models.tenant import Tenant
from app.schemas.technician_kpi import TechnicianMetrics, WeeklyCommissionStatement
from app.services.technician_kpi import technician_kpi_service

router = APIRouter(tags=["Technician Performance Scorecard & Commission Engine"])

TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "templates")
templates = Jinja2Templates(directory=TEMPLATES_DIR)


@router.get(
    "/technicians/{tenant_slug}",
    response_class=HTMLResponse,
    summary="Technician Performance Scorecards & Leaderboard",
    description="Renders technician conversion close rates, revenue closed, OSHA safety scores, and accrued commissions.",
)
async def get_technicians_portal_view(
    tenant_slug: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    format: Optional[str] = Query(None),
) -> Response:
    stmt = select(Tenant).where(Tenant.slug == tenant_slug)
    tenant = (await db.execute(stmt)).scalar_one_or_none()
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Contractor tenant '{tenant_slug}' not found",
        )

    scorecards = await technician_kpi_service.calculate_technician_scorecards(tenant, db)

    accept_header = request.headers.get("accept", "").lower()
    if "application/json" in accept_header or format == "json":
        return JSONResponse(content=[s.model_dump() for s in scorecards])

    return templates.TemplateResponse(
        request=request,
        name="technician_kpi.html",
        context={
            "tenant": tenant,
            "scorecards": scorecards,
            "statement": None,
            "message": request.query_params.get("msg"),
        },
    )


@router.get(
    "/technicians/{tenant_slug}/commission/{tech_name}",
    response_class=HTMLResponse,
    summary="Printable Weekly Commission Slip for Technician",
    description="Generates an itemized payroll voucher displaying job earnings, membership bonuses, and net commission payout.",
)
async def get_technician_commission_slip(
    tenant_slug: str,
    tech_name: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    format: Optional[str] = Query(None),
) -> Response:
    stmt = select(Tenant).where(Tenant.slug == tenant_slug)
    tenant = (await db.execute(stmt)).scalar_one_or_none()
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Contractor tenant '{tenant_slug}' not found",
        )

    scorecards = await technician_kpi_service.calculate_technician_scorecards(tenant, db)
    statement = await technician_kpi_service.generate_weekly_commission_slip(tech_name, tenant, db)

    accept_header = request.headers.get("accept", "").lower()
    if "application/json" in accept_header or format == "json":
        return JSONResponse(content=statement.model_dump())

    return templates.TemplateResponse(
        request=request,
        name="technician_kpi.html",
        context={
            "tenant": tenant,
            "scorecards": scorecards,
            "statement": statement,
            "message": request.query_params.get("msg"),
        },
    )


@router.get(
    "/api/v1/technicians/{tenant_slug}/scorecards",
    response_model=List[TechnicianMetrics],
    summary="REST API: Get Technician Scorecards",
    description="Returns list of technician metrics, conversion rates, and accrued commissions.",
)
async def api_get_technician_scorecards(
    tenant_slug: str,
    db: AsyncSession = Depends(get_db),
) -> List[TechnicianMetrics]:
    stmt = select(Tenant).where(Tenant.slug == tenant_slug)
    tenant = (await db.execute(stmt)).scalar_one_or_none()
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Contractor tenant '{tenant_slug}' not found",
        )

    return await technician_kpi_service.calculate_technician_scorecards(tenant, db)


@router.get(
    "/api/v1/technicians/{tenant_slug}/commission/{tech_name}",
    response_model=WeeklyCommissionStatement,
    summary="REST API: Get Weekly Commission Slip",
    description="Returns structured weekly commission statement for the requested technician.",
)
async def api_get_technician_commission(
    tenant_slug: str,
    tech_name: str,
    db: AsyncSession = Depends(get_db),
) -> WeeklyCommissionStatement:
    stmt = select(Tenant).where(Tenant.slug == tenant_slug)
    tenant = (await db.execute(stmt)).scalar_one_or_none()
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Contractor tenant '{tenant_slug}' not found",
        )

    return await technician_kpi_service.generate_weekly_commission_slip(tech_name, tenant, db)
