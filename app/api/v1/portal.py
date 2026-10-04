import hmac
import os
from typing import Any, Dict, Optional
from fastapi import APIRouter, Cookie, Depends, Form, Header, HTTPException, Query, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.core.config import settings
from app.core.logging import logger
from app.core.security import hash_api_key
from app.models.lead_action import LeadAction
from app.models.tenant import Tenant
from app.models.webhook_event import WebhookEvent
from app.services.analytics import generate_weekly_roi_digest

router = APIRouter()

# Locate templates directory
TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "templates")
templates = Jinja2Templates(directory=TEMPLATES_DIR)


def authenticate_portal_request(
    tenant: Tenant,
    x_api_key: Optional[str] = None,
    query_api_key: Optional[str] = None,
    cookie_token: Optional[str] = None,
) -> bool:
    """Validate tenant credentials from header, query param, or session cookie."""
    candidate_key = x_api_key or query_api_key or cookie_token
    if not candidate_key:
        return False

    candidate_hash = hash_api_key(candidate_key)
    return hmac.compare_digest(candidate_hash, tenant.api_key_hash)


@router.get(
    "/portal/{tenant_slug}",
    response_class=HTMLResponse,
    summary="Client Operations Portal",
    description="Renders tenant-isolated dark operational dashboard with metrics, live activity log, and business settings.",
)
async def client_portal_view(
    tenant_slug: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    api_key: Optional[str] = Query(None),
    updated: Optional[str] = Query(None),
    portal_token: Optional[str] = Cookie(None),
) -> Response:
    # 1. Resolve Tenant
    query = select(Tenant).where(Tenant.slug == tenant_slug, Tenant.is_active == True)
    tenant = (await db.execute(query)).scalar_one_or_none()

    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant '{tenant_slug}' not found or inactive",
        )

    # 2. Authenticate
    is_authenticated = authenticate_portal_request(
        tenant=tenant,
        x_api_key=x_api_key,
        query_api_key=api_key,
        cookie_token=portal_token,
    )

    if not is_authenticated:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized: Valid tenant API key or portal session required.",
        )

    # 3. Aggregate Tenant-Isolated Metrics
    total_calls_q = select(func.count(WebhookEvent.id)).where(WebhookEvent.tenant_id == tenant.id)
    total_calls = (await db.execute(total_calls_q)).scalar() or 0

    emergencies_q = select(func.count(LeadAction.id)).where(
        LeadAction.tenant_id == tenant.id,
        or_(
            LeadAction.action_type.like("%EMERGENCY%"),
            LeadAction.qualification_score >= 0.8,
        ),
    )
    emergencies_count = (await db.execute(emergencies_q)).scalar() or 0

    qualified_leads_q = select(func.count(LeadAction.id)).where(
        LeadAction.tenant_id == tenant.id,
        LeadAction.qualification_score >= 0.4,
    )
    qualified_count = (await db.execute(qualified_leads_q)).scalar() or 0

    avg_job_value = float(tenant.settings.get("avg_job_value", 3500.0))
    pipeline_value = qualified_count * avg_job_value

    # 4. Fetch Isolated Lead Actions
    leads_q = (
        select(LeadAction)
        .where(LeadAction.tenant_id == tenant.id)
        .order_by(LeadAction.created_at.desc())
        .limit(30)
    )
    lead_actions = list((await db.execute(leads_q)).scalars().all())

    # Review Metrics
    actions_with_review = [a for a in lead_actions if a.review_data]
    reviews_prompted_count = len(actions_with_review)
    reviews_boosted_count = sum(1 for a in actions_with_review if (a.review_data or {}).get("outcome_status") == "BOOST_SENT")
    reviews_shielded_count = sum(1 for a in actions_with_review if (a.review_data or {}).get("outcome_status") == "NEGATIVE_INSULATED")

    # Membership Metrics
    membership_q = select(LeadAction).where(
        LeadAction.tenant_id == tenant.id,
        LeadAction.membership_enrollment.is_not(None),
    )
    membership_actions = list((await db.execute(membership_q)).scalars().all())
    active_memberships = [
        a for a in membership_actions
        if (a.membership_enrollment or {}).get("status") == "ACTIVE"
    ]
    active_memberships_count = len(active_memberships)
    contractor_mrr = sum(
        float((a.membership_enrollment or {}).get("monthly_price", 0.0) or 0.0)
        for a in active_memberships
    )

    # Invoicing & Revenue Metrics
    invoice_q = select(LeadAction).where(
        LeadAction.tenant_id == tenant.id,
        LeadAction.invoice_data.is_not(None),
    )
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

    # Reactivated Pipeline Revenue Metrics
    reactivation_q = select(LeadAction).where(
        LeadAction.tenant_id == tenant.id,
        LeadAction.reactivation_data.is_not(None),
    )
    reactivation_actions = list((await db.execute(reactivation_q)).scalars().all())
    reactivated_revenue = sum(
        float((a.reactivation_data or {}).get("potential_recovered_revenue", 0.0) or 0.0)
        for a in reactivation_actions
        if (a.reactivation_data or {}).get("status") in ("SENT", "ACCEPTED")
    )
    reactivated_count = len(reactivation_actions)

    # Referral Metrics
    ref_q = select(LeadAction).where(
        LeadAction.tenant_id == tenant.id,
        LeadAction.referral_data.is_not(None),
    )
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

    # 5. Render Template & Set Session Cookie
    feedback = "Settings updated successfully." if updated else None
    effective_key = x_api_key or api_key or portal_token or ""

    response = templates.TemplateResponse(
        request=request,
        name="client_portal.html",
        context={
            "tenant": tenant,
            "raw_api_key": effective_key,
            "total_calls_count": total_calls,
            "emergencies_bridged_count": emergencies_count,
            "pipeline_value": pipeline_value,
            "avg_job_value": avg_job_value,
            "lead_actions": lead_actions,
            "feedback_message": feedback,
            "reviews_prompted_count": reviews_prompted_count,
            "reviews_boosted_count": reviews_boosted_count,
            "reviews_shielded_count": reviews_shielded_count,
            "active_memberships_count": active_memberships_count,
            "contractor_mrr": contractor_mrr,
            "revenue_collected": revenue_collected,
            "invoices_settled_count": invoices_settled_count,
            "reactivated_revenue": reactivated_revenue,
            "reactivated_count": reactivated_count,
            "referral_conversions_count": referral_conversions_count,
            "referral_rewards_paid": referral_rewards_paid,
        },
    )


    # Set authentication cookie so subsequent clicks remain authenticated
    if effective_key:
        response.set_cookie(
            key="portal_token",
            value=effective_key,
            httponly=True,
            samesite="lax",
            max_age=86400 * 7,
        )

    return response


@router.post(
    "/portal/{tenant_slug}/settings",
    summary="Update Tenant Business Settings",
    description="Updates on-call emergency phone number, operating hours, and notification rules.",
)
async def update_portal_settings(
    tenant_slug: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    api_key: Optional[str] = Form(None),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    portal_token: Optional[str] = Cookie(None),
    alert_phone_number: Optional[str] = Form(None),
    business_hours: Optional[str] = Form(None),
    crm_provider: Optional[str] = Form("generic_webhook"),
    crm_webhook_url: Optional[str] = Form(None),
    avg_job_value: Optional[float] = Form(3500.0),
    sms_alerts_enabled: Optional[str] = Form(None),
    crm_forwarding_enabled: Optional[str] = Form(None),
    fallback_owner_phone: Optional[str] = Form(None),
    google_review_url: Optional[str] = Form(None),
    on_call_roster_json: Optional[str] = Form(None),
) -> Response:
    # 1. Resolve Tenant
    query = select(Tenant).where(Tenant.slug == tenant_slug, Tenant.is_active == True)
    tenant = (await db.execute(query)).scalar_one_or_none()

    if not tenant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")

    # 2. Authenticate
    is_authenticated = authenticate_portal_request(
        tenant=tenant,
        x_api_key=x_api_key,
        query_api_key=api_key,
        cookie_token=portal_token,
    )
    if not is_authenticated:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")

    # 3. Update Settings
    cur_crm = tenant.settings.get("crm", {})
    new_settings = {
        **tenant.settings,
        "alert_phone_number": alert_phone_number or tenant.settings.get("alert_phone_number"),
        "fallback_owner_phone": fallback_owner_phone or tenant.settings.get("fallback_owner_phone"),
        "google_review_url": google_review_url or tenant.settings.get("google_review_url"),
        "business_hours": business_hours or tenant.settings.get("business_hours", "24/7 Continuous Emergency Coverage"),
        "avg_job_value": avg_job_value or 3500.0,
        "notifications": {
            "sms": sms_alerts_enabled == "true",
            "crm_forwarding": crm_forwarding_enabled == "true",
        },
        "crm": {
            **cur_crm,
            "provider": crm_provider or "generic_webhook",
            "webhook_url": crm_webhook_url or cur_crm.get("webhook_url", ""),
        },
    }

    if on_call_roster_json:
        import json
        try:
            parsed_roster = json.loads(on_call_roster_json)
            if isinstance(parsed_roster, list):
                new_settings["on_call_roster"] = parsed_roster
        except Exception as e:
            logger.warning("Failed to parse on_call_roster_json in portal settings: %s", e)

    tenant.settings = new_settings
    await db.commit()
    await db.refresh(tenant)

    effective_key = api_key or x_api_key or portal_token or ""
    redirect_url = f"/portal/{tenant.slug}?updated=true"
    if effective_key:
        redirect_url += f"&api_key={effective_key}"

    response = RedirectResponse(url=redirect_url, status_code=status.HTTP_303_SEE_OTHER)
    if effective_key:
        response.set_cookie(
            key="portal_token",
            value=effective_key,
            httponly=True,
            samesite="lax",
            max_age=86400 * 7,
        )

    return response


@router.get(
    "/api/v1/portal/{tenant_slug}/digest",
    summary="Weekly ROI Analytics Digest",
    description="Returns aggregated 7-day ROI analytics digest and executive email template.",
)
async def get_weekly_roi_digest(
    tenant_slug: str,
    format: Optional[str] = Query(None, description="Set to 'html' to receive rendered HTML email"),
    db: AsyncSession = Depends(get_db),
) -> Any:
    query = select(Tenant).where(Tenant.slug == tenant_slug, Tenant.is_active == True)
    tenant = (await db.execute(query)).scalar_one_or_none()

    if not tenant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")

    digest = await generate_weekly_roi_digest(tenant.id, db)

    if format == "html":
        return HTMLResponse(content=digest["email_html"])

    return digest
