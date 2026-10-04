import os
import uuid
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.models.lead_action import LeadAction
from app.models.tenant import Tenant
from app.schemas.warranty import WarrantyCertificate, WarrantyResponse
from app.services.warranty import warranty_service

router = APIRouter(tags=["Autonomous Equipment Warranty Certificate Engine"])

TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "templates")
templates = Jinja2Templates(directory=TEMPLATES_DIR)


@router.get(
    "/warranty/{action_id}",
    response_class=HTMLResponse,
    summary="Printable Equipment Warranty Certificate",
    description="Renders formal transferable warranty deed certificate with official contractor seal and CPSC verification.",
)
async def get_warranty_certificate_view(
    action_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    format: Optional[str] = Query(None),
) -> Response:
    stmt = select(LeadAction).where(LeadAction.id == action_id)
    action = (await db.execute(stmt)).scalar_one_or_none()
    if not action:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Lead action '{action_id}' not found",
        )

    stmt_tenant = select(Tenant).where(Tenant.id == action.tenant_id)
    tenant = (await db.execute(stmt_tenant)).scalar_one_or_none()
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Contractor tenant for this lead action not found",
        )

    if action.warranty_data:
        try:
            cert = WarrantyCertificate.model_validate(action.warranty_data)
        except Exception:
            cert = warranty_service.generate_warranty_certificate(action, tenant)
            await db.commit()
            await db.refresh(action)
    else:
        cert = warranty_service.generate_warranty_certificate(action, tenant)
        await db.commit()
        await db.refresh(action)

    accept_header = request.headers.get("accept", "").lower()
    if "application/json" in accept_header or format == "json":
        return JSONResponse(content=cert.model_dump())

    return templates.TemplateResponse(
        request=request,
        name="warranty.html",
        context={
            "cert": cert,
            "lead": action,
            "tenant": tenant,
        },
    )


@router.post(
    "/warranty/{action_id}/generate",
    summary="Generate or Refresh Equipment Warranty Certificate",
    description="Extracts equipment serial numbers and CPSC safety status, persists certificate, and redirects.",
)
async def post_generate_warranty(
    action_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Response:
    stmt = select(LeadAction).where(LeadAction.id == action_id)
    action = (await db.execute(stmt)).scalar_one_or_none()
    if not action:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Lead action '{action_id}' not found",
        )

    stmt_tenant = select(Tenant).where(Tenant.id == action.tenant_id)
    tenant = (await db.execute(stmt_tenant)).scalar_one_or_none()
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Contractor tenant for this lead action not found",
        )

    cert = warranty_service.generate_warranty_certificate(action, tenant)
    await db.commit()
    await db.refresh(action)

    accept_header = request.headers.get("accept", "").lower()
    if "application/json" in accept_header or request.query_params.get("format") == "json":
        return JSONResponse(
            content=WarrantyResponse(
                status="SUCCESS",
                certificate=cert,
                message=f"Warranty certificate {cert.certificate_number} registered successfully.",
            ).model_dump()
        )

    return RedirectResponse(
        url=f"/warranty/{action.id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.get(
    "/api/v1/warranty/{action_id}",
    response_model=WarrantyCertificate,
    summary="REST API: Get Equipment Warranty Certificate",
    description="Returns structured JSON certificate for the specified lead work order.",
)
async def api_get_warranty_certificate(
    action_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> WarrantyCertificate:
    stmt = select(LeadAction).where(LeadAction.id == action_id)
    action = (await db.execute(stmt)).scalar_one_or_none()
    if not action:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Lead action '{action_id}' not found",
        )

    stmt_tenant = select(Tenant).where(Tenant.id == action.tenant_id)
    tenant = (await db.execute(stmt_tenant)).scalar_one_or_none()
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Contractor tenant for this lead action not found",
        )

    if action.warranty_data:
        try:
            return WarrantyCertificate.model_validate(action.warranty_data)
        except Exception:
            pass

    cert = warranty_service.generate_warranty_certificate(action, tenant)
    await db.commit()
    return cert
