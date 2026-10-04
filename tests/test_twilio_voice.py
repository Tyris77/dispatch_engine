import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lead_action import LeadAction
from app.models.webhook_event import WebhookEvent


@pytest.mark.asyncio
async def test_twilio_voice_initial_greeting_and_gather(
    client: AsyncClient,
    sample_tenant: dict,
):
    """Test inbound voice call receives Polly Danielle Neural greeting and speech Gather verb."""
    tenant = sample_tenant["tenant"]
    form_data = {
        "CallSid": "CA_INITIAL_GREETING_001",
        "From": "+15551234567",
        "To": "+15559876543",
    }

    response = await client.post(
        f"/api/v1/webhooks/twilio/voice?tenant_slug={tenant.slug}",
        data=form_data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    assert response.status_code == 200
    assert "xml" in response.headers.get("content-type", "").lower()
    text = response.text

    # Assert TwiML response tags and Polly.Danielle-Neural voice
    assert "<Response>" in text
    assert 'voice="Polly.Danielle-Neural"' in text
    assert f"Thank you for calling {tenant.name}" in text
    assert '<Gather input="speech"' in text
    assert f'action="/api/v1/webhooks/twilio/voice/process?tenant_slug={tenant.slug}"' in text
    assert 'timeout="5"' in text
    assert "<Hangup/>" in text


@pytest.mark.asyncio
async def test_twilio_voice_emergency_speech_triggers_dial_bridge(
    client: AsyncClient,
    sample_tenant: dict,
    db_session: AsyncSession,
):
    """Test emergency speech transcript qualifies as emergency and bridges call via <Dial>."""
    tenant = sample_tenant["tenant"]
    alert_phone = "+15558887777"
    tenant.settings = {**tenant.settings, "alert_phone_number": alert_phone}
    await db_session.commit()
    await db_session.refresh(tenant)

    form_data = {
        "CallSid": "CA_EMERGENCY_BRIDGE_002",
        "From": "+15552345678",
        "To": "+15559876543",
        "SpeechResult": "Immediate emergency! Our main pipe burst, water is flooding into the server room right now!",
    }

    response = await client.post(
        f"/api/v1/webhooks/twilio/voice/process?tenant_slug={tenant.slug}",
        data=form_data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    assert response.status_code == 200
    assert "xml" in response.headers.get("content-type", "").lower()
    text = response.text

    # Assert emergency call bridge TwiML
    assert "<Say>Connecting you to our emergency line now.</Say>" in text
    assert '<Dial timeout="25">' in text
    assert f"<Number>{alert_phone}</Number>" in text
    assert "<Hangup/>" not in text

    # Verify WebhookEvent stored with channel="voice"
    query_event = select(WebhookEvent).where(
        WebhookEvent.idempotency_key == "voice_CA_EMERGENCY_BRIDGE_002"
    )
    event = (await db_session.execute(query_event)).scalar_one_or_none()
    assert event is not None
    assert event.source == "twilio_voice"
    assert event.event_type == "voice.received"
    assert event.payload.get("channel") == "voice"
    assert "flooding" in event.payload.get("SpeechResult", "").lower()

    # Verify LeadAction created and marked with voice channel
    query_action = select(LeadAction).where(LeadAction.webhook_event_id == event.id)
    action = (await db_session.execute(query_action)).scalar_one_or_none()
    assert action is not None
    assert action.dispatch_status == "COMPLETED"
    assert action.metadata_payload.get("channel") == "voice"


@pytest.mark.asyncio
async def test_twilio_voice_standard_speech_triggers_hangup_and_sms(
    client: AsyncClient,
    sample_tenant: dict,
    db_session: AsyncSession,
):
    """Test routine non-emergency speech receives confirmation, sends follow-up SMS, and hangs up."""
    tenant = sample_tenant["tenant"]

    form_data = {
        "CallSid": "CA_STANDARD_QUOTE_003",
        "From": "+15553456789",
        "To": "+15559876543",
        "SpeechResult": "Hello, I would like to schedule a general consultation for next Thursday afternoon.",
    }

    response = await client.post(
        f"/api/v1/webhooks/twilio/voice/process?tenant_slug={tenant.slug}",
        data=form_data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    assert response.status_code == 200
    assert "xml" in response.headers.get("content-type", "").lower()
    text = response.text

    # Assert standard quote receipt & hangup
    assert "sent a text to your phone to schedule an estimate" in text
    assert "<Hangup/>" in text
    assert "<Dial" not in text

    # Verify WebhookEvent stored
    query_event = select(WebhookEvent).where(
        WebhookEvent.idempotency_key == "voice_CA_STANDARD_QUOTE_003"
    )
    event = (await db_session.execute(query_event)).scalar_one_or_none()
    assert event is not None
    assert event.source == "twilio_voice"
    assert event.payload.get("channel") == "voice"


@pytest.mark.asyncio
async def test_twilio_voice_idempotency_duplicate_call_sid(
    client: AsyncClient,
    sample_tenant: dict,
):
    """Test duplicate voice process submissions with the same CallSid are safely acknowledged."""
    tenant = sample_tenant["tenant"]

    form_data = {
        "CallSid": "CA_IDEMPOTENT_VOICE_004",
        "From": "+15554567890",
        "To": "+15559876543",
        "SpeechResult": "Inquiry about basic rates.",
    }

    # First call
    res1 = await client.post(
        f"/api/v1/webhooks/twilio/voice/process?tenant_slug={tenant.slug}",
        data=form_data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert res1.status_code == 200
    assert "<Response>" in res1.text

    # Duplicate call retry
    res2 = await client.post(
        f"/api/v1/webhooks/twilio/voice/process?tenant_slug={tenant.slug}",
        data=form_data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert res2.status_code == 200
    assert "<Response>" in res2.text
    assert "<Hangup/>" in res2.text


@pytest.mark.asyncio
async def test_twilio_voice_spanish_speech_triggers_lupe_neural_and_bridge(
    client: AsyncClient,
    sample_tenant: dict,
    db_session: AsyncSession,
):
    """Test that Spanish emergency speech uses Polly.Lupe-Neural voice and bridges to emergency line."""
    tenant = sample_tenant["tenant"]
    alert_phone = "+15559998888"
    tenant.settings = {**tenant.settings, "alert_phone_number": alert_phone}
    await db_session.commit()

    form_data = {
        "CallSid": "CA_SPANISH_VOICE_005",
        "From": "+15557776655",
        "To": "+15559876543",
        "SpeechResult": "¡Emergencia urgente! Se rompió una tubería en el sótano y hay una fuga grande de agua!",
    }

    response = await client.post(
        f"/api/v1/webhooks/twilio/voice/process?tenant_slug={tenant.slug}",
        data=form_data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    assert response.status_code == 200
    assert "xml" in response.headers.get("content-type", "").lower()
    text = response.text

    # Assert Polly.Lupe-Neural voice and Spanish language attribute
    assert 'voice="Polly.Lupe-Neural"' in text
    assert 'language="es-US"' in text
    assert "Conectando con nuestra línea de emergencia" in text
    assert '<Dial timeout="25">' in text
    assert f"<Number>{alert_phone}</Number>" in text
