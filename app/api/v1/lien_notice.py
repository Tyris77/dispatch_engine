import os
import uuid
from typing import Optional
from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, Response, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.models.lead_action import LeadAction
from app.models.tenant import Tenant
from app.schemas.lien_notice import LienNoticeDocument, LienNoticeResponse
from app.services.lien_notice import lien_notice_service

router = APIRouter(tags=["Statutory Preliminary Notice & Intent to Lien Guard"])

TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "templates")
templates = Jinja2Templates(directory=TEMPLATES_DIR)


@router.get(
    "/lien-notice/{action_id}",
    response_class=HTMLResponse,
    summary="Printable Statutory Preliminary Notice & Intent to Lien",
    description="Renders formal statutory notice with USPS certified mail tracking barcode, legal warning, and proof of service.",
)
async def get_lien_notice_view(
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

    if action.lien_notice_data:
        try:
            notice = LienNoticeDocument.model_validate(action.lien_notice_data)
        except Exception:
            notice = lien_notice_service.generate_statutory_lien_notice(action, tenant)
    else:
        notice = lien_notice_service.generate_statutory_lien_notice(action, tenant)
        await db.commit()
        await db.refresh(action)

    accept_header = request.headers.get("accept", "").lower()
    if "application/json" in accept_header or format == "json":
        return JSONResponse(content=notice.model_dump())

    return templates.TemplateResponse(
        request=request,
        name="lien_notice.html",
        context={
            "notice": notice,
            "lead": action,
            "tenant": tenant,
        },
    )


@router.post(
    "/lien-notice/{action_id}/generate",
    summary="Generate or Refresh Statutory Notice to Owner",
    description="Drafts legal notice citing MD § 9-104, VA § 43-4, or DC § 40-303, saves to lead action, and redirects.",
)
async def post_generate_lien_notice(
    action_id: uuid.UUID,
    request: Request,
    notice_type: Optional[str] = Form(None),
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

    notice = lien_notice_service.generate_statutory_lien_notice(action, tenant, notice_type=notice_type)
    await db.commit()
    await db.refresh(action)

    accept_header = request.headers.get("accept", "").lower()
    if "application/json" in accept_header or request.query_params.get("format") == "json":
        return JSONResponse(
            content=LienNoticeResponse(
                status="SUCCESS",
                notice=notice,
                message=f"Statutory lien notice {notice.notice_number} generated successfully.",
            ).model_dump()
        )

    return RedirectResponse(
        url=f"/lien-notice/{action.id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.get(
    "/api/v1/lien-notice/{action_id}",
    response_model=LienNoticeDocument,
    summary="REST API: Get Statutory Lien Notice Document",
    description="Returns JSON representation of the generated statutory notice to owner.",
)
async def api_get_lien_notice(
    action_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> LienNoticeDocument:
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

    if action.lien_notice_data:
        try:
            return LienNoticeDocument.model_validate(action.lien_notice_data)
        except Exception:
            pass

    notice = lien_notice_service.generate_statutory_lien_notice(action, tenant)
    await db.commit()
    return notice
