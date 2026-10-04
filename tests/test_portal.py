import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lead_action import LeadAction
from app.models.tenant import Tenant
from app.models.webhook_event import WebhookEvent


@pytest.mark.asyncio
async def test_portal_unauthorized_access_fails_401(client: AsyncClient, sample_tenant: dict):
    """Verify accessing /portal/{tenant_slug} without credentials returns 401 Unauthorized."""
    tenant = sample_tenant["tenant"]
    response = await client.get(f"/portal/{tenant.slug}")
    assert response.status_code == 401
    assert "detail" in response.json()


@pytest.mark.asyncio
async def test_portal_authenticated_access_renders_tenant_data(
    client: AsyncClient,
    sample_tenant: dict,
    db_session: AsyncSession,
):
    """Verify accessing /portal/{tenant_slug} with X-API-Key renders isolated tenant dashboard."""
    tenant = sample_tenant["tenant"]
    raw_api_key = sample_tenant["raw_api_key"]

    # Seed a LeadAction and WebhookEvent for this tenant
    event = WebhookEvent(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        source="twilio_voice",
        event_type="voice.received",
        idempotency_key=str(uuid.uuid4()),
        status="PROCESSED",
        payload={"channel": "voice", "From": "+15551239999", "SpeechResult": "Burst pipe flooding the kitchen!"},
    )
    db_session.add(event)
    await db_session.flush()

    action = LeadAction(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        webhook_event_id=event.id,
        lead_external_id="+15551239999",
        qualification_score=0.95,
        qualification_summary="Emergency flooding in residential kitchen.",
        action_type="DISPATCH_EMERGENCY_DISPATCH_QUEUE",
        dispatch_status="COMPLETED",
        crm_sync_status="SYNCED",
        metadata_payload={"channel": "voice", "speech_result": "Burst pipe flooding the kitchen!"},
    )
    db_session.add(action)
    await db_session.commit()

    response = await client.get(
        f"/portal/{tenant.slug}",
        headers={"X-API-Key": raw_api_key},
    )

    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")
    html = response.text

    # Verify tenant isolated branding & metrics
    assert tenant.name in html
    assert tenant.slug in html
    assert "Recovered Pipeline Value" in html
    assert "+15551239999" in html
    assert "EMERGENCY" in html
    assert "VOICE" in html


@pytest.mark.asyncio
async def test_portal_query_param_authentication(client: AsyncClient, sample_tenant: dict):
    """Verify ?api_key= query parameter authenticates successfully and sets session cookie."""
    tenant = sample_tenant["tenant"]
    raw_api_key = sample_tenant["raw_api_key"]

    response = await client.get(f"/portal/{tenant.slug}?api_key={raw_api_key}")
    assert response.status_code == 200
    assert tenant.name in response.text
    # Verify cookie was set
    assert "portal_token" in response.cookies


@pytest.mark.asyncio
async def test_portal_update_settings(
    client: AsyncClient,
    sample_tenant: dict,
    db_session: AsyncSession,
):
    """Verify POST /portal/{tenant_slug}/settings updates alert phone and notification preferences."""
    tenant = sample_tenant["tenant"]
    raw_api_key = sample_tenant["raw_api_key"]

    form_data = {
        "api_key": raw_api_key,
        "alert_phone_number": "+15559998888",
        "business_hours": "Mon-Fri 7am-7pm, 24/7 Emergency",
        "crm_provider": "servicetitan",
        "crm_webhook_url": "https://webhook.servicetitan.example.com/inbound",
        "avg_job_value": "4500",
        "sms_alerts_enabled": "true",
        "crm_forwarding_enabled": "true",
    }

    response = await client.post(
        f"/portal/{tenant.slug}/settings",
        data=form_data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        follow_redirects=False,
    )

    # Asserts 303 redirect back to portal
    assert response.status_code == 303
    assert f"/portal/{tenant.slug}?updated=true" in response.headers.get("location", "")

    # Verify settings persisted in DB
    query = select(Tenant).where(Tenant.id == tenant.id)
    updated_tenant = (await db_session.execute(query)).scalar_one()
    assert updated_tenant.settings.get("alert_phone_number") == "+15559998888"
    assert updated_tenant.settings.get("business_hours") == "Mon-Fri 7am-7pm, 24/7 Emergency"
    assert updated_tenant.settings.get("avg_job_value") == 4500.0
    assert updated_tenant.settings.get("crm", {}).get("provider") == "servicetitan"


@pytest.mark.asyncio
async def test_portal_weekly_roi_digest_endpoint(
    client: AsyncClient,
    sample_tenant: dict,
    db_session: AsyncSession,
):
    """Verify GET /api/v1/portal/{tenant_slug}/digest returns 7-day ROI analytics JSON & HTML."""
    tenant = sample_tenant["tenant"]

    # 1. JSON format
    res_json = await client.get(f"/api/v1/portal/{tenant.slug}/digest")
    assert res_json.status_code == 200
    data = res_json.json()
    assert data["tenant_slug"] == tenant.slug
    assert "pipeline_value_recovered" in data
    assert "emergencies_bridged" in data
    assert "email_html" in data

    # 2. HTML email format
    res_html = await client.get(f"/api/v1/portal/{tenant.slug}/digest?format=html")
    assert res_html.status_code == 200
    assert "text/html" in res_html.headers.get("content-type", "")
    assert "Weekly Performance Digest" in res_html.text
    assert tenant.name in res_html.text
