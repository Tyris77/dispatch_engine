import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lead_action import LeadAction
from app.models.tenant import Tenant
from app.schemas.insurance import InsuranceClaimDossier
from app.services.insurance import insurance_service


@pytest.fixture
async def seeded_roofing_lead(sample_tenant: dict, db_session: AsyncSession) -> LeadAction:
    """Fixture providing a seeded LeadAction for roofing storm damage."""
    tenant = sample_tenant["tenant"]
    tenant.name = "Apex Roofing & Restoration"
    tenant.settings["license_number"] = "MD Home Improvement Lic #50192-A"
    db_session.add(tenant)
    await db_session.commit()

    action = LeadAction(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        lead_external_id="+15559876543",
        qualification_score=0.96,
        qualification_summary="Severe hail punctures through architectural shingles and attic water leak.",
        action_type="DISPATCH_EMERGENCY_DISPATCH_QUEUE",
        dispatch_status="QUEUED",
        crm_sync_status="PENDING",
        metadata_payload={
            "customer_name": "David Wallace",
            "address": "742 Evergreen Terrace, Potomac, MD 20854",
            "phone": "+15559876543",
        },
        diagnostic_data={
            "equipment_type": "Architectural Shingle Roof",
            "brand_manufacturer": "GAF Timberline HDZ",
            "damage_assessment": "1.75 inch hail impact punctures, cracked shingles, and soaked plywood sheathing.",
            "recommended_parts_tools": ["GAF WeatherWatch Ice & Water Shield", "GAF Timberline HDZ Shingles"],
        },
    )
    db_session.add(action)
    await db_session.commit()
    await db_session.refresh(action)
    return action


@pytest.fixture
async def seeded_plumbing_lead(sample_tenant: dict, db_session: AsyncSession) -> LeadAction:
    """Fixture providing a seeded LeadAction for freeze-thaw pipe rupture."""
    tenant = sample_tenant["tenant"]

    action = LeadAction(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        lead_external_id="+15551234567",
        qualification_score=0.94,
        qualification_summary="Frozen burst copper pipe flooding finished basement.",
        action_type="DISPATCH_EMERGENCY_DISPATCH_QUEUE",
        dispatch_status="QUEUED",
        crm_sync_status="PENDING",
        metadata_payload={
            "customer_name": "Sarah Connor",
            "address": "1200 Pennsylvania Ave NW, Washington, DC 20004",
        },
        diagnostic_data={
            "equipment_type": "Burst Domestic Copper Water Pipe",
            "damage_assessment": "Sub-freezing thermal shock split 3/4 inch Type L pipe along exterior wall.",
        },
    )
    db_session.add(action)
    await db_session.commit()
    await db_session.refresh(action)
    return action


@pytest.fixture
async def seeded_hvac_lead(sample_tenant: dict, db_session: AsyncSession) -> LeadAction:
    """Fixture providing a seeded LeadAction for HVAC hail and surge damage."""
    tenant = sample_tenant["tenant"]

    action = LeadAction(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        lead_external_id="+15553337777",
        qualification_score=0.91,
        qualification_summary="Condenser coil crushed by hail during convective thunderstorm.",
        action_type="DISPATCH_EMERGENCY_DISPATCH_QUEUE",
        dispatch_status="QUEUED",
        crm_sync_status="PENDING",
        metadata_payload={
            "customer_name": "Michael Scott",
            "address": "1725 Slough Ave, Scranton, PA 18508",
        },
        diagnostic_data={
            "equipment_type": "HVAC Condenser Unit",
            "brand_manufacturer": "Trane",
            "damage_assessment": "Crushed condenser coil fins >50% blockage and burnt contactor.",
        },
    )
    db_session.add(action)
    await db_session.commit()
    await db_session.refresh(action)
    return action


@pytest.mark.asyncio
async def test_generate_insurance_dossier_roofing(
    seeded_roofing_lead: LeadAction,
    sample_tenant: dict,
):
    """Verify roofing dossier correlates NOAA hail event, IRC building codes, and Xactimate items."""
    tenant = sample_tenant["tenant"]

    dossier = insurance_service.generate_insurance_dossier(
        lead_action=seeded_roofing_lead,
        tenant=tenant,
        date_of_loss="2026-09-14",
    )

    assert isinstance(dossier, InsuranceClaimDossier)
    assert dossier.trade_category == "Roofing"
    assert dossier.homeowner_name == "David Wallace"
    assert "Potomac, MD" in dossier.property_address
    assert dossier.date_of_loss == "2026-09-14"

    # NOAA Weather correlation
    assert "Hail" in dossier.weather_verification["event_type"]
    assert dossier.weather_verification["recorded_metrics"]["hail_diameter_in"] == 1.75
    assert dossier.weather_verification["recorded_metrics"]["radar_verified"] is True

    # Statutory Code Citations
    citations_text = " ".join(dossier.code_compliance_citations)
    assert "Section R905.1.2" in citations_text
    assert "Section R908.3" in citations_text
    assert "Ice Barrier" in citations_text

    # Xactimate items & total valuation
    assert len(dossier.itemized_line_items) >= 5
    codes = [item.xactimate_code for item in dossier.itemized_line_items]
    assert "RFG 300" in codes
    assert "RFG IWS" in codes
    assert "RFG 300S" in codes
    assert dossier.total_claim_estimate > 5000.0

    # Adjuster scope narrative
    assert "EXECUTIVE SCOPE JUSTIFICATION FOR PROPERTY ADJUSTER" in dossier.xactimate_scope_narrative
    assert "David Wallace" not in dossier.xactimate_scope_narrative or "Potomac" in dossier.xactimate_scope_narrative

    # Lead action persistence
    assert seeded_roofing_lead.insurance_data is not None
    assert seeded_roofing_lead.insurance_data["claim_reference_id"] == dossier.claim_reference_id


@pytest.mark.asyncio
async def test_generate_insurance_dossier_plumbing(
    seeded_plumbing_lead: LeadAction,
    sample_tenant: dict,
):
    """Verify plumbing dossier correlates NOAA sub-freezing polar vortex and IPC code mandates."""
    tenant = sample_tenant["tenant"]

    dossier = insurance_service.generate_insurance_dossier(
        lead_action=seeded_plumbing_lead,
        tenant=tenant,
    )

    assert dossier.trade_category == "Plumbing"
    assert "Polar Vortex" in dossier.weather_verification["event_type"]
    assert dossier.weather_verification["recorded_metrics"]["hours_sub_freezing"] == 54

    citations = " ".join(dossier.code_compliance_citations)
    assert "Section 305.4" in citations
    assert "Freezing Protection" in citations

    codes = [item.xactimate_code for item in dossier.itemized_line_items]
    assert "PLM PIPEC" in codes
    assert "WTR EXTR" in codes
    assert dossier.total_claim_estimate > 2000.0


@pytest.mark.asyncio
async def test_generate_insurance_dossier_hvac(
    seeded_hvac_lead: LeadAction,
    sample_tenant: dict,
):
    """Verify HVAC dossier correlates wind/convective deluge and IMC code citations."""
    tenant = sample_tenant["tenant"]

    dossier = insurance_service.generate_insurance_dossier(
        lead_action=seeded_hvac_lead,
        tenant=tenant,
    )

    assert dossier.trade_category == "HVAC"
    assert "Convective Deluge" in dossier.weather_verification["event_type"]
    citations = " ".join(dossier.code_compliance_citations)
    assert "Section 304.1" in citations
    codes = [item.xactimate_code for item in dossier.itemized_line_items]
    assert "HVC COND" in codes
    assert "HVC REF" in codes


@pytest.mark.asyncio
async def test_get_insurance_dossier_view_html(
    client: AsyncClient,
    seeded_roofing_lead: LeadAction,
    sample_tenant: dict,
):
    """Verify GET /insurance/{action_id} renders print-ready insurance adjuster dossier."""
    url = f"/insurance/{seeded_roofing_lead.id}"
    response = await client.get(url)

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    text = response.text

    assert "INSURANCE CLAIM DOSSIER" in text
    assert "NOAA Meteorological Weather Peril Verification" in text
    assert "Mandatory Statutory Building Code Citations" in text
    assert "Executive Adjuster Scope of Work Narrative" in text
    assert "Itemized Xactimate Schedule of Values" in text
    assert "Claim Scope Approval &amp; Authorization" in text or "Claim Scope Approval & Authorization" in text
    assert "David Wallace" in text
    assert "RFG 300" in text
    assert "Print / Export PDF" in text


@pytest.mark.asyncio
async def test_get_insurance_dossier_view_json(
    client: AsyncClient,
    seeded_roofing_lead: LeadAction,
):
    """Verify GET /insurance/{action_id}?format=json returns structured dossier."""
    url = f"/insurance/{seeded_roofing_lead.id}?format=json"
    response = await client.get(url)

    assert response.status_code == 200
    data = response.json()
    assert "claim_reference_id" in data
    assert data["trade_category"] == "Roofing"
    assert "weather_verification" in data
    assert "code_compliance_citations" in data
    assert len(data["itemized_line_items"]) > 0
    assert data["total_claim_estimate"] > 0


@pytest.mark.asyncio
async def test_post_insurance_generate_endpoint(
    client: AsyncClient,
    seeded_roofing_lead: LeadAction,
    db_session: AsyncSession,
):
    """Verify POST /insurance/{action_id}/generate regenerates dossier with custom carrier and policy."""
    url = f"/insurance/{seeded_roofing_lead.id}/generate"
    response = await client.post(
        url,
        data={
            "insurer": "State Farm Fire & Casualty",
            "policy_num": "POL-SF-4499112",
            "date_of_loss": "2026-08-20",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == f"/insurance/{seeded_roofing_lead.id}"

    # Verify updated database state
    query = select(LeadAction).where(LeadAction.id == seeded_roofing_lead.id)
    refreshed = (await db_session.execute(query)).scalar_one()
    assert refreshed.insurance_data["insurer_name"] == "State Farm Fire & Casualty"
    assert refreshed.insurance_data["policy_number"] == "POL-SF-4499112"
    assert refreshed.insurance_data["date_of_loss"] == "2026-08-20"


@pytest.mark.asyncio
async def test_api_v1_insurance_endpoint(
    client: AsyncClient,
    seeded_roofing_lead: LeadAction,
):
    """Verify GET /api/v1/insurance/{action_id} endpoint returns validated InsuranceClaimDossier schema."""
    url = f"/api/v1/insurance/{seeded_roofing_lead.id}"
    response = await client.get(url)

    assert response.status_code == 200
    data = response.json()
    validated = InsuranceClaimDossier.model_validate(data)
    assert validated.claim_reference_id.startswith("CLM-2026-")
    assert validated.trade_category == "Roofing"
    assert validated.status == "READY_FOR_ADJUSTER"
