import os
import uuid
from typing import Optional
from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.core.config import settings
from app.core.logging import logger
from app.core.security import generate_api_key, generate_webhook_secret
from app.db.session import check_db_connection
from app.models.lead_action import LeadAction
from app.models.tenant import Tenant
from app.models.webhook_event import WebhookEvent
from app.services.dispatch import dispatch_service
from app.services.qualification import qualification_service

router = APIRouter()

# Locate templates directory reliably
TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "templates")
templates = Jinja2Templates(directory=TEMPLATES_DIR)


@router.get(
    "/dashboard",
    response_class=HTMLResponse,
    summary="Operator Overview Dashboard",
    description="Renders metrics banner, live qualification & dispatch feed, simulator, and Twilio config.",
)
async def operator_dashboard(
    request: Request,
    tenant_slug: Optional[str] = Query(None),
    simulated: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    # 1. Fetch Metrics
    total_events_count = (await db.execute(select(func.count(WebhookEvent.id)))).scalar() or 0
    urgent_leads_count = (
        await db.execute(
            select(func.count(LeadAction.id)).where(
                or_(
                    LeadAction.qualification_score >= 0.8,
                    LeadAction.action_type.like("%EMERGENCY%"),
                )
            )
        )
    ).scalar() or 0
    dispatched_count = (
        await db.execute(
            select(func.count(LeadAction.id)).where(LeadAction.dispatch_status == "COMPLETED")
        )
    ).scalar() or 0

    # 2. Fetch Active Tenants
    tenants_result = await db.execute(select(Tenant).where(Tenant.is_active == True).order_by(Tenant.created_at.asc()))
    tenants = list(tenants_result.scalars().all())

    # Selected Tenant context
    current_tenant = None
    if tenant_slug:
        current_tenant = next((t for t in tenants if t.slug == tenant_slug), None)
    if not current_tenant and tenants:
        current_tenant = tenants[0]

    # 3. Fetch Recent Lead Actions with Tenant Slug
    query = (
        select(LeadAction, Tenant.slug.label("tenant_slug"))
        .join(Tenant, LeadAction.tenant_id == Tenant.id)
        .order_by(LeadAction.created_at.desc())
        .limit(20)
    )
    if tenant_slug:
        query = query.where(Tenant.slug == tenant_slug)

    actions_result = await db.execute(query)
    lead_rows = actions_result.all()

    # Format lead action rows
    formatted_leads = []
    for action, slug in lead_rows:
        action.tenant_slug = slug
        formatted_leads.append(action)

    # 4. Check Database Connection (session queries already confirmed connection)
    is_db_connected = True
    db_status = "connected"


    # Base URL for webhook copy display
    base_url = str(request.base_url).rstrip("/")

    # 5. Reputation & Review Metrics
    review_q = select(LeadAction).where(LeadAction.review_data.isnot(None))
    if tenant_slug and current_tenant:
        review_q = review_q.where(LeadAction.tenant_id == current_tenant.id)
    review_actions = list((await db.execute(review_q)).scalars().all())
    reviews_prompted_count = len(review_actions)
    reviews_boosted_count = sum(1 for a in review_actions if (a.review_data or {}).get("outcome_status") == "BOOST_SENT")
    reviews_shielded_count = sum(1 for a in review_actions if (a.review_data or {}).get("outcome_status") == "NEGATIVE_INSULATED")

    # 6. Invoicing & Revenue Metrics
    invoice_q = select(LeadAction).where(LeadAction.invoice_data.isnot(None))
    if tenant_slug and current_tenant:
        invoice_q = invoice_q.where(LeadAction.tenant_id == current_tenant.id)
    invoice_actions = list((await db.execute(invoice_q)).scalars().all())
    revenue_collected = sum(
        float((a.invoice_data or {}).get("contract_total", 0.0) or 0.0)
        for a in invoice_actions
        if (a.invoice_data or {}).get("payment_status") == "PAID"
    )
    invoices_settled_count = sum(
        1 for a in invoice_actions
        if (a.invoice_data or {}).get("payment_status") == "PAID"
    )
    invoices_pending_count = sum(
        1 for a in invoice_actions
        if (a.invoice_data or {}).get("payment_status") == "PENDING"
    )

    # 7. Reactivated Pipeline Revenue Metrics
    reactivation_q = select(LeadAction).where(LeadAction.reactivation_data.isnot(None))
    if tenant_slug and current_tenant:
        reactivation_q = reactivation_q.where(LeadAction.tenant_id == current_tenant.id)
    reactivation_actions = list((await db.execute(reactivation_q)).scalars().all())
    reactivated_revenue = sum(
        float((a.reactivation_data or {}).get("potential_recovered_revenue", 0.0) or 0.0)
        for a in reactivation_actions
        if (a.reactivation_data or {}).get("status") in ("SENT", "ACCEPTED")
    )
    reactivated_count = len(reactivation_actions)

    # 8. Customer Neighbor Referral Metrics
    ref_q = select(LeadAction).where(LeadAction.referral_data.isnot(None))
    if tenant_slug and current_tenant:
        ref_q = ref_q.where(LeadAction.tenant_id == current_tenant.id)
    ref_actions = list((await db.execute(ref_q)).scalars().all())
    referral_conversions_count = sum(
        int((a.referral_data or {}).get("conversions_count", 0))
        for a in ref_actions
        if "referral_code" in (a.referral_data or {})
    )
    referral_rewards_paid = sum(
        float((a.referral_data or {}).get("rewards_earned", 0.0))
        for a in ref_actions
        if "referral_code" in (a.referral_data or {})
    )

    # Render template
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "project_name": settings.PROJECT_NAME,
            "total_events_count": total_events_count,
            "urgent_leads_count": urgent_leads_count,
            "dispatched_count": dispatched_count,
            "tenants": tenants,
            "current_tenant": current_tenant,
            "active_tenant_slug": tenant_slug or (current_tenant.slug if current_tenant else ""),
            "lead_actions": formatted_leads,
            "db_status": db_status,
            "base_url": base_url,
            "simulated_feedback": simulated,
            "reviews_prompted_count": reviews_prompted_count,
            "reviews_boosted_count": reviews_boosted_count,
            "reviews_shielded_count": reviews_shielded_count,
            "revenue_collected": revenue_collected,
            "invoices_settled_count": invoices_settled_count,
            "invoices_pending_count": invoices_pending_count,
            "reactivated_revenue": reactivated_revenue,
            "reactivated_count": reactivated_count,
            "referral_conversions_count": referral_conversions_count,
            "referral_rewards_paid": referral_rewards_paid,
        },
    )



@router.post(
    "/simulator/simulate-lead",
    summary="Simulate Inbound Lead",
    description="Processes test lead through Gemini LLM qualification, executes dispatch rules, and logs outcomes.",
)
async def simulate_lead(
    request: Request,
    tenant_slug: str = Form(None),
    sender_phone: str = Form(None),
    message_body: str = Form(None),
    db: AsyncSession = Depends(get_db),
):
    # Support JSON fallback if submitted via API
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        try:
            body_json = await request.json()
            tenant_slug = body_json.get("tenant_slug")
            sender_phone = body_json.get("sender_phone")
            message_body = body_json.get("message_body")
        except Exception:
            pass

    if not tenant_slug or not sender_phone or not message_body:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="tenant_slug, sender_phone, and message_body are required",
        )

    # 1. Resolve or Auto-Provision Target Tenant
    query = select(Tenant).where(Tenant.slug == tenant_slug)
    tenant = (await db.execute(query)).scalar_one_or_none()

    if not tenant:
        raw_api_key, api_key_hash = generate_api_key()
        webhook_secret = generate_webhook_secret()
        tenant = Tenant(
            id=uuid.uuid4(),
            name=f"Demo ({tenant_slug.capitalize()})",
            slug=tenant_slug,
            api_key_hash=api_key_hash,
            webhook_secret=webhook_secret,
            is_active=True,
            settings={
                "min_qualification_score": 0.4,
                "alert_phone_number": "+15559876543",
                "routing_rules": {
                    "default_route": "general_inbox",
                    "high_priority_route": "vip_sales_queue",
                    "emergency_route": "emergency_dispatch_queue",
                },
            },
        )
        db.add(tenant)
        await db.flush()
        await db.refresh(tenant)

    # 2. Record Inbound WebhookEvent
    event_id = uuid.uuid4()
    payload = {
        "From": sender_phone,
        "Body": message_body,
        "MessageSid": f"SIM_{uuid.uuid4().hex[:12]}",
        "source": "simulator",
    }
    event = WebhookEvent(
        id=event_id,
        tenant_id=tenant.id,
        source="simulator",
        event_type="sms.simulated",
        idempotency_key=str(uuid.uuid4()),
        status="PROCESSED",
        payload=payload,
        headers={"user-agent": "DispatchSimulator/1.0"},
    )
    db.add(event)
    await db.flush()

    # 3. Qualify & Dispatch
    qualification = await qualification_service.qualify_lead(
        tenant_settings=tenant.settings,
        lead_payload=payload,
    )

    plan = dispatch_service.create_dispatch_plan(
        tenant=tenant,
        qualification=qualification,
        lead_payload=payload,
    )

    action = await dispatch_service.execute_dispatch(
        db=db,
        tenant=tenant,
        event=event,
        qualification=qualification,
        plan=plan,
    )

    logger.info(f"Simulated lead processed: {action.id} (Score: {qualification.qualification_score})")

    # If API requested JSON response
    accept_header = request.headers.get("accept", "")
    if "application/json" in accept_header or "application/json" in content_type:
        return {
            "success": True,
            "tenant_slug": tenant.slug,
            "event_id": str(event.id),
            "lead_action_id": str(action.id),
            "qualification": qualification.model_dump(),
            "plan": plan.model_dump(),
            "dispatch_status": action.dispatch_status,
        }

    # Redirect to dashboard with feedback message
    feedback = f"Action: {action.action_type} | Score: {qualification.qualification_score} | Urgency: {qualification.intent_level.value}"
    return RedirectResponse(
        url=f"/dashboard?tenant_slug={tenant.slug}&simulated={feedback}",
        status_code=status.HTTP_303_SEE_OTHER,
    )
