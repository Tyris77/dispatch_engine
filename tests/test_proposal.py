import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lead_action import LeadAction
from app.models.tenant import Tenant
from app.schemas.proposal import (
    ContractSignatureSubmission,
    ProposalEstimate,
    ProposalOption,
    ProposalResponse,
    SignedContractData,
)
from app.schemas.vision import EquipmentDiagnosticReport
from app.services.proposal import generate_tiered_proposal, proposal_service


def test_proposal_schemas():
    """Verify that ProposalOption, ProposalEstimate, and ContractSignatureSubmission validate correctly."""
    option = ProposalOption(
        tier_name="Standard Replacement",
        title="15-SEER2 High Efficiency Heat Pump",
        price_estimate=6800.0,
        scope_bullets=["Install outdoor unit", "Eco refrigerant", "New pad"],
        warranty_info="10-Year Parts + 2-Year Labor",
        badge="RECOMMENDED",
    )
    assert option.price_estimate == 6800.0
    assert len(option.scope_bullets) == 3

    estimate = ProposalEstimate(
        equipment_summary="Carrier HVAC Condenser | Low Refrigerant",
        options=[option],
        deposit_required=1700.0,
        deposit_percentage=25.0,
    )
    assert estimate.deposit_required == 1700.0
    assert len(estimate.options) == 1

    submission = ContractSignatureSubmission(
        selected_tier="Standard Replacement",
        signature_base64="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
        customer_name="Jane Homeowner",
        customer_phone="+15559876543",
    )
    assert submission.selected_tier == "Standard Replacement"
    assert submission.customer_name == "Jane Homeowner"


def test_generate_tiered_proposal_hvac():
    """Verify generate_tiered_proposal creates 3 customized tiers for HVAC equipment."""
    diagnostic = EquipmentDiagnosticReport(
        equipment_type="HVAC Condenser",
        brand_manufacturer="Carrier",
        model_number="24ACC636A003",
        serial_number="12345678",
        detected_materials=["Copper", "Aluminum"],
        damage_assessment="Blown dual run capacitor and contactor pitting.",
        recommended_parts_tools=["45/5 uF Capacitor", "Single Pole Contactor"],
        confidence_score=0.92,
    )
    estimate = generate_tiered_proposal(diagnostic)

    assert len(estimate.options) == 3
    tiers = [opt.tier_name for opt in estimate.options]
    assert "Repair / Patch" in tiers
    assert "Standard Replacement" in tiers
    assert "Premium System" in tiers

    bronze = next(opt for opt in estimate.options if opt.tier_name == "Repair / Patch")
    assert "Carrier" in bronze.title
    assert any("Capacitor" in b for b in bronze.scope_bullets)
    assert bronze.price_estimate > 0

    silver = next(opt for opt in estimate.options if opt.tier_name == "Standard Replacement")
    assert "Carrier" in silver.title
    assert "RECOMMENDED" in (silver.badge or "")

    gold = next(opt for opt in estimate.options if opt.tier_name == "Premium System")
    assert gold.price_estimate > silver.price_estimate > bronze.price_estimate

    # Default deposit 25% of Silver
    expected_deposit = round(silver.price_estimate * 0.25, 2)
    assert estimate.deposit_required == expected_deposit


def test_generate_tiered_proposal_plumbing_with_settings():
    """Verify tiered proposal respects trade rate-card and tenant settings markup."""
    diagnostic = EquipmentDiagnosticReport(
        equipment_type="Water Heater",
        brand_manufacturer="Bradford White",
        model_number="RG250T6N",
        serial_number="BW9988",
        detected_materials=["Copper"],
        damage_assessment="Leaking relief valve and severe mineral buildup.",
        recommended_parts_tools=["T&P Relief Valve", "Magnesium Anode Rod"],
        confidence_score=0.95,
    )
    tenant_settings = {
        "pricing_markup_multiplier": 1.25,
        "deposit_percentage": 30.0,
    }
    estimate = generate_tiered_proposal(diagnostic, tenant_settings=tenant_settings)

    assert "Bradford White" in estimate.equipment_summary
    silver = next(opt for opt in estimate.options if opt.tier_name == "Standard Replacement")
    # Base 2650.0 * 1.25 = 3312.50
    assert silver.price_estimate == 3312.50
    assert estimate.deposit_percentage == 30.0
    assert estimate.deposit_required == round(3312.50 * 0.30, 2)


def test_generate_tiered_proposal_fallback_no_diagnostic():
    """Verify fallback proposal generation when diagnostic report is absent."""
    estimate = generate_tiered_proposal(diagnostic=None)
    assert len(estimate.options) == 3
    assert estimate.deposit_required > 0
    assert "Repair / Patch" in [opt.tier_name for opt in estimate.options]


@pytest.mark.asyncio
async def test_get_proposal_page_html(
    client: AsyncClient,
    db_session: AsyncSession,
    sample_tenant: dict,
):
    """Verify GET /proposal/{action_id} dynamically generates proposal and returns mobile HTML."""
    tenant: Tenant = sample_tenant["tenant"]

    action = LeadAction(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        lead_external_id="+15553334444",
        action_type="DISPATCH_EMERGENCY",
        dispatch_status="QUEUED",
        crm_sync_status="PENDING",
        metadata_payload={"caller_phone": "+15553334444"},
        diagnostic_data={
            "equipment_type": "HVAC Condenser",
            "brand_manufacturer": "Trane",
            "model_number": "XR14",
            "serial_number": "TR-5544",
            "detected_materials": ["Copper"],
            "damage_assessment": "Coil corrosion and compressor lockup.",
            "recommended_parts_tools": ["Hard Start Kit"],
            "confidence_score": 0.88,
        },
    )
    db_session.add(action)
    await db_session.commit()

    response = await client.get(f"/proposal/{action.id}")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert tenant.name in response.text
    assert "Trane HVAC Condenser" in response.text
    assert "Repair / Patch" in response.text
    assert "Standard Replacement" in response.text
    assert "Premium System" in response.text
    assert "signature-pad" in response.text
    assert "Accept & Sign Proposal" in response.text


@pytest.mark.asyncio
async def test_get_proposal_json_mode(
    client: AsyncClient,
    db_session: AsyncSession,
    sample_tenant: dict,
):
    """Verify GET /proposal/{action_id}?format=json returns structured ProposalResponse."""
    tenant: Tenant = sample_tenant["tenant"]

    action = LeadAction(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        lead_external_id="+15558889999",
        action_type="DISPATCH_ROUTED",
        dispatch_status="QUEUED",
        crm_sync_status="PENDING",
        metadata_payload={},
    )
    db_session.add(action)
    await db_session.commit()

    response = await client.get(f"/proposal/{action.id}?format=json")
    assert response.status_code == 200
    data = response.json()
    assert data["action_id"] == str(action.id)
    assert data["tenant_slug"] == tenant.slug
    assert len(data["estimate"]["options"]) == 3
    assert data["is_signed"] is False
    assert data["signed_contract"] is None


@pytest.mark.asyncio
async def test_get_proposal_not_found(client: AsyncClient):
    """Verify GET /proposal/{action_id} returns 404 for invalid ID."""
    fake_id = uuid.uuid4()
    response = await client.get(f"/proposal/{fake_id}")
    assert response.status_code == 404
    assert f"Lead action '{fake_id}' not found" in response.text


@pytest.mark.asyncio
async def test_post_proposal_accept_form_data(
    client: AsyncClient,
    db_session: AsyncSession,
    sample_tenant: dict,
):
    """Verify POST /proposal/{action_id}/accept saves signature, updates LeadAction, and redirects."""
    tenant: Tenant = sample_tenant["tenant"]
    tenant.settings = {
        **tenant.settings,
        "alert_phone_number": "+15557778899",
    }
    await db_session.commit()

    action = LeadAction(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        lead_external_id="+15552221111",
        action_type="DISPATCH_ROUTED",
        dispatch_status="QUEUED",
        crm_sync_status="PENDING",
        metadata_payload={"caller_phone": "+15552221111"},
    )
    db_session.add(action)
    await db_session.commit()

    sig_data = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
    form_data = {
        "selected_tier": "Standard Replacement",
        "signature_base64": sig_data,
        "customer_name": "Michael Scott",
        "customer_phone": "+15552221111",
    }

    response = await client.post(
        f"/proposal/{action.id}/accept",
        data=form_data,
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == f"/proposal/{action.id}?signed=true"

    # Refresh DB session and verify persisted state
    await db_session.refresh(action)
    assert action.action_type == "CONTRACT_SIGNED"
    assert action.dispatch_status == "CONFIRMED"
    assert action.signed_contract is not None
    assert action.signed_contract["selected_tier"] == "Standard Replacement"
    assert action.signed_contract["customer_name"] == "Michael Scott"
    assert action.signed_contract["signature_base64"] == sig_data
    assert action.signed_contract["contract_status"] == "SIGNED"


@pytest.mark.asyncio
async def test_post_proposal_accept_json_mode(
    client: AsyncClient,
    db_session: AsyncSession,
    sample_tenant: dict,
):
    """Verify POST /proposal/{action_id}/accept supports JSON submission."""
    tenant: Tenant = sample_tenant["tenant"]

    action = LeadAction(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        lead_external_id="+15553332222",
        action_type="DISPATCH_ROUTED",
        dispatch_status="QUEUED",
        crm_sync_status="PENDING",
        metadata_payload={},
    )
    db_session.add(action)
    await db_session.commit()

    sig_data = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
    json_payload = {
        "selected_tier": "Premium System",
        "signature_base64": sig_data,
        "customer_name": "Sarah Connor",
        "customer_phone": "+15553332222",
        "deposit_paid": 2500.0,
    }

    response = await client.post(
        f"/proposal/{action.id}/accept",
        json=json_payload,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["contract"]["selected_tier"] == "Premium System"
    assert data["contract"]["customer_name"] == "Sarah Connor"
    assert data["contract"]["deposit_paid"] == 2500.0


@pytest.mark.asyncio
async def test_post_proposal_missing_fields_validation(
    client: AsyncClient,
    db_session: AsyncSession,
    sample_tenant: dict,
):
    """Verify POST /proposal/{action_id}/accept validates required signature and tier."""
    tenant: Tenant = sample_tenant["tenant"]

    action = LeadAction(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        lead_external_id="+15554445555",
        action_type="DISPATCH_ROUTED",
        dispatch_status="QUEUED",
        crm_sync_status="PENDING",
        metadata_payload={},
    )
    db_session.add(action)
    await db_session.commit()

    # Missing signature
    response = await client.post(
        f"/proposal/{action.id}/accept",
        data={"selected_tier": "Standard Replacement"},
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_get_proposal_already_signed_renders_confirmation(
    client: AsyncClient,
    db_session: AsyncSession,
    sample_tenant: dict,
):
    """Verify GET /proposal/{action_id} renders locked confirmation banner when contract is signed."""
    tenant: Tenant = sample_tenant["tenant"]

    sig_data = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
    action = LeadAction(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        lead_external_id="+15556667777",
        action_type="CONTRACT_SIGNED",
        dispatch_status="CONFIRMED",
        crm_sync_status="PENDING",
        metadata_payload={},
        signed_contract={
            "selected_tier": "Standard Replacement",
            "tier_title": "Standard High-Efficiency System Replacement",
            "price_total": 4800.0,
            "deposit_required": 1200.0,
            "deposit_paid": 1200.0,
            "signature_base64": sig_data,
            "customer_name": "Alice Smith",
            "signed_at": "2026-10-02T16:00:00Z",
            "contract_status": "SIGNED",
        },
    )
    db_session.add(action)
    await db_session.commit()

    response = await client.get(f"/proposal/{action.id}")
    assert response.status_code == 200
    assert "Proposal Accepted & Contract Signed" in response.text
    assert "Alice Smith" in response.text
    assert "$4,800.00" in response.text
    assert "LOCKED & SCHEDULED" in response.text
    # Signature pad form should not be rendered
    assert 'id="proposal-form"' not in response.text
    assert "Customer Authorization & E-Signature" not in response.text
