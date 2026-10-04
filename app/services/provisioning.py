import re
import secrets
import uuid
from typing import Any, Dict, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import logger
from app.core.security import generate_api_key, generate_webhook_secret
from app.models.tenant import Tenant


def slugify(text: str) -> str:
    """Convert text to URL-safe alphanumeric slug with hyphens."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "-", text)
    text = re.sub(r"^-+|-+$", "", text)
    return text or "client"


def extract_area_code(phone: Optional[str]) -> Optional[str]:
    """Extract 3-digit US area code from phone string."""
    if not phone:
        return None
    cleaned = re.sub(r"\D", "", phone)
    if len(cleaned) == 11 and cleaned.startswith("1"):
        return cleaned[1:4]
    elif len(cleaned) == 10:
        return cleaned[:3]
    return None


async def generate_unique_slug(base_name: str, db: AsyncSession) -> str:
    """Generate a unique slug, appending a short suffix if collisions occur."""
    base_slug = slugify(base_name)
    slug = base_slug
    attempt = 1

    while True:
        query = select(Tenant).where(Tenant.slug == slug)
        existing = (await db.execute(query)).scalar_one_or_none()
        if not existing:
            return slug
        slug = f"{base_slug}-{secrets.token_hex(2)}"
        attempt += 1
        if attempt > 10:
            return f"{base_slug}-{uuid.uuid4().hex[:6]}"


def allocate_twilio_number(
    slug: str,
    business_name: str,
    alert_phone: Optional[str] = None,
) -> str:
    """
    Search and provision an incoming local Twilio phone number configured
    with the tenant's webhook URL. Falls back to a virtual demo line if credentials
    are absent or in sandbox/test environments.
    """
    if settings.TWILIO_ACCOUNT_SID and settings.TWILIO_AUTH_TOKEN:
        try:
            from twilio.rest import Client

            twilio_client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
            area_code = extract_area_code(alert_phone)

            # Search available local numbers in the customer's area code
            numbers = []
            if area_code:
                try:
                    numbers = twilio_client.available_phone_numbers("US").local.list(area_code=area_code, limit=1)
                except Exception as area_err:
                    logger.warning(f"Area code search failed for {area_code}: {area_err}")

            if not numbers:
                numbers = twilio_client.available_phone_numbers("US").local.list(limit=1)

            if numbers:
                target_number = numbers[0].phone_number
                webhook_url = f"http://{settings.HOST}:{settings.PORT}/api/v1/webhooks/twilio/sms?tenant_slug={slug}"
                purchased = twilio_client.incoming_phone_numbers.create(
                    phone_number=target_number,
                    sms_url=webhook_url,
                    sms_method="POST",
                    friendly_name=f"DispatchEngine - {business_name}",
                )
                logger.info(f"Successfully provisioned Twilio line {purchased.phone_number} for tenant '{slug}'.")
                return purchased.phone_number
        except Exception as exc:
            logger.warning(f"Twilio live number provisioning failed ({exc}); assigning virtual line.")

    # Graceful fallback: assign simulated dedicated forwarding number
    random_digits = secrets.randbelow(8999) + 1000
    demo_number = f"+1800555{random_digits}"
    logger.info(f"Assigned virtual demo line {demo_number} to tenant '{slug}'.")
    return demo_number


def send_welcome_sms(
    alert_phone: str,
    business_name: str,
    assigned_number: str,
) -> None:
    """Send onboarding confirmation SMS to client alert phone."""
    if not alert_phone:
        return

    message_body = (
        f"Welcome to DispatchEngine, {business_name}!\n"
        f"Your dedicated operations line is active: {assigned_number}.\n"
        f"Inbound SMS sent to this number will immediately qualify and alert your team."
    )

    if settings.TWILIO_ACCOUNT_SID and settings.TWILIO_AUTH_TOKEN and settings.TWILIO_FROM_NUMBER:
        try:
            from twilio.rest import Client

            client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
            client.messages.create(
                to=alert_phone,
                from_=settings.TWILIO_FROM_NUMBER,
                body=message_body,
            )
            logger.info(f"Sent welcome SMS to client alert phone {alert_phone}.")
            return
        except Exception as exc:
            logger.error(f"Failed sending welcome SMS to {alert_phone}: {exc}")

    logger.info(f"[Simulation] Welcome SMS dispatched to {alert_phone}: {message_body}")


async def provision_new_tenant_from_stripe(
    session_data: Dict[str, Any],
    db_session: AsyncSession,
) -> Tenant:
    """
    Auto-provision a new tenant from a completed Stripe Checkout session.
    1. Extracts metadata, customer email, and alert phone.
    2. Generates slug, credentials, and Twilio phone line.
    3. Persists active Tenant record.
    4. Dispatches confirmation SMS.
    """
    metadata = session_data.get("metadata") or {}
    customer_details = session_data.get("customer_details") or {}

    business_name = (
        metadata.get("business_name")
        or metadata.get("company_name")
        or customer_details.get("name")
        or "New Client"
    )
    customer_email = customer_details.get("email") or session_data.get("customer_email") or ""
    alert_phone = metadata.get("alert_phone") or customer_details.get("phone") or ""
    stripe_customer_id = session_data.get("customer") or ""
    stripe_subscription_id = session_data.get("subscription") or ""

    # Generate slug & credentials
    slug = await generate_unique_slug(business_name, db_session)
    raw_api_key, api_key_hash = generate_api_key()
    webhook_secret = generate_webhook_secret()

    # Provision or allocate forwarding number
    assigned_number = allocate_twilio_number(
        slug=slug,
        business_name=business_name,
        alert_phone=alert_phone,
    )

    tenant_settings = {
        "stripe_customer_id": stripe_customer_id,
        "stripe_subscription_id": stripe_subscription_id,
        "customer_email": customer_email,
        "alert_phone_number": alert_phone,
        "assigned_twilio_number": assigned_number,
        "min_qualification_score": float(metadata.get("min_qualification_score", 0.4)),
        "routing_rules": {
            "default_route": "general_inbox",
            "high_priority_route": "vip_sales_queue",
            "emergency_route": "emergency_dispatch_queue",
        },
    }

    tenant = Tenant(
        id=uuid.uuid4(),
        name=business_name,
        slug=slug,
        api_key_hash=api_key_hash,
        webhook_secret=webhook_secret,
        is_active=True,
        settings=tenant_settings,
    )
    db_session.add(tenant)
    await db_session.commit()
    await db_session.refresh(tenant)

    logger.info(
        f"Stripe Auto-Provisioning Successful: Created tenant '{tenant.slug}' (ID: {tenant.id}, Line: {assigned_number})"
    )

    # Send confirmation SMS
    send_welcome_sms(
        alert_phone=alert_phone,
        business_name=business_name,
        assigned_number=assigned_number,
    )

    return tenant


async def deactivate_tenant_by_stripe_customer(
    customer_id: str,
    subscription_id: Optional[str],
    db_session: AsyncSession,
) -> Optional[Tenant]:
    """Deactivate a tenant whose Stripe subscription was cancelled or deleted."""
    query = select(Tenant)
    result = await db_session.execute(query)
    all_tenants = result.scalars().all()

    target_tenant = None
    for t in all_tenants:
        t_cust = t.settings.get("stripe_customer_id")
        t_sub = t.settings.get("stripe_subscription_id")
        if (customer_id and t_cust == customer_id) or (subscription_id and t_sub == subscription_id):
            target_tenant = t
            break

    if target_tenant:
        target_tenant.is_active = False
        await db_session.commit()
        await db_session.refresh(target_tenant)
        logger.info(
            f"Stripe Cancellation: Deactivated tenant '{target_tenant.slug}' (Customer: {customer_id}, Sub: {subscription_id})."
        )

    return target_tenant
