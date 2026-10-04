import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lead_action import LeadAction
from app.models.tenant import Tenant
from app.schemas.map import MapDataResponse, MapLeadFeature


def test_map_schemas():
    """Verify MapLeadFeature and MapDataResponse validate correctly."""
    feature = MapLeadFeature(
        id=str(uuid.uuid4()),
        action_id=str(uuid.uuid4()),
        tenant_name="Apex HVAC",
        tenant_slug="apex-hvac",
        caller="John Doe (+15551234567)",
        lat=32.7767,
        lng=-96.7970,
        urgency="EMERGENCY",
        status="ACTIVE",
        status_label="🔴 Emergency Dispatch Active",
        equipment_type="HVAC Condenser",
        equipment_brand="Carrier",
        damage="Blown capacitor and burning odor",
        marker_type="emergency",
        tracking_url="/track/123",
        intake_url="/intake/123",
        proposal_url="/proposal/123",
        created_at="2026-10-03 14:00 UTC",
    )
    assert feature.marker_type == "emergency"
    assert feature.lat == 32.7767

    response = MapDataResponse(
        center=[32.7767, -96.7970],
        zoom=11,
        total_active=1,
        features=[feature],
    )
    assert response.total_active == 1
    assert len(response.features) == 1


@pytest.mark.asyncio
async def test_get_map_data_endpoint(
    client: AsyncClient,
    db_session: AsyncSession,
    sample_tenant: dict,
):
    """Verify GET /api/v1/events/map-data returns valid GeoJSON-compatible response."""
    tenant: Tenant = sample_tenant["tenant"]

    # 1. Emergency action
    action_emergency = LeadAction(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        lead_external_id="+15551110001",
        action_type="DISPATCH_EMERGENCY",
        qualification_score=0.95,
        dispatch_status="CONFIRMED",
        crm_sync_status="PENDING",
        metadata_payload={"caller_name": "Emergency Caller", "caller_phone": "+15551110001"},
        diagnostic_data={
            "equipment_type": "Water Heater",
            "brand_manufacturer": "Rheem",
            "damage_assessment": "Burst tank flooding garage floor",
        },
    )

    # 2. Routine action
    action_routine = LeadAction(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        lead_external_id="+15551110002",
        action_type="DISPATCH_ROUTED",
        qualification_score=0.5,
        dispatch_status="QUEUED",
        crm_sync_status="PENDING",
        metadata_payload={"caller_phone": "+15551110002"},
        diagnostic_data={
            "equipment_type": "HVAC Filter",
            "damage_assessment": "Routine seasonal tune-up",
        },
    )

    # 3. Completed / Signed action
    action_completed = LeadAction(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        lead_external_id="+15551110003",
        action_type="CONTRACT_SIGNED",
        dispatch_status="CONFIRMED",
        crm_sync_status="SYNCED",
        metadata_payload={"caller_name": "Signed Customer", "status": "COMPLETED"},
        signed_contract={"selected_tier": "Standard Replacement", "contract_status": "SIGNED"},
    )

    db_session.add_all([action_emergency, action_routine, action_completed])
    await db_session.commit()

    response = await client.get("/api/v1/events/map-data")
    assert response.status_code == 200
    data = response.json()
    assert "center" in data
    assert "zoom" in data
    assert data["total_active"] >= 3

    features = {f["action_id"]: f for f in data["features"]}

    # Check emergency pin classification
    em_pin = features[str(action_emergency.id)]
    assert em_pin["marker_type"] == "emergency"
    assert "Emergency" in em_pin["status_label"]
    assert em_pin["equipment_brand"] == "Rheem"
    assert em_pin["tracking_url"] == f"/track/{action_emergency.id}"

    # Check routine pin classification
    ro_pin = features[str(action_routine.id)]
    assert ro_pin["marker_type"] == "routine"

    # Check completed pin classification
    comp_pin = features[str(action_completed.id)]
    assert comp_pin["marker_type"] == "completed"
    assert "Signed" in comp_pin["status_label"]


@pytest.mark.asyncio
async def test_get_map_data_filtered_by_tenant_slug(
    client: AsyncClient,
    db_session: AsyncSession,
    sample_tenant: dict,
):
    """Verify GET /api/v1/events/map-data?tenant_slug=... filters features to only that tenant."""
    tenant: Tenant = sample_tenant["tenant"]

    # Other tenant
    other_tenant = Tenant(
        id=uuid.uuid4(),
        name="Other Trades Inc",
        slug="other-trades-inc",
        api_key_hash="fakehash",
        webhook_secret="whsec_other_test",
        is_active=True,
        settings={},
    )
    db_session.add(other_tenant)
    await db_session.flush()

    my_action = LeadAction(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        lead_external_id="+15550001111",
        action_type="DISPATCH_ROUTED",
        dispatch_status="QUEUED",
        crm_sync_status="PENDING",
        metadata_payload={},
    )
    other_action = LeadAction(
        id=uuid.uuid4(),
        tenant_id=other_tenant.id,
        lead_external_id="+15550002222",
        action_type="DISPATCH_ROUTED",
        dispatch_status="QUEUED",
        crm_sync_status="PENDING",
        metadata_payload={},
    )
    db_session.add_all([my_action, other_action])
    await db_session.commit()

    # Query with tenant slug filter
    response = await client.get(f"/api/v1/events/map-data?tenant_slug={tenant.slug}")
    assert response.status_code == 200
    data = response.json()
    action_ids = [f["action_id"] for f in data["features"]]
    assert str(my_action.id) in action_ids
    assert str(other_action.id) not in action_ids


@pytest.mark.asyncio
async def test_dashboard_and_portal_include_fleet_map_elements(
    client: AsyncClient,
    db_session: AsyncSession,
    sample_tenant: dict,
):
    """Verify Dashboard and Client Portal HTML contain the #fleet-map container and Leaflet assets."""
    tenant: Tenant = sample_tenant["tenant"]
    api_key: str = sample_tenant["raw_api_key"]

    # 1. Dashboard
    dash_res = await client.get("/dashboard")
    assert dash_res.status_code == 200
    assert 'id="fleet-map"' in dash_res.text
    assert "leaflet.css" in dash_res.text
    assert "leaflet.js" in dash_res.text
    assert "Interactive Fleet &amp; Territory Dispatch Map" in dash_res.text or "Interactive Fleet & Territory Dispatch Map" in dash_res.text

    # 2. Client Portal
    portal_res = await client.get(f"/portal/{tenant.slug}?api_key={api_key}")
    assert portal_res.status_code == 200
    assert 'id="fleet-map"' in portal_res.text
    assert "leaflet.css" in portal_res.text
    assert "leaflet.js" in portal_res.text
    assert "Interactive Territory &amp; Fleet Dispatch Map" in portal_res.text or "Interactive Territory & Fleet Dispatch Map" in portal_res.text
