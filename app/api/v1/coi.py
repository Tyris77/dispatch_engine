import os
import uuid
from typing import Optional
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, Response, UploadFile, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.models.tenant import Tenant
from app.schemas.coi import CertificateOfInsurance, COIUploadResponse
from app.services.coi import coi_service

router = APIRouter(tags=["Commercial ACORD Certificate of Insurance (COI) Guard"])

TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "templates")
templates = Jinja2Templates(directory=TEMPLATES_DIR)


@router.get(
    "/coi/{tenant_slug}",
    response_class=HTMLResponse,
    summary="Commercial ACORD Insurance Verification Portal",
    description="Renders dedicated commercial contractor insurance compliance portal, coverage limit breakdown, and upload dropzone.",
)
async def get_coi_portal_view(
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

    coi = coi_service.get_tenant_coi(tenant)
    await db.commit()

    accept_header = request.headers.get("accept", "").lower()
    if "application/json" in accept_header or format == "json":
        return JSONResponse(content=coi.model_dump())

    return templates.TemplateResponse(
        request=request,
        name="coi_tracker.html",
        context={
            "tenant": tenant,
            "coi": coi,
            "message": request.query_params.get("msg"),
        },
    )


@router.post(
    "/coi/{tenant_slug}/upload",
    summary="Upload & Audit ACORD 25 Certificate for Tenant",
    description="Accepts PDF or image certificate file, runs Gemini Vision insurance audit, and updates tenant settings.",
)
async def upload_coi_portal_endpoint(
    tenant_slug: str,
    request: Request,
    coi_file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
) -> Response:
    stmt = select(Tenant).where(Tenant.slug == tenant_slug)
    tenant = (await db.execute(stmt)).scalar_one_or_none()
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Contractor tenant '{tenant_slug}' not found",
        )

    file_bytes = await coi_file.read()
    if not file_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded insurance file is empty",
        )

    mime = coi_file.content_type or "application/pdf"
    coi = await coi_service.audit_document(
        file_bytes=file_bytes,
        mime_type=mime,
        tenant=tenant,
    )
    await db.commit()
    await db.refresh(tenant)

    accept_header = request.headers.get("accept", "").lower()
    if "application/json" in accept_header or request.query_params.get("format") == "json":
        return JSONResponse(
            content=COIUploadResponse(
                status="SUCCESS",
                coi=coi,
                message=f"ACORD 25 verified. Compliance status: {coi.compliance_status}.",
            ).model_dump()
        )

    return RedirectResponse(
        url=f"/coi/{tenant.slug}?msg=Insurance+Policy+Successfully+Verified",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post(
    "/api/v1/coi/upload",
    response_model=COIUploadResponse,
    summary="Audit ACORD 25 Document via API",
    description="Audits an ACORD 25 certificate document and optionally updates associated tenant settings.",
)
async def api_upload_coi(
    request: Request,
    coi_file: UploadFile = File(...),
    tenant_slug: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
) -> COIUploadResponse:
    tenant = None
    if tenant_slug:
        stmt = select(Tenant).where(Tenant.slug == tenant_slug)
        tenant = (await db.execute(stmt)).scalar_one_or_none()

    file_bytes = await coi_file.read()
    if not file_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded insurance file is empty",
        )

    mime = coi_file.content_type or "application/pdf"
    coi = await coi_service.audit_document(
        file_bytes=file_bytes,
        mime_type=mime,
        tenant=tenant,
    )

    if tenant:
        await db.commit()

    return COIUploadResponse(
        status="SUCCESS",
        coi=coi,
        message=f"ACORD 25 audited successfully. Status: {coi.compliance_status}.",
    )


@router.get(
    "/api/v1/coi/{tenant_slug}",
    response_model=CertificateOfInsurance,
    summary="Get Active Certificate of Insurance JSON",
    description="Returns verified CertificateOfInsurance JSON for the given contractor tenant.",
)
async def get_coi_json(
    tenant_slug: str,
    db: AsyncSession = Depends(get_db),
) -> CertificateOfInsurance:
    stmt = select(Tenant).where(Tenant.slug == tenant_slug)
    tenant = (await db.execute(stmt)).scalar_one_or_none()
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Contractor tenant '{tenant_slug}' not found",
        )

    return coi_service.get_tenant_coi(tenant)
