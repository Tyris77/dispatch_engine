import uuid
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from app.models.lead_action import LeadAction
from app.models.tenant import Tenant
from app.schemas.lead import IntentLevel
from app.services.dispatch import dispatch_service


@pytest.mark.asyncio
async def test_execute_dispatch_plan_sms_and_http_webhook():
    """Verify execute_dispatch_plan triggers outbound Twilio SMS and HTTP webhook when configured."""
    tenant = Tenant(
        id=uuid.uuid4(),
        name="Apex Emergency Ops",
        slug="apex-emergency",
        api_key_hash="hash123",
        webhook_secret="secret123",
        is_active=True,
        settings={
            "alert_phone_number": "+15559998888",
            "webhook_url": "https://api.external-crm.com/leads",
        },
    )

    lead_action = LeadAction(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        lead_external_id="+15550001234",
        qualification_score=0.95,
        qualification_summary="Emergency power failure reported.",
        action_type="DISPATCH_EMERGENCY_DISPATCH_QUEUE",
        dispatch_status="QUEUED",
        crm_sync_status="PENDING",
        metadata_payload={
            "qualification": {
                "intent_level": IntentLevel.EMERGENCY.value,
                "qualification_score": 0.95,
            },
        },
    )

    mock_msg = MagicMock()
    mock_msg.sid = "SM_MOCK_ALERT_SENT_777"

    mock_twilio_client = MagicMock()
    mock_twilio_client.messages.create.return_value = mock_msg

    mock_http_response = MagicMock()
    mock_http_response.status_code = 200
    mock_http_response.is_success = True

    with patch("app.services.dispatch.settings.TWILIO_ACCOUNT_SID", "AC_MOCK_123"):
        with patch("app.services.dispatch.settings.TWILIO_AUTH_TOKEN", "AUTH_MOCK_123"):
            with patch("twilio.rest.Client", return_value=mock_twilio_client):
                with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
                    mock_post.return_value = mock_http_response

                    result = await dispatch_service.execute_dispatch_plan(
                        lead_action=lead_action,
                        tenant=tenant,
                        lead_payload={"Body": "Power failure outage at facility", "From": "+15550001234"},
                    )

    assert result.dispatch_status == "COMPLETED"
    assert result.crm_sync_status == "SYNCED"
    assert result.metadata_payload.get("notifications", {}).get("twilio_sms_sid") == "SM_MOCK_ALERT_SENT_777"
    assert result.metadata_payload.get("dispatch_http", {}).get("status_code") == 200
    mock_twilio_client.messages.create.assert_called_once()
    mock_post.assert_called_once()
