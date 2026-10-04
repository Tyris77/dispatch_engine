import datetime
from unittest.mock import AsyncMock, patch
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lead_action import LeadAction
from app.models.tenant import Tenant
from app.services.dispatch import (
    dispatch_service,
    get_active_on_call_technicians,
)


def test_get_active_on_call_technicians_filtering():
    """Verify on-call roster resolves technicians based on active days and priorities."""
    tenant = Tenant(
        name="Apex Climate Pro",
        slug="apex-climate",
        settings={
            "on_call_roster": [
                {
                    "name": "Sarah Connor",
                    "phone": "+15552222222",
                    "role": "Backup Tech",
                    "priority": 2,
                    "active_days": ["Monday", "Tuesday", "Wednesday"],
                },
                {
                    "name": "John Connor",
                    "phone": "+15551111111",
                    "role": "Lead Tech",
                    "priority": 1,
                    "active_days": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"],
                },
                {
                    "name": "Weekend Warrior",
                    "phone": "+15553333333",
                    "role": "Weekend Specialist",
                    "priority": 1,
                    "active_days": ["Saturday", "Sunday"],
                },
            ]
        },
    )

    # Monday (weekday index 0)
    monday_dt = datetime.datetime(2026, 10, 5, 12, 0)  # Monday
    active_monday = get_active_on_call_technicians(tenant, monday_dt)
    assert len(active_monday) == 2
    assert active_monday[0]["name"] == "John Connor"  # Priority 1
    assert active_monday[1]["name"] == "Sarah Connor"  # Priority 2

    # Thursday (weekday index 3)
    thursday_dt = datetime.datetime(2026, 10, 8, 12, 0)  # Thursday
    active_thursday = get_active_on_call_technicians(tenant, thursday_dt)
    assert len(active_thursday) == 1
    assert active_thursday[0]["name"] == "John Connor"

    # Sunday (weekday index 6)
    sunday_dt = datetime.datetime(2026, 10, 11, 12, 0)  # Sunday
    active_sunday = get_active_on_call_technicians(tenant, sunday_dt)
    assert len(active_sunday) == 1
    assert active_sunday[0]["name"] == "Weekend Warrior"


@pytest.mark.asyncio
async def test_cascading_voice_initial_emergency_dials_primary_tech(
    client: AsyncClient,
    sample_tenant: dict,
    db_session: AsyncSession,
):
    """Test emergency call qualifies and dials Primary Tech with 15s timeout and dial-status action."""
    tenant = sample_tenant["tenant"]
    tenant.settings = {
        **tenant.settings,
        "on_call_roster": [
            {
                "name": "Alex Tech",
                "phone": "+15551110001",
                "role": "Primary Tech",
                "priority": 1,
                "active_days": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
            },
            {
                "name": "Ben Backup",
                "phone": "+15551110002",
                "role": "Secondary Tech",
                "priority": 2,
                "active_days": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
            },
        ],
        "fallback_owner_phone": "+15559990000",
    }
    await db_session.commit()
    await db_session.refresh(tenant)

    form_data = {
        "CallSid": "CA_CASCADING_001",
        "From": "+15559876543",
        "To": "+15551234567",
        "SpeechResult": "Major emergency! Water pipe exploded in the basement, need someone now!",
    }

    response = await client.post(
        f"/api/v1/webhooks/twilio/voice/process?tenant_slug={tenant.slug}",
        data=form_data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    assert response.status_code == 200
    assert "xml" in response.headers.get("content-type", "").lower()
    text = response.text

    # Assert TwiML dialed primary tech with 15s timeout and dial-status callback step 1
    assert '<Dial timeout="15"' in text
    assert f'action="/api/v1/webhooks/twilio/voice/dial-status?tenant_slug={tenant.slug}&amp;step=1"' in text
    assert "<Number>+15551110001</Number>" in text


@pytest.mark.asyncio
async def test_cascading_voice_step1_unanswered_cascades_to_step2_backup(
    client: AsyncClient,
    sample_tenant: dict,
    db_session: AsyncSession,
):
    """Test step 1 no-answer cascades to step 2 backup tech."""
    tenant = sample_tenant["tenant"]
    tenant.settings = {
        **tenant.settings,
        "on_call_roster": [
            {
                "name": "Alex Tech",
                "phone": "+15551110001",
                "role": "Primary Tech",
                "priority": 1,
                "active_days": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
            },
            {
                "name": "Ben Backup",
                "phone": "+15551110002",
                "role": "Secondary Tech",
                "priority": 2,
                "active_days": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
            },
        ],
        "fallback_owner_phone": "+15559990000",
    }
    await db_session.commit()
    await db_session.refresh(tenant)

    form_data = {
        "CallSid": "CA_CASCADING_002",
        "From": "+15559876543",
        "DialCallStatus": "no-answer",
    }

    response = await client.post(
        f"/api/v1/webhooks/twilio/voice/dial-status?tenant_slug={tenant.slug}&step=1",
        data=form_data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    assert response.status_code == 200
    text = response.text

    assert "Connecting to backup emergency technician" in text
    assert '<Dial timeout="15"' in text
    assert f'action="/api/v1/webhooks/twilio/voice/dial-status?tenant_slug={tenant.slug}&amp;step=2"' in text
    assert "<Number>+15551110002</Number>" in text


@pytest.mark.asyncio
async def test_cascading_voice_step2_busy_cascades_to_step3_owner(
    client: AsyncClient,
    sample_tenant: dict,
    db_session: AsyncSession,
):
    """Test step 2 busy cascades to step 3 fallback owner phone."""
    tenant = sample_tenant["tenant"]
    tenant.settings = {
        **tenant.settings,
        "on_call_roster": [
            {
                "name": "Alex Tech",
                "phone": "+15551110001",
                "role": "Primary Tech",
                "priority": 1,
            },
            {
                "name": "Ben Backup",
                "phone": "+15551110002",
                "role": "Secondary Tech",
                "priority": 2,
            },
        ],
        "fallback_owner_phone": "+15559990000",
    }
    await db_session.commit()
    await db_session.refresh(tenant)

    form_data = {
        "CallSid": "CA_CASCADING_003",
        "From": "+15559876543",
        "DialCallStatus": "busy",
    }

    response = await client.post(
        f"/api/v1/webhooks/twilio/voice/dial-status?tenant_slug={tenant.slug}&step=2",
        data=form_data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    assert response.status_code == 200
    text = response.text

    assert "Escalating to our operations manager" in text
    assert '<Dial timeout="15"' in text
    assert f'action="/api/v1/webhooks/twilio/voice/dial-status?tenant_slug={tenant.slug}&amp;step=3"' in text
    assert "<Number>+15559990000</Number>" in text


@pytest.mark.asyncio
async def test_cascading_voice_step3_all_fail_drops_voicemail_and_blasts_sms(
    client: AsyncClient,
    sample_tenant: dict,
    db_session: AsyncSession,
):
    """Test all cascading steps failed: drops emergency voicemail and blasts priority SMS."""
    tenant = sample_tenant["tenant"]
    tenant.settings = {
        **tenant.settings,
        "on_call_roster": [
            {
                "name": "Alex Tech",
                "phone": "+15551110001",
                "role": "Primary Tech",
                "priority": 1,
            },
        ],
        "fallback_owner_phone": "+15559990000",
    }
    await db_session.commit()
    await db_session.refresh(tenant)

    form_data = {
        "CallSid": "CA_CASCADING_004",
        "From": "+15559876543",
        "DialCallStatus": "failed",
    }

    with patch("app.api.v1.webhooks.broadcast_unanswered_emergency_sms", new_callable=AsyncMock) as mock_broadcast:
        response = await client.post(
            f"/api/v1/webhooks/twilio/voice/dial-status?tenant_slug={tenant.slug}&step=3",
            data=form_data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

        assert response.status_code == 200
        text = response.text

        # Verify voicemail prompt and record verb
        assert "All emergency technicians are currently responding to active jobs" in text
        assert "<Record maxLength=" in text

        # Verify broadcast task added
        mock_broadcast.assert_called_once_with(tenant, "+15559876543")


@pytest.mark.asyncio
async def test_cascading_voice_answered_call_hangs_up(
    client: AsyncClient,
    sample_tenant: dict,
):
    """Test when call is successfully answered, dial-status hangs up cleanly."""
    tenant = sample_tenant["tenant"]
    form_data = {
        "CallSid": "CA_CASCADING_005",
        "From": "+15559876543",
        "DialCallStatus": "completed",
    }

    response = await client.post(
        f"/api/v1/webhooks/twilio/voice/dial-status?tenant_slug={tenant.slug}&step=1",
        data=form_data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    assert response.status_code == 200
    text = response.text
    assert "<Response><Hangup/></Response>" in text or "<Hangup/>" in text
