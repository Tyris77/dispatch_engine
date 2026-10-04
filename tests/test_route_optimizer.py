import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lead_action import LeadAction
from app.models.tenant import Tenant
from app.schemas.route_optimizer import (
    DailyFleetOptimizationReport,
    OptimizedRouteStop,
    TechnicianDailyRoute,
)
from app.services.route_optimizer import route_optimizer_service


@pytest.fixture
async def route_test_data(sample_tenant: dict, db_session: AsyncSession) -> dict:
    """Fixture providing tenant with active technicians and scheduled LeadActions with addresses."""
    tenant = sample_tenant["tenant"]
    tenant.name = "Apex Precision Fleet Services LLC"
    tenant.settings = {
        "shop_address": "4000 Commercial Center Dr, Austin, TX 78744",
        "on_call_roster": [
            {"name": "Marcus Vance", "truck_id": "TRUCK-01", "phone": "+15551112233", "trade": "HVAC"},
            {"name": "Dave Miller", "truck_id": "TRUCK-02", "phone": "+15552223344", "trade": "Plumbing"},
        ],
    }
    db_session.add(tenant)

    # Lead 1: South corridor stop
    action1 = LeadAction(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        lead_external_id="+15553334444",
        qualification_score=0.95,
        qualification_summary="Emergency burst commercial water riser flooding mechanical room.",
        action_type="EMERGENCY_DISPATCH",
        dispatch_status="COMPLETED",
        crm_sync_status="SYNCED",
        metadata_payload={
            "customer_name": "Travis County Center",
            "address": "700 Lavaca St, Austin, TX 78701",
            "service_needed": "Emergency Riser Repair",
        },
    )

    # Lead 2: North corridor stop
    action2 = LeadAction(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        lead_external_id="+15554445555",
        qualification_score=0.88,
        qualification_summary="Comprehensive commercial HVAC inspection.",
        action_type="DISPATCH_ROUTED",
        dispatch_status="CONFIRMED",
        crm_sync_status="SYNCED",
        metadata_payload={
            "customer_name": "Austin Tech Ridge Office",
            "address": "11200 Metric Blvd, Austin, TX 78758",
            "service_needed": "HVAC Chiller Diagnostic",
        },
    )

    # Lead 3: Central corridor stop
    action3 = LeadAction(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        lead_external_id="+15555556666",
        qualification_score=0.85,
        qualification_summary="Residential heat pump diagnostic.",
        action_type="DISPATCH_ROUTED",
        dispatch_status="PENDING",
        crm_sync_status="SYNCED",
        metadata_payload={
            "customer_name": "Eleanor Vance",
            "address": "1402 Oak Grove Ln, Austin, TX 78704",
            "service_needed": "Heat Pump Diagnostic",
        },
    )

    db_session.add_all([action1, action2, action3])
    await db_session.commit()
    await db_session.refresh(action1)
    await db_session.refresh(action2)
    await db_session.refresh(action3)

    return {"tenant": tenant, "actions": [action1, action2, action3]}


def test_route_optimizer_schemas():
    """Verify serialization and validation of route optimizer schemas."""
    stop = OptimizedRouteStop(
        stop_order=1,
        action_id="act-12345",
        customer_name="Eleanor Vance",
        address="1402 Oak Grove Ln, Austin, TX 78704",
        scheduled_time="08:30 AM",
        service_type="Emergency Compressor Diagnostic",
        estimated_duration_min=60,
        nav_link="https://www.google.com/maps/dir/?api=1&destination=1402+Oak+Grove+Ln",
        status="SCHEDULED",
    )
    assert stop.stop_order == 1
    assert stop.customer_name == "Eleanor Vance"
    assert stop.estimated_duration_min == 60
    assert "google.com/maps" in stop.nav_link

    tech_route = TechnicianDailyRoute(
        tech_name="Marcus Vance",
        truck_id="TRUCK-01",
        phone="+15551112233",
        corridor_zone="North / Central Corridor",
        stops=[stop],
        total_miles=18.4,
        total_drive_time_minutes=42,
        fuel_saved_dollars=12.50,
    )
    assert tech_route.tech_name == "Marcus Vance"
    assert tech_route.truck_id == "TRUCK-01"
    assert len(tech_route.stops) == 1
    assert tech_route.fuel_saved_dollars == 12.50

    report = DailyFleetOptimizationReport(
        date="2026-10-04",
        tenant_slug="apex-fleet",
        tenant_name="Apex Precision Fleet Services LLC",
        total_stops=1,
        total_fleet_miles=18.4,
        total_fuel_saved_dollars=12.50,
        routes_by_tech=[tech_route],
    )
    assert report.total_stops == 1
    assert report.total_fleet_miles == 18.4
    assert len(report.routes_by_tech) == 1


@pytest.mark.asyncio
async def test_route_optimizer_service_clustering_and_persistence(
    route_test_data: dict,
    db_session: AsyncSession,
):
    """Verify route optimizer clusters stops, sequences waypoints, and persists route_stop_data on LeadAction."""
    tenant = route_test_data["tenant"]
    action1 = route_test_data["actions"][0]

    report = await route_optimizer_service.optimize_daily_fleet_routes(
        tenant=tenant,
        target_date="2026-10-04",
        db=db_session,
        dispatch_sms=False,
    )

    assert report.date == "2026-10-04"
    assert report.tenant_slug == tenant.slug
    assert report.total_stops >= 3
    assert len(report.routes_by_tech) == 2
    assert report.total_fleet_miles > 0.0
    assert report.total_fuel_saved_dollars > 0.0

    # Verify technician daily routes
    tech_names = [r.tech_name for r in report.routes_by_tech]
    assert "Marcus Vance" in tech_names
    assert "Dave Miller" in tech_names

    for r in report.routes_by_tech:
        assert len(r.stops) > 0
        for s in r.stops:
            assert s.stop_order >= 1
            assert s.scheduled_time
            assert "google.com/maps" in s.nav_link

    # Verify route_stop_data was persisted to action1
    await db_session.refresh(action1)
    assert action1.route_stop_data is not None
    assert "assigned_technician" in action1.route_stop_data
    assert "truck_id" in action1.route_stop_data
    assert "stop_order" in action1.route_stop_data
    assert "nav_link" in action1.route_stop_data


@pytest.mark.asyncio
async def test_route_optimizer_sms_dispatch_simulation(
    route_test_data: dict,
    db_session: AsyncSession,
):
    """Verify SMS dispatch simulation executes without errors."""
    tenant = route_test_data["tenant"]

    report = await route_optimizer_service.optimize_daily_fleet_routes(
        tenant=tenant,
        target_date="2026-10-04",
        db=db_session,
        dispatch_sms=True,
    )
    assert report.total_stops >= 3
    assert len(report.routes_by_tech) == 2


@pytest.mark.asyncio
async def test_route_optimizer_html_view(
    client: AsyncClient,
    route_test_data: dict,
    db_session: AsyncSession,
):
    """Verify GET /fleet/routes/{tenant_slug} renders HTML fleet console."""
    tenant = route_test_data["tenant"]

    response = await client.get(f"/fleet/routes/{tenant.slug}")
    assert response.status_code == 200
    html = response.text
    assert "Multi-Vehicle Fleet Route Optimizer" in html
    assert "Marcus Vance" in html
    assert "Dave Miller" in html
    assert "Re-Optimize Routes" in html
    assert "Dispatch Fleet SMS" in html


@pytest.mark.asyncio
async def test_route_optimizer_json_format_override(
    client: AsyncClient,
    route_test_data: dict,
    db_session: AsyncSession,
):
    """Verify GET /fleet/routes/{tenant_slug}?format=json returns valid JSON report."""
    tenant = route_test_data["tenant"]

    response = await client.get(f"/fleet/routes/{tenant.slug}?format=json")
    assert response.status_code == 200
    data = response.json()
    assert data["tenant_slug"] == tenant.slug
    assert "total_stops" in data
    assert "routes_by_tech" in data
    assert len(data["routes_by_tech"]) == 2


@pytest.mark.asyncio
async def test_route_optimizer_post_optimize_endpoint(
    client: AsyncClient,
    route_test_data: dict,
    db_session: AsyncSession,
):
    """Verify POST /api/v1/fleet/routes/optimize executes optimization and returns report."""
    tenant = route_test_data["tenant"]

    response = await client.post(
        "/api/v1/fleet/routes/optimize",
        json={
            "tenant_slug": tenant.slug,
            "target_date": "2026-10-05",
            "dispatch_sms": False,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["date"] == "2026-10-05"
    assert data["tenant_slug"] == tenant.slug
    assert data["total_stops"] >= 3
    assert len(data["routes_by_tech"]) == 2


@pytest.mark.asyncio
async def test_route_optimizer_api_get_endpoint(
    client: AsyncClient,
    route_test_data: dict,
    db_session: AsyncSession,
):
    """Verify GET /api/v1/fleet/routes/{tenant_slug} returns report directly."""
    tenant = route_test_data["tenant"]

    response = await client.get(f"/api/v1/fleet/routes/{tenant.slug}")
    assert response.status_code == 200
    data = response.json()
    assert data["tenant_slug"] == tenant.slug
    assert len(data["routes_by_tech"]) == 2


@pytest.mark.asyncio
async def test_route_optimizer_tenant_not_found(
    client: AsyncClient,
    db_session: AsyncSession,
):
    """Verify 404 response for nonexistent tenant slug."""
    response = await client.get("/fleet/routes/nonexistent-tenant-slug")
    assert response.status_code == 404
