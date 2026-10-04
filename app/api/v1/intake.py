import os
import uuid
from typing import Any, Dict, Optional
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, Response, UploadFile, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.core.config import settings
from app.core.logging import logger
from app.models.lead_action import LeadAction
from app.models.tenant import Tenant
from app.schemas.vision import DiagnosticSubmissionResponse, EquipmentDiagnosticReport
from app.services.crm_sync import sync_lead_to_external_crm
from app.services.vision import analyze_diagnostic_image

router = APIRouter()

# Locate templates directory
TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "templates")
templates = Jinja2Templates(directory=TEMPLATES_DIR)


async def send_diagnostic_sms_alert(
    to_phone: str,
    message_body: str,
    from_number: Optional[str] = None,
) -> bool:
    """Send immediate diagnostic SMS notification to on-call technician phone."""
    if not to_phone:
        return False

    if settings.TWILIO_ACCOUNT_SID and settings.TWILIO_AUTH_TOKEN:
        try:
            from twilio.rest import Client

            client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
            from_num = from_number or settings.TWILIO_FROM_NUMBER or "+15005550006"
            message = client.messages.create(
                to=to_phone,
                from_=from_num,
                body=message_body,
            )
            logger.info(f"Sent diagnostic SMS alert to {to_phone} (SID: {message.sid})")
            return True
        except Exception as exc:
            logger.error(f"Failed to send diagnostic SMS alert to {to_phone}: {exc}")
            return False
    else:
        logger.info(f"[Simulation] Diagnostic SMS alert to {to_phone}: {message_body}")
        return True


@router.get(
    "/intake/{action_id}",
    response_class=HTMLResponse,
    summary="Field Equipment Photo Intake View",
    description="Renders mobile-first camera capture screen or diagnostic report for the specified LeadAction.",
)
async def intake_view(
    action_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    success: Optional[str] = Query(None),
) -> Response:
    # 1. Fetch LeadAction
    query = select(LeadAction).where(LeadAction.id == action_id)
    lead_action = (await db.execute(query)).scalar_one_or_none()

    if not lead_action:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Lead action '{action_id}' not found",
        )

    # 2. Fetch associated Tenant
    tenant_query = select(Tenant).where(Tenant.id == lead_action.tenant_id)
    tenant = (await db.execute(tenant_query)).scalar_one_or_none()

    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Associated tenant not found",
        )

    # 3. Parse existing diagnostic report if present
    report_dict = lead_action.diagnostic_data or lead_action.metadata_payload.get("diagnostic_report")
    report = None
    if report_dict:
        try:
            report = EquipmentDiagnosticReport.model_validate(report_dict)
        except Exception as exc:
            logger.warning(f"Error parsing existing diagnostic data for action {action_id}: {exc}")

    success_msg = None
    if success:
        success_msg = "Equipment photo successfully scanned and dispatched to the on-call technician."

    return templates.TemplateResponse(
        request=request,
        name="intake.html",
        context={
            "lead_action": lead_action,
            "tenant": tenant,
            "report": report,
            "success_message": success_msg,
        },
    )


@router.post(
    "/intake/{action_id}",
    summary="Upload & Analyze Equipment Photo",
    description="Accepts photo upload, executes Gemini Multimodal Vision analysis, updates LeadAction, alerts technician via SMS, and syncs to CRM.",
)
async def process_photo_intake(
    action_id: uuid.UUID,
    request: Request,
    photo: UploadFile = File(..., description="Equipment photo or data plate image"),
    notes: Optional[str] = Form(None, description="Optional symptoms or observations"),
    db: AsyncSession = Depends(get_db),
) -> Response:
    # 1. Fetch LeadAction
    query = select(LeadAction).where(LeadAction.id == action_id)
    lead_action = (await db.execute(query)).scalar_one_or_none()

    if not lead_action:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Lead action '{action_id}' not found",
        )

    # 2. Fetch associated Tenant
    tenant_query = select(Tenant).where(Tenant.id == lead_action.tenant_id)
    tenant = (await db.execute(tenant_query)).scalar_one_or_none()

    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Associated tenant not found",
        )

    # 3. Read image bytes and run Multimodal Vision
    image_bytes = await photo.read()
    if not image_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty",
        )

    mime_type = photo.content_type or "image/jpeg"
    report = await analyze_diagnostic_image(
        image_bytes=image_bytes,
        mime_type=mime_type,
        trade_context=tenant.settings,
    )

    # 4. Persist diagnostic data on LeadAction
    report_dict = report.model_dump()
    lead_action.diagnostic_data = report_dict
    lead_action.metadata_payload = {
        **lead_action.metadata_payload,
        "diagnostic_report": report_dict,
        "intake_photo": {
            "filename": photo.filename,
            "content_type": mime_type,
            "size_bytes": len(image_bytes),
        },
    }
    if notes:
        lead_action.metadata_payload["intake_notes"] = notes

    # 5. Format and dispatch instant SMS update to tenant's on-call phone
    alert_phone = (
        tenant.settings.get("alert_phone_number")
        or tenant.settings.get("phone")
    )
    brand = report.brand_manufacturer or "Equipment"
    model = report.model_number or "N/A"
    eq_type = report.equipment_type
    damage = report.damage_assessment
    parts_str = ", ".join(report.recommended_parts_tools) if report.recommended_parts_tools else "Standard Truck Stock"

    sms_body = (
        f"📸 DIAGNOSTIC UPDATE: Detected {brand} {eq_type} ({model}). "
        f"Issue: {damage}. Recommended truck parts: {parts_str}."
    )

    sms_sent = False
    if alert_phone:
        from_phone = tenant.settings.get("twilio_phone_number") or settings.TWILIO_FROM_NUMBER
        sms_sent = await send_diagnostic_sms_alert(
            to_phone=alert_phone,
            message_body=sms_body,
            from_number=from_phone,
        )
        lead_action.metadata_payload.setdefault("notifications", {})["diagnostic_sms_sent"] = sms_sent

    # 6. Forward updated payload to external CRM if configured
    crm_sync_result = await sync_lead_to_external_crm(lead_action, tenant, db=db)
    crm_synced = crm_sync_result.get("success", False)

    await db.commit()
    await db.refresh(lead_action)

    # 7. Respond with JSON or redirect to intake view
    accept_header = request.headers.get("accept", "").lower()
    if "application/json" in accept_header or request.query_params.get("format") == "json":
        response_model = DiagnosticSubmissionResponse(
            success=True,
            action_id=str(lead_action.id),
            tenant_slug=tenant.slug,
            report=report,
            sms_alert_sent=sms_sent,
            crm_synced=crm_synced,
        )
        return JSONResponse(content=response_model.model_dump())

    # Form submission redirect
    return RedirectResponse(
        url=f"/intake/{lead_action.id}?success=true",
        status_code=status.HTTP_303_SEE_OTHER,
    )
