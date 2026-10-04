import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lead_action import LeadAction
from app.models.tenant import Tenant
from app.schemas.partner_exchange import (
    PartnerReferralDispatchPayload,
    PartnerReferralTrade,
    TradePartner,
)
from app.services.partner_exchange import partner_exchange_service


def test_partner_exchange_schemas():
    """Verify validation of TradePartner and PartnerReferralTrade models."""
    partner = TradePartner(
        partner_id="PARTNER-PLUMB-01",
        company_name="Keystone Plumbing",
        trade_specialty="Plumbing",
        phone="+15551112233",
        email="dispatch@keystone.com",
        finder_fee_rate=0.10,
    )
    assert partner.trade_specialty == "Plumbing"
    assert partner.finder_fee_rate == 0.10

    referral = PartnerReferralTrade(
        referral_id="REF-PLU-9901A",
        referring_tenant_slug="apex-hvac",
        recipient_partner=partner,
        customer_name="Dr. Richard Kimble",
        customer_phone="+15559871122",
        service_needed="Main backflow preventer failed and water service locked out",
        estimated_job_value=12000.0,
        finder_fee_due=1200.0,
        status="DISPATCHED_TO_PARTNER",
    )
    assert referral.finder_fee_due == 1200.0
    assert referral.status == "DISPATCHED_TO_PARTNER"


@pytest.mark.asyncio
async def test_partner_network_service(db_session: AsyncSession):
    """Test trade partner matching, warm lead packaging, and 10% fee calculation."""
    tenant = Tenant(
        id=uuid.uuid4(),
        name="Apex Commercial HVAC",
        slug=f"apex-hvac-{uuid.uuid4().hex[:6]}",
        api_key_hash="hash",
        webhook_secret="secret",
        settings={"cross_trade_referrals": []},
    )
    db_session.add(tenant)

    lead = LeadAction(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        action_type="SITE_SURVEY",
        lead_external_id="LEAD-B2B-101",
        qualification_summary="Tower One - 480V 3-Phase Transformer Hum & Arcing",
        metadata_payload={
            "customer_name": "Tower One Facilities",
            "phone": "+15553337777",
            "address": "500 West Madison, Chicago, IL",
            "estimated_cost": 25000.00,
        },
    )
    db_session.add(lead)
    await db_session.commit()

    # 1. Test roster retrieval
    roster = partner_exchange_service.get_partner_network_roster(tenant)
    assert len(roster) >= 5
    specialties = [p.trade_specialty for p in roster]
    assert "Electrical" in specialties
    assert "Plumbing" in specialties

    # 2. Test referral dispatch to Electrical
    referral = await partner_exchange_service.dispatch_cross_trade_referral(
        action_id=lead.id,
        target_trade="Electrical",
        referring_tenant=tenant,
        db=db_session,
        estimated_job_value=25000.00,
        custom_service_needed="480V 3-Phase Service Disconnect Replacement",
    )

    assert referral.recipient_partner.trade_specialty == "Electrical"
    assert referral.estimated_job_value == 25000.00
    assert referral.finder_fee_due == 2500.00  # 10%
    assert referral.status == "DISPATCHED_TO_PARTNER"

    # Verify persistence on LeadAction
    await db_session.refresh(lead)
    assert lead.partner_exchange_data is not None
    assert lead.partner_exchange_data["finder_fee_due"] == 2500.00

    # Verify persistence in Tenant Settings
    tenant_referrals = partner_exchange_service.get_partner_referrals(tenant)
    assert len(tenant_referrals) == 1
    assert tenant_referrals[0].referral_id == referral.referral_id

    # 3. Test Fee Settlement
    settled = await partner_exchange_service.settle_finder_fee(
        referral_id=referral.referral_id,
        tenant=tenant,
        db=db_session,
    )
    assert settled is True
    updated_referrals = partner_exchange_service.get_partner_referrals(tenant)
    assert updated_referrals[0].status == "FEE_SETTLED"


@pytest.mark.asyncio
async def test_partner_exchange_endpoints(client: AsyncClient, db_session: AsyncSession):
    """Test console view, referral API dispatch, and settlement endpoint."""
    tenant = Tenant(
        id=uuid.uuid4(),
        name="Keystone Building Services",
        slug=f"keystone-bld-{uuid.uuid4().hex[:6]}",
        api_key_hash="hash",
        webhook_secret="secret",
        settings={"cross_trade_referrals": []},
    )
    db_session.add(tenant)

    lead = LeadAction(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        action_type="INSPECTION",
        lead_external_id="LEAD-B2B-202",
        qualification_summary="Oakridge Office - Roof Flashing Tear During HVAC Install",
        metadata_payload={
            "customer_name": "Oakridge Property Management",
            "phone": "+15558889900",
            "address": "8800 Oakridge Blvd, Austin, TX",
        },
    )
    db_session.add(lead)
    await db_session.commit()

    # 1. GET Partner Exchange Console View (HTML)
    resp_html = await client.get(f"/partner-exchange/{tenant.slug}")
    assert resp_html.status_code == 200
    assert "Cross-Trade Partner Exchange" in resp_html.text
    assert "Verified Commercial Trade Partner Network" in resp_html.text

    # 2. GET JSON view via format=json
    resp_json = await client.get(f"/partner-exchange/{tenant.slug}?format=json")
    assert resp_json.status_code == 200
    data = resp_json.json()
    assert data["partner_count"] >= 5
    assert "partners" in data

    # 3. POST Referral API
    dispatch_payload = {
        "target_trade": "Roofing",
        "estimated_job_value": 18000.0,
        "service_needed": "Commercial TPO Parapet Flashing Reseal",
    }
    resp_ref = await client.post(
        f"/api/v1/partner-exchange/refer/{lead.id}",
        json=dispatch_payload,
    )
    assert resp_ref.status_code == 200
    ref_data = resp_ref.json()
    assert ref_data["recipient_partner"]["trade_specialty"] == "Roofing"
    assert ref_data["finder_fee_due"] == 1800.0  # 10% of $18,000

    # 4. POST Settle Finder Fee
    ref_id = ref_data["referral_id"]
    resp_settle = await client.post(
        f"/api/v1/partner-exchange/settle/{ref_id}?tenant_slug={tenant.slug}"
    )
    assert resp_settle.status_code == 200
    assert resp_settle.json()["fee_status"] == "FEE_SETTLED"

    # 5. 404 for unknown tenant
    resp_404 = await client.get("/partner-exchange/nonexistent-tenant-slug")
    assert resp_404.status_code == 404
