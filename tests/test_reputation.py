from unittest.mock import AsyncMock, patch
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lead_action import LeadAction
from app.models.tenant import Tenant
from app.models.webhook_event import WebhookEvent
from app.services.reputation import (
    extract_rating_and_feedback,
    reputation_service,
)


def test_extract_rating_and_feedback():
    """Verify regex and parsing of numeric ratings and customer feedback."""
    # Simple digits
    assert extract_rating_and_feedback("5") == (5, "")
    assert extract_rating_and_feedback("1") == (1, "")

    # Rating with words
    rating, fb = extract_rating_and_feedback("5 stars! Fast and professional service")
    assert rating == 5
    assert "Fast and professional service" in fb

    # Rating with dash
    rating, fb = extract_rating_and_feedback("1 - AC stopped working an hour after tech left")
    assert rating == 1
    assert "AC stopped working" in fb

    # Rating out of 5
    rating, fb = extract_rating_and_feedback("4 out of 5 stars. Good overall")
    assert rating == 4
    assert "Good overall" in fb

    # Invalid / non-rating messages
    assert extract_rating_and_feedback("Hello can someone come tomorrow?") is None
    assert extract_rating_and_feedback("Is this HVAC emergency?") is None


@pytest.mark.asyncio
async def test_trigger_post_job_review_request(
    sample_tenant: dict,
    db_session: AsyncSession,
):
    """Test triggering post-job review request SMS and updating lead review_data."""
    tenant = sample_tenant["tenant"]
    action = LeadAction(
        tenant_id=tenant.id,
        webhook_event_id=None,
        lead_external_id="+15554443333",
        action_type="SMS_BOOKING_LINK",
        dispatch_status="COMPLETED",
        qualification_score=0.9,
        qualification_summary="Emergency water burst repair",
        metadata_payload={"customer_name": "Marcus Vance"},
    )
    db_session.add(action)
    await db_session.commit()
    await db_session.refresh(action)

    with patch.object(reputation_service, "_send_sms", new_callable=AsyncMock) as mock_sms:
        result = await reputation_service.trigger_post_job_review_request(action, tenant, db_session)

        assert result["status"] == "PROMPTED"
        assert result["customer_phone"] == "+15554443333"

        # Verify SMS text sent
        mock_sms.assert_called_once()
        sms_text = mock_sms.call_args.kwargs.get("message_body") or (mock_sms.call_args[0][1] if len(mock_sms.call_args[0]) > 1 else "")
        assert "Marcus Vance" in sms_text
        assert tenant.name in sms_text
        assert "rate your experience from 1 to 5 stars" in sms_text

        # Verify LeadAction DB record
        await db_session.refresh(action)
        assert action.review_data is not None
        assert action.review_data["status"] == "PROMPTED"
        assert "prompted_at" in action.review_data


@pytest.mark.asyncio
async def test_process_review_reply_positive_5_star_boost(
    sample_tenant: dict,
    db_session: AsyncSession,
):
    """Test 5-star positive review sends Google profile link and records BOOST_SENT."""
    tenant = sample_tenant["tenant"]
    tenant.settings = {
        **tenant.settings,
        "google_review_url": "https://g.page/r/apex-air/review",
    }
    await db_session.commit()
    await db_session.refresh(tenant)

    action = LeadAction(
        tenant_id=tenant.id,
        webhook_event_id=None,
        lead_external_id="+15554443333",
        action_type="SMS_BOOKING_LINK",
        dispatch_status="COMPLETED",
        review_data={"status": "PROMPTED"},
        metadata_payload={"customer_name": "Marcus Vance"},
    )
    db_session.add(action)
    await db_session.commit()
    await db_session.refresh(action)

    with patch.object(reputation_service, "_send_sms", new_callable=AsyncMock) as mock_sms:
        outcome = await reputation_service.process_review_reply(
            rating=5,
            feedback="Technician was polite, super quick!",
            lead=action,
            tenant=tenant,
            db_session=db_session,
        )

        assert outcome.status == "BOOST_SENT"
        assert "https://g.page/r/apex-air/review" in outcome.customer_reply
        assert outcome.owner_alert is None

        # Check DB update
        await db_session.refresh(action)
        assert action.review_data["outcome_status"] == "BOOST_SENT"
        assert action.review_data["rating"] == 5
        assert action.review_data["feedback"] == "Technician was polite, super quick!"


@pytest.mark.asyncio
async def test_process_review_reply_negative_shield_and_owner_alert(
    sample_tenant: dict,
    db_session: AsyncSession,
):
    """Test 1-3 star review activates insulation shield: sends apology and alerts owner."""
    tenant = sample_tenant["tenant"]
    owner_phone = "+15559990000"
    tenant.settings = {
        **tenant.settings,
        "fallback_owner_phone": owner_phone,
    }
    await db_session.commit()
    await db_session.refresh(tenant)

    action = LeadAction(
        tenant_id=tenant.id,
        webhook_event_id=None,
        lead_external_id="+15554443333",
        action_type="SMS_BOOKING_LINK",
        dispatch_status="COMPLETED",
        review_data={"status": "PROMPTED"},
        metadata_payload={"customer_name": "Dave Miller"},
    )
    db_session.add(action)
    await db_session.commit()
    await db_session.refresh(action)

    with patch.object(reputation_service, "_send_sms", new_callable=AsyncMock) as mock_sms:
        outcome = await reputation_service.process_review_reply(
            rating=2,
            feedback="Arrived 2 hours late and didn't clean up",
            lead=action,
            tenant=tenant,
            db_session=db_session,
        )

        assert outcome.status == "NEGATIVE_INSULATED"
        assert "We're so sorry to hear that" in outcome.customer_reply
        assert "owner's personal phone" in outcome.customer_reply
        assert outcome.owner_alert is not None
        assert "⚠️ NEGATIVE FEEDBACK ALERT" in outcome.owner_alert
        assert "Rated 2/5 stars" in outcome.owner_alert
        assert "Dave Miller" in outcome.owner_alert

        # Verify SMS called twice: once for customer apology, once for owner alert
        assert mock_sms.call_count == 2
        recipients = [call.kwargs.get("to_phone") or call.args[0] for call in mock_sms.call_args_list]
        assert "+15554443333" in recipients
        assert owner_phone in recipients

        # Verify DB review_data
        await db_session.refresh(action)
        assert action.review_data["outcome_status"] == "NEGATIVE_INSULATED"
        assert action.review_data["rating"] == 2


@pytest.mark.asyncio
async def test_api_trigger_review_endpoint(
    client: AsyncClient,
    sample_tenant: dict,
    db_session: AsyncSession,
):
    """Test POST /api/v1/reputation/trigger/{action_id} endpoint."""
    tenant = sample_tenant["tenant"]
    action = LeadAction(
        tenant_id=tenant.id,
        webhook_event_id=None,
        lead_external_id="+15557778888",
        action_type="SMS_BOOKING_LINK",
        dispatch_status="COMPLETED",
        metadata_payload={"customer_name": "Elena Rostova"},
    )
    db_session.add(action)
    await db_session.commit()
    await db_session.refresh(action)

    with patch.object(reputation_service, "_send_sms", new_callable=AsyncMock):
        response = await client.post(f"/api/v1/reputation/trigger/{action.id}")
        assert response.status_code == 200
        data = response.json()
        assert data["action_id"] == str(action.id)
        assert data["status"] == "PROMPTED"
        assert data["customer_phone"] == "+15557778888"


@pytest.mark.asyncio
async def test_inbound_sms_webhook_intercepts_review_rating(
    client: AsyncClient,
    sample_tenant: dict,
    db_session: AsyncSession,
):
    """Test inbound Twilio SMS with numeric rating intercepts and executes review workflow."""
    tenant = sample_tenant["tenant"]
    tenant.settings = {
        **tenant.settings,
        "google_review_url": "https://g.page/r/apex-air/review",
    }
    await db_session.commit()
    await db_session.refresh(tenant)

    # Lead with active review prompt
    action = LeadAction(
        tenant_id=tenant.id,
        webhook_event_id=None,
        lead_external_id="+15556667777",
        action_type="SMS_BOOKING_LINK",
        dispatch_status="COMPLETED",
        review_data={"status": "PROMPTED", "customer_phone": "+15556667777"},
        metadata_payload={"customer_name": "Samantha Jones"},
    )
    db_session.add(action)
    await db_session.commit()
    await db_session.refresh(action)

    form_data = {
        "MessageSid": "SM_REVIEW_REPLY_001",
        "From": "+15556667777",
        "To": "+15550001111",
        "Body": "5 - Outstanding service! Heater was fixed instantly.",
    }

    response = await client.post(
        f"/api/v1/webhooks/twilio/sms?tenant_slug={tenant.slug}",
        data=form_data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    assert response.status_code == 200
    assert "xml" in response.headers.get("content-type", "").lower()
    text = response.text

    # Assert TwiML response contains thank you and google review URL
    assert "<Message>" in text
    assert "https://g.page/r/apex-air/review" in text

    # Verify DB update
    await db_session.refresh(action)
    assert action.review_data["outcome_status"] == "BOOST_SENT"
    assert action.review_data["rating"] == 5
    assert "Outstanding service" in action.review_data["feedback"]


@pytest.mark.asyncio
async def test_inbound_sms_webhook_intercepts_negative_review_rating(
    client: AsyncClient,
    sample_tenant: dict,
    db_session: AsyncSession,
):
    """Test inbound Twilio SMS with 1-star negative rating triggers insulation shield."""
    tenant = sample_tenant["tenant"]
    owner_phone = "+15559990000"
    tenant.settings = {
        **tenant.settings,
        "fallback_owner_phone": owner_phone,
    }
    await db_session.commit()
    await db_session.refresh(tenant)

    # Lead with active review prompt
    action = LeadAction(
        tenant_id=tenant.id,
        webhook_event_id=None,
        lead_external_id="+15556668888",
        action_type="SMS_BOOKING_LINK",
        dispatch_status="COMPLETED",
        review_data={"status": "PROMPTED", "customer_phone": "+15556668888"},
        metadata_payload={"customer_name": "Robert Paulson"},
    )
    db_session.add(action)
    await db_session.commit()
    await db_session.refresh(action)

    form_data = {
        "MessageSid": "SM_REVIEW_REPLY_002",
        "From": "+15556668888",
        "To": "+15550001111",
        "Body": "1 - System is still leaking everywhere!",
    }

    with patch.object(reputation_service, "_send_sms", new_callable=AsyncMock) as mock_sms:
        response = await client.post(
            f"/api/v1/webhooks/twilio/sms?tenant_slug={tenant.slug}",
            data=form_data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

        assert response.status_code == 200
        text = response.text

        # Verify customer received apology message in TwiML
        assert "We're so sorry to hear that" in text
        assert "owner's personal phone" in text

        # Verify owner received SMS alert
        mock_sms.assert_called_once()
        called_to = mock_sms.call_args.kwargs.get("to_phone") or (mock_sms.call_args[0][0] if mock_sms.call_args[0] else "")
        called_body = mock_sms.call_args.kwargs.get("message_body") or (mock_sms.call_args[0][1] if len(mock_sms.call_args[0]) > 1 else "")
        assert called_to == owner_phone
        assert "⚠️ NEGATIVE FEEDBACK ALERT" in called_body

        # Verify DB update
        await db_session.refresh(action)
        assert action.review_data["outcome_status"] == "NEGATIVE_INSULATED"
        assert action.review_data["rating"] == 1
