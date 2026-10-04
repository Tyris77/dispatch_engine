import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lead_action import LeadAction
from app.models.tenant import Tenant
from app.schemas.crew import CrewVoucherData
from app.services.crews import crew_settlement_service


@pytest.fixture
async def seeded_crew_lead(sample_tenant: dict, db_session: AsyncSession) -> LeadAction:
    """Fixture providing a seeded LeadAction with proposal and material PO data."""
    tenant = sample_tenant["tenant"]
    tenant.name = "Apex Roofing & Building Solutions"
    db_session.add(tenant)

    action = LeadAction(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        lead_external_id="+15558881234",
        qualification_score=0.95,
        qualification_summary="Emergency roof tear-off and architectural shingle re-installation.",
        action_type="DISPATCH_EMERGENCY_DISPATCH_QUEUE",
        dispatch_status="QUEUED",
        crm_sync_status="PENDING",
        metadata_payload={
            "customer_name": "Eleanor Vance",
            "address": "420 Maple Ave, Bethesda, MD 20814",
        },
        proposal_data={
            "selected_tier": {
                "name": "Better - Architectural Shingle System",
                "price": 3200.0,
            }
        },
        material_po={
            "total_material_cost": 650.0,
            "po_number": "PO-2026-0811",
        },
        profitability_data={
            "contract_revenue": 3200.0,
            "material_costs": 650.0,
            "estimated_labor_cost": 800.0,
            "net_profit": 1750.0,
            "margin_percentage": 54.7,
            "margin_tier": "EXCELLENT",
        },
    )
    db_session.add(action)
    await db_session.commit()
    await db_session.refresh(action)
    return action


@pytest.mark.asyncio
async def test_assign_crew_percentage_payout(
    seeded_crew_lead: LeadAction,
    db_session: AsyncSession,
):
    """Verify assigning a subcontractor crew with percentage rate computes payout and net profit."""
    payload = {
        "crew_name": "Morales Rapid Shingle Crew",
        "foreman_name": "Mateo Morales",
        "foreman_phone": "+12025550188",
        "trade_specialty": "Roofing",
        "payout_type": "PERCENTAGE",
        "rate_amount": 25.0,  # 25% of $3,200 = $800.00
        "scope_summary": "Tear off 22 SQ shingles down to deck, install drip edge and ice shield.",
        "notes": "Walkthrough inspected with customer.",
    }

    voucher = await crew_settlement_service.assign_crew_to_job(
        action_id=seeded_crew_lead.id,
        crew_payload=payload,
        db=db_session,
    )

    assert isinstance(voucher, CrewVoucherData)
    assert voucher.voucher_number.startswith("VOUCH-2026-")
    assert voucher.contract_revenue == 3200.0
    assert voucher.material_cost == 650.0
    assert voucher.crew_assignment.total_crew_payout == 800.0  # 25% of 3200
    assert voucher.net_contractor_profit == 1750.0  # 3200 - 650 - 800
    assert voucher.margin_percentage == 54.7
    assert voucher.status == "ASSIGNED"

    # Verify database persistence
    query = select(LeadAction).where(LeadAction.id == seeded_crew_lead.id)
    refreshed = (await db_session.execute(query)).scalar_one()
    assert refreshed.crew_data["voucher_number"] == voucher.voucher_number
    assert refreshed.profitability_data["estimated_labor_cost"] == 800.0
    assert refreshed.profitability_data["net_profit"] == 1750.0


@pytest.mark.asyncio
async def test_assign_crew_flat_and_piece_rate(
    seeded_crew_lead: LeadAction,
    db_session: AsyncSession,
):
    """Verify flat rate and piece rate labor calculation modes."""
    # Flat rate
    flat_payload = {
        "crew_name": "Silva Emergency Dry-In Crew",
        "foreman_name": "Javier Silva",
        "foreman_phone": "+12025550199",
        "trade_specialty": "Roofing Tarping",
        "payout_type": "FLAT",
        "rate_amount": 600.0,
    }
    voucher_flat = await crew_settlement_service.assign_crew_to_job(
        action_id=seeded_crew_lead.id,
        crew_payload=flat_payload,
        db=db_session,
    )
    assert voucher_flat.crew_assignment.total_crew_payout == 600.0
    assert voucher_flat.net_contractor_profit == 1950.0  # 3200 - 650 - 600

    # Piece rate
    piece_payload = {
        "crew_name": "Piece Rate Specialists",
        "foreman_name": "Darnell Washington",
        "foreman_phone": "+12025550177",
        "trade_specialty": "Roofing",
        "payout_type": "PIECE_RATE",
        "rate_amount": 65.0,
        "unit_quantity": 20.0,  # 20 SQ * $65 = $1,300
    }
    voucher_piece = await crew_settlement_service.assign_crew_to_job(
        action_id=seeded_crew_lead.id,
        crew_payload=piece_payload,
        db=db_session,
    )
    assert voucher_piece.crew_assignment.total_crew_payout == 1300.0
    assert voucher_piece.net_contractor_profit == 1250.0  # 3200 - 650 - 1300


@pytest.mark.asyncio
async def test_api_assign_crew_endpoint(
    client: AsyncClient,
    seeded_crew_lead: LeadAction,
):
    """Verify POST /api/v1/crews/assign/{action_id} creates voucher via API."""
    url = f"/api/v1/crews/assign/{seeded_crew_lead.id}"
    payload = {
        "crew_name": "Apex Commercial Shingle Crew",
        "foreman_name": "Hector Salamanca",
        "foreman_phone": "+15552223344",
        "trade_specialty": "Roofing",
        "payout_type": "PERCENTAGE",
        "rate_amount": 30.0,
        "scope_summary": "Full commercial membrane replacement.",
    }
    response = await client.post(url, json=payload)

    assert response.status_code == 200
    data = response.json()
    validated = CrewVoucherData.model_validate(data)
    assert validated.voucher_number.startswith("VOUCH-2026-")
    assert validated.crew_assignment.foreman_name == "Hector Salamanca"
    assert validated.crew_assignment.total_crew_payout == 960.0  # 30% of 3200


@pytest.mark.asyncio
async def test_get_crew_voucher_html(
    client: AsyncClient,
    seeded_crew_lead: LeadAction,
):
    """Verify GET /crew-voucher/{action_id} renders printable 1099 settlement voucher."""
    url = f"/crew-voucher/{seeded_crew_lead.id}"
    response = await client.get(url)

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    text = response.text

    assert "1099 SUBCONTRACTOR SETTLEMENT VOUCHER" in text
    assert "Subcontractor Settlement &amp; Net Profit Ledger" in text or "Subcontractor Settlement & Net Profit Ledger" in text
    assert "Labor Settlement Authorization &amp; Lien Waiver" in text or "Labor Settlement Authorization & Lien Waiver" in text
    assert "Eleanor Vance" in text
    assert "Bethesda, MD" in text
    assert "Print / Export PDF" in text


@pytest.mark.asyncio
async def test_get_crew_voucher_json(
    client: AsyncClient,
    seeded_crew_lead: LeadAction,
):
    """Verify GET /api/v1/crews/voucher/{action_id} returns structured JSON."""
    url = f"/api/v1/crews/voucher/{seeded_crew_lead.id}"
    response = await client.get(url)

    assert response.status_code == 200
    data = response.json()
    validated = CrewVoucherData.model_validate(data)
    assert validated.voucher_number.startswith("VOUCH-2026-")
    assert validated.net_contractor_profit > 0.0
