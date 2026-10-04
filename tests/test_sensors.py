import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lead_action import LeadAction
from app.models.tenant import Tenant
from app.schemas.sensors import (
    ConnectedSensorDevice,
    SensorAlertPayload,
    SensorAlertResponse,
)
from app.services.sensors import sensors_service


def test_sensor_schemas():
    """Verify validation and serialization of Smart IoT sensor schemas."""
    payload = SensorAlertPayload(
        sensor_id="SN-WL-9021",
        sensor_type="WATER_LEAK_DETECTOR",
        property_address="742 Evergreen Terr, Springfield, VA",
        customer_name="Homer Simpson",
        customer_phone="+17035550199",
        reading_value="9.4 GPM continuous flow",
        severity="CRITICAL_EMERGENCY",
        water_shutoff_actuated=True,
    )
    assert payload.sensor_id == "SN-WL-9021"
    assert payload.sensor_type == "WATER_LEAK_DETECTOR"
    assert payload.severity == "CRITICAL_EMERGENCY"
    assert payload.water_shutoff_actuated is True

    device = ConnectedSensorDevice(
        sensor_id="SN-DEV-001",
        sensor_type="FREEZE_TEMP_SENSOR",
        brand_model="Honeywell Lyric WiFi Freeze Detector",
        property_name="Penthouse Suite",
        property_address="1401 S Joyce St, Arlington, VA",
        current_reading="68.2°F ambient",
        battery_level=98,
        status="ONLINE_NORMAL",
    )
    assert device.battery_level == 98
    assert device.status == "ONLINE_NORMAL"

    response = SensorAlertResponse(
        action_id="act-1234",
        dispatch_status="DISPATCHED",
        call_triggered=True,
        tech_alerted="Marcus Vance (Master Plumber)",
        message="Emergency sensor alert triaged successfully",
    )
    assert response.call_triggered is True
    assert response.tech_alerted.startswith("Marcus")


@pytest.mark.asyncio
async def test_process_iot_sensor_alert_critical(db_session: AsyncSession):
    """Verify critical water leak IoT alert creates emergency LeadAction and cascades dispatch."""
    tenant = Tenant(
        id=uuid.uuid4(),
        name="Rapid Restoration & Plumbing",
        slug=f"rapid-{uuid.uuid4().hex[:6]}",
        api_key_hash="hash",
        webhook_secret="secret",
        is_active=True,
        settings={"base_url": "http://testserver"},
    )
    db_session.add(tenant)
    await db_session.commit()

    payload = SensorAlertPayload(
        sensor_id="SN-BURST-101",
        sensor_type="FLOW_BURST_ALARM",
        property_address="1600 Pennsylvania Ave NW, Washington, DC",
        customer_name="Operations HQ",
        customer_phone="+12025550100",
        reading_value="14.8 GPM high volume burst",
        severity="CRITICAL_EMERGENCY",
        water_shutoff_actuated=True,
    )

    resp = await sensors_service.process_iot_sensor_alert(payload, tenant, db_session)
    assert resp.action_id is not None
    assert resp.dispatch_status == "DISPATCHED"
    assert resp.call_triggered is True
    assert "Marcus Vance" in resp.tech_alerted

    # Query LeadAction in DB
    action_uuid = uuid.UUID(resp.action_id)
    action = await db_session.get(LeadAction, action_uuid)
    assert action is not None
    assert action.action_type == "EMERGENCY_DISPATCH"
    assert action.metadata_payload.get("source") == "iot_sensor"
    assert action.sensor_data is not None
    assert action.sensor_data.get("sensor_id") == "SN-BURST-101"
    assert action.sensor_data.get("reading_value") == "14.8 GPM high volume burst"
    assert action.sensor_data.get("homeowner_call_triggered") is True


@pytest.mark.asyncio
async def test_process_iot_sensor_alert_warning(db_session: AsyncSession):
    """Verify warning alert sets appropriate metadata and triage records."""
    tenant = Tenant(
        id=uuid.uuid4(),
        name="Apex Climate Control",
        slug=f"apex-{uuid.uuid4().hex[:6]}",
        api_key_hash="hash",
        webhook_secret="secret",
        is_active=True,
        settings={"base_url": "http://testserver"},
    )
    db_session.add(tenant)
    await db_session.commit()

    payload = SensorAlertPayload(
        sensor_id="SN-FZ-44",
        sensor_type="FREEZE_TEMP_SENSOR",
        property_address="4500 Wisconsin Ave NW, Washington, DC",
        customer_name="Sarah Connor",
        customer_phone="+12025550177",
        reading_value="31.8°F sub-freezing warning",
        severity="WARNING",
    )

    resp = await sensors_service.process_iot_sensor_alert(payload, tenant, db_session)
    assert resp.action_id is not None
    assert resp.dispatch_status == "DISPATCHED"
    assert resp.call_triggered is True

    action = await db_session.get(LeadAction, uuid.UUID(resp.action_id))
    assert action is not None
    assert action.action_type == "EMERGENCY_DISPATCH"
    assert action.metadata_payload.get("source") == "iot_sensor"
    assert action.metadata_payload.get("severity") == "WARNING"


def test_get_connected_fleet_telemetry():
    """Verify fleet sensor telemetry device catalog retrieval."""
    tenant = Tenant(
        id=uuid.uuid4(),
        name="Telemetry Pro",
        slug=f"telemetry-{uuid.uuid4().hex[:6]}",
        api_key_hash="hash",
        webhook_secret="secret",
        is_active=True,
    )

    devices = sensors_service.get_connected_fleet_telemetry(tenant)
    assert len(devices) >= 4
    device_types = [d.sensor_type for d in devices]
    assert "WATER_LEAK_DETECTOR" in device_types
    assert "FREEZE_TEMP_SENSOR" in device_types
    assert "FLOW_BURST_ALARM" in device_types


@pytest.mark.asyncio
async def test_sensor_alert_api_webhook(client: AsyncClient, sample_tenant: dict):
    """Verify POST /api/v1/sensors/alert processes JSON payload successfully."""
    tenant = sample_tenant["tenant"]
    payload = {
        "tenant_id": str(tenant.id),
        "sensor_id": "SN-REST-8812",
        "sensor_type": "WATER_LEAK_DETECTOR",
        "property_address": "8200 Greensboro Dr, McLean, VA",
        "customer_name": "Tysons Tech Park",
        "customer_phone": "+17035550198",
        "reading_value": "Moisture detected under main riser",
        "severity": "CRITICAL_EMERGENCY",
        "water_shutoff_actuated": True,
    }

    res = await client.post("/api/v1/sensors/alert", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["dispatch_status"] == "DISPATCHED"
    assert data["call_triggered"] is True
    assert "action_id" in data


@pytest.mark.asyncio
async def test_sensor_monitor_console_view(client: AsyncClient, sample_tenant: dict):
    """Verify GET /sensors/{tenant_slug} renders the interactive IoT monitor console."""
    tenant = sample_tenant["tenant"]
    res = await client.get(f"/sensors/{tenant.slug}")
    assert res.status_code == 200
    html = res.text
    assert "Smart Property IoT Sensor Console" in html
    assert "Connected Property Sensor Fleet" in html
    assert "Test Instant IoT Dispatch Cascades" in html
    assert tenant.name in html


@pytest.mark.asyncio
async def test_sensor_monitor_console_not_found(client: AsyncClient):
    """Verify GET /sensors/{tenant_slug} returns 404 for unknown tenant slug."""
    res = await client.get("/sensors/unknown-tenant-999")
    assert res.status_code == 404
