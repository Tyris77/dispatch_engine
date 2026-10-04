import datetime
import os
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.models.tenant import Tenant
from app.schemas.route_optimizer import DailyFleetOptimizationReport
from app.services.route_optimizer import route_optimizer_service

router = APIRouter(tags=["Multi-Vehicle Fleet Route Optimizer"])

TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "templates")
templates = Jinja2Templates(directory=TEMPLATES_DIR)


class OptimizeFleetRoutesRequest(BaseModel):
    tenant_slug: str = Field(..., description="Unique slug of the contractor tenant")
    target_date: Optional[str] = Field(None, description="ISO format date string (YYYY-MM-DD)")
    dispatch_sms: bool = Field(False, description="Whether to dispatch turn-by-turn route SMS to on-call drivers")


@router.get(
    "/fleet/routes/{tenant_slug}",
    response_class=HTMLResponse,
    summary="Fleet Route Optimization Console",
    description="Interactive fleet route optimization console showing technician route itineraries, waypoint sequences, and fuel savings.",
)
async def get_fleet_routes_view(
    tenant_slug: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    date: Optional[str] = Query(None, description="Target optimization date (YYYY-MM-DD)"),
    format: Optional[str] = Query(None, description="Response format override ('json')"),
) -> Response:
    # 1. Resolve tenant
    stmt = select(Tenant).where(Tenant.slug == tenant_slug)
    tenant = (await db.execute(stmt)).scalar_one_or_none()
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant '{tenant_slug}' not found",
        )

    # 2. Determine target date
    target_date = date or datetime.date.today().isoformat()

    # 3. Generate route optimization
    report: DailyFleetOptimizationReport = await route_optimizer_service.optimize_daily_fleet_routes(
        tenant=tenant,
        target_date=target_date,
        db=db,
        dispatch_sms=False,
    )

    # 4. Handle JSON response if requested
    accept_header = request.headers.get("accept", "").lower()
    if format == "json" or "application/json" in accept_header:
        return JSONResponse(content=report.model_dump())

    # 5. Render HTML console template
    return templates.TemplateResponse(
        request=request,
        name="route_optimizer.html",
        context={
            "report": report,
            "tenant": tenant,
        },
    )


@router.post(
    "/api/v1/fleet/routes/optimize",
    response_model=DailyFleetOptimizationReport,
    summary="Run Fleet Route Optimization & Driver SMS Dispatch",
    description="Clusters queued service calls into geographic corridors, minimizes fleet mileage, and optionally dispatches turn-by-turn SMS to technicians.",
)
async def optimize_fleet_routes_api(
    payload: OptimizeFleetRoutesRequest,
    db: AsyncSession = Depends(get_db),
) -> DailyFleetOptimizationReport:
    # 1. Resolve tenant
    stmt = select(Tenant).where(Tenant.slug == payload.tenant_slug)
    tenant = (await db.execute(stmt)).scalar_one_or_none()
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant '{payload.tenant_slug}' not found",
        )

    target_date = payload.target_date or datetime.date.today().isoformat()

    # 2. Run optimization service
    report = await route_optimizer_service.optimize_daily_fleet_routes(
        tenant=tenant,
        target_date=target_date,
        db=db,
        dispatch_sms=payload.dispatch_sms,
    )

    return report


@router.get(
    "/api/v1/fleet/routes/{tenant_slug}",
    response_model=DailyFleetOptimizationReport,
    summary="Get Daily Fleet Route Optimization Report",
    description="Retrieves the current optimized daily route itineraries and fuel savings breakdown for a contractor tenant.",
)
async def get_fleet_routes_report_api(
    tenant_slug: str,
    date: Optional[str] = Query(None, description="Target optimization date (YYYY-MM-DD)"),
    db: AsyncSession = Depends(get_db),
) -> DailyFleetOptimizationReport:
    stmt = select(Tenant).where(Tenant.slug == tenant_slug)
    tenant = (await db.execute(stmt)).scalar_one_or_none()
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant '{tenant_slug}' not found",
        )

    target_date = date or datetime.date.today().isoformat()

    report = await route_optimizer_service.optimize_daily_fleet_routes(
        tenant=tenant,
        target_date=target_date,
        db=db,
        dispatch_sms=False,
    )
    return report
