import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lead_action import LeadAction
from app.models.tenant import Tenant
from app.schemas.financing import (
    FinancingBreakdown,
    FinancingPlanOption,
    FinancingSelectionSubmission,
)
from app.schemas.proposal import ContractSignatureSubmission
from app.services.financing import financing_service


def test_financing_schemas():
    """Verify serialization and validation of financing plan options and breakdowns."""
    opt = FinancingPlanOption(
        plan_name="0% APR 18-Mo Promo",
        interest_rate_pct=0.0,
        term_months=18,
        monthly_payment_estimate=277.78,
        total_financed_amount=5000.0,
        lender_partner="Wisetack Consumer Finance",
    )
    assert opt.plan_name == "0% APR 18-Mo Promo"
    assert opt.monthly_payment_estimate == 277.78
    assert opt.interest_rate_pct == 0.0

    breakdown = FinancingBreakdown(
        cash_price=5500.0,
        deposit_required=500.0,
        financed_principal=5000.0,
        plans=[opt],
    )
    assert breakdown.financed_principal == 5000.0
    assert len(breakdown.plans) == 1

    submission = FinancingSelectionSubmission(
        tier_name="Premium High-Efficiency",
        plan_name="Low Monthly 60-Mo Fixed",
        term_months=60,
        interest_rate_pct=7.99,
        monthly_payment=101.38,
        total_financed_amount=6082.80,
    )
    assert submission.monthly_payment == 101.38
    assert submission.term_months == 60


def test_financing_service_amortization_math():
    """Verify promotional 0% same-as-cash and standard compound interest amortization formulas."""
    # 0% interest on $1,800 over 18 months = $100.00/mo
    m_promo = financing_service._compute_amortized_monthly(1800.0, apr_pct=0.0, months=18)
    assert m_promo == 100.0

    # 0 principal edge cases
    assert financing_service._compute_amortized_monthly(0.0, apr_pct=7.99, months=60) == 0.0
    assert financing_service._compute_amortized_monthly(1000.0, apr_pct=7.99, months=0) == 0.0

    # Compound amortization formula: P = $6,000, APR = 7.99%, n = 60 months
    # Formula: r = 0.0799 / 12 = 0.00665833
    # Monthly payment approx $121.61
    m_fixed = financing_service._compute_amortized_monthly(6000.0, apr_pct=7.99, months=60)
    assert 120.0 <= m_fixed <= 123.0


def test_calculate_financing_plans_breakdown():
    """Verify calculate_financing_plans produces all 3 tiers with customizable tenant settings."""
    settings = {
        "financing_fixed_60_apr": 7.50,
        "financing_long_term_apr": 8.99,
        "financing_lender_partner": "Synchrony Financial / TradeOps",
    }
    breakdown = financing_service.calculate_financing_plans(
        cash_price=9000.0,
        deposit=1000.0,
        tenant_settings=settings,
    )

    assert breakdown.cash_price == 9000.0
    assert breakdown.deposit_required == 1000.0
    assert breakdown.financed_principal == 8000.0
    assert len(breakdown.plans) == 3

    # Plan 1: 0% APR 18-Mo
    p1 = breakdown.plans[0]
    assert p1.plan_name == "0% APR 18-Mo Promo"
    assert p1.interest_rate_pct == 0.0
    assert p1.term_months == 18
    assert p1.monthly_payment_estimate == round(8000.0 / 18.0, 2)
    assert p1.lender_partner == "Synchrony Financial / TradeOps"

    # Plan 2: 60-Month Fixed
    p2 = breakdown.plans[1]
    assert p2.plan_name == "Low Monthly 60-Mo Fixed"
    assert p2.interest_rate_pct == 7.50
    assert p2.term_months == 60
    assert p2.monthly_payment_estimate > 0.0

    # Plan 3: 120-Month Standard
    p3 = breakdown.plans[2]
    assert p3.plan_name == "Standard 120-Mo"
    assert p3.interest_rate_pct == 8.99
    assert p3.term_months == 120
    assert p3.monthly_payment_estimate < p2.monthly_payment_estimate


@pytest.mark.asyncio
async def test_proposal_view_contains_financing_breakdowns(
    client: AsyncClient,
    db_session: AsyncSession,
    sample_tenant: dict,
):
    """Verify GET /proposal/{action_id} returns financing breakdown data in JSON and renders in HTML."""
    tenant: Tenant = sample_tenant["tenant"]
    tenant.name = "Apex Mechanical & HVAC Solutions"
    tenant.settings = {
        "financing_fixed_60_apr": 7.99,
        "financing_long_term_apr": 9.99,
        "financing_lender_partner": "Wisetack / TradeOps Consumer Finance",
    }
    db_session.add(tenant)

    action = LeadAction(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        lead_external_id="+15554443322",
        qualification_score=0.92,
        qualification_summary="Dual-fuel heat pump inverter system replacement.",
        action_type="DISPATCH_EMERGENCY_DISPATCH_QUEUE",
        dispatch_status="ROUTED",
        crm_sync_status="PENDING",
        metadata_payload={
            "customer_name": "Eleanor Vance",
            "caller_phone": "+15554443322",
            "address": "1200 Barton Springs Rd, Austin, TX",
            "trade_type": "HVAC",
        },
    )
    db_session.add(action)
    await db_session.commit()

    # 1. JSON Mode
    resp_json = await client.get(f"/proposal/{action.id}?format=json")
    assert resp_json.status_code == 200
    data = resp_json.json()
    assert "financing_breakdowns" in data
    assert len(data["financing_breakdowns"]) > 0

    # Verify options in breakdown
    first_tier = next(iter(data["financing_breakdowns"].values()))
    assert "plans" in first_tier
    assert len(first_tier["plans"]) == 3
    assert first_tier["plans"][0]["plan_name"] == "0% APR 18-Mo Promo"

    # 2. HTML Mode
    resp_html = await client.get(f"/proposal/{action.id}")
    assert resp_html.status_code == 200
    html_text = resp_html.text
    assert "Monthly Financing" in html_text
    assert "Pay in Full" in html_text
    assert "Instant Financing Pre-Qualification" in html_text
    assert "prequal-modal" in html_text


@pytest.mark.asyncio
async def test_proposal_accept_records_financing_selection(
    client: AsyncClient,
    db_session: AsyncSession,
    sample_tenant: dict,
):
    """Verify accepting proposal with financing plan locks contract and records financing_selection in DB."""
    tenant: Tenant = sample_tenant["tenant"]
    action = LeadAction(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        lead_external_id="+15554443322",
        qualification_score=0.92,
        qualification_summary="Dual-fuel heat pump inverter system replacement.",
        action_type="DISPATCH_EMERGENCY_DISPATCH_QUEUE",
        dispatch_status="ROUTED",
        crm_sync_status="PENDING",
        metadata_payload={
            "customer_name": "Eleanor Vance",
            "caller_phone": "+15554443322",
            "address": "1200 Barton Springs Rd, Austin, TX",
            "trade_type": "HVAC",
        },
    )
    db_session.add(action)
    await db_session.commit()

    payload = {
        "selected_tier": "Standard Replacement",
        "signature_base64": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
        "customer_name": "Eleanor Vance",
        "customer_phone": "+15554443322",
        "financing_plan": "Low Monthly 60-Mo Fixed",
        "financing_monthly_payment": 128.50,
    }

    resp = await client.post(
        f"/proposal/{action.id}/accept",
        json=payload,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["financing_selected"] is True
    assert data["financing_selection"]["plan_name"] == "Low Monthly 60-Mo Fixed"
    assert data["financing_selection"]["monthly_payment"] == 128.50
    assert data["contract"]["financing_plan"] == "Low Monthly 60-Mo Fixed"

    # Verify DB persistence
    await db_session.refresh(action)
    assert action.financing_selection is not None
    assert action.financing_selection["plan_name"] == "Low Monthly 60-Mo Fixed"
    assert action.financing_selection["monthly_payment"] == 128.50
    assert action.financing_selection["status"] == "APPROVED_PREQUALIFIED"

    # Verify HTML signed state displays financing
    signed_resp = await client.get(f"/proposal/{action.id}")
    assert signed_resp.status_code == 200
    assert "Payment Option" in signed_resp.text
    assert "Low Monthly 60-Mo Fixed" in signed_resp.text
