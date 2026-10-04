import json
import uuid
from unittest.mock import patch
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import stripe

from app.core.config import settings
from app.models.tenant import Tenant


@pytest.mark.asyncio
async def test_stripe_checkout_completed_auto_provisioning(
    client: AsyncClient,
    db_session: AsyncSession,
):
    """Verify checkout.session.completed triggers automatic tenant creation and phone line allocation."""
    mock_event = {
        "id": "evt_test_checkout_123",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_test_session_123",
                "customer": "cus_stripe_1111",
                "subscription": "sub_stripe_2222",
                "customer_email": "owner@solarpowerpro.com",
                "metadata": {
                    "business_name": "Solar Power Pro",
                    "alert_phone": "+15553334444",
                    "min_qualification_score": "0.5",
                },
                "customer_details": {
                    "name": "Solar Power Pro",
                    "phone": "+15553334444",
                    "email": "owner@solarpowerpro.com",
                },
            }
        },
    }

    with patch("app.api.v1.webhooks.settings.STRIPE_WEBHOOK_SECRET", "whsec_test_secret_123"):
        with patch("stripe.Webhook.construct_event", return_value=mock_event):
            response = await client.post(
                "/api/v1/webhooks/stripe",
                content=json.dumps(mock_event),
                headers={
                    "Content-Type": "application/json",
                    "stripe-signature": "t=1234567,v1=valid_mock_signature",
                },
            )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["event_type"] == "checkout.session.completed"
    assert "solar-power-pro" in data["tenant_slug"]

    # Verify Tenant record created in database
    query = select(Tenant).where(Tenant.slug == data["tenant_slug"])
    tenant = (await db_session.execute(query)).scalar_one_or_none()
    assert tenant is not None
    assert tenant.is_active is True
    assert tenant.name == "Solar Power Pro"
    assert tenant.settings.get("stripe_customer_id") == "cus_stripe_1111"
    assert tenant.settings.get("alert_phone_number") == "+15553334444"
    assert "assigned_twilio_number" in tenant.settings


@pytest.mark.asyncio
async def test_stripe_invalid_signature_rejection(client: AsyncClient):
    """Verify that forged or invalid stripe signatures return 400 Bad Request."""
    payload = json.dumps({"type": "checkout.session.completed"})

    with patch("app.api.v1.webhooks.settings.STRIPE_WEBHOOK_SECRET", "whsec_strict_secret"):
        response = await client.post(
            "/api/v1/webhooks/stripe",
            content=payload,
            headers={
                "Content-Type": "application/json",
                "stripe-signature": "t=12345,v1=invalid_forged_sig",
            },
        )

    assert response.status_code == 400
    assert "Invalid signature" in response.json().get("detail", "") or response.status_code == 400


@pytest.mark.asyncio
async def test_stripe_subscription_cancellation_deactivates_tenant(
    client: AsyncClient,
    db_session: AsyncSession,
):
    """Verify customer.subscription.deleted event deactivates the corresponding tenant."""
    # 1. Seed tenant with active stripe customer
    tenant = Tenant(
        id=uuid.uuid4(),
        name="Cancel Subscription Corp",
        slug=f"cancel-corp-{uuid.uuid4().hex[:6]}",
        api_key_hash="hash_cancel_123",
        webhook_secret="whsec_cancel_123",
        is_active=True,
        settings={
            "stripe_customer_id": "cus_cancel_target_999",
            "stripe_subscription_id": "sub_cancel_target_999",
        },
    )
    db_session.add(tenant)
    await db_session.commit()
    await db_session.refresh(tenant)
    assert tenant.is_active is True

    # 2. Fire subscription deletion event
    mock_event = {
        "id": "evt_test_sub_deleted_999",
        "type": "customer.subscription.deleted",
        "data": {
            "object": {
                "id": "sub_cancel_target_999",
                "customer": "cus_cancel_target_999",
            }
        },
    }

    with patch("app.api.v1.webhooks.settings.STRIPE_WEBHOOK_SECRET", "whsec_test_secret"):
        with patch("stripe.Webhook.construct_event", return_value=mock_event):
            response = await client.post(
                "/api/v1/webhooks/stripe",
                content=json.dumps(mock_event),
                headers={
                    "Content-Type": "application/json",
                    "stripe-signature": "t=12345,v1=valid_sig",
                },
            )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["deactivated"] is True

    # 3. Verify tenant is_active is now False in DB
    query = select(Tenant).where(Tenant.id == tenant.id)
    updated_tenant = (await db_session.execute(query)).scalar_one()
    assert updated_tenant.is_active is False
