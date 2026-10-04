import os
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.models.tenant import Tenant
from app.schemas.compliance import RegulatoryCompliancePacket
from app.services.compliance import compliance_service

router = APIRouter(tags=["Trade License & Regulatory Compliance Vault"])

TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "templates")
templates = Jinja2Templates(directory=TEMPLATES_DIR)


@router.get(
    "/compliance/{tenant_slug}",
    response_class=HTMLResponse,
    summary="Trade License & Regulatory Compliance Packet",
    description="Official printable regulatory compliance and state trade license packet for commercial general contractor pre-qualification.",
)
async def get_compliance_packet_view(
    tenant_slug: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
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

    # 2. Compile Packet
    packet = compliance_service.get_compliance_packet(tenant)

    if format == "json" or "application/json" in request.headers.get("accept", ""):
        return JSONResponse(content=packet.model_dump())

    return templates.TemplateResponse(
        request=request,
        name="compliance_packet.html",
        context={
            "tenant": tenant,
            "packet": packet,
        },
    )


@router.get(
    "/api/v1/compliance/{tenant_slug}",
    response_model=RegulatoryCompliancePacket,
    summary="Trade License & Compliance REST API",
    description="Returns JSON compliance submittal packet for automated commercial procurement verification.",
)
async def get_compliance_packet_api(
    tenant_slug: str,
    db: AsyncSession = Depends(get_db),
) -> RegulatoryCompliancePacket:
    stmt = select(Tenant).where(Tenant.slug == tenant_slug)
    tenant = (await db.execute(stmt)).scalar_one_or_none()
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant '{tenant_slug}' not found",
        )
    return compliance_service.get_compliance_packet(tenant)
