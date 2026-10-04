import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lead_action import LeadAction
from app.models.tenant import Tenant
from app.schemas.membership import (
    MembershipEnrollmentRecord,
    MembershipEnrollmentRequest,
    MembershipOfferCalculation,
    MembershipPlan,
)
from app.schemas.proposal import ProposalEstimate, ProposalOption
from app.services.proposal import calculate_membership_offer, generate_tiered_proposal


def test_membership_schemas():
    """Verify MembershipPlan and MembershipEnrollment schemas validate correctly."""
    plan = MembershipPlan(
        name="Comfort Club VIP",
        monthly_price=19.99,
        discount_pct=15.0,
        perks=["Annual Tune-up", "Priority Dispatch", "$0 Trip Fee"],
    )
    assert plan.name == "Comfort Club VIP"
    assert plan.monthly_price == 19.99
    assert plan.discount_pct == 15.0
    assert len(plan.perks) == 3

    req = MembershipEnrollmentRequest(
        plan_name="Comfort Club VIP",
        monthly_price=19.99,
        discount_pct=15.0,
        customer_name="John Doe",
        customer_phone="+15551234567",
    )
    assert req.plan_name == "Comfort Club VIP"
    assert req.monthly_price == 19.99

    record = MembershipEnrollmentRecord(
        status="ACTIVE",
        plan_name="Comfort Club VIP",
        monthly_price=19.99,
        discount_pct=15.0,
        discount_amount=120.0,
        original_price=800.0,
        discounted_price=680.0,
        stripe_subscription_id="sub_sim_12345",
        enrolled_at="2026-10-03T14:00:00Z",
    )
    assert record.stripe_subscription_id == "sub_sim_12345"
    assert record.status == "ACTIVE"


def test_calculate_membership_offer():
    """Verify calculate_membership_offer computes correct discount savings and discounted price."""
    plan = MembershipPlan(
        name="Platinum Shield",
        monthly_price=24.99,
        discount_pct=20.0,
        perks=["Free Filters", "20% off all repairs"],
    )

    offer = calculate_membership_offer(tier_price=600.0, tenant_settings={"membership_plans": [plan.model_dump()]})
    assert offer["plan"]["name"] == "Platinum Shield"
    assert offer["original_price"] == 600.0
    assert offer["discount_pct"] == 20.0
    # 20% of 600 = 120.0
    assert offer["discount_amount"] == 120.0
    assert offer["discounted_price"] == 480.0


@pytest.mark.asyncio
async def test_proposal_page_renders_membership_upsell(
    client: AsyncClient,
    db_session: AsyncSession,
    sample_tenant: dict,
):
    """Verify GET /proposal/{action_id} renders VIP Membership toggle and plan details."""
    tenant: Tenant = sample_tenant["tenant"]
    tenant.settings = {
        **tenant.settings,
        "membership_plans": [
            {
                "name": "Diamond Comfort Club",
                "monthly_price": 29.99,
                "discount_pct": 18.0,
                "perks": ["2 Tune-ups/yr", "No Emergency Surcharge"],
            }
        ],
    }
    await db_session.commit()

    action = LeadAction(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        lead_external_id="+15554443322",
        action_type="DISPATCH_ROUTED",
        dispatch_status="QUEUED",
        crm_sync_status="PENDING",
        metadata_payload={"caller_phone": "+15554443322"},
    )
    db_session.add(action)
    await db_session.commit()

    response = await client.get(f"/proposal/{action.id}")
    assert response.status_code == 200
    assert "Diamond Comfort Club" in response.text
    assert "$29.99/month" in response.text
    assert "SAVE <span id=\"vip-discount-pct\">18%</span> TODAY" in response.text
    assert "membership-toggle" in response.text
    assert "toggleMembership(this.checked)" in response.text


@pytest.mark.asyncio
async def test_proposal_json_includes_membership_plan_and_offer(
    client: AsyncClient,
    db_session: AsyncSession,
    sample_tenant: dict,
):
    """Verify GET /proposal/{action_id}?format=json includes membership_plan and membership_offer."""
    tenant: Tenant = sample_tenant["tenant"]

    action = LeadAction(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        lead_external_id="+15558881122",
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
    assert "membership_plan" in data
    assert data["membership_plan"] is not None
    assert "membership_offer" in data
    assert data["membership_offer"]["discount_pct"] > 0


@pytest.mark.asyncio
async def test_post_proposal_accept_with_membership_enrollment(
    client: AsyncClient,
    db_session: AsyncSession,
    sample_tenant: dict,
):
    """Verify POST /proposal/{action_id}/accept saves membership enrollment and applies discount."""
    tenant: Tenant = sample_tenant["tenant"]
    tenant.settings = {
        **tenant.settings,
        "membership_plans": [
            {
                "name": "Comfort Club VIP",
                "monthly_price": 19.99,
                "discount_pct": 15.0,
                "perks": ["Annual Tune-up", "Priority Dispatch"],
            }
        ],
    }
    await db_session.commit()

    action = LeadAction(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        lead_external_id="+15559998877",
        action_type="DISPATCH_ROUTED",
        dispatch_status="QUEUED",
        crm_sync_status="PENDING",
        metadata_payload={"caller_phone": "+15559998877"},
    )
    db_session.add(action)
    await db_session.commit()

    sig_data = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
    json_payload = {
        "selected_tier": "Standard Replacement",
        "signature_base64": sig_data,
        "customer_name": "Eleanor Vance",
        "customer_phone": "+15559998877",
        "enroll_membership": True,
        "membership_plan_name": "Comfort Club VIP",
    }

    response = await client.post(
        f"/proposal/{action.id}/accept",
        json=json_payload,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["membership_enrolled"] is True
    assert data["membership_details"]["status"] == "ACTIVE"
    assert data["membership_details"]["monthly_price"] == 19.99
    assert data["membership_details"]["discount_applied"] > 0
    assert data["membership_details"]["subscription_id"].startswith("sub_sim_")

    # Refresh DB session and verify persisted state
    await db_session.refresh(action)
    assert action.membership_enrollment is not None
    assert action.membership_enrollment["status"] == "ACTIVE"
    assert action.membership_enrollment["plan_name"] == "Comfort Club VIP"
    assert action.signed_contract["membership_enrolled"] is True
    assert action.signed_contract["final_price"] < action.signed_contract["original_price"]


@pytest.mark.asyncio
async def test_client_portal_membership_kpi_banner(
    client: AsyncClient,
    db_session: AsyncSession,
    sample_tenant: dict,
):
    """Verify client portal displays Active Memberships and Contractor MRR ($/mo)."""
    tenant: Tenant = sample_tenant["tenant"]
    api_key: str = sample_tenant["raw_api_key"]

    # Create 2 lead actions with active membership enrollments
    action1 = LeadAction(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        lead_external_id="+15551112233",
        action_type="CONTRACT_SIGNED",
        dispatch_status="CONFIRMED",
        crm_sync_status="PENDING",
        metadata_payload={},
        membership_enrollment={
            "plan_name": "Comfort Club",
            "monthly_price": 19.99,
            "status": "ACTIVE",
            "subscription_id": "sub_sim_aaa",
        },
    )
    action2 = LeadAction(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        lead_external_id="+15552223344",
        action_type="CONTRACT_SIGNED",
        dispatch_status="CONFIRMED",
        crm_sync_status="PENDING",
        metadata_payload={},
        membership_enrollment={
            "plan_name": "Premium Protection",
            "monthly_price": 29.99,
            "status": "ACTIVE",
            "subscription_id": "sub_sim_bbb",
        },
    )
    db_session.add_all([action1, action2])
    await db_session.commit()

    response = await client.get(
        f"/portal/{tenant.slug}?api_key={api_key}",
    )
    assert response.status_code == 200
    assert "Active Memberships" in response.text
    assert "Contractor MRR ($/mo)" in response.text
    # 2 active memberships, total MRR = 19.99 + 29.99 = 49.98
    assert ">2</p>" in response.text or ">2<" in response.text
    assert "$49.98" in response.text
