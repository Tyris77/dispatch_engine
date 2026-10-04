import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lead_action import LeadAction
from app.models.tenant import Tenant
from app.schemas.rebates import (
    RebateCalculationResult,
    RebateClaimDossier,
    UtilityRebateProgram,
)
from app.services.rebates import rebates_service


@pytest.fixture
async def rebate_test_data(sample_tenant: dict, db_session: AsyncSession) -> dict:
    """Fixture providing tenant and signed LeadAction with diagnostic and contract data."""
    tenant = sample_tenant["tenant"]
    tenant.name = "Apex Precision Green HVAC Solutions LLC"
    tenant.settings = {
        "utility_provider": "Pepco Home Energy Solutions",
        "contractor_license": "MD-HVAC-MASTER-881920",
        "phone": "+15553334444",
        "address": "4000 Commercial Center Dr, Austin, TX 78744",
    }
    db_session.add(tenant)

    action = LeadAction(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        lead_external_id="+15559990000",
        qualification_score=0.95,
        qualification_summary="Emergency replacement of cracked heat exchanger with ultra-high efficiency inverter heat pump.",
        action_type="DISPATCH_ROUTED",
        dispatch_status="COMPLETED",
        crm_sync_status="SYNCED",
        metadata_payload={
            "customer_name": "Eleanor Vance",
            "address": "1402 Oak Grove Ln, Washington, DC 20001",
            "service_needed": "Inverter Heat Pump Replacement",
        },
        diagnostic_data={
            "equipment_type": "Inverter Cold-Climate Heat Pump",
            "brand_manufacturer": "Carrier Infinity Series",
            "model_number": "25VNA436A003",
            "serial_number": "SN9928174102",
            "ahri_number": "AHRI-209841824",
        },
        signed_contract={
            "customer_name": "Eleanor Vance",
            "tier_title": "Best",
            "selected_tier": "Premium System",
            "price_total": 12500.0,
            "signed_at": "2026-10-04T10:30:00Z",
        },
    )

    db_session.add(action)
    await db_session.commit()
    await db_session.refresh(action)

    return {"tenant": tenant, "action": action}


def test_rebate_schemas():
    """Verify validation and serialization of utility rebate schemas."""
    prog = UtilityRebateProgram(
        program_name="Pepco Heat Pump Rebate",
        utility_provider="Pepco Energy",
        eligible_trade="HVAC",
        rebate_amount=1200.0,
        efficiency_criteria="SEER2 >= 18.0",
    )
    assert prog.rebate_amount == 1200.0
    assert prog.utility_provider == "Pepco Energy"

    calc = RebateCalculationResult(
        gross_price=10000.0,
        total_rebates_available=3200.0,
        net_customer_investment=6800.0,
        qualifying_programs=[prog],
    )
    assert calc.gross_price == 10000.0
    assert calc.net_customer_investment == 6800.0
    assert len(calc.qualifying_programs) == 1

    dossier = RebateClaimDossier(
        claim_id="REBATE-APEX-001",
        action_id="act-1234",
        tenant_slug="apex-fleet",
        tenant_name="Apex Green Energy LLC",
        contractor_license="MD-HVAC-9918",
        contractor_phone="+15551112233",
        contractor_address="100 Solar Way, Austin, TX",
        customer_name="Eleanor Vance",
        customer_phone="+15559990000",
        service_address="1402 Oak Grove Ln, Washington, DC",
        utility_provider="Pepco",
        installed_equipment_type="Heat Pump",
        installed_equipment_brand="Carrier",
        installed_equipment_model="25VNA4",
        installed_equipment_serial="SN12345",
        ahri_certificate_number="AHRI-9988",
        installation_date="2026-10-04",
        programs=[prog],
        total_rebate_amount=1200.0,
        status="PRE_FILLED",
    )
    assert dossier.claim_id == "REBATE-APEX-001"
    assert dossier.total_rebate_amount == 1200.0


def test_calculate_applicable_rebates_heat_pump():
    """Verify calculation for heat pump equipment across proposal tiers."""
    # Best tier: 2000 Federal IRA + 1200 Utility = 3200
    best_res = rebates_service.calculate_applicable_rebates(
        equipment_type="Inverter Cold Climate Heat Pump",
        proposal_tier="Best",
        gross_price=12000.0,
        tenant_settings={"utility_provider": "Dominion Energy"},
    )
    assert best_res.total_rebates_available == 3200.0
    assert best_res.net_customer_investment == 8800.0
    assert len(best_res.qualifying_programs) == 2

    # Better tier: 1200 Federal IRA + 750 Utility = 1950
    better_res = rebates_service.calculate_applicable_rebates(
        equipment_type="Heat Pump",
        proposal_tier="Better",
        gross_price=9000.0,
    )
    assert better_res.total_rebates_available == 1950.0
    assert better_res.net_customer_investment == 7050.0

    # Good tier: 450 Utility
    good_res = rebates_service.calculate_applicable_rebates(
        equipment_type="Heat Pump",
        proposal_tier="Good",
        gross_price=6500.0,
    )
    assert good_res.total_rebates_available == 450.0
    assert good_res.net_customer_investment == 6050.0


def test_calculate_applicable_rebates_water_heaters_and_furnaces():
    """Verify calculation for plumbing water heaters and gas furnaces."""
    # Hybrid Heat pump water heater
    water_res = rebates_service.calculate_applicable_rebates(
        equipment_type="Hybrid Heat Pump Water Heater",
        proposal_tier="Best",
        gross_price=5500.0,
    )
    assert water_res.total_rebates_available == 2550.0  # 1750 Federal + 800 Utility
    assert water_res.net_customer_investment == 2950.0

    # 97% Modulating Gas furnace
    furnace_res = rebates_service.calculate_applicable_rebates(
        equipment_type="Condensing Gas Furnace",
        proposal_tier="Best",
        gross_price=7800.0,
    )
    assert furnace_res.total_rebates_available == 1100.0  # 600 Federal + 500 Utility
    assert furnace_res.net_customer_investment == 6700.0


def test_generate_rebate_claim_dossier_service(rebate_test_data: dict):
    """Verify dossier generation populates AHRI cert, customer details, and persists rebate_data."""
    tenant = rebate_test_data["tenant"]
    action = rebate_test_data["action"]

    dossier = rebates_service.generate_rebate_claim_dossier(
        lead_action=action,
        tenant=tenant,
    )

    assert dossier.claim_id.startswith("REBATE-")
    assert dossier.customer_name == "Eleanor Vance"
    assert dossier.service_address == "1402 Oak Grove Ln, Washington, DC 20001"
    assert dossier.installed_equipment_brand == "Carrier Infinity Series"
    assert dossier.installed_equipment_model == "25VNA436A003"
    assert dossier.ahri_certificate_number == "AHRI-209841824"
    assert dossier.contractor_license == "MD-HVAC-MASTER-881920"
    assert dossier.total_rebate_amount > 0.0
    assert len(dossier.programs) >= 2

    # Check persistence on lead_action
    assert action.rebate_data is not None
    assert action.rebate_data["claim_id"] == dossier.claim_id
    assert action.rebate_data["total_rebate_amount"] == dossier.total_rebate_amount


@pytest.mark.asyncio
async def test_get_rebate_claim_view_html(
    client: AsyncClient,
    rebate_test_data: dict,
    db_session: AsyncSession,
):
    """Verify GET /rebate/{action_id} renders official printable certificate."""
    action = rebate_test_data["action"]

    response = await client.get(f"/rebate/{action.id}")
    assert response.status_code == 200
    html = response.text
    assert "RESIDENTIAL CLEAN ENERGY INCENTIVE CERTIFICATE" in html
    assert "Eleanor Vance" in html
    assert "Carrier Infinity Series" in html
    assert "AHRI-209841824" in html
    assert "MD-HVAC-MASTER-881920" in html
    assert "Print / Save PDF" in html


@pytest.mark.asyncio
async def test_get_rebate_claim_view_json(
    client: AsyncClient,
    rebate_test_data: dict,
    db_session: AsyncSession,
):
    """Verify GET /rebate/{action_id}?format=json returns valid claim dossier JSON."""
    action = rebate_test_data["action"]

    response = await client.get(f"/rebate/{action.id}?format=json")
    assert response.status_code == 200
    data = response.json()
    assert data["action_id"] == str(action.id)
    assert data["customer_name"] == "Eleanor Vance"
    assert "programs" in data
    assert data["total_rebate_amount"] > 0.0


@pytest.mark.asyncio
async def test_get_rebate_claim_not_found(
    client: AsyncClient,
    db_session: AsyncSession,
):
    """Verify 404 response for nonexistent or invalid action ID."""
    response = await client.get(f"/rebate/{uuid.uuid4()}")
    assert response.status_code == 404

    invalid_resp = await client.get("/rebate/invalid-uuid-token")
    assert invalid_resp.status_code == 404


@pytest.mark.asyncio
async def test_post_rebates_calculate_api(
    client: AsyncClient,
    db_session: AsyncSession,
):
    """Verify POST /api/v1/rebates/calculate returns breakdown."""
    response = await client.post(
        "/api/v1/rebates/calculate",
        json={
            "equipment_type": "Heat Pump",
            "proposal_tier": "Best",
            "gross_price": 11500.0,
            "utility_provider": "Pepco Home Energy",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["gross_price"] == 11500.0
    assert data["total_rebates_available"] == 3200.0
    assert data["net_customer_investment"] == 8300.0
    assert len(data["qualifying_programs"]) == 2
