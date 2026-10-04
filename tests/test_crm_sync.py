import uuid
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lead_action import LeadAction
from app.models.tenant import Tenant
from app.services.crm_sync import (
    crm_sync_service,
    format_generic_webhook_payload,
    format_hubspot_payload,
    format_jobber_payload,
    format_servicetitan_payload,
    sync_lead_to_external_crm,
)


@pytest.fixture
def mock_lead_action(sample_tenant: dict) -> LeadAction:
    tenant = sample_tenant["tenant"]
    return LeadAction(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        lead_external_id="+15559876543",
        qualification_score=0.92,
        qualification_summary="Major commercial pipeline rupture requiring immediate heavy extraction equipment.",
        action_type="DISPATCH_EMERGENCY_DISPATCH_QUEUE",
        dispatch_status="COMPLETED",
        crm_sync_status="PENDING",
        metadata_payload={
            "channel": "voice",
            "speech_result": "Emergency! Our main line broke and water is pouring into the warehouse!",
            "qualification": {
                "intent_level": "EMERGENCY",
                "pain_points": ["Flooding in warehouse", "Equipment danger"],
                "qualification_score": 0.92,
            },
        },
    )


def test_crm_sync_jobber_formatting(sample_tenant: dict, mock_lead_action: LeadAction):
    """Verify Jobber webhook payload adheres to client/request/custom_fields schema."""
    tenant = sample_tenant["tenant"]
    payload = format_jobber_payload(mock_lead_action, tenant)

    assert "client" in payload
    assert payload["client"]["phones"][0]["number"] == "+15559876543"
    assert "request" in payload
    assert payload["request"]["urgency"] == "EMERGENCY"
    assert "custom_fields" in payload
    assert payload["custom_fields"]["gemini_qualification_score"] == 0.92
    assert payload["custom_fields"]["channel"] == "voice"


def test_crm_sync_servicetitan_formatting(sample_tenant: dict, mock_lead_action: LeadAction):
    """Verify ServiceTitan payload adheres to customer/job schema with critical priority."""
    tenant = sample_tenant["tenant"]
    payload = format_servicetitan_payload(mock_lead_action, tenant)

    assert "customer" in payload
    assert payload["customer"]["phoneNumber"] == "+15559876543"
    assert "job" in payload
    assert payload["job"]["jobType"] == "Emergency Dispatch"
    assert payload["job"]["priority"] == "Critical"
    assert "DispatchEngine AI" in payload["job"]["source"]


def test_crm_sync_hubspot_formatting(sample_tenant: dict, mock_lead_action: LeadAction):
    """Verify HubSpot payload formats properties correctly for CRM deal/contact creation."""
    tenant = sample_tenant["tenant"]
    payload = format_hubspot_payload(mock_lead_action, tenant)

    assert "properties" in payload
    props = payload["properties"]
    assert props["phone"] == "+15559876543"
    assert props["lifecyclestage"] == "lead"
    assert props["hs_lead_status"] == "NEW"
    assert props["urgency_rating"] == "EMERGENCY"
    assert props["gemini_score"] == "0.92"


@pytest.mark.asyncio
async def test_crm_sync_simulated_fallback(sample_tenant: dict, mock_lead_action: LeadAction, db_session: AsyncSession):
    """Verify that when no external destination webhook is configured, sync falls back to simulation and marks SYNCED."""
    tenant = sample_tenant["tenant"]
    tenant.settings = {**tenant.settings, "crm": {"provider": "jobber"}}

    result = await sync_lead_to_external_crm(mock_lead_action, tenant, db=db_session)

    assert result["success"] is True
    assert result["status"] == "SIMULATED"
    assert result["provider"] == "jobber"
    assert mock_lead_action.crm_sync_status == "SYNCED"


@pytest.mark.asyncio
async def test_crm_sync_service_backward_compatibility(sample_tenant: dict, mock_lead_action: LeadAction, db_session: AsyncSession):
    """Verify crm_sync_service.sync_lead method continues to work seamlessly."""
    tenant = sample_tenant["tenant"]
    success = await crm_sync_service.sync_lead(tenant, mock_lead_action, db=db_session)
    assert success is True
    assert mock_lead_action.crm_sync_status == "SYNCED"
