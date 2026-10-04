import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lead_action import LeadAction
from app.models.tenant import Tenant
from app.schemas.weather import WeatherAlert, WeatherBroadcastResponse
from app.services.weather_dispatch import weather_dispatch_service


@pytest.fixture
async def seeded_weather_tenant(sample_tenant: dict, db_session: AsyncSession) -> Tenant:
    """Fixture providing an active tenant with seeded leads for weather broadcast."""
    tenant = sample_tenant["tenant"]
    tenant.name = "Apex Climate & Emergency Pros"
    tenant.settings["phone"] = "+12025550199"
    db_session.add(tenant)

    # Seed past customer leads
    lead1 = LeadAction(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        lead_external_id="+12025550144",
        action_type="DISPATCH_EMERGENCY_DISPATCH_QUEUE",
        dispatch_status="RESOLVED",
        crm_sync_status="SYNCED",
        metadata_payload={"customer_name": "Eleanor Vance", "address": "Bethesda, MD"},
    )
    lead2 = LeadAction(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        lead_external_id="+12025550189",
        action_type="DISPATCH_EMERGENCY_DISPATCH_QUEUE",
        dispatch_status="RESOLVED",
        crm_sync_status="SYNCED",
        metadata_payload={"customer_name": "Marcus Vance", "address": "Fairfax, VA"},
    )
    db_session.add_all([lead1, lead2])
    await db_session.commit()
    await db_session.refresh(tenant)
    return tenant


def test_get_active_weather_alerts_service():
    """Verify weather service returns active meteorological alerts across trades."""
    alerts = weather_dispatch_service.get_active_weather_alerts()
    assert len(alerts) >= 3

    titles = [a.event_title for a in alerts]
    assert any("Freeze" in t for t in titles)
    assert any("Thunderstorm" in t or "Wind" in t for t in titles)
    assert any("Heat" in t for t in titles)

    freeze_alert = next(a for a in alerts if "Freeze" in a.event_title)
    assert freeze_alert.severity == "WARNING"
    assert freeze_alert.trade_category == "Plumbing"
    assert "14°F" in freeze_alert.metric_detail
    assert len(freeze_alert.affected_counties) > 0
    assert "faucets" in freeze_alert.safety_guidance.lower()


def test_generate_sms_body_trades(seeded_weather_tenant: Tenant):
    """Verify tailored SMS copy for each hazard type includes links and instructions."""
    alerts = weather_dispatch_service.get_active_weather_alerts()

    for alert in alerts:
        sms = weather_dispatch_service._generate_sms_body(
            tenant=seeded_weather_tenant,
            alert=alert,
            custom_note="Priority line open.",
        )
        assert seeded_weather_tenant.name in sms
        assert alert.metric_detail in sms
        assert "Priority line open." in sms
        assert "portal" in sms


@pytest.mark.asyncio
async def test_dispatch_proactive_weather_alert_service(
    seeded_weather_tenant: Tenant,
    db_session: AsyncSession,
):
    """Verify dispatch_proactive_weather_alert reaches seeded contacts and outputs broadcast response."""
    result = await weather_dispatch_service.dispatch_proactive_weather_alert(
        tenant=seeded_weather_tenant,
        alert_id="ALERT-2026-FREEZE-01",
        custom_note="Call immediately if pipes are exposed.",
        db=db_session,
    )

    assert isinstance(result, WeatherBroadcastResponse)
    assert result.alert_id == "ALERT-2026-FREEZE-01"
    assert result.trade_category == "Plumbing"
    assert result.recipients_contacted >= 2
    assert result.status in ["DISPATCHED", "SIMULATED"]
    assert "FREEZE ALERT" in result.sample_message
    assert "Call immediately if pipes are exposed." in result.sample_message


@pytest.mark.asyncio
async def test_api_get_weather_alerts_endpoint(
    client: AsyncClient,
    seeded_weather_tenant: Tenant,
):
    """Verify GET /api/v1/weather/alerts returns structured meteorological hazard alerts."""
    url = f"/api/v1/weather/alerts?tenant_slug={seeded_weather_tenant.slug}"
    response = await client.get(url)

    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 3

    validated = [WeatherAlert.model_validate(item) for item in data]
    assert all(isinstance(a, WeatherAlert) for a in validated)


@pytest.mark.asyncio
async def test_api_post_weather_broadcast_endpoint(
    client: AsyncClient,
    seeded_weather_tenant: Tenant,
):
    """Verify POST /api/v1/weather/broadcast initiates emergency SMS blast."""
    url = f"/api/v1/weather/broadcast?tenant_slug={seeded_weather_tenant.slug}"
    payload = {
        "alert_id": "ALERT-2026-WIND-02",
        "trade_category": "Roofing",
        "custom_note": "Emergency tarping team dispatched.",
    }
    response = await client.post(url, json=payload)

    assert response.status_code == 200
    data = response.json()
    resp_obj = WeatherBroadcastResponse.model_validate(data)
    assert resp_obj.alert_id == "ALERT-2026-WIND-02"
    assert resp_obj.trade_category == "Roofing"
    assert resp_obj.recipients_contacted >= 2
    assert "Emergency tarping team dispatched." in resp_obj.sample_message
