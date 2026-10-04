import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tenant import Tenant
from app.schemas.tech_mentor import (
    DiagnosticTroubleshootGuide,
    DiagnosticTroubleshootRequest,
)
from app.services.tech_mentor import tech_mentor_service


@pytest.fixture
async def mentor_test_tenant(sample_tenant: dict, db_session: AsyncSession) -> Tenant:
    tenant = sample_tenant["tenant"]
    tenant.name = "Apex Precision Commercial Services LLC"
    db_session.add(tenant)
    await db_session.commit()
    await db_session.refresh(tenant)
    return tenant


def test_tech_mentor_schemas():
    """Verify validation and serialization of tech mentor diagnostic schemas."""
    req = DiagnosticTroubleshootRequest(
        equipment_brand="Carrier",
        equipment_type="Gas Furnace",
        fault_code_or_symptom="Code 31",
        technician_notes="Draft motor running but burners do not light",
    )
    assert req.equipment_brand == "Carrier"
    assert req.fault_code_or_symptom == "Code 31"

    guide = DiagnosticTroubleshootGuide(
        equipment_context="Carrier Inducing Draft Furnace",
        probable_root_causes=["Blocked condensate trap", "Vent restriction"],
        step_by_step_test_procedure=["Step 1: Check drain trap", "Step 2: Measure draft"],
        multimeter_readings_expected={"Draft": ">= -0.65 in. W.C."},
        common_replacement_parts=["Pressure Switch HK06WC024"],
        safety_warnings=["120V shock hazard"],
    )
    assert len(guide.probable_root_causes) == 2
    assert len(guide.step_by_step_test_procedure) == 2
    assert "Draft" in guide.multimeter_readings_expected


@pytest.mark.asyncio
async def test_carrier_code_31_troubleshooting():
    """Verify Carrier Code 31 matches pressure switch and draft inducer procedures."""
    req = DiagnosticTroubleshootRequest(
        equipment_brand="Carrier",
        equipment_type="Gas Furnace",
        fault_code_or_symptom="Code 31 Pressure Switch Open",
    )
    guide = await tech_mentor_service.troubleshoot_equipment_fault(req)

    assert "Carrier" in guide.equipment_context
    assert any("pressure switch" in c.lower() or "condensate" in c.lower() for c in guide.probable_root_causes)
    assert len(guide.step_by_step_test_procedure) >= 4
    assert any("manometer" in s.lower() or "voltage" in s.lower() for s in guide.step_by_step_test_procedure)
    assert "Draft Manometer Target" in guide.multimeter_readings_expected
    assert len(guide.common_replacement_parts) > 0
    assert len(guide.safety_warnings) > 0


@pytest.mark.asyncio
async def test_carrier_code_13_flame_rectification_troubleshooting():
    """Verify Carrier Code 13 matches flame sensor microamp testing."""
    req = DiagnosticTroubleshootRequest(
        equipment_brand="Carrier",
        equipment_type="Gas Furnace",
        fault_code_or_symptom="Code 13 Ignition Lockout Flame Sensor",
    )
    guide = await tech_mentor_service.troubleshoot_equipment_fault(req)

    assert any("flame" in c.lower() or "igniter" in c.lower() for c in guide.probable_root_causes)
    assert "Flame Sensor Rectification" in guide.multimeter_readings_expected
    assert "Hot Surface Igniter Resistance" in guide.multimeter_readings_expected


@pytest.mark.asyncio
async def test_trane_flashes_troubleshooting():
    """Verify Trane blinking diagnostic LED codes."""
    req = DiagnosticTroubleshootRequest(
        equipment_brand="Trane",
        equipment_type="Gas Furnace",
        fault_code_or_symptom="3 Flashes High Limit Switch Open",
    )
    guide = await tech_mentor_service.troubleshoot_equipment_fault(req)

    assert "Trane" in guide.equipment_context
    assert any("limit" in c.lower() or "switch" in c.lower() for c in guide.probable_root_causes)
    assert len(guide.multimeter_readings_expected) > 0


@pytest.mark.asyncio
async def test_navien_tankless_troubleshooting():
    """Verify Navien E003 dynamic gas pressure and ignition procedures."""
    req = DiagnosticTroubleshootRequest(
        equipment_brand="Navien",
        equipment_type="Tankless Water Heater",
        fault_code_or_symptom="Error E003 Ignition Failure",
    )
    guide = await tech_mentor_service.troubleshoot_equipment_fault(req)

    assert "Navien" in guide.equipment_context
    assert any("gas" in c.lower() or "electrode" in c.lower() for c in guide.probable_root_causes)
    assert "Inlet Dynamic Gas Pressure" in guide.multimeter_readings_expected
    assert "Flame Sensor Current" in guide.multimeter_readings_expected


@pytest.mark.asyncio
async def test_heat_pump_e1_troubleshooting():
    """Verify Mini-Split / Heat Pump high pressure error E1."""
    req = DiagnosticTroubleshootRequest(
        equipment_brand="Daikin",
        equipment_type="Heat Pump",
        fault_code_or_symptom="Error E1 High Pressure Protection",
    )
    guide = await tech_mentor_service.troubleshoot_equipment_fault(req)

    assert "Heat Pump" in guide.equipment_context
    assert any("coil" in c.lower() or "fan" in c.lower() or "pressure" in c.lower() for c in guide.probable_root_causes)
    assert "Thermistor Sensor Resistance" in guide.multimeter_readings_expected
    assert "Inverter DC Bus Voltage" in guide.multimeter_readings_expected


@pytest.mark.asyncio
async def test_universal_fallback_troubleshooting():
    """Verify unrecognized equipment falls back to universal field isolation protocol."""
    req = DiagnosticTroubleshootRequest(
        equipment_brand="Custom Brand X",
        equipment_type="Custom Industrial Machine",
        fault_code_or_symptom="Strange humming noise and intermittent shutdown",
    )
    guide = await tech_mentor_service.troubleshoot_equipment_fault(req)

    assert "Universal" in guide.equipment_context
    assert len(guide.step_by_step_test_procedure) >= 4
    assert "Primary Line Voltage" in guide.multimeter_readings_expected


@pytest.mark.asyncio
async def test_get_tech_mentor_html_view(
    client: AsyncClient,
    mentor_test_tenant: Tenant,
    db_session: AsyncSession,
):
    """Verify GET /tech-mentor/{tenant_slug} renders mobile technician portal."""
    response = await client.get(f"/tech-mentor/{mentor_test_tenant.slug}")
    assert response.status_code == 200
    html = response.text
    assert "Field Tech AI Mentor" in html
    assert mentor_test_tenant.name in html
    assert "Equipment Brand &amp; Fault Code" in html
    assert "Get Diagnostic Guide" in html
    assert "Target Multimeter Test Readings" in html


@pytest.mark.asyncio
async def test_get_tech_mentor_tenant_not_found(
    client: AsyncClient,
    db_session: AsyncSession,
):
    """Verify 404 response for nonexistent tenant slug."""
    response = await client.get("/tech-mentor/nonexistent-tenant-slug")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_post_tech_mentor_troubleshoot_api(
    client: AsyncClient,
    db_session: AsyncSession,
):
    """Verify POST /api/v1/tech-mentor/troubleshoot returns guide JSON."""
    response = await client.post(
        "/api/v1/tech-mentor/troubleshoot",
        json={
            "equipment_brand": "Carrier",
            "equipment_type": "Gas Furnace",
            "fault_code_or_symptom": "Code 31 Pressure Switch Open",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert "equipment_context" in data
    assert "Carrier" in data["equipment_context"]
    assert len(data["probable_root_causes"]) > 0
    assert len(data["step_by_step_test_procedure"]) > 0
    assert "multimeter_readings_expected" in data
