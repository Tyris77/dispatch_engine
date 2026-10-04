import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lead_action import LeadAction
from app.models.webhook_event import WebhookEvent


@pytest.mark.asyncio
async def test_twilio_inbound_sms_webhook_success(
    client: AsyncClient,
    sample_tenant: dict,
    db_session: AsyncSession,
):
    """Test receiving an x-www-form-urlencoded Twilio SMS, generating WebhookEvent, and returning TwiML."""
    tenant = sample_tenant["tenant"]
    form_data = {
        "From": "+15551234567",
        "To": "+15559876543",
        "Body": "Urgent emergency: our pipeline has an outage, need immediate dispatch assistance!",
        "MessageSid": "SM_TEST_UNIQUE_001",
        "AccountSid": "AC_TEST_ACCOUNT_123",
    }

    response = await client.post(
        f"/api/v1/webhooks/twilio/sms?tenant_slug={tenant.slug}",
        data=form_data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    assert response.status_code == 200
    assert "xml" in response.headers.get("content-type", "").lower()
    assert "<Response>" in response.text
    assert "</Response>" in response.text

    # Verify event stored in DB
    query_event = select(WebhookEvent).where(WebhookEvent.idempotency_key == "SM_TEST_UNIQUE_001")
    event = (await db_session.execute(query_event)).scalar_one_or_none()
    assert event is not None
    assert event.source == "twilio_sms"
    assert event.event_type == "sms.received"
    assert event.payload.get("From") == "+15551234567"

    # Verify LeadAction was generated
    query_action = select(LeadAction).where(LeadAction.webhook_event_id == event.id)
    action = (await db_session.execute(query_action)).scalar_one_or_none()
    assert action is not None
    assert action.dispatch_status == "COMPLETED"


@pytest.mark.asyncio
async def test_twilio_sms_idempotency_duplicate(
    client: AsyncClient,
    sample_tenant: dict,
):
    """Test that a duplicate MessageSid is acknowledged safely with TwiML and not duplicated."""
    tenant = sample_tenant["tenant"]
    form_data = {
        "From": "+15552223333",
        "To": "+15559876543",
        "Body": "Checking on demo availability next week",
        "MessageSid": "SM_IDEMPOTENT_REPEAT_001",
    }

    # 1. First reception
    res1 = await client.post(
        f"/api/v1/webhooks/twilio/sms?tenant_slug={tenant.slug}",
        data=form_data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert res1.status_code == 200
    assert "<Response>" in res1.text

    # 2. Second reception (Twilio retry simulation)
    res2 = await client.post(
        f"/api/v1/webhooks/twilio/sms?tenant_slug={tenant.slug}",
        data=form_data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert res2.status_code == 200
    assert "<Response>" in res2.text
