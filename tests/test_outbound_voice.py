import uuid
from unittest.mock import MagicMock, patch
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lead_action import LeadAction
from app.models.tenant import Tenant
from app.services.outbound_voice import outbound_voice_service


@pytest.fixture
async def seeded_voice_action(sample_tenant: dict, db_session: AsyncSession) -> LeadAction:
    """Fixture providing a seeded LeadAction ready for outbound arrival call testing."""
    tenant = sample_tenant["tenant"]

    # Configure tenant settings with on-call roster and twilio numbers
    tenant.settings["twilio_phone_number"] = "+15005550006"
    tenant.settings["phone"] = "+12025550199"
    tenant.settings["on_call_roster"] = [
        {
            "name": "Marcus Vance",
            "phone": "+15557778888",
            "role": "Lead HVAC Specialist",
            "priority": 1,
            "active_days": [
                "Monday",
                "Tuesday",
                "Wednesday",
                "Thursday",
                "Friday",
                "Saturday",
                "Sunday",
            ],
        }
    ]
    db_session.add(tenant)
    await db_session.commit()

    action = LeadAction(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        lead_external_id="+15553332222",
        qualification_score=0.95,
        qualification_summary="Emergency high-priority dispatch.",
        action_type="DISPATCH_EMERGENCY_DISPATCH_QUEUE",
        dispatch_status="QUEUED",
        crm_sync_status="PENDING",
        metadata_payload={
            "customer_name": "Eleanor Vance",
            "address": "420 Maple Ave, Bethesda, MD 20814",
            "phone": "+15553332222",
        },
        tracking_data={
            "status": "EN_ROUTE",
            "eta_minutes": 20,
            "technician": {
                "name": "Marcus Vance",
                "phone": "+15557778888",
            },
        },
    )
    db_session.add(action)
    await db_session.commit()
    await db_session.refresh(action)
    return action


@pytest.mark.asyncio
async def test_trigger_outbound_arrival_call_service(
    seeded_voice_action: LeadAction,
    sample_tenant: dict,
    db_session: AsyncSession,
):
    """Verify trigger_outbound_arrival_call sets tracking data and creates simulated or live call SID."""
    tenant = sample_tenant["tenant"]

    result = await outbound_voice_service.trigger_outbound_arrival_call(
        lead_action=seeded_voice_action,
        tenant=tenant,
        eta_minutes=25,
        base_url="https://api.contractor.com",
        db=db_session,
    )

    assert result["success"] is True
    assert result["call_sid"].startswith("CA_sim_")
    assert result["to"] == "+15553332222"
    assert result["eta_minutes"] == 25
    assert (
        result["callback_url"]
        == f"https://api.contractor.com/api/v1/webhooks/twilio/voice/outbound-confirm?action_id={seeded_voice_action.id}&eta=25"
    )

    # Verify updated lead_action tracking data
    assert seeded_voice_action.tracking_data["outbound_call_status"] == "IN_PROGRESS"
    assert seeded_voice_action.tracking_data["outbound_call_eta"] == 25
    assert "outbound_call_at" in seeded_voice_action.tracking_data


def test_generate_outbound_confirm_twiml(sample_tenant: dict):
    """Verify generate_outbound_confirm_twiml produces expected Polly greeting and Gather block."""
    tenant = sample_tenant["tenant"]
    action_id = str(uuid.uuid4())

    twiml = outbound_voice_service.generate_outbound_confirm_twiml(
        tenant=tenant,
        eta=18,
        action_id=action_id,
    )

    assert "<Response>" in twiml
    assert 'voice="Polly.Danielle-Neural"' in twiml
    assert tenant.name in twiml
    assert "arriving in approximately 18 minutes" in twiml
    assert "Press 1 to confirm you are on site, or press 2 to speak directly" in twiml
    assert f'action="/api/v1/webhooks/twilio/voice/outbound-confirm/process?action_id={action_id}"' in twiml
    assert '<Gather numDigits="1"' in twiml
    assert "<Hangup/>" in twiml


@pytest.mark.asyncio
async def test_webhook_outbound_confirm_endpoint(
    client: AsyncClient,
    seeded_voice_action: LeadAction,
    sample_tenant: dict,
):
    """Verify POST /api/v1/webhooks/twilio/voice/outbound-confirm endpoint returns TwiML with neural greeting."""
    tenant = sample_tenant["tenant"]
    url = f"/api/v1/webhooks/twilio/voice/outbound-confirm?action_id={seeded_voice_action.id}&eta=15"
    response = await client.post(url)

    assert response.status_code == 200
    assert "application/xml" in response.headers["content-type"]
    text = response.text
    assert "<Response>" in text
    assert tenant.name in text
    assert "arriving in approximately 15 minutes" in text
    assert "numDigits=\"1\"" in text


@pytest.mark.asyncio
async def test_webhook_outbound_confirm_process_digits_1_confirmed(
    client: AsyncClient,
    seeded_voice_action: LeadAction,
    db_session: AsyncSession,
):
    """Verify Digits=1 marks homeowner_confirmed=True in tracking_data and returns confirmation TwiML."""
    url = f"/api/v1/webhooks/twilio/voice/outbound-confirm/process?action_id={seeded_voice_action.id}"
    response = await client.post(url, data={"Digits": "1"})

    assert response.status_code == 200
    assert "application/xml" in response.headers["content-type"]
    assert "Thank you, your technician has been notified that you are ready" in response.text
    assert "<Hangup/>" in response.text

    # Re-fetch lead action to confirm persistence
    query = select(LeadAction).where(LeadAction.id == seeded_voice_action.id)
    refreshed = (await db_session.execute(query)).scalar_one()
    assert refreshed.tracking_data.get("homeowner_confirmed") is True
    assert "homeowner_confirmed_at" in refreshed.tracking_data


@pytest.mark.asyncio
async def test_webhook_outbound_confirm_process_digits_2_dial_tech(
    client: AsyncClient,
    seeded_voice_action: LeadAction,
):
    """Verify Digits=2 bridges call via <Dial> directly to on-call technician."""
    url = f"/api/v1/webhooks/twilio/voice/outbound-confirm/process?action_id={seeded_voice_action.id}"
    response = await client.post(url, data={"Digits": "2"})

    assert response.status_code == 200
    assert "application/xml" in response.headers["content-type"]
    assert "Connecting you directly to your technician now" in response.text
    assert '<Dial timeout="20"><Number>+15557778888</Number></Dial>' in response.text


@pytest.mark.asyncio
async def test_webhook_outbound_confirm_process_unrecognized_digits(
    client: AsyncClient,
    seeded_voice_action: LeadAction,
):
    """Verify unrecognized DTMF digit plays polite error and hangs up."""
    url = f"/api/v1/webhooks/twilio/voice/outbound-confirm/process?action_id={seeded_voice_action.id}"
    response = await client.post(url, data={"Digits": "9"})

    assert response.status_code == 200
    assert "application/xml" in response.headers["content-type"]
    assert "We did not recognize that option" in response.text
    assert "<Hangup/>" in response.text


@pytest.mark.asyncio
async def test_track_endpoint_trigger_arrival_call(
    client: AsyncClient,
    seeded_voice_action: LeadAction,
    db_session: AsyncSession,
):
    """Verify POST /track/{action_id}/outbound-arrival-call initiates call via API."""
    url = f"/track/{seeded_voice_action.id}/outbound-arrival-call?eta_minutes=22"
    response = await client.post(url)

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["eta_minutes"] == 22
    assert "call_sid" in data

    # Verify tracking update
    query = select(LeadAction).where(LeadAction.id == seeded_voice_action.id)
    refreshed = (await db_session.execute(query)).scalar_one()
    assert refreshed.tracking_data.get("outbound_call_eta") == 22
