import os
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.models.tenant import Tenant
from app.schemas.tax_vault import Annual1099Report
from app.services.tax_vault import tax_vault_service

router = APIRouter(tags=["1099-NEC Subcontractor Tax Vault"])

TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "templates")
templates = Jinja2Templates(directory=TEMPLATES_DIR)


@router.get(
    "/tax-vault/{tenant_slug}",
    response_class=HTMLResponse,
    summary="1099-NEC Subcontractor Tax Vault Ledger",
    description="Printable IRS Form 1099-NEC summary ledger with W-9 status badges and 1-click CPA CSV export.",
)
async def get_tax_vault_ledger_view(
    tenant_slug: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    tax_year: int = Query(2026, description="Filing calendar tax year"),
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

    # 2. Compile Annual 1099 report
    report: Annual1099Report = await tax_vault_service.generate_annual_1099_report(
        tenant=tenant,
        tax_year=tax_year,
        db=db,
    )

    # 3. JSON content negotiation
    accept_header = request.headers.get("accept", "").lower()
    if format == "json" or "application/json" in accept_header:
        return JSONResponse(content=report.model_dump())

    # 4. Render HTML template
    return templates.TemplateResponse(
        request=request,
        name="tax_vault.html",
        context={
            "report": report,
            "tenant": tenant,
        },
    )


@router.get(
    "/api/v1/tax-vault/{tenant_slug}/export.csv",
    summary="Export IRS Form 1099-NEC CPA CSV",
    description="Instant CPA tax CSV download formatted for QuickBooks, Xero, and IRS FIRE / IRIS e-filing systems.",
)
async def export_tax_vault_csv(
    tenant_slug: str,
    db: AsyncSession = Depends(get_db),
    tax_year: int = Query(2026, description="Filing calendar tax year"),
) -> Response:
    stmt = select(Tenant).where(Tenant.slug == tenant_slug)
    tenant = (await db.execute(stmt)).scalar_one_or_none()
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant '{tenant_slug}' not found",
        )

    report = await tax_vault_service.generate_annual_1099_report(
        tenant=tenant,
        tax_year=tax_year,
        db=db,
    )

    csv_data = tax_vault_service.export_1099_csv(report)
    filename = f"IRS_1099_NEC_{tenant_slug}_{tax_year}.csv"

    return Response(
        content=csv_data,
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-cache",
        },
    )


@router.get(
    "/api/v1/tax-vault/{tenant_slug}",
    response_model=Annual1099Report,
    summary="Get 1099-NEC Subcontractor Tax Report JSON",
    description="Returns structured 1099 nonemployee compensation ledger for tax reporting.",
)
async def get_tax_vault_data(
    tenant_slug: str,
    db: AsyncSession = Depends(get_db),
    tax_year: int = Query(2026, description="Filing calendar tax year"),
) -> Annual1099Report:
    stmt = select(Tenant).where(Tenant.slug == tenant_slug)
    tenant = (await db.execute(stmt)).scalar_one_or_none()
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant '{tenant_slug}' not found",
        )

    return await tax_vault_service.generate_annual_1099_report(
        tenant=tenant,
        tax_year=tax_year,
        db=db,
    )
