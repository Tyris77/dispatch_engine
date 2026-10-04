import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lead_action import LeadAction
from app.models.tenant import Tenant
from app.schemas.technician_kpi import (
    CommissionJobItem,
    TechnicianMetrics,
    WeeklyCommissionStatement,
)
from app.services.technician_kpi import technician_kpi_service


@pytest.fixture
async def kpi_test_env(sample_tenant: dict, db_session: AsyncSession) -> dict:
    """Fixture providing a tenant and sample LeadActions with contracts, invoices, and memberships."""
    tenant = sample_tenant["tenant"]
    tenant.name = "Apex Mechanical & Electrical Services"
    tenant.settings = {
        "commission_rate_pct": 6.0,
        "membership_bonus_per_unit": 25.0,
        "on_call_roster": [
            {"name": "Marcus Vance", "phone": "+15551234567", "trade": "HVAC"},
            {"name": "Dave Miller", "phone": "+15552345678", "trade": "Plumbing"},
        ],
    }
    db_session.add(tenant)

    # Lead 1: Marcus Vance - Signed Contract $3,500 + Membership + Safety 96.0
    action1 = LeadAction(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        lead_external_id="+15551112233",
        qualification_score=0.92,
        qualification_summary="Dual heat pump replacement with 10-year warranty.",
        action_type="DISPATCH_EMERGENCY_DISPATCH_QUEUE",
        dispatch_status="COMPLETED",
        crm_sync_status="SYNCED",
        metadata_payload={
            "customer_name": "Gregory House",
            "assigned_technician": "Marcus Vance",
            "trade_type": "HVAC",
        },
        tracking_data={
            "technician_name": "Marcus Vance",
            "current_status": "COMPLETED",
        },
        signed_contract={
            "proposal_id": "prop-101",
            "total_amount": 3500.0,
            "status": "SIGNED",
        },
        membership_enrollment={
            "plan_name": "Gold Comfort Care",
            "billing_interval": "ANNUAL",
            "price": 288.0,
        },
        safety_data={
            "safety_score": 96,
            "compliance_status": "COMPLIANT",
        },
    )

    # Lead 2: Marcus Vance - Invoiced $1,200 (No membership)
    action2 = LeadAction(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        lead_external_id="+15552223344",
        qualification_score=0.88,
        qualification_summary="Blower motor capacitor and contactor rebuild.",
        action_type="DISPATCH_EMERGENCY_DISPATCH_QUEUE",
        dispatch_status="INVOICED",
        crm_sync_status="SYNCED",
        metadata_payload={
            "customer_name": "Lisa Cuddy",
            "assigned_technician": "Marcus Vance",
            "trade_type": "HVAC",
        },
        invoice_data={
            "contract_total": 1200.0,
            "balance_due": 0.0,
            "status": "PAID",
        },
        safety_data={
            "safety_score": 100,
            "compliance_status": "COMPLIANT",
        },
    )

    # Lead 3: Dave Miller - Proposal $800, Invoiced $800, 1 Membership
    action3 = LeadAction(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        lead_external_id="+15553334455",
        qualification_score=0.85,
        qualification_summary="Main drain line snake and hydro-jetting.",
        action_type="DISPATCH_EMERGENCY_DISPATCH_QUEUE",
        dispatch_status="COMPLETED",
        crm_sync_status="SYNCED",
        metadata_payload={
            "customer_name": "James Wilson",
            "assigned_technician": "Dave Miller",
            "trade_type": "Plumbing",
        },
        signed_contract={
            "proposal_id": "prop-103",
            "total_amount": 800.0,
        },
        membership_enrollment={
            "plan_name": "Diamond Plumbing Shield",
            "price": 199.0,
        },
    )

    db_session.add_all([action1, action2, action3])
    await db_session.commit()
    await db_session.refresh(tenant)

    return {
        "tenant": tenant,
        "actions": [action1, action2, action3],
    }


def test_technician_metrics_schemas():
    """Verify validation and serialization of TechnicianMetrics and WeeklyCommissionStatement."""
    metric = TechnicianMetrics(
        tech_name="Marcus Vance",
        phone="+15551234567",
        jobs_dispatched=10,
        jobs_completed=8,
        proposals_closed=6,
        closing_rate_pct=75.0,
        revenue_generated=14500.0,
        memberships_sold=4,
        safety_score_avg=97.5,
        commission_earned=970.0,
    )
    assert metric.tech_name == "Marcus Vance"
    assert metric.closing_rate_pct == 75.0
    assert metric.commission_earned == 970.0

    job_item = CommissionJobItem(
        job_id="job-101",
        customer_name="Gregory House",
        trade="HVAC",
        contract_total=3500.0,
        commission_rate_pct=6.0,
        commission_amount=210.0,
    )
    slip = WeeklyCommissionStatement(
        statement_id="COMM-2026-W40-001",
        tech_name="Marcus Vance",
        pay_period="Week 40 (Rolling 7-Day Performance Period)",
        itemized_jobs=[job_item],
        membership_bonuses=50.0,
        total_commission_payout=260.0,
    )
    assert slip.total_commission_payout == 260.0
    assert len(slip.itemized_jobs) == 1
    assert slip.statement_id.startswith("COMM-2026-")


@pytest.mark.asyncio
async def test_calculate_technician_scorecards_aggregation(
    kpi_test_env: dict,
    db_session: AsyncSession,
):
    """Verify scorecard calculation aggregates revenue, close rates, memberships, and commissions correctly."""
    tenant = kpi_test_env["tenant"]
    scorecards = await technician_kpi_service.calculate_technician_scorecards(tenant, db_session)

    assert len(scorecards) == 2
    # Marcus Vance had $3,500 + $1,200 = $4,700 revenue, Dave had $800
    # Marcus should be ranked first
    top_tech = scorecards[0]
    assert top_tech.tech_name == "Marcus Vance"
    assert top_tech.jobs_completed == 2
    assert top_tech.proposals_closed == 2
    assert top_tech.closing_rate_pct == 100.0
    assert top_tech.revenue_generated == 4700.0
    assert top_tech.memberships_sold == 1
    # Safety score avg: (96 + 100) / 2 = 98.0
    assert top_tech.safety_score_avg == 98.0
    # Commission: 6% of $4,700 ($282.00) + 1 membership * $25 = $307.00
    assert top_tech.commission_earned == 307.0

    second_tech = scorecards[1]
    assert second_tech.tech_name == "Dave Miller"
    assert second_tech.revenue_generated == 800.0
    assert second_tech.memberships_sold == 1
    # Commission: 6% of $800 ($48.00) + 1 membership * $25 = $73.00
    assert second_tech.commission_earned == 73.0


@pytest.mark.asyncio
async def test_generate_weekly_commission_slip(
    kpi_test_env: dict,
    db_session: AsyncSession,
):
    """Verify weekly pay slip itemizes jobs, calculates bonuses, and computes total net payout."""
    tenant = kpi_test_env["tenant"]
    slip = await technician_kpi_service.generate_weekly_commission_slip(
        tech_name="Marcus Vance",
        tenant=tenant,
        db=db_session,
    )

    assert isinstance(slip, WeeklyCommissionStatement)
    assert slip.tech_name == "Marcus Vance"
    assert len(slip.itemized_jobs) == 2
    assert slip.membership_bonuses == 25.0
    # Marcus job commissions: 6% of 3500 (210) + 6% of 1200 (72) = 282.00 + 25 = 307.00
    assert slip.total_commission_payout == 307.0


@pytest.mark.asyncio
async def test_generate_weekly_commission_slip_baseline_fallback(
    sample_tenant: dict,
    db_session: AsyncSession,
):
    """Verify commission slip falls back to baseline demonstration items when tech has no logged closed jobs."""
    tenant = sample_tenant["tenant"]
    slip = await technician_kpi_service.generate_weekly_commission_slip(
        tech_name="New Tech",
        tenant=tenant,
        db=db_session,
    )

    assert isinstance(slip, WeeklyCommissionStatement)
    assert slip.tech_name == "New Tech"
    assert len(slip.itemized_jobs) == 2
    assert slip.total_commission_payout > 0


@pytest.mark.asyncio
async def test_get_technicians_portal_html(
    kpi_test_env: dict,
    client: AsyncClient,
):
    """GET /technicians/{tenant_slug} renders technician leaderboard HTML."""
    tenant = kpi_test_env["tenant"]
    resp = await client.get(f"/technicians/{tenant.slug}")
    assert resp.status_code == 200
    html = resp.text
    assert "Technician Performance Scorecards" in html
    assert "Marcus Vance" in html
    assert "Dave Miller" in html
    assert "Print Pay Slip" in html or "Pay Slip" in html


@pytest.mark.asyncio
async def test_get_technicians_portal_json_format(
    kpi_test_env: dict,
    client: AsyncClient,
):
    """GET /technicians/{tenant_slug}?format=json returns serialized scorecards."""
    tenant = kpi_test_env["tenant"]
    resp = await client.get(f"/technicians/{tenant.slug}?format=json")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 2
    assert data[0]["tech_name"] == "Marcus Vance"
    assert data[0]["revenue_generated"] == 4700.0


@pytest.mark.asyncio
async def test_get_technicians_portal_not_found(client: AsyncClient):
    """GET /technicians/{unknown_slug} returns 404."""
    resp = await client.get("/technicians/non-existent-tenant-xyz")
    assert resp.status_code == 404
    assert "not found" in resp.text.lower()


@pytest.mark.asyncio
async def test_get_technician_commission_slip_html(
    kpi_test_env: dict,
    client: AsyncClient,
):
    """GET /technicians/{tenant_slug}/commission/{tech_name} renders printable voucher."""
    tenant = kpi_test_env["tenant"]
    resp = await client.get(f"/technicians/{tenant.slug}/commission/Marcus%20Vance")
    assert resp.status_code == 200
    html = resp.text
    assert "OFFICIAL PAYROLL VOUCHER" in html or "Payroll Voucher" in html or "Commission" in html
    assert "Marcus Vance" in html
    assert "Net Commission Payout" in html or "$307.00" in html


@pytest.mark.asyncio
async def test_get_technician_commission_slip_json(
    kpi_test_env: dict,
    client: AsyncClient,
):
    """GET /technicians/{tenant_slug}/commission/{tech_name}?format=json returns statement JSON."""
    tenant = kpi_test_env["tenant"]
    resp = await client.get(f"/technicians/{tenant.slug}/commission/Marcus%20Vance?format=json")
    assert resp.status_code == 200
    data = resp.json()
    assert data["tech_name"] == "Marcus Vance"
    assert data["total_commission_payout"] == 307.0
    assert len(data["itemized_jobs"]) == 2


@pytest.mark.asyncio
async def test_api_get_technician_scorecards(
    kpi_test_env: dict,
    client: AsyncClient,
):
    """GET /api/v1/technicians/{tenant_slug}/scorecards returns structured scorecard list."""
    tenant = kpi_test_env["tenant"]
    resp = await client.get(f"/api/v1/technicians/{tenant.slug}/scorecards")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert data[0]["tech_name"] == "Marcus Vance"
    assert data[0]["commission_earned"] == 307.0


@pytest.mark.asyncio
async def test_api_get_technician_commission(
    kpi_test_env: dict,
    client: AsyncClient,
):
    """GET /api/v1/technicians/{tenant_slug}/commission/{tech_name} returns structured statement."""
    tenant = kpi_test_env["tenant"]
    resp = await client.get(f"/api/v1/technicians/{tenant.slug}/commission/Marcus%20Vance")
    assert resp.status_code == 200
    data = resp.json()
    assert data["tech_name"] == "Marcus Vance"
    assert data["total_commission_payout"] == 307.0
