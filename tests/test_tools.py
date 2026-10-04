import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tenant import Tenant
from app.schemas.tools import ToolAuditReport, ToolAuditResponse, ToolItem, TruckToolRegistry
from app.services.tools import (
    audit_truck_tools,
    fallback_truck_tool_audit,
    tools_service,
)


def test_tool_item_and_registry_schemas():
    """Verify tool asset and truck registry schema validations."""
    item = ToolItem(
        tool_name="Fieldpiece SMAN480V Digital Manifold",
        brand="Fieldpiece",
        category="Diagnostic Gauge",
        estimated_value=680.0,
    )
    assert item.tool_name == "Fieldpiece SMAN480V Digital Manifold"
    assert item.estimated_value == 680.0

    registry = TruckToolRegistry(
        truck_id="VAN-09",
        driver_name="Elena Vance",
        trade_type="HVAC",
        required_tools=[item],
    )
    assert registry.truck_id == "VAN-09"
    assert len(registry.required_tools) == 1
    assert registry.compliance_status == "ACTIVE"


def test_fallback_truck_tool_audit_pass():
    """Verify clean tool audit detects all assets and reports 100% compliance."""
    tools = [
        ToolItem(tool_name="RIDGID RP 351 ProPress", brand="RIDGID", category="Press Tool", estimated_value=3850.0),
        ToolItem(tool_name="RIDGID SeeSnake Camera", brand="RIDGID", category="Inspection Camera", estimated_value=4200.0),
    ]
    report = fallback_truck_tool_audit(required_tools=tools, truck_id="VAN-02", force_missing=False)

    assert isinstance(report, ToolAuditReport)
    assert report.truck_id == "VAN-02"
    assert report.status == "PASS"
    assert report.audit_score == 100.0
    assert report.replacement_cost_at_risk == 0.0
    assert len(report.missing_tools) == 0
    assert len(report.verified_tools) == 2


def test_fallback_truck_tool_audit_missing_assets():
    """Verify missing asset conditions calculate replacement risk and flag MISSING_ASSETS."""
    tools = [
        ToolItem(tool_name="Milwaukee M18 Drill Kit", brand="Milwaukee", category="Power Tool", estimated_value=399.0),
        ToolItem(tool_name="Fluke 87V Multimeter", brand="Fluke", category="Diagnostic Meter", estimated_value=560.0),
    ]
    report = fallback_truck_tool_audit(required_tools=tools, truck_id="VAN-01", force_missing=True)

    assert report.status == "MISSING_ASSETS"
    assert report.audit_score == 50.0
    assert report.replacement_cost_at_risk == 560.0
    assert len(report.missing_tools) == 1
    assert report.missing_tools[0].tool_name == "Fluke 87V Multimeter"


@pytest.mark.asyncio
async def test_tool_tracker_service_registry_and_recording(sample_tenant: dict, db_session: AsyncSession):
    """Verify ToolTrackerService provides default fleet and persists audit history to tenant settings."""
    tenant = sample_tenant["tenant"]
    trucks = tools_service.get_truck_registry(tenant)

    assert len(trucks) >= 3
    van_ids = [t.truck_id for t in trucks]
    assert "VAN-01" in van_ids
    assert "VAN-02" in van_ids

    # Run audit and record
    sample_tools = trucks[0].required_tools
    report = fallback_truck_tool_audit(required_tools=sample_tools, truck_id="VAN-01")
    tools_service.record_audit(tenant, report)

    assert "tool_audits" in tenant.settings
    assert len(tenant.settings["tool_audits"]) >= 1
    assert tenant.settings["tool_audits"][0]["truck_id"] == "VAN-01"

    history = tools_service.get_audit_history(tenant, truck_id="VAN-01")
    assert len(history) >= 1
    assert history[0].truck_id == "VAN-01"


@pytest.mark.asyncio
async def test_get_tools_portal_html(sample_tenant: dict, client: AsyncClient):
    """Verify GET /tools/{tenant_slug} renders fleet tool portal view."""
    tenant = sample_tenant["tenant"]
    response = await client.get(f"/tools/{tenant.slug}")

    assert response.status_code == 200
    html = response.text
    assert "Van Tool & Equipment Asset Scanner" in html or "Fleet Tool" in html
    assert tenant.name in html
    assert "Mandatory Tool Inventory" in html


@pytest.mark.asyncio
async def test_get_tools_portal_json_format(sample_tenant: dict, client: AsyncClient):
    """Verify GET /tools/{tenant_slug}?format=json returns fleet trucks and audits JSON."""
    tenant = sample_tenant["tenant"]
    response = await client.get(f"/tools/{tenant.slug}?format=json")

    assert response.status_code == 200
    data = response.json()
    assert "trucks" in data
    assert "audits" in data
    assert len(data["trucks"]) >= 3


@pytest.mark.asyncio
async def test_get_tools_portal_not_found(client: AsyncClient):
    """Verify 404 response for unknown tenant slug."""
    response = await client.get("/tools/non-existent-contractor-999")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_post_tools_portal_audit_redirect(sample_tenant: dict, client: AsyncClient):
    """Verify POST /tools/{tenant_slug}/audit processes photo upload and redirects."""
    tenant = sample_tenant["tenant"]
    dummy_jpg = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xdb\x00C\x00"

    response = await client.post(
        f"/tools/{tenant.slug}/audit",
        files={"tool_photo": ("van_rack.jpg", dummy_jpg, "image/jpeg")},
        data={"truck_id": "VAN-01"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert f"/tools/{tenant.slug}" in response.headers["location"]


@pytest.mark.asyncio
async def test_post_tools_portal_audit_empty_file_rejected(sample_tenant: dict, client: AsyncClient):
    """Verify empty image upload is rejected with 400 Bad Request."""
    tenant = sample_tenant["tenant"]
    response = await client.post(
        f"/tools/{tenant.slug}/audit",
        files={"tool_photo": ("empty.jpg", b"", "image/jpeg")},
        data={"truck_id": "VAN-01"},
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_api_audit_tools_endpoint(sample_tenant: dict, client: AsyncClient):
    """Verify POST /api/v1/tools/audit returns ToolAuditResponse JSON."""
    tenant = sample_tenant["tenant"]
    dummy_jpg = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xdb\x00C\x00"

    response = await client.post(
        "/api/v1/tools/audit",
        files={"tool_photo": ("van_shelf.jpg", dummy_jpg, "image/jpeg")},
        data={"truck_id": "VAN-01", "tenant_slug": tenant.slug},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "SUCCESS"
    assert "report" in data
    assert data["report"]["truck_id"] == "VAN-01"
    assert "audit_score" in data["report"]


@pytest.mark.asyncio
async def test_api_get_tool_registry_endpoint(sample_tenant: dict, client: AsyncClient):
    """Verify GET /api/v1/tools/{tenant_slug} returns list of fleet truck registries."""
    tenant = sample_tenant["tenant"]
    response = await client.get(f"/api/v1/tools/{tenant.slug}")

    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 3
    assert data[0]["truck_id"].startswith("VAN-")
