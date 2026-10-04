import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lead_action import LeadAction
from app.models.tenant import Tenant
from app.schemas.lead import IntentLevel


@pytest.mark.asyncio
async def test_get_widget_js_renders_successfully(client: AsyncClient, sample_tenant: dict):
    """Verify GET /api/v1/widget/{slug}.js returns dynamically configured JavaScript."""
    tenant = sample_tenant["tenant"]
    response = await client.get(f"/api/v1/widget/{tenant.slug}.js")

    assert response.status_code == 200
    assert "application/javascript" in response.headers["content-type"]
    js_text = response.text

    assert "window.__DISPATCH_WIDGET_INITIALIZED__" in js_text
    assert f'var TENANT_SLUG = "{tenant.slug}";' in js_text
    assert f'var TENANT_NAME = "{tenant.name}";' in js_text
    assert "dispatch-widget-root" in js_text
    assert "dispatch-widget-bubble" in js_text
    assert "1-Tap Emergency Call" in js_text
    assert "Snap Photo for Quote" in js_text


@pytest.mark.asyncio
async def test_get_widget_js_invalid_tenant(client: AsyncClient):
    """Verify 404 response when querying widget JavaScript for unknown tenant."""
    response = await client.get("/api/v1/widget/unknown-nonexistent-tenant.js")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_widget_chat_endpoint_routine_inquiry(client: AsyncClient, sample_tenant: dict, db_session: AsyncSession):
    """Verify POST /api/v1/widget/{slug}/chat processes routine inquiry and stores lead."""
    tenant = sample_tenant["tenant"]

    chat_payload = {
        "message": "Hi, I need an estimate for routine seasonal AC maintenance.",
        "sender_name": "Sarah Connor",
        "sender_phone": "+15551234567",
    }

    response = await client.post(f"/api/v1/widget/{tenant.slug}/chat", json=chat_payload)
    assert response.status_code == 200

    data = response.json()
    assert "response_text" in data
    assert data["intent_level"] in ["MEDIUM", "LOW", "NORMAL"]
    assert data["action_id"] is not None
    assert data["intake_url"] is not None
    assert f"/intake/{data['action_id']}" in data["intake_url"]
    assert data["is_emergency"] is False

    # Check database persistence
    action_uuid = uuid.UUID(data["action_id"])
    query = select(LeadAction).where(LeadAction.id == action_uuid)
    lead_action = (await db_session.execute(query)).scalar_one_or_none()

    assert lead_action is not None
    assert lead_action.tenant_id == tenant.id
    assert lead_action.lead_external_id == "+15551234567"
    assert lead_action.metadata_payload.get("channel") == "widget_chat"
    assert lead_action.tracking_data is not None
    assert lead_action.tracking_data.get("technician") is not None


@pytest.mark.asyncio
async def test_widget_chat_emergency_returns_tracking_url(client: AsyncClient, sample_tenant: dict, db_session: AsyncSession):
    """Verify emergency message triggers emergency qualification, high priority, and live tracking link."""
    tenant = sample_tenant["tenant"]
    # Configure an on_call_roster for this tenant
    tenant.settings["on_call_roster"] = [
        {
            "name": "Carlos Gomez",
            "phone": "+15558889999",
            "role": "Lead Master Technician",
            "truck_number": "Truck #09",
            "priority": 1,
            "certifications": ["EPA Master", "NATE Core"],
        }
    ]
    tenant.settings["alert_phone_number"] = "+15558889999"
    await db_session.commit()

    chat_payload = {
        "message": "EMERGENCY: Gas smell and main water pipe burst in the basement, water everywhere!",
        "sender_phone": "+15559876543",
        "sender_name": "John Doe",
    }

    response = await client.post(f"/api/v1/widget/{tenant.slug}/chat", json=chat_payload)
    assert response.status_code == 200

    data = response.json()
    assert data["is_emergency"] is True
    assert data["intent_level"] in ["EMERGENCY", "HIGH"]
    assert data["tracking_url"] is not None
    assert f"/track/{data['action_id']}" in data["tracking_url"]

    # Verify technician was assigned in tracking_data
    action_uuid = uuid.UUID(data["action_id"])
    query = select(LeadAction).where(LeadAction.id == action_uuid)
    lead_action = (await db_session.execute(query)).scalar_one_or_none()

    assert lead_action is not None
    assert lead_action.tracking_data["status"] == "DISPATCHED"
    assert lead_action.tracking_data["technician"]["name"] == "Carlos Gomez"
    assert lead_action.tracking_data["technician"]["truck_number"] == "Truck #09"


@pytest.mark.asyncio
async def test_widget_demo_page_renders(client: AsyncClient, sample_tenant: dict):
    """Verify GET /widget-demo preview page renders contractor marketing demo with embedded script."""
    tenant = sample_tenant["tenant"]
    response = await client.get(f"/widget-demo?tenant_slug={tenant.slug}")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    html_text = response.text

    assert "Contractor Website Preview" in html_text
    assert tenant.name in html_text
    assert f'/api/v1/widget/{tenant.slug}.js' in html_text
    assert "Autonomous Dispatch Enabled" in html_text


@pytest.mark.asyncio
async def test_widget_lead_submission_fast_response(client: AsyncClient, sample_tenant: dict, db_session: AsyncSession):
    """Verify POST /api/v1/widget/lead qualifies inbound lead and returns structured response."""
    tenant = sample_tenant["tenant"]

    lead_payload = {
        "tenant_slug": tenant.slug,
        "name": "David Wallace",
        "phone": "+12025550177",
        "message": "Water heater is leaking actively and dripping through basement drywall.",
    }

    response = await client.post("/api/v1/widget/lead", json=lead_payload)
    assert response.status_code == 200
    data = response.json()

    assert data["action_id"] is not None
    assert data["intent_level"] in ["EMERGENCY", "HIGH", "MEDIUM"]
    assert data["qualification_score"] > 0.0
    assert "response_text" in data

