import os
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import get_db
from app.models.tenant import Tenant
from app.schemas.audit import AuditCalculateRequest, AuditReportResponse
from app.services.audit import audit_service

router = APIRouter(tags=["Missed Call Revenue Leak Audit Calculator"])

TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "templates")
templates = Jinja2Templates(directory=TEMPLATES_DIR)


@router.post(
    "/audit/calculate",
    response_model=AuditReportResponse,
    summary="Calculate Missed Call Revenue Leakage",
    description="Calculates exact dollar revenue leakage, competitor defection index, and recovery blueprint in <20ms.",
)
@router.post(
    "/api/v1/audit/calculate",
    response_model=AuditReportResponse,
    include_in_schema=False,
)
async def calculate_audit_leakage(
    payload: AuditCalculateRequest,
) -> AuditReportResponse:
    return audit_service.calculate_leakage(req=payload)


@router.get(
    "/audit",
    response_class=HTMLResponse,
    summary="Interactive Revenue Leak Audit Calculator",
    description="Web calculator with interactive sliders modeling fleet size, ticket sizes, and lost profit.",
)
@router.get(
    "/audit/{tenant_slug}",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def get_audit_page(
    request: Request,
    tenant_slug: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    format: Optional[str] = Query(None),
) -> Response:
    tenant_name = "Apex Roofing & Mechanical"
    slug = tenant_slug or "apex-roofing"

    if tenant_slug:
        tenant = (await db.execute(select(Tenant).where(Tenant.slug == tenant_slug))).scalar_one_or_none()
        if tenant:
            tenant_name = tenant.name
            slug = tenant.slug

    default_req = AuditCalculateRequest(
        trade="Plumbing",
        truck_count=5,
        monthly_call_volume=250,
        average_ticket=850.0,
        zip_code="20001",
    )
    report = audit_service.calculate_leakage(req=default_req)

    accept_header = request.headers.get("accept", "").lower()
    if format == "json" or "application/json" in accept_header:
        return JSONResponse(content=report.model_dump())

    return templates.TemplateResponse(
        request=request,
        name="audit.html",
        context={
            "tenant_slug": slug,
            "tenant_name": tenant_name,
            "report": report,
        },
    )
