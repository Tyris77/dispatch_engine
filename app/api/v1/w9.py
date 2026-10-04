import os
from typing import Optional
from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.models.tenant import Tenant
from app.schemas.w9 import TAX_CLASSIFICATIONS, W9CertificationRecord, W9FormSubmission, W9RequestPayload
from app.services.w9 import w9_service

router = APIRouter(tags=["Subcontractor Digital W-9 E-Sign Portal"])

TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "templates")
templates = Jinja2Templates(directory=TEMPLATES_DIR)


@router.get(
    "/w9/{tenant_slug}/{crew_name}",
    response_class=HTMLResponse,
    summary="Subcontractor Mobile Digital W-9 Form",
    description="Clean mobile IRS Form W-9 certification with legal tax classification radios, EIN entry, and touch signature canvas.",
)
async def get_digital_w9_form(
    tenant_slug: str,
    crew_name: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Response:
    tenant = (await db.execute(select(Tenant).where(Tenant.slug == tenant_slug))).scalar_one_or_none()
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Contractor tenant '{tenant_slug}' not found",
        )

    existing_entry = w9_service.get_w9_entry(tenant, crew_name)

    return templates.TemplateResponse(
        request=request,
        name="w9_form.html",
        context={
            "tenant": tenant,
            "crew_name": crew_name,
            "existing_entry": existing_entry,
            "tax_classifications": TAX_CLASSIFICATIONS,
        },
    )


@router.post(
    "/w9/{tenant_slug}/{crew_name}",
    summary="Submit Digital W-9 Form",
    description="Validates taxpayer identification number, creates audit certification record, and records ON_FILE status in tenant settings.",
)
async def submit_digital_w9_endpoint(
    tenant_slug: str,
    crew_name: str,
    request: Request,
    submission_data: Optional[W9FormSubmission] = None,
    db: AsyncSession = Depends(get_db),
) -> Response:
    tenant = (await db.execute(select(Tenant).where(Tenant.slug == tenant_slug))).scalar_one_or_none()
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Contractor tenant '{tenant_slug}' not found",
        )

    # Allow either JSON body or HTML Form post
    content_type = request.headers.get("content-type", "").lower()
    if "application/json" in content_type:
        payload = await request.json()
        try:
            submission = W9FormSubmission.model_validate(payload)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid W-9 payload: {exc}",
            )
    else:
        form = await request.form()
        try:
            submission = W9FormSubmission(
                crew_name=form.get("crew_name") or crew_name,
                foreman_name=form.get("foreman_name", ""),
                business_legal_name=form.get("business_legal_name", ""),
                federal_tax_classification=form.get("federal_tax_classification", ""),
                address=form.get("address", ""),
                ein_or_ssn=form.get("ein_or_ssn", ""),
                signature_base64=form.get("signature_base64", ""),
            )
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid form fields: {exc}",
            )

    try:
        record: W9CertificationRecord = await w9_service.submit_digital_w9(
            submission=submission,
            tenant=tenant,
            db=db,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )

    accept_header = request.headers.get("accept", "").lower()
    if (
        "application/json" in content_type
        or "application/json" in accept_header
        or request.headers.get("x-requested-with") == "XMLHttpRequest"
    ):
        return JSONResponse(content=record.model_dump())

    return templates.TemplateResponse(
        request=request,
        name="w9_form.html",
        context={
            "tenant": tenant,
            "crew_name": crew_name,
            "existing_entry": record.model_dump(),
            "tax_classifications": TAX_CLASSIFICATIONS,
            "submitted_success": True,
        },
    )


@router.post(
    "/api/v1/tax-vault/request-w9",
    summary="Dispatch Subcontractor W-9 Request SMS",
    description="Sends SMS link to crew foreman requesting completion of digital Form W-9.",
)
async def request_w9_via_sms_api(
    payload: W9RequestPayload,
    db: AsyncSession = Depends(get_db),
) -> dict:
    tenant = (await db.execute(select(Tenant).where(Tenant.slug == payload.tenant_slug))).scalar_one_or_none()
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant '{payload.tenant_slug}' not found",
        )

    res = await w9_service.request_w9_via_sms(
        crew_name=payload.crew_name,
        foreman_phone=payload.foreman_phone,
        tenant=tenant,
    )
    return {
        "status": "SMS_DISPATCHED" if res.get("sent") else "SIMULATED",
        "crew_name": payload.crew_name,
        "foreman_phone": payload.foreman_phone,
        "link": res.get("link"),
    }
