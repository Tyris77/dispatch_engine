import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lead_action import LeadAction
from app.models.tenant import Tenant
from app.schemas.legal import LienWaiverDocument
from app.services.legal import lien_waiver_service, resolve_jurisdiction_and_citation


@pytest.fixture
async def seeded_legal_lead(sample_tenant: dict, db_session: AsyncSession) -> LeadAction:
    """Fixture providing a seeded LeadAction with paid invoice for lien waiver generation."""
    tenant = sample_tenant["tenant"]
    tenant.name = "Capital Trade Solutions LLC"
    db_session.add(tenant)

    action = LeadAction(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        lead_external_id="+15557778899",
        qualification_score=0.96,
        qualification_summary="Emergency water heater burst and structural dry-out.",
        action_type="DISPATCH_EMERGENCY_DISPATCH_QUEUE",
        dispatch_status="COMPLETED",
        crm_sync_status="SYNCED",
        metadata_payload={
            "customer_name": "Jonathan Sterling",
            "address": "1600 K Street NW, Washington, DC 20006",
            "trade_type": "Plumbing",
            "category": "Plumbing",
        },
        invoice_data={
            "invoice_number": "INV-2026-0099",
            "contract_total": 4500.0,
            "payment_status": "PAID",
        },
    )
    db_session.add(action)
    await db_session.commit()
    await db_session.refresh(action)
    return action


def test_resolve_jurisdiction_and_citation():
    """Verify statutory jurisdiction code citations for DC, VA, MD, and US Standard."""
    jur_dc, cit_dc = resolve_jurisdiction_and_citation("123 Constitution Ave NW, Washington, DC 20001")
    assert jur_dc == "DC"
    assert "D.C. Code § 40-301" in cit_dc

    jur_va, cit_va = resolve_jurisdiction_and_citation("8000 Tysons Corner Center, McLean, VA 22102")
    assert jur_va == "VA"
    assert "Va. Code Ann. § 43-3" in cit_va

    jur_md, cit_md = resolve_jurisdiction_and_citation("7200 Wisconsin Ave, Bethesda, MD 20814")
    assert jur_md == "MD"
    assert "Real Prop. § 9-102" in cit_md

    jur_us, cit_us = resolve_jurisdiction_and_citation("100 Main St, Austin, TX 78701")
    assert jur_us == "US_STANDARD"
    assert "Uniform Construction Lien Act" in cit_us


@pytest.mark.asyncio
async def test_generate_lien_waiver_service(seeded_legal_lead: LeadAction, sample_tenant: dict):
    """Verify service extracts property address, detects DC code, and sets amount from invoice."""
    tenant = sample_tenant["tenant"]
    waiver = lien_waiver_service.generate_lien_waiver(
        lead_action=seeded_legal_lead,
        tenant=tenant,
        waiver_type="FINAL_UNCONDITIONAL_RELEASE",
    )
    assert isinstance(waiver, LienWaiverDocument)
    assert waiver.waiver_number.startswith("LIEN-2026-")
    assert waiver.waiver_type == "FINAL_UNCONDITIONAL_RELEASE"
    assert waiver.customer_name == "Jonathan Sterling"
    assert waiver.statutory_jurisdiction == "DC"
    assert "D.C. Code" in waiver.legal_code_citation
    assert waiver.amount_waived == 4500.0
    assert len(waiver.contractor_license_number) > 0


@pytest.mark.asyncio
async def test_get_lien_waiver_view(client: AsyncClient, seeded_legal_lead: LeadAction):
    """Verify GET /lien-waiver/{action_id} renders printable legal document with notary block."""
    response = await client.get(f"/lien-waiver/{seeded_legal_lead.id}")
    assert response.status_code == 200
    assert "Statutory Mechanic&#39;s Lien Waiver" in response.text or "Lien Waiver" in response.text
    assert "Jonathan Sterling" in response.text
    assert "Notary Public" in response.text
    assert "D.C. Code" in response.text


@pytest.mark.asyncio
async def test_get_lien_waiver_json_format(client: AsyncClient, seeded_legal_lead: LeadAction):
    """Verify GET /lien-waiver/{action_id}?format=json returns valid JSON document."""
    response = await client.get(f"/lien-waiver/{seeded_legal_lead.id}?format=json")
    assert response.status_code == 200
    data = response.json()
    validated = LienWaiverDocument.model_validate(data)
    assert validated.statutory_jurisdiction == "DC"
    assert validated.amount_waived == 4500.0


@pytest.mark.asyncio
async def test_post_lien_waiver_custom_generate(
    client: AsyncClient,
    seeded_legal_lead: LeadAction,
    db_session: AsyncSession,
):
    """Verify POST /lien-waiver/{action_id}/generate allows overriding amount waived."""
    response = await client.post(
        f"/lien-waiver/{seeded_legal_lead.id}/generate",
        data={
            "waiver_type": "PROGRESS_PAYMENT",
            "amount_override": "2250.00",
        },
        headers={"accept": "application/json"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["waiver_type"] == "PROGRESS_PAYMENT"
    assert data["amount_waived"] == 2250.0

    # Verify database persistence
    query = select(LeadAction).where(LeadAction.id == seeded_legal_lead.id)
    refreshed = (await db_session.execute(query)).scalar_one()
    assert refreshed.lien_waiver_data is not None
    assert refreshed.lien_waiver_data["amount_waived"] == 2250.0


@pytest.mark.asyncio
async def test_get_lien_waiver_api_endpoint(client: AsyncClient, seeded_legal_lead: LeadAction):
    """Verify GET /api/v1/legal/lien-waiver/{action_id} returns LienWaiverDocument."""
    response = await client.get(f"/api/v1/legal/lien-waiver/{seeded_legal_lead.id}")
    assert response.status_code == 200
    data = response.json()
    validated = LienWaiverDocument.model_validate(data)
    assert validated.waiver_number.startswith("LIEN-2026-")
    assert validated.customer_name == "Jonathan Sterling"
