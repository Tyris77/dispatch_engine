import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lead_action import LeadAction
from app.models.webhook_event import WebhookEvent


@pytest.mark.asyncio
async def test_dashboard_renders_successfully(client: AsyncClient, sample_tenant: dict):
    """Verify GET /dashboard returns 200 OK and renders HTML with table, metrics, and simulator."""
    response = await client.get("/dashboard")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")

    html = response.text
    # Verify core layout elements
    assert "DispatchEngine" in html
    assert "Total Ingested Events" in html
    assert "High & Emergency Leads" in html
    assert "Live Qualification & Dispatch Stream" in html
    assert "Inbound Lead Simulator" in html
    assert "Tenant Twilio Adapter Config" in html
    assert "Inbound Twilio SMS Webhook URL" in html


@pytest.mark.asyncio
async def test_root_landing_page_renders_headline_and_cta(client: AsyncClient):
    """Verify that root GET / returns 200 OK and contains hero headline and CTA elements."""
    response = await client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")
    assert "Never Lose a" in response.text
    assert "Activate Now" in response.text
    assert "/dashboard" in response.text
    assert "/docs" in response.text


@pytest.mark.asyncio
async def test_dashboard_with_tenant_filter(client: AsyncClient, sample_tenant: dict):
    """Verify GET /dashboard?tenant_slug={slug} renders with tenant-specific context."""
    tenant = sample_tenant["tenant"]
    response = await client.get(f"/dashboard?tenant_slug={tenant.slug}")
    assert response.status_code == 200
    assert tenant.slug in response.text


@pytest.mark.asyncio
async def test_simulator_processes_lead_and_redirects(
    client: AsyncClient,
    sample_tenant: dict,
    db_session: AsyncSession,
):
    """Verify POST /api/v1/simulator/simulate-lead processes inbound text and redirects to dashboard."""
    tenant = sample_tenant["tenant"]
    form_data = {
        "tenant_slug": tenant.slug,
        "sender_phone": "+15554443333",
        "message_body": "Critical emergency: power outage at main depot, need immediate dispatch assistance!",
    }

    response = await client.post(
        "/api/v1/simulator/simulate-lead",
        data=form_data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        follow_redirects=False,
    )

    # Should redirect (303 See Other) to /dashboard
    assert response.status_code == 303
    assert "/dashboard" in response.headers.get("location", "")

    # Verify event recorded in DB
    query_event = select(WebhookEvent).where(WebhookEvent.source == "simulator")
    events = (await db_session.execute(query_event)).scalars().all()
    assert len(events) >= 1
    assert any(e.payload.get("From") == "+15554443333" for e in events)

    # Verify action recorded in DB
    query_action = select(LeadAction).where(LeadAction.lead_external_id == "+15554443333")
    action = (await db_session.execute(query_action)).scalar_one_or_none()
    assert action is not None
    assert action.dispatch_status == "COMPLETED"


@pytest.mark.asyncio
async def test_simulator_json_mode(client: AsyncClient, sample_tenant: dict):
    """Verify POST /api/v1/simulator/simulate-lead supports API clients returning JSON."""
    tenant = sample_tenant["tenant"]
    json_payload = {
        "tenant_slug": tenant.slug,
        "sender_phone": "+15557778888",
        "message_body": "We need a $30,000 enterprise deployment proposal for next quarter.",
    }

    response = await client.post(
        "/api/v1/simulator/simulate-lead",
        json=json_payload,
        headers={"Accept": "application/json"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "qualification" in data
    assert data["qualification"]["is_qualified"] is True
    assert "lead_action_id" in data
