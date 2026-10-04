import uuid
from unittest.mock import MagicMock, patch
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lead_action import LeadAction
from app.models.tenant import Tenant
from app.schemas.lead import IntentLevel
from app.services.dispatch import dispatch_service


@pytest.fixture
async def seeded_lead_action(sample_tenant: dict, db_session: AsyncSession) -> LeadAction:
    """Fixture providing a seeded LeadAction with diagnostic and tracking info."""
    tenant = sample_tenant["tenant"]

    action = LeadAction(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        lead_external_id="+15554443333",
        qualification_score=0.92,
        qualification_summary="Emergency air conditioning failure in extreme heat.",
        action_type="DISPATCH_EMERGENCY_DISPATCH_QUEUE",
        dispatch_status="QUEUED",
        crm_sync_status="PENDING",
        metadata_payload={
            "qualification": {
                "intent_level": IntentLevel.EMERGENCY.value,
                "qualification_score": 0.92,
            },
        },
        diagnostic_data={
            "equipment_type": "HVAC Condenser",
            "brand_manufacturer": "Carrier",
            "model_number": "24ABB336A003",
            "serial_number": "1420E12345",
            "detected_materials": ["Copper", "Aluminum Fins"],
            "damage_assessment": "Blown dual run capacitor and seized fan motor.",
            "recommended_parts_tools": ["45/5 MFD 440V Capacitor", "1/3 HP Condenser Fan Motor"],
            "confidence_score": 0.94,
        },
        tracking_data={
            "status": "EN_ROUTE",
            "eta_minutes": 15,
            "technician": {
                "name": "Marcus Vance",
                "phone": "+15557778888",
                "role": "Lead HVAC Specialist",
                "truck_number": "Truck #22",
                "certifications": ["EPA Universal", "NATE Certified Master"],
                "rating": 4.99,
            },
            "notes": ["Gate code is #7788 from previous service"],
        },
    )
    db_session.add(action)
    await db_session.commit()
    await db_session.refresh(action)
    return action


@pytest.mark.asyncio
async def test_get_track_view_html(client: AsyncClient, seeded_lead_action: LeadAction, sample_tenant: dict):
    """Verify GET /track/{action_id} renders mobile-first arrival tracker with tech info and equipment parts."""
    tenant = sample_tenant["tenant"]
    response = await client.get(f"/track/{seeded_lead_action.id}")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    html_text = response.text

    # Technician verification
    assert "Marcus Vance" in html_text
    assert "Lead HVAC Specialist" in html_text
    assert "Truck #22" in html_text
    assert "EPA Universal" in html_text

    # Equipment verification
    assert "Carrier" in html_text
    assert "HVAC Condenser" in html_text
    assert "45/5 MFD 440V Capacitor" in html_text
    assert "Blown dual run capacitor" in html_text

    # Status stepper and ETA
    assert "En Route" in html_text
    assert "Live GPS ETA Window" in html_text
    assert "Gate code is #7788" in html_text


@pytest.mark.asyncio
async def test_get_track_view_json(client: AsyncClient, seeded_lead_action: LeadAction, sample_tenant: dict):
    """Verify GET /track/{action_id} with JSON accept header returns structured tracking data."""
    response = await client.get(
        f"/track/{seeded_lead_action.id}",
        headers={"Accept": "application/json"},
    )

    assert response.status_code == 200
    data = response.json()

    assert data["action_id"] == str(seeded_lead_action.id)
    assert data["status"] == "EN_ROUTE"
    assert data["eta_minutes"] == 15
    assert data["technician"]["name"] == "Marcus Vance"
    assert data["technician"]["truck_number"] == "Truck #22"
    assert data["equipment_brand"] == "Carrier"
    assert "45/5 MFD 440V Capacitor" in data["parts_packed"]
    assert "Gate code is #7788 from previous service" in data["notes"]


@pytest.mark.asyncio
async def test_get_track_view_not_found(client: AsyncClient):
    """Verify 404 response when querying invalid action ID."""
    random_id = uuid.uuid4()
    response = await client.get(f"/track/{random_id}")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_post_track_notes_form_redirects_and_sends_sms(
    client: AsyncClient,
    seeded_lead_action: LeadAction,
    db_session: AsyncSession,
):
    """Verify submitting gate code via form updates lead record, texts tech, and redirects."""
    form_data = {
        "notes": "Gate code is #4921. Beware of the friendly labrador in the yard.",
        "sender_name": "Dave Miller",
    }

    response = await client.post(
        f"/track/{seeded_lead_action.id}/notes",
        data=form_data,
        follow_redirects=False,
    )

    # Must redirect back to track view with note_added=1
    assert response.status_code == 303
    assert f"/track/{seeded_lead_action.id}?note_added=1" in response.headers["location"]

    # Verify note persisted in database
    await db_session.refresh(seeded_lead_action)
    notes_list = seeded_lead_action.tracking_data.get("notes", [])
    assert any("Gate code is #4921" in n for n in notes_list)
    assert any("Dave Miller" in n for n in notes_list)
    assert seeded_lead_action.metadata_payload.get("notifications", {}).get("entry_notes_sms_sent") is True


@pytest.mark.asyncio
async def test_post_track_notes_json_mode(
    client: AsyncClient,
    seeded_lead_action: LeadAction,
    db_session: AsyncSession,
):
    """Verify submitting notes via JSON body returns 200 with note payload."""
    payload = {
        "notes": "Dial 044 on call box for elevator access.",
        "sender_name": "Resident",
    }

    response = await client.post(
        f"/track/{seeded_lead_action.id}/notes",
        json=payload,
    )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "Dial 044 on call box" in data["note"]
    assert data["action_id"] == str(seeded_lead_action.id)


@pytest.mark.asyncio
async def test_update_tracking_status_endpoint(
    client: AsyncClient,
    seeded_lead_action: LeadAction,
    db_session: AsyncSession,
):
    """Verify POST /track/{action_id}/status advances technician dispatch stepper."""
    payload = {
        "status": "ON_SITE",
        "eta_minutes": 0,
    }

    response = await client.post(
        f"/track/{seeded_lead_action.id}/status",
        json=payload,
    )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["status"] == "ON_SITE"
    assert data["eta_minutes"] == 0

    # Verify DB update
    await db_session.refresh(seeded_lead_action)
    assert seeded_lead_action.tracking_data["status"] == "ON_SITE"
    assert seeded_lead_action.tracking_data["eta_minutes"] == 0


@pytest.mark.asyncio
async def test_dispatch_notification_contains_tracking_link(sample_tenant: dict):
    """Verify emergency dispatch SMS automatically appends the live tracking link."""
    tenant = sample_tenant["tenant"]
    tenant.settings["alert_phone_number"] = "+15559990000"
    tenant.settings["base_url"] = "https://dispatch.apexops.com"

    lead_action = LeadAction(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        lead_external_id="+15551112222",
        qualification_score=0.98,
        qualification_summary="Major flooding reported in utility closet.",
        action_type="DISPATCH_EMERGENCY_DISPATCH_QUEUE",
        dispatch_status="QUEUED",
        crm_sync_status="PENDING",
        metadata_payload={
            "qualification": {
                "intent_level": IntentLevel.EMERGENCY.value,
                "qualification_score": 0.98,
            },
        },
    )

    mock_msg = MagicMock()
    mock_msg.sid = "SM_TRACKING_TEST_123"

    mock_twilio_client = MagicMock()
    mock_twilio_client.messages.create.return_value = mock_msg

    with patch("app.services.dispatch.settings.TWILIO_ACCOUNT_SID", "AC_MOCK"):
        with patch("app.services.dispatch.settings.TWILIO_AUTH_TOKEN", "AUTH_MOCK"):
            with patch("twilio.rest.Client", return_value=mock_twilio_client):
                result = await dispatch_service.execute_dispatch_plan(
                    lead_action=lead_action,
                    tenant=tenant,
                )

    mock_twilio_client.messages.create.assert_called_once()
    call_kwargs = mock_twilio_client.messages.create.call_args.kwargs
    sms_body = call_kwargs["body"]

    expected_tracking_link = f"https://dispatch.apexops.com/track/{lead_action.id}"
    assert f"Track your technician's arrival live: {expected_tracking_link}" in sms_body
    assert result.metadata_payload.get("notifications", {}).get("tracking_url") == expected_tracking_link
