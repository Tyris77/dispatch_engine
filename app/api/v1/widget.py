import os
import uuid
from typing import Any, Dict, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.core.config import settings
from app.core.logging import logger
from app.models.lead_action import LeadAction
from app.models.tenant import Tenant
from app.models.webhook_event import WebhookEvent
from app.schemas.lead import IntentLevel
from app.schemas.widget import WidgetChatRequest, WidgetChatResponse, WidgetLeadRequest
from app.services.dispatch import dispatch_service, get_active_on_call_technicians

from app.services.qualification import qualify_lead_with_gemini

router = APIRouter()

TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "templates")
templates = Jinja2Templates(directory=TEMPLATES_DIR)


@router.get(
    "/widget/{tenant_slug}.js",
    summary="Serve Dynamic Embeddable Website Widget JavaScript",
    description="Renders branded vanilla JavaScript for embedding the 24/7 AI fast-response widget on contractor websites.",
)
async def get_widget_js(
    tenant_slug: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Returns dynamically configured JavaScript snippet for the requested tenant.
    Falls back gracefully to a default demo configuration if tenant is not found.
    """
    # Clean slug if .js was included in path
    clean_slug = tenant_slug.removesuffix(".js")

    query = select(Tenant).where(Tenant.slug == clean_slug)
    tenant = (await db.execute(query)).scalar_one_or_none()

    if tenant:
        slug = tenant.slug
        name = tenant.name or "Apex Comfort Systems"
        phone = (
            tenant.settings.get("phone")
            or tenant.settings.get("alert_phone_number")
            or "(555) 234-5678"
        )
        base_url = tenant.settings.get("base_url") or str(request.base_url).rstrip("/")
    else:
        # Fall back gracefully to default demo configuration for unseeded or demo tenants
        slug = clean_slug or "apex-plumbing"
        name = "Apex Comfort Systems"
        phone = "(555) 234-5678"
        base_url = str(request.base_url).rstrip("/")

    # Render template
    js_template_path = os.path.join(TEMPLATES_DIR, "widget.js")
    with open(js_template_path, "r", encoding="utf-8") as f:
        js_content = f.read()

    # Substitute dynamic properties
    rendered_js = (
        js_content
        .replace("{{ tenant_slug }}", slug)
        .replace("{{ tenant_name }}", name)
        .replace("{{ tenant_phone }}", phone)
        .replace("{{ base_url }}", base_url)
    )

    return Response(
        content=rendered_js,
        media_type="application/javascript; charset=utf-8",
        headers={"Cache-Control": "public, max-age=60"},
    )


get_widget_javascript = get_widget_js


@router.post(
    "/widget/{tenant_slug}/chat",
    response_model=WidgetChatResponse,
    summary="Interactive Widget AI Chat Qualification",
    description="Processes real-time conversation via Gemini, scores urgency, creates LeadAction, and triggers live tracking if emergency.",
)
async def widget_chat(
    tenant_slug: str,
    chat_req: WidgetChatRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> WidgetChatResponse:
    # 1. Fetch Tenant
    query = select(Tenant).where(Tenant.slug == tenant_slug)
    tenant = (await db.execute(query)).scalar_one_or_none()

    if not tenant:
        query_fallback = select(Tenant).where(Tenant.is_active == True).order_by(Tenant.created_at.asc()).limit(1)
        tenant = (await db.execute(query_fallback)).scalar_one_or_none()

    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant '{tenant_slug}' not found",
        )

    # 2. Qualify lead using Google Gemini
    qualification = await qualify_lead_with_gemini(
        raw_text=chat_req.message,
        tenant_context=tenant.settings,
    )

    # 3. Record WebhookEvent
    lead_id = chat_req.sender_phone or f"widget_{uuid.uuid4().hex[:8]}"
    event = WebhookEvent(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        source="widget_chat",
        event_type="widget.chat",
        status="PROCESSED",
        payload={
            "message": chat_req.message,
            "From": lead_id,
            "sender_name": chat_req.sender_name,
            "language": chat_req.language or getattr(qualification, "detected_language", "en"),
            "channel": "widget",
        },
    )
    db.add(event)
    await db.flush()


    # 4. Generate Dispatch Plan
    plan = dispatch_service.create_dispatch_plan(tenant, qualification, event.payload)

    # 5. Determine active on-call technician profile
    active_techs = get_active_on_call_technicians(tenant)
    if active_techs:
        primary_tech = active_techs[0]
        technician_data = {
            "name": primary_tech.get("name", "Mike Callahan"),
            "phone": primary_tech.get("phone", tenant.settings.get("phone")),
            "role": primary_tech.get("role", "Emergency Response Lead"),
            "truck_number": primary_tech.get("truck_number", "Truck #14"),
            "certifications": primary_tech.get("certifications", ["EPA Universal", "NATE Certified"]),
            "photo_url": primary_tech.get("photo_url"),
            "rating": 4.98,
        }
    else:
        technician_data = {
            "name": "Mike Callahan",
            "phone": tenant.settings.get("alert_phone_number") or tenant.settings.get("phone") or "+15552345678",
            "role": "Master Lead Technician",
            "truck_number": "Truck #14",
            "certifications": ["EPA Universal", "NATE Certified", "Master Specialist"],
            "photo_url": None,
            "rating": 4.98,
        }

    is_emergency = (
        qualification.intent_level in [IntentLevel.EMERGENCY, IntentLevel.HIGH]
        or qualification.qualification_score >= 0.8
        or "EMERGENCY" in plan.target_route.upper()
    )

    initial_tracking = {
        "status": "DISPATCHED" if is_emergency else "PENDING",
        "eta_minutes": 20 if is_emergency else 60,
        "technician": technician_data,
        "notes": [],
    }

    # 6. Create LeadAction
    action = LeadAction(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        webhook_event_id=event.id,
        lead_external_id=lead_id,
        qualification_score=qualification.qualification_score,
        qualification_summary=qualification.reasoning,
        action_type=f"DISPATCH_{plan.target_route.upper()}",
        dispatch_status="QUEUED",
        crm_sync_status="PENDING",
        metadata_payload={
            "plan": plan.model_dump(),
            "qualification": qualification.model_dump(),
            "channel": "widget_chat",
        },
        tracking_data=initial_tracking,
    )
    db.add(action)
    await db.flush()

    # 7. Execute immediate dispatch if emergency
    if is_emergency:
        await dispatch_service.execute_dispatch_plan(action, tenant, event.payload)

    await db.commit()
    await db.refresh(action)

    base_url = tenant.settings.get("base_url") or str(request.base_url).rstrip("/")
    tracking_url = f"{base_url}/track/{action.id}" if is_emergency else None
    intake_url = f"{base_url}/intake/{action.id}"

    # Formulate conversational reply
    if qualification.caller_response:
        reply_text = qualification.caller_response
    elif is_emergency:
        reply_text = (
            f"🚨 Priority emergency dispatch alert received for {tenant.name}. "
            "Our on-call technician has been alerted and is reviewing your ticket now."
        )
    else:
        reply_text = (
            f"Thank you for reaching out to {tenant.name}. "
            "We have recorded your details and our team will follow up promptly."
        )

    return WidgetChatResponse(
        response_text=reply_text,
        intent_level=qualification.intent_level.value if hasattr(qualification.intent_level, "value") else str(qualification.intent_level),
        qualification_score=qualification.qualification_score,
        action_id=str(action.id),
        tracking_url=tracking_url,
        intake_url=intake_url,
        is_emergency=is_emergency,
    )


async def _process_lead_intake(
    lead_req: WidgetLeadRequest,
    tenant_slug: Optional[str],
    request: Request,
    db: AsyncSession,
) -> WidgetChatResponse:
    """Internal helper to qualify and ingest widget/form leads into the dispatch engine."""
    # 1. Resolve tenant
    target_slug = lead_req.tenant_slug or tenant_slug
    tenant = None
    if target_slug:
        query = select(Tenant).where(Tenant.slug == target_slug)
        tenant = (await db.execute(query)).scalar_one_or_none()

    if not tenant:
        query = select(Tenant).where(Tenant.is_active == True).order_by(Tenant.created_at.asc()).limit(1)
        tenant = (await db.execute(query)).scalar_one_or_none()

    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active contractor tenant found for dispatch.",
        )

    # 2. Extract message / notes / description
    inquiry_text = (
        lead_req.message
        or lead_req.notes
        or lead_req.service_needed
        or "New lead inquiry submitted via website widget."
    )
    sender_phone = lead_req.phone or lead_req.sender_phone
    sender_name = lead_req.name or lead_req.sender_name

    # 3. Fast Qualify Lead
    qualification = await qualify_lead_with_gemini(
        raw_text=inquiry_text,
        tenant_context=tenant.settings,
    )

    # 4. Record WebhookEvent
    lead_id = sender_phone or f"lead_{uuid.uuid4().hex[:8]}"
    event = WebhookEvent(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        source="widget_lead",
        event_type="widget.lead",
        status="PROCESSED",
        payload={
            "message": inquiry_text,
            "From": lead_id,
            "sender_name": sender_name,
            "email": lead_req.email,
            "address": lead_req.address,
            "service_needed": lead_req.service_needed,
            "language": lead_req.language or getattr(qualification, "detected_language", "en"),
            "channel": "widget_lead",
        },
    )
    db.add(event)
    await db.flush()

    # 5. Generate Dispatch Plan
    plan = dispatch_service.create_dispatch_plan(tenant, qualification, event.payload)

    # 6. Determine active technician
    active_techs = get_active_on_call_technicians(tenant)
    if active_techs:
        primary_tech = active_techs[0]
        technician_data = {
            "name": primary_tech.get("name", "Mike Callahan"),
            "phone": primary_tech.get("phone", tenant.settings.get("phone")),
            "role": primary_tech.get("role", "Emergency Response Lead"),
            "truck_number": primary_tech.get("truck_number", "Truck #14"),
            "certifications": primary_tech.get("certifications", ["EPA Universal", "NATE Certified"]),
            "photo_url": primary_tech.get("photo_url"),
            "rating": 4.98,
        }
    else:
        technician_data = {
            "name": "Mike Callahan",
            "phone": tenant.settings.get("alert_phone_number") or tenant.settings.get("phone") or "+15552345678",
            "role": "Master Lead Technician",
            "truck_number": "Truck #14",
            "certifications": ["EPA Universal", "NATE Certified", "Master Specialist"],
            "photo_url": None,
            "rating": 4.98,
        }

    is_emergency = (
        qualification.intent_level in [IntentLevel.EMERGENCY, IntentLevel.HIGH]
        or qualification.qualification_score >= 0.8
        or "EMERGENCY" in plan.target_route.upper()
    )

    initial_tracking = {
        "status": "DISPATCHED" if is_emergency else "PENDING",
        "eta_minutes": 20 if is_emergency else 60,
        "technician": technician_data,
        "notes": [],
    }

    # 7. Create LeadAction
    action = LeadAction(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        webhook_event_id=event.id,
        lead_external_id=lead_id,
        qualification_score=qualification.qualification_score,
        qualification_summary=qualification.reasoning,
        action_type=f"DISPATCH_{plan.target_route.upper()}",
        dispatch_status="QUEUED",
        crm_sync_status="PENDING",
        metadata_payload={
            "plan": plan.model_dump(),
            "qualification": qualification.model_dump(),
            "channel": "widget_lead",
            "sender_name": sender_name,
            "email": lead_req.email,
            "address": lead_req.address,
        },
        tracking_data=initial_tracking,
    )
    db.add(action)
    await db.flush()

    if is_emergency:
        await dispatch_service.execute_dispatch_plan(action, tenant, event.payload)

    await db.commit()
    await db.refresh(action)

    base_url = tenant.settings.get("base_url") or str(request.base_url).rstrip("/")
    tracking_url = f"{base_url}/track/{action.id}" if is_emergency else None
    intake_url = f"{base_url}/intake/{action.id}"

    if qualification.caller_response:
        reply_text = qualification.caller_response
    elif is_emergency:
        reply_text = (
            f"🚨 Priority emergency dispatch alert received for {tenant.name}. "
            "Our on-call technician has been alerted and is reviewing your ticket now."
        )
    else:
        reply_text = (
            f"Thank you for contacting {tenant.name}. "
            "Your estimate request has been logged and our dispatch desk will reach out shortly."
        )

    return WidgetChatResponse(
        response_text=reply_text,
        intent_level=qualification.intent_level.value if hasattr(qualification.intent_level, "value") else str(qualification.intent_level),
        qualification_score=qualification.qualification_score,
        action_id=str(action.id),
        tracking_url=tracking_url,
        intake_url=intake_url,
        is_emergency=is_emergency,
    )


@router.post(
    "/widget/lead",
    response_model=WidgetChatResponse,
    summary="Submit Inbound Website Lead",
    description="Processes website form or widget lead, qualifies urgency, creates LeadAction, and returns tracking/intake URLs.",
)
async def submit_widget_lead(
    lead_req: WidgetLeadRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> WidgetChatResponse:
    return await _process_lead_intake(
        lead_req=lead_req,
        tenant_slug=lead_req.tenant_slug,
        request=request,
        db=db,
    )


@router.post(
    "/widget/{tenant_slug}/lead",
    response_model=WidgetChatResponse,
    summary="Submit Inbound Website Lead for Specific Tenant",
    description="Processes tenant-specific website form or widget lead, qualifies urgency, and routes immediately.",
)
async def submit_tenant_widget_lead(
    tenant_slug: str,
    lead_req: WidgetLeadRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> WidgetChatResponse:
    return await _process_lead_intake(
        lead_req=lead_req,
        tenant_slug=tenant_slug,
        request=request,
        db=db,
    )


@router.get(
    "/widget-demo",
    response_class=HTMLResponse,
    summary="Contractor Website Widget Preview",
    description="Interactive preview demonstrating the embeddable floating widget running live on a contractor marketing site.",
)
async def widget_demo_view(
    request: Request,
    tenant_slug: Optional[str] = Query(None, description="Tenant slug to preview"),
    db: AsyncSession = Depends(get_db),
) -> Response:
    tenant = None
    if tenant_slug:
        query = select(Tenant).where(Tenant.slug == tenant_slug)
        tenant = (await db.execute(query)).scalar_one_or_none()

    if not tenant:
        # Fall back to first available tenant
        query = select(Tenant).where(Tenant.is_active.is_(True)).limit(1)
        tenant = (await db.execute(query)).scalar_one_or_none()

    slug = tenant.slug if tenant else "apex-plumbing"
    name = tenant.name if tenant else "Apex Comfort Systems"
    phone = (
        tenant.settings.get("phone")
        or tenant.settings.get("alert_phone_number")
        or "(555) 234-5678"
    ) if tenant else "(555) 234-5678"

    return templates.TemplateResponse(
        request=request,
        name="widget_demo.html",
        context={
            "tenant_slug": slug,
            "tenant_name": name,
            "tenant_phone": phone,
        },
    )
