import os
import uuid
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, Response, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.attributes import flag_modified

from app.api.deps import get_db
from app.core.config import settings
from app.core.logging import logger
from app.models.lead_action import LeadAction
from app.models.tenant import Tenant
from app.schemas.tracking import (
    EntryNoteSubmission,
    TechnicianInfo,
    TrackingStatusUpdate,
    TrackingViewResponse,
)
from app.schemas.vision import EquipmentDiagnosticReport
from app.services.dispatch import get_active_on_call_technicians
from app.services.outbound_voice import outbound_voice_service

router = APIRouter()

TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "templates")
templates = Jinja2Templates(directory=TEMPLATES_DIR)


async def send_tech_entry_notes_sms(
    to_phone: str,
    message_body: str,
    from_number: Optional[str] = None,
) -> bool:
    """Dispatches immediate SMS notification with gate codes/entry instructions to technician."""
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
            logger.info(f"Sent entry notes SMS alert to technician {to_phone} (SID: {message.sid})")
            return True
        except Exception as exc:
            logger.error(f"Failed to send entry notes SMS to technician {to_phone}: {exc}")
            return False
    else:
        logger.info(f"[Simulation] Entry notes SMS to tech {to_phone}: {message_body}")
        return True


def _resolve_technician(lead_action: LeadAction, tenant: Tenant) -> Dict[str, Any]:
    """Helper to extract or populate technician details."""
    tracking = lead_action.tracking_data or {}
    if tracking.get("technician"):
        return tracking["technician"]

    active_techs = get_active_on_call_technicians(tenant)
    if active_techs:
        t = active_techs[0]
        return {
            "name": t.get("name", "Mike Callahan"),
            "phone": t.get("phone", tenant.settings.get("phone")),
            "role": t.get("role", "Senior Emergency Specialist"),
            "truck_number": t.get("truck_number", "Truck #14"),
            "certifications": t.get("certifications", ["EPA Universal", "NATE Certified"]),
            "photo_url": t.get("photo_url"),
            "rating": 4.98,
        }

    return {
        "name": "Mike Callahan",
        "phone": tenant.settings.get("alert_phone_number") or tenant.settings.get("phone") or "+15552345678",
        "role": "Master Lead Technician",
        "truck_number": "Truck #14",
        "certifications": ["EPA Universal", "NATE Certified", "Master Specialist"],
        "photo_url": None,
        "rating": 4.98,
    }


def _calculate_step_index(status_str: str) -> int:
    s = (status_str or "").upper()
    if s == "DISPATCHED":
        return 1
    elif s == "EN_ROUTE":
        return 2
    elif s == "ON_SITE":
        return 3
    elif s in ["COMPLETED", "RESOLVED"]:
        return 4
    return 2


@router.get(
    "/track/{action_id}",
    response_class=HTMLResponse,
    summary="Live 'Where's My Tech?' Arrival Tracker",
    description="Mobile-first live tracking view rendering technician identity, status stepper, ETA countdown, and truck-stock verified parts.",
)
async def track_view(
    action_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    note_added: Optional[str] = Query(None),
) -> Response:
    # 1. Fetch LeadAction
    query = select(LeadAction).where(LeadAction.id == action_id)
    lead_action = (await db.execute(query)).scalar_one_or_none()

    if not lead_action:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Dispatch action '{action_id}' not found",
        )

    # 2. Fetch Tenant
    tenant_query = select(Tenant).where(Tenant.id == lead_action.tenant_id)
    tenant = (await db.execute(tenant_query)).scalar_one_or_none()

    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Associated tenant not found",
        )

    # 3. Resolve tracking state
    tracking = lead_action.tracking_data or {}
    technician_dict = _resolve_technician(lead_action, tenant)
    curr_status = tracking.get("status", "EN_ROUTE")
    step_idx = _calculate_step_index(curr_status)
    eta_mins = tracking.get("eta_minutes", 18)
    notes_list = tracking.get("notes", [])

    # If tracking_data was uninitialized, persist it now
    if not lead_action.tracking_data:
        lead_action.tracking_data = {
            "status": curr_status,
            "eta_minutes": eta_mins,
            "technician": technician_dict,
            "notes": notes_list,
        }
        await db.commit()

    # 4. Resolve diagnostic equipment report if present
    diagnostic_report = None
    report_dict = lead_action.diagnostic_data or lead_action.metadata_payload.get("diagnostic_report")
    if report_dict:
        try:
            diagnostic_report = EquipmentDiagnosticReport.model_validate(report_dict)
        except Exception as exc:
            logger.warning(f"Error parsing diagnostic report for tracking {action_id}: {exc}")

    # 5. Check if client wants JSON
    accept_header = request.headers.get("accept", "").lower()
    if "application/json" in accept_header or request.query_params.get("format") == "json":
        parts = diagnostic_report.recommended_parts_tools if diagnostic_report else ["Universal OEM Truck Stock"]
        resp_model = TrackingViewResponse(
            action_id=str(lead_action.id),
            tenant_name=tenant.name,
            tenant_phone=tenant.settings.get("phone") or tenant.settings.get("alert_phone_number"),
            status=curr_status,
            eta_minutes=eta_mins,
            technician=TechnicianInfo.model_validate(technician_dict),
            equipment_brand=diagnostic_report.brand_manufacturer if diagnostic_report else None,
            equipment_model=diagnostic_report.model_number if diagnostic_report else None,
            equipment_type=diagnostic_report.equipment_type if diagnostic_report else None,
            parts_packed=parts,
            notes=notes_list,
            created_at=lead_action.created_at.isoformat() if lead_action.created_at else None,
            updated_at=lead_action.updated_at.isoformat() if lead_action.updated_at else None,
        )
        return JSONResponse(content=resp_model.model_dump())

    return templates.TemplateResponse(
        request=request,
        name="track.html",
        context={
            "lead_action": lead_action,
            "tenant": tenant,
            "technician": technician_dict,
            "eta_minutes": eta_mins,
            "step_idx": step_idx,
            "status": curr_status,
            "diagnostic": diagnostic_report,
            "notes": notes_list,
            "note_added": bool(note_added),
        },
    )


@router.post(
    "/track/{action_id}/notes",
    summary="Submit Gate Code or Entry Instructions",
    description="Logs entry notes to lead record and immediately dispatches SMS alert to the on-call technician.",
)
async def post_entry_notes(
    action_id: uuid.UUID,
    request: Request,
    notes: Optional[str] = Form(None),
    sender_name: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
) -> Response:
    # 1. Fetch LeadAction
    query = select(LeadAction).where(LeadAction.id == action_id)
    lead_action = (await db.execute(query)).scalar_one_or_none()

    if not lead_action:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Dispatch action '{action_id}' not found",
        )

    # 2. Fetch Tenant
    tenant_query = select(Tenant).where(Tenant.id == lead_action.tenant_id)
    tenant = (await db.execute(tenant_query)).scalar_one_or_none()

    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Associated tenant not found",
        )

    # 3. Parse input from form or JSON
    note_text = notes
    author = sender_name
    content_type = request.headers.get("content-type", "").lower()
    if not note_text and "application/json" in content_type:
        try:
            body = await request.json()
            note_obj = EntryNoteSubmission.model_validate(body)
            note_text = note_obj.notes
            author = note_obj.sender_name
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid JSON payload: {exc}",
            )

    if not note_text:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Entry notes cannot be empty",
        )

    # 4. Save note in lead_action.tracking_data
    tracking = dict(lead_action.tracking_data or {})
    technician_dict = _resolve_technician(lead_action, tenant)
    tracking.setdefault("technician", technician_dict)
    
    current_notes = list(tracking.get("notes", []))
    formatted_note = f"{author + ': ' if author else ''}{note_text.strip()}"
    current_notes.append(formatted_note)
    tracking["notes"] = current_notes
    lead_action.tracking_data = tracking
    flag_modified(lead_action, "tracking_data")

    # Also record in metadata_payload
    meta = dict(lead_action.metadata_payload or {})
    meta.setdefault("entry_notes", []).append({
        "note": note_text.strip(),
        "sender": author,
    })
    lead_action.metadata_payload = meta
    flag_modified(lead_action, "metadata_payload")

    # 5. Send immediate SMS notification to technician
    tech_phone = (
        technician_dict.get("phone")
        or tenant.settings.get("alert_phone_number")
        or tenant.settings.get("phone")
    )
    sms_body = (
        f"📍 ENTRY NOTE for {lead_action.lead_external_id} (Ticket {str(lead_action.id)[:8]}): "
        f"'{note_text}'. Added to dispatch ticket."
    )
    from_phone = tenant.settings.get("twilio_phone_number") or settings.TWILIO_FROM_NUMBER
    sms_sent = False
    if tech_phone:
        sms_sent = await send_tech_entry_notes_sms(
            to_phone=tech_phone,
            message_body=sms_body,
            from_number=from_phone,
        )
        lead_action.metadata_payload.setdefault("notifications", {})["entry_notes_sms_sent"] = sms_sent
        flag_modified(lead_action, "metadata_payload")

    await db.commit()
    await db.refresh(lead_action)

    # 6. Response format
    accept_header = request.headers.get("accept", "").lower()
    if "application/json" in accept_header or "application/json" in content_type:
        return JSONResponse(content={
            "success": True,
            "action_id": str(lead_action.id),
            "note": formatted_note,
            "sms_sent": sms_sent,
        })

    return RedirectResponse(
        url=f"/track/{lead_action.id}?note_added=1",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post(
    "/track/{action_id}/status",
    summary="Update Technician Dispatch Status",
    description="Advances status stepper (DISPATCHED, EN_ROUTE, ON_SITE, COMPLETED) and updates ETA.",
)
async def update_tracking_status(
    action_id: uuid.UUID,
    status_update: TrackingStatusUpdate,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    query = select(LeadAction).where(LeadAction.id == action_id)
    lead_action = (await db.execute(query)).scalar_one_or_none()

    if not lead_action:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Dispatch action '{action_id}' not found",
        )

    valid_statuses = ["DISPATCHED", "EN_ROUTE", "ON_SITE", "COMPLETED", "RESOLVED"]
    norm_status = status_update.status.upper()
    if norm_status not in valid_statuses:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid status '{status_update.status}'. Must be one of {valid_statuses}",
        )

    tracking = dict(lead_action.tracking_data or {})
    tracking["status"] = norm_status
    if status_update.eta_minutes is not None:
        tracking["eta_minutes"] = status_update.eta_minutes

    lead_action.tracking_data = tracking
    flag_modified(lead_action, "tracking_data")
    await db.commit()
    await db.refresh(lead_action)


    return JSONResponse(content={
        "success": True,
        "action_id": str(lead_action.id),
        "status": norm_status,
        "eta_minutes": tracking.get("eta_minutes"),
    })


@router.post(
    "/track/{action_id}/outbound-arrival-call",
    summary="Trigger Outbound Voice Arrival Confirmation Call",
    description="Places automated phone call to customer to confirm they are on-site prior to technician arrival.",
)
async def trigger_arrival_confirmation_call(
    action_id: uuid.UUID,
    request: Request,
    eta_minutes: int = Query(20),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    stmt = (
        select(LeadAction)
        .options(selectinload(LeadAction.tenant))
        .where(LeadAction.id == action_id)
    )
    action = (await db.execute(stmt)).scalar_one_or_none()
    if not action:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Dispatch action '{action_id}' not found",
        )
    result = await outbound_voice_service.trigger_outbound_arrival_call(
        lead_action=action,
        tenant=action.tenant,
        eta_minutes=eta_minutes,
        base_url=str(request.base_url),
        db=db,
    )
    return JSONResponse(content=result)

