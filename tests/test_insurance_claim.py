import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lead_action import LeadAction
from app.models.tenant import Tenant
from app.schemas.insurance_claim import (
    ClaimGenerateRequest,
    InsuranceClaimSupplementReport,
    XactimateLineItem,
)
from app.services.insurance_claim import insurance_claim_service


@pytest.fixture
async def seeded_mitigation_action(sample_tenant: dict, db_session: AsyncSession) -> LeadAction:
    """Fixture providing a seeded water mitigation lead action."""
    tenant = sample_tenant["tenant"]

    action = LeadAction(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        lead_external_id="+15552223344",
        qualification_score=0.95,
        qualification_summary="Category 3 black water sewer backup flooding finished basement floor.",
        action_type="EMERGENCY_WATER_EXTRACTION",
        dispatch_status="QUEUED",
        crm_sync_status="PENDING",
        metadata_payload={
            "sender_name": "Eleanor Vance",
            "address": "1428 Elm Street, Bethesda, MD 20814",
            "phone": "+15552223344",
        },
        diagnostic_data={
            "water_category": "Category 3",
            "standing_water_depth_inches": 3.5,
            "affected_area_sqft": 450,
            "structural_materials": ["subfloor", "framing", "drywall"],
        },
        mitigation_data={
            "extraction_completed": True,
            "dehumidifiers_deployed": 4,
            "air_movers_deployed": 12,
        },
    )
    db_session.add(action)
    await db_session.commit()
    await db_session.refresh(action)
    return action


@pytest.fixture
async def seeded_roofing_action(sample_tenant: dict, db_session: AsyncSession) -> LeadAction:
    """Fixture providing a seeded roofing storm damage lead action."""
    tenant = sample_tenant["tenant"]

    action = LeadAction(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        lead_external_id="+15554445566",
        qualification_score=0.98,
        qualification_summary="Severe hail and wind strike tore off roof shingles and damaged flashing.",
        action_type="ROOF_HAIL_STORM_DAMAGE",
        dispatch_status="QUEUED",
        crm_sync_status="PENDING",
        metadata_payload={
            "sender_name": "Robert Langdon",
            "address": "3300 Whitehaven St NW, Washington, DC 20007",
            "phone": "+15554445566",
        },
        diagnostic_data={
            "peril": "Hail & Windstorm",
            "shingle_type": "Architectural",
            "pitch": "9/12 steep slope",
            "observed_leaks": True,
        },
    )
    db_session.add(action)
    await db_session.commit()
    await db_session.refresh(action)
    return action


def test_water_mitigation_line_items_generation(seeded_mitigation_action: LeadAction):
    """Verify water mitigation generates required Xactimate codes and IICRC S500 citations."""
    report = insurance_claim_service.generate_claim_supplement(
        action=seeded_mitigation_action,
        request_data=ClaimGenerateRequest(
            insurance_carrier="State Farm",
            claim_number="CLM-WATER-001",
            policyholder_name="Eleanor Vance",
            original_adjuster_amount=1200.0,
        ),
        tenant_name="Apex Restoration",
    )

    codes = [item.item_code for item in report.line_items]
    assert "WTR EXTW" in codes
    assert "WTR DHM" in codes
    assert "WTR DRY" in codes
    assert "WTR MMAP" in codes
    assert "WTR BARR" in codes
    assert "WTR GRM" in codes

    # Citations check
    citations_text = " ".join(report.code_citations)
    assert "IICRC S500" in citations_text

    # Financial check
    assert report.supplement_amount > 0
    assert report.total_claim_value == report.original_adjuster_amount + report.supplement_amount
    assert report.insurance_carrier == "State Farm"
    assert report.claim_number == "CLM-WATER-001"


def test_roofing_line_items_and_irc_citations(seeded_roofing_action: LeadAction):
    """Verify roofing generates required Xactimate codes and IRC R905 citations."""
    report = insurance_claim_service.generate_claim_supplement(
        action=seeded_roofing_action,
        request_data=ClaimGenerateRequest(
            insurance_carrier="Travelers",
            claim_number="CLM-ROOF-777",
            policyholder_name="Robert Langdon",
            original_adjuster_amount=2500.0,
        ),
        tenant_name="Apex Roofing",
    )

    codes = [item.item_code for item in report.line_items]
    assert "RFG DRIP" in codes
    assert "RFG ICE" in codes
    assert "RFG FLSTEP" in codes
    assert "RFG RIDGE" in codes
    assert "RFG STEEP" in codes

    # Building code citations
    citations_text = " ".join(report.code_citations)
    assert "R905.2.8.5" in citations_text
    assert "R905.1.2" in citations_text

    # Demand letter verification
    letter = report.adjuster_demand_letter
    assert "Travelers" in letter
    assert "CLM-ROOF-777" in letter
    assert "Robert Langdon" in letter
    assert "RFG FLSTEP" in letter
    assert "FINANCIAL RECONCILIATION SUMMARY" in letter


@pytest.mark.asyncio
async def test_post_generate_supplement_api(
    client: AsyncClient,
    seeded_mitigation_action: LeadAction,
    db_session: AsyncSession,
):
    """Verify POST /api/v1/claims/generate-supplement/{action_id} endpoint."""
    url = f"/api/v1/claims/generate-supplement/{seeded_mitigation_action.id}"
    payload = {
        "insurance_carrier": "Allstate",
        "claim_number": "ALL-998877",
        "policyholder_name": "Eleanor Vance",
        "original_adjuster_amount": 1500.0,
    }
    response = await client.post(url, json=payload)
    assert response.status_code == 200

    data = response.json()
    assert data["claim_number"] == "ALL-998877"
    assert data["insurance_carrier"] == "Allstate"
    assert data["original_adjuster_amount"] == 1500.0
    assert data["supplement_amount"] > 0
    assert len(data["line_items"]) >= 6

    # Verify persisted in database
    await db_session.refresh(seeded_mitigation_action)
    assert seeded_mitigation_action.claim_supplement_data is not None
    assert seeded_mitigation_action.claim_supplement_data["claim_number"] == "ALL-998877"


@pytest.mark.asyncio
async def test_get_claim_supplement_html_view(
    client: AsyncClient,
    seeded_roofing_action: LeadAction,
):
    """Verify GET /claims/{action_id} renders interactive claim supplement HTML."""
    url = f"/claims/{seeded_roofing_action.id}"
    response = await client.get(url)
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]

    html = response.text
    assert "Insurance Claim Supplement Dossier" in html
    assert "RFG DRIP" in html
    assert "RFG FLSTEP" in html
    assert "Export Adjuster Packet" in html
    assert "Submit to Insurance" in html


@pytest.mark.asyncio
async def test_get_claim_supplement_json_api(
    client: AsyncClient,
    seeded_roofing_action: LeadAction,
):
    """Verify GET /api/v1/claims/{action_id}/json returns valid structured report."""
    url = f"/api/v1/claims/{seeded_roofing_action.id}/json"
    response = await client.get(url)
    assert response.status_code == 200

    data = response.json()
    assert "line_items" in data
    assert "adjuster_demand_letter" in data
    assert data["supplement_amount"] > 0


@pytest.mark.asyncio
async def test_get_claims_vault_html_view(
    client: AsyncClient,
    sample_tenant: dict,
    seeded_mitigation_action: LeadAction,
):
    """Verify GET /claims-vault/{tenant_slug} renders claims recovery vault."""
    tenant = sample_tenant["tenant"]
    url = f"/claims-vault/{tenant.slug}"
    response = await client.get(url)
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]

    html = response.text
    assert "Autonomous Insurance Recovery Vault" in html
    assert "Total Supplement Dollars Recovered" in html
    assert "Supplement Recovery by Insurance Carrier" in html


@pytest.fixture
async def seeded_hvac_action(sample_tenant: dict, db_session: AsyncSession) -> LeadAction:
    """Fixture providing a seeded HVAC compressor burnout & drainage failure lead action."""
    tenant = sample_tenant["tenant"]

    action = LeadAction(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        lead_external_id="+15557778899",
        qualification_score=0.92,
        qualification_summary="Attic air handler compressor electrical burnout with contaminated line set and missing drain pan float switch.",
        action_type="HVAC_COMPRESSOR_REPLACEMENT",
        dispatch_status="QUEUED",
        crm_sync_status="PENDING",
        metadata_payload={
            "sender_name": "Marcus Aurelius",
            "address": "1600 Pennsylvania Ave NW, Washington, DC 20500",
            "phone": "+15557778899",
        },
        diagnostic_data={
            "equipment_type": "Split Heat Pump System",
            "failure_mode": "Compressor Burnout & Acid Contamination",
        },
        proposal_data={
            "original_adjuster_amount": 1850.0,
            "selected_tier": "silver",
        },
    )
    db_session.add(action)
    await db_session.commit()
    await db_session.refresh(action)
    return action


def test_hvac_line_items_and_imc_citations(seeded_hvac_action: LeadAction):
    """Verify HVAC trade generates required line items and IMC Section 307.2.3 citations."""
    report = insurance_claim_service.generate_claim_supplement(
        action=seeded_hvac_action,
        request_data=ClaimGenerateRequest(
            insurance_carrier="USAA",
            claim_number="CLM-HVAC-990",
            policyholder_name="Marcus Aurelius",
            original_adjuster_amount=1850.0,
        ),
        tenant_name="Apex Mechanical",
    )

    codes = [item.item_code for item in report.line_items]
    assert "HVC LINE" in codes
    assert "HVC COND" in codes

    # Citations check
    citations_text = " ".join(report.code_citations)
    assert "IMC" in citations_text
    assert "307.2.3" in citations_text
    assert "Clean Air Act" in citations_text

    # Letter verification
    assert "USAA" in report.adjuster_demand_letter
    assert "CLM-HVAC-990" in report.adjuster_demand_letter
    assert "Marcus Aurelius" in report.adjuster_demand_letter


def test_water_mitigation_dynamic_synthesis_from_data(seeded_mitigation_action: LeadAction):
    """Verify water mitigation line items dynamically size quantities from diagnostic and mitigation data."""
    report = insurance_claim_service.generate_claim_supplement(
        action=seeded_mitigation_action,
        tenant_name="Apex Restoration",
    )

    item_map = {item.item_code: item for item in report.line_items}
    # From seeded_mitigation_action: affected_area_sqft = 450
    assert item_map["WTR EXTW"].quantity == 450.0
    assert item_map["WTR GRM"].quantity == 450.0
    # From seeded_mitigation_action: dehumidifiers_deployed = 4
    assert item_map["WTR DHM"].quantity == 4.0
    # From seeded_mitigation_action: air_movers_deployed = 12
    assert item_map["WTR DRY"].quantity == 12.0


@pytest.mark.asyncio
async def test_claims_unknown_ids_return_404(client: AsyncClient):
    """Verify endpoints return 404 for nonexistent action ID and tenant slug."""
    fake_id = uuid.uuid4()
    resp1 = await client.get(f"/claims/{fake_id}")
    assert resp1.status_code == 404

    resp2 = await client.get(f"/api/v1/claims/{fake_id}/json")
    assert resp2.status_code == 404

    resp3 = await client.post(f"/api/v1/claims/generate-supplement/{fake_id}", json={"insurance_carrier": "Allstate"})
    assert resp3.status_code == 404

    resp4 = await client.get("/claims-vault/completely-non-existent-tenant-slug")
    assert resp4.status_code == 404

