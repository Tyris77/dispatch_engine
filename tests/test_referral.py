import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lead_action import LeadAction
from app.models.tenant import Tenant
from app.schemas.referral import (
    ReferralClaimResponse,
    ReferralClaimSubmission,
    ReferralVoucher,
)
from app.services.referral import referral_service


@pytest.fixture
async def referral_test_data(sample_tenant: dict, db_session: AsyncSession) -> dict:
    """Fixture providing tenant and completed LeadAction for referral voucher generation."""
    tenant = sample_tenant["tenant"]
    tenant.name = "Apex Precision Comfort Heating and Air"
    db_session.add(tenant)

    await db_session.commit()
    await db_session.refresh(tenant)

    # Completed LeadAction with paid invoice and customer info

    lead = LeadAction(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        lead_external_id="+15559876543",
        qualification_score=0.92,
        qualification_summary="Residential complete heat pump compressor overhaul.",
        action_type="DISPATCH_ROUTED",
        dispatch_status="COMPLETED",
        crm_sync_status="SYNCED",
        metadata_payload={
            "customer_name": "Eleanor Vance",
            "customer_phone": "+15559876543",
            "address": "1402 Oak Grove Ln, Austin, TX 78704",
            "trade_type": "HVAC",
        },
        signed_contract={
            "customer_name": "Eleanor Vance",
            "customer_phone": "+15559876543",
            "price_total": 4850.0,
            "selected_tier": "Premium Inverter Heat Pump",
        },
        invoice_data={
            "invoice_number": "INV-2026-9012",
            "contract_total": 4850.0,
            "payment_status": "PAID",
        },
    )
    db_session.add(lead)
    await db_session.commit()
    await db_session.refresh(lead)

    return {"tenant": tenant, "lead": lead}


def test_referral_schemas():
    """Verify validation and serialization of ReferralVoucher and ReferralClaimSubmission."""
    voucher = ReferralVoucher(
        referral_code="REF-APEX-A8F192",
        referrer_name="Eleanor Vance",
        referrer_phone="+15559876543",
        discount_amount=150.0,
        reward_amount=100.0,
        shareable_url="/refer/12345678-1234-5678-1234-567812345678",
        conversions_count=2,
        rewards_earned=200.0,
        tenant_name="Apex Precision",
        tenant_slug="apex-precision",
    )
    assert voucher.referral_code == "REF-APEX-A8F192"
    assert voucher.discount_amount == 150.0
    assert voucher.reward_amount == 100.0
    assert voucher.conversions_count == 2
    assert voucher.rewards_earned == 200.0

    submission = ReferralClaimSubmission(
        referral_code="REF-APEX-A8F192",
        neighbor_name="David Miller",
        neighbor_phone="+15553332211",
        service_needed="AC blowing room temperature air during heat wave",
        address="1406 Oak Grove Ln, Austin, TX 78704",
        photo_notes="Rooftop condenser unit",
    )
    assert submission.referral_code == "REF-APEX-A8F192"
    assert submission.neighbor_name == "David Miller"
    assert submission.neighbor_phone == "+15553332211"

    response = ReferralClaimResponse(
        success=True,
        message="Voucher redeemed!",
        referral_code="REF-APEX-A8F192",
        new_action_id="some-uuid",
        discount_applied=150.0,
        neighbor_name="David Miller",
    )
    assert response.success is True
    assert response.discount_applied == 150.0


@pytest.mark.asyncio
async def test_referral_service_generate_voucher(
    referral_test_data: dict,
    db_session: AsyncSession,
):
    """Verify referral service generates voucher and populates lead_action.referral_data."""
    tenant = referral_test_data["tenant"]
    lead = referral_test_data["lead"]

    voucher = referral_service.generate_referral_voucher(
        lead_action=lead,
        tenant=tenant,
        base_url="https://dispatch.apex.com",
    )

    assert voucher.referral_code.startswith("REF-")
    assert voucher.referrer_name == "Eleanor Vance"
    assert voucher.referrer_phone == "+15559876543"
    assert voucher.discount_amount == 150.0
    assert voucher.reward_amount == 100.0
    assert str(lead.id) in voucher.shareable_url
    assert voucher.conversions_count == 0
    assert voucher.rewards_earned == 0.0

    # Ensure lead.referral_data is persisted
    assert lead.referral_data is not None
    assert lead.referral_data["referral_code"] == voucher.referral_code


@pytest.mark.asyncio
async def test_referral_service_claim_processing(
    referral_test_data: dict,
    db_session: AsyncSession,
):
    """Verify claim processing credits referring customer $100 and creates new LeadAction."""
    tenant = referral_test_data["tenant"]
    lead = referral_test_data["lead"]

    voucher = referral_service.generate_referral_voucher(lead, tenant)
    await db_session.commit()

    submission = ReferralClaimSubmission(
        referral_code=voucher.referral_code,
        neighbor_name="Marcus Vance",
        neighbor_phone="+15554443322",
        service_needed="Emergency condenser fan motor breakdown",
        address="1410 Oak Grove Ln, Austin, TX 78704",
        photo_notes="Carrier Infinity unit serial tag",
    )

    claim_resp = await referral_service.process_referral_claim(
        submission=submission,
        tenant=tenant,
        db=db_session,
    )

    assert claim_resp.success is True
    assert claim_resp.discount_applied == 150.0
    assert claim_resp.neighbor_name == "Marcus Vance"
    assert claim_resp.new_action_id is not None

    # Check referrer rewards updated
    await db_session.refresh(lead)
    assert lead.referral_data["conversions_count"] == 1
    assert lead.referral_data["rewards_earned"] == 100.0
    assert len(lead.referral_data["conversions"]) == 1

    # Check tenant referral metrics
    metrics = await referral_service.get_tenant_referral_metrics(tenant, db_session)
    assert metrics["total_vouchers_issued"] == 1
    assert metrics["total_conversions"] == 1
    assert metrics["total_rewards_paid"] == 100.0
    assert metrics["total_discounts_granted"] == 150.0


@pytest.mark.asyncio
async def test_referral_voucher_html_view(
    client: AsyncClient,
    referral_test_data: dict,
    db_session: AsyncSession,
):
    """Verify GET /refer/{action_id} renders dark #0B0F19 mobile voucher page."""
    tenant = referral_test_data["tenant"]
    lead = referral_test_data["lead"]

    resp = await client.get(f"/refer/{lead.id}")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    html = resp.text

    assert "Eleanor Vance" in html
    assert "$150" in html
    assert tenant.name in html
    assert "Claim $150 Voucher" in html
    assert "1-Tap Emergency Booking & Camera Quote" in html
    assert "Property / Service Address" in html


@pytest.mark.asyncio
async def test_referral_claim_api_submission(
    client: AsyncClient,
    referral_test_data: dict,
    db_session: AsyncSession,
):
    """Verify POST /refer/{action_id}/claim processes neighbor claim and creates new lead."""
    lead = referral_test_data["lead"]

    payload = {
        "referral_code": f"REF-TEST-{str(lead.id)[:6].upper()}",
        "neighbor_name": "Sarah Connor",
        "neighbor_phone": "+15557778899",
        "service_needed": "Water heater leaking into garage",
        "address": "1420 Oak Grove Ln, Austin, TX 78704",
        "photo_notes": "50 gallon Bradford White gas unit",
    }

    resp = await client.post(f"/refer/{lead.id}/claim", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["discount_applied"] == 150.0
    assert data["neighbor_name"] == "Sarah Connor"
    assert data["new_action_id"] is not None


@pytest.mark.asyncio
async def test_referral_rest_json_endpoints(
    client: AsyncClient,
    referral_test_data: dict,
    db_session: AsyncSession,
):

    """Verify JSON content negotiation and direct REST endpoints for referral voucher."""
    lead = referral_test_data["lead"]

    # Endpoint 1: format=json on /refer/{action_id}
    resp1 = await client.get(f"/refer/{lead.id}?format=json")
    assert resp1.status_code == 200
    data1 = resp1.json()
    assert data1["referrer_name"] == "Eleanor Vance"
    assert data1["discount_amount"] == 150.0
    assert data1["reward_amount"] == 100.0

    # Endpoint 2: GET /api/v1/referral/{action_id}
    resp2 = await client.get(f"/api/v1/referral/{lead.id}")
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["referral_code"] == data1["referral_code"]

    # 404 test
    fake_id = str(uuid.uuid4())
    resp_404 = await client.get(f"/api/v1/referral/{fake_id}")
    assert resp_404.status_code == 404
