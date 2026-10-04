import os
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.models.tenant import Tenant
from app.schemas.mileage import FleetMileageReport
from app.services.mileage import mileage_service

router = APIRouter(tags=["IRS Fleet Mileage Tax Ledger"])

TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "templates")
templates = Jinja2Templates(directory=TEMPLATES_DIR)


@router.get(
    "/fleet/mileage/{tenant_slug}",
    response_class=HTMLResponse,
    summary="IRS Fleet Mileage Tax Ledger View",
    description="Printable IRS Publication 463 vehicle tax ledger with odometer miles, deduction savings counter, and CPA CSV export.",
)
async def get_fleet_mileage_ledger_view(
    tenant_slug: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    tax_year: int = Query(2026, description="Filing tax year"),
    format: Optional[str] = Query(None),
) -> Response:
    # 1. Resolve tenant
    stmt = select(Tenant).where(Tenant.slug == tenant_slug)
    tenant = (await db.execute(stmt)).scalar_one_or_none()
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant '{tenant_slug}' not found",
        )

    # 2. Generate IRS mileage report
    report: FleetMileageReport = await mileage_service.generate_fleet_mileage_report(
        tenant=tenant,
        tax_year=tax_year,
        db=db,
    )

    # 3. Handle JSON response
    accept_header = request.headers.get("accept", "").lower()
    if format == "json" or "application/json" in accept_header:
        return JSONResponse(content=report.model_dump())

    # 4. Render HTML ledger template
    return templates.TemplateResponse(
        request=request,
        name="mileage_ledger.html",
        context={
            "report": report,
            "tenant": tenant,
        },
    )


@router.get(
    "/api/v1/mileage/{tenant_slug}/export.csv",
    summary="Export IRS CPA Mileage CSV",
    description="Downloads IRS Publication 463 compliant CSV for Schedule C or Form 1120-S corporate tax filing.",
)
async def export_fleet_mileage_csv(
    tenant_slug: str,
    db: AsyncSession = Depends(get_db),
    tax_year: int = Query(2026, description="Filing tax year"),
) -> Response:
    stmt = select(Tenant).where(Tenant.slug == tenant_slug)
    tenant = (await db.execute(stmt)).scalar_one_or_none()
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant '{tenant_slug}' not found",
        )

    report = await mileage_service.generate_fleet_mileage_report(
        tenant=tenant,
        tax_year=tax_year,
        db=db,
    )

    csv_data = mileage_service.generate_mileage_csv(report)
    filename = f"IRS_Fleet_Mileage_{tenant_slug}_{tax_year}.csv"

    return Response(
        content=csv_data,
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-cache",
        },
    )


@router.get(
    "/api/v1/mileage/{tenant_slug}",
    response_model=FleetMileageReport,
    summary="Get Fleet Mileage Tax Ledger Data",
    description="Returns JSON fleet mileage report with itemized trips, deductible miles, and tax deduction values.",
)
async def get_fleet_mileage_data(
    tenant_slug: str,
    db: AsyncSession = Depends(get_db),
    tax_year: int = Query(2026, description="Filing tax year"),
) -> FleetMileageReport:
    stmt = select(Tenant).where(Tenant.slug == tenant_slug)
    tenant = (await db.execute(stmt)).scalar_one_or_none()
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant '{tenant_slug}' not found",
        )

    return await mileage_service.generate_fleet_mileage_report(
        tenant=tenant,
        tax_year=tax_year,
        db=db,
    )
