import os
import uuid
from typing import Optional
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, Response, UploadFile, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_db
from app.models.lead_action import LeadAction
from app.schemas.safety import SafetyAuditReport, SafetySubmissionResponse
from app.services.safety import safety_service

router = APIRouter(tags=["AI Jobsite Safety OSHA Auditor"])

TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "templates")
templates = Jinja2Templates(directory=TEMPLATES_DIR)


@router.get(
    "/safety/{action_id}",
    response_class=HTMLResponse,
    summary="Jobsite Safety Analysis & OSHA Audit View",
    description="Renders mobile-first JSA inspection card, safety compliance score, detected PPE badges, and OSHA mitigations.",
)
async def get_safety_audit_view(
    action_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    format: Optional[str] = Query(None),
) -> Response:
    stmt = (
        select(LeadAction)
        .options(selectinload(LeadAction.tenant))
        .where(LeadAction.id == action_id)
    )
    action = (await db.execute(stmt)).scalar_one_or_none()
    if not action:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Dispatch lead '{action_id}' not found",
        )

    tenant = action.tenant
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant association missing for lead",
        )

    audit: Optional[SafetyAuditReport] = None
    if action.safety_data:
        try:
            audit = SafetyAuditReport.model_validate(action.safety_data)
        except Exception:
            audit = None

    accept_header = request.headers.get("accept", "").lower()
    if "application/json" in accept_header or format == "json":
        if audit:
            return JSONResponse(content=audit.model_dump())
        return JSONResponse(
            content={"message": "No safety audit has been conducted yet for this jobsite", "status": "PENDING"},
            status_code=status.HTTP_200_OK,
        )

    return templates.TemplateResponse(
        request=request,
        name="safety.html",
        context={
            "action_id": str(action.id),
            "lead_action": action,
            "tenant": tenant,
            "audit": audit,
        },
    )


@router.post(
    "/safety/{action_id}/audit",
    summary="Ingest Jobsite Photo & Execute AI OSHA Audit",
    description="Uploads a field photo, executes Gemini 2.5 Flash multimodal vision safety audit, and updates lead_action.safety_data.",
)
async def submit_safety_audit(
    action_id: uuid.UUID,
    request: Request,
    image: UploadFile = File(...),
    trade_type: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
) -> Response:
    stmt = (
        select(LeadAction)
        .options(selectinload(LeadAction.tenant))
        .where(LeadAction.id == action_id)
    )
    action = (await db.execute(stmt)).scalar_one_or_none()
    if not action:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Dispatch lead '{action_id}' not found",
        )

    image_bytes = await image.read()
    if not image_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded image file is empty",
        )

    resolved_trade = trade_type or action.category or "General Construction"

    report = await safety_service.audit_jobsite_safety(
        image_bytes=image_bytes,
        trade_type=resolved_trade,
    )

    action.safety_data = report.model_dump()
    await db.commit()
    await db.refresh(action)

    accept_header = request.headers.get("accept", "").lower()
    if "application/json" in accept_header or request.query_params.get("format") == "json":
        return JSONResponse(
            content=SafetySubmissionResponse(
                action_id=str(action.id),
                status="SUCCESS",
                report=report,
            ).model_dump()
        )

    # Browser form post -> redirect back to /safety/{action_id} to display results
    return RedirectResponse(
        url=f"/safety/{action.id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.get(
    "/api/v1/safety/{action_id}",
    response_model=SafetyAuditReport,
    summary="Get Jobsite Safety Audit JSON",
    description="Returns the structured SafetyAuditReport JSON for the given dispatch action ID.",
)
async def get_safety_audit_json(
    action_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> SafetyAuditReport:
    stmt = select(LeadAction).where(LeadAction.id == action_id)
    action = (await db.execute(stmt)).scalar_one_or_none()
    if not action:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Dispatch lead '{action_id}' not found",
        )

    if not action.safety_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No safety audit data recorded for this lead",
        )

    return SafetyAuditReport.model_validate(action.safety_data)
