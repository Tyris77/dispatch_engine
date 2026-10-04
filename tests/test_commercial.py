import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tenant import Tenant
from app.schemas.commercial import (
    CommercialWorkOrder,
    ConsolidatedMonthlyStatement,
    PropertyPortfolio,
)
from app.services.commercial import commercial_service


def test_commercial_schemas():
    """Verify validation and serialization of commercial property manager schemas."""
    portfolio = PropertyPortfolio(
        portfolio_id="port-101",
        property_name="Meridian Lofts",
        property_address="1401 S Joyce St, Arlington, VA",
        unit_count=120,
        manager_name="Elena Rostova",
        manager_phone="+17035550182",
        manager_email="elena@meridian.com",
        auto_approval_threshold=600.0,
    )
    assert portfolio.auto_approval_threshold == 600.0
    assert portfolio.unit_count == 120

    wo = CommercialWorkOrder(
        order_id="WO-101A",
        property_name="Meridian Lofts",
        unit_number="Apt 304",
        tenant_name="Jane Doe",
        issue_description="Leaking garbage disposal",
        estimated_cost=285.0,
        approval_status="APPROVED_AUTO",
        action_id=str(uuid.uuid4()),
        portfolio_id="port-101",
    )
    assert wo.approval_status == "APPROVED_AUTO"
    assert wo.estimated_cost == 285.0

    stmt = ConsolidatedMonthlyStatement(
        statement_id="STM-2026-10-01",
        billing_period="October 2026",
        itemized_orders=[wo.model_dump()],
        total_billed=285.0,
        payment_terms="NET_30",
        due_date="2026-11-04",
    )
    assert stmt.total_billed == 285.0
    assert stmt.payment_terms == "NET_30"


def test_estimate_repair_cost():
    """Verify scope keyword cost estimation engine."""
    assert commercial_service.estimate_repair_cost("Rooftop RTU compressor failed") == 1450.0
    assert commercial_service.estimate_repair_cost("Water heater leaking from bottom") == 580.0
    assert commercial_service.estimate_repair_cost("Clogged kitchen sink faucet") == 285.0


@pytest.mark.asyncio
async def test_process_commercial_request_auto_approved(db_session: AsyncSession):
    """Verify request below threshold automatically approves and schedules."""
    tenant = Tenant(
        id=uuid.uuid4(),
        name="Titan Commercial Services",
        slug=f"titan-comm-{uuid.uuid4().hex[:6]}",
        api_key_hash="hash",
        webhook_secret="secret",
        is_active=True,
        settings={"base_url": "http://testserver"},
    )
    db_session.add(tenant)
    await db_session.commit()

    portfolio = PropertyPortfolio(
        portfolio_id="meridian-test",
        property_name="Meridian Test Tower",
        property_address="100 Crystal Dr, Arlington, VA",
        unit_count=50,
        manager_name="Elena Rostova",
        manager_phone="+17035550182",
        manager_email="elena@meridian.com",
        auto_approval_threshold=500.0,
    )

    # Issue with $285 cost <= $500 threshold
    wo = await commercial_service.process_commercial_tenant_request(
        portfolio=portfolio,
        unit_number="Unit 204",
        tenant_name="Alice Smith",
        issue_text="Dripping bathroom faucet",
        tenant=tenant,
        db=db_session,
    )

    assert wo.approval_status == "APPROVED_AUTO"
    assert wo.estimated_cost == 285.0
    assert wo.action_id != ""
    assert wo.approval_link is None


@pytest.mark.asyncio
async def test_process_commercial_request_pending_approval(db_session: AsyncSession):
    """Verify request above threshold flags for PM approval and generates 1-tap link."""
    tenant = Tenant(
        id=uuid.uuid4(),
        name="Titan Commercial Services",
        slug=f"titan-comm-{uuid.uuid4().hex[:6]}",
        api_key_hash="hash",
        webhook_secret="secret",
        is_active=True,
        settings={"base_url": "http://testserver"},
    )
    db_session.add(tenant)
    await db_session.commit()

    portfolio = PropertyPortfolio(
        portfolio_id="meridian-test-2",
        property_name="Meridian Test Tower",
        property_address="100 Crystal Dr, Arlington, VA",
        unit_count=50,
        manager_name="Elena Rostova",
        manager_phone="+17035550182",
        manager_email="elena@meridian.com",
        auto_approval_threshold=500.0,
    )

    # Issue with $1450 cost > $500 threshold
    wo = await commercial_service.process_commercial_tenant_request(
        portfolio=portfolio,
        unit_number="Suite 500",
        tenant_name="Capital Financial Group",
        issue_text="Main RTU compressor burnout with electrical panel tripping",
        tenant=tenant,
        db=db_session,
    )

    assert wo.approval_status == "PENDING_PM_APPROVAL"
    assert wo.estimated_cost == 1450.0
    assert wo.approval_link is not None
    assert f"approve={wo.order_id}" in wo.approval_link


@pytest.mark.asyncio
async def test_approve_commercial_work_order(db_session: AsyncSession):
    """Verify 1-tap approval execution updates status and triggers dispatch."""
    tenant = Tenant(
        id=uuid.uuid4(),
        name="Titan Commercial Services",
        slug=f"titan-comm-{uuid.uuid4().hex[:6]}",
        api_key_hash="hash",
        webhook_secret="secret",
        is_active=True,
        settings={},
    )
    db_session.add(tenant)
    await db_session.commit()

    portfolio = PropertyPortfolio(
        portfolio_id="meridian-test-3",
        property_name="Meridian Test Tower",
        property_address="100 Crystal Dr, Arlington, VA",
        unit_count=50,
        manager_name="Elena Rostova",
        manager_phone="+17035550182",
        manager_email="elena@meridian.com",
        auto_approval_threshold=500.0,
    )

    wo = await commercial_service.process_commercial_tenant_request(
        portfolio=portfolio,
        unit_number="Suite 601",
        tenant_name="Summit Legal",
        issue_text="Boiler circulation pump replacement",
        tenant=tenant,
        db=db_session,
    )
    assert wo.approval_status == "PENDING_PM_APPROVAL"

    # Execute 1-tap approval
    approved = await commercial_service.approve_commercial_work_order(
        order_id=wo.order_id,
        tenant=tenant,
        db=db_session,
    )
    assert approved is not None
    assert approved.approval_status == "APPROVED_BY_PM"


@pytest.mark.asyncio
async def test_generate_consolidated_statement(db_session: AsyncSession):
    """Verify consolidated statement aggregation and Net-30 terms."""
    tenant = Tenant(
        id=uuid.uuid4(),
        name="Titan Commercial Services",
        slug=f"titan-comm-{uuid.uuid4().hex[:6]}",
        api_key_hash="hash",
        webhook_secret="secret",
        is_active=True,
        settings={},
    )
    db_session.add(tenant)
    await db_session.commit()

    statement = await commercial_service.generate_consolidated_statement(
        portfolio_id="meridian-pentagon",
        billing_period="October 2026",
        db=db_session,
        tenant=tenant,
    )
    assert statement.payment_terms == "NET_30"
    assert statement.total_billed > 0
    assert len(statement.itemized_orders) > 0
    assert statement.due_date is not None


@pytest.mark.asyncio
async def test_get_commercial_portal_html(client: AsyncClient, db_session: AsyncSession):
    """Verify commercial portal HTML dashboard rendering."""
    tenant = Tenant(
        id=uuid.uuid4(),
        name="Apex Commercial Property Solutions",
        slug=f"apex-comm-{uuid.uuid4().hex[:6]}",
        api_key_hash="hash",
        webhook_secret="secret",
        is_active=True,
        settings={},
    )
    db_session.add(tenant)
    await db_session.commit()

    resp = await client.get(f"/commercial/{tenant.slug}")
    assert resp.status_code == 200
    assert "Commercial Property Manager Portal" in resp.text
    assert tenant.name in resp.text
    assert "Consolidated Monthly Statement" in resp.text


@pytest.mark.asyncio
async def test_get_commercial_portal_json(client: AsyncClient, db_session: AsyncSession):
    """Verify commercial portal REST JSON serialization."""
    tenant = Tenant(
        id=uuid.uuid4(),
        name="Apex Commercial Property Solutions",
        slug=f"apex-comm-{uuid.uuid4().hex[:6]}",
        api_key_hash="hash",
        webhook_secret="secret",
        is_active=True,
        settings={},
    )
    db_session.add(tenant)
    await db_session.commit()

    resp = await client.get(f"/commercial/{tenant.slug}?format=json")
    assert resp.status_code == 200
    data = resp.json()
    assert data["tenant_slug"] == tenant.slug
    assert "portfolios" in data
    assert "work_orders" in data
    assert "statement" in data
    assert data["total_units"] > 0


@pytest.mark.asyncio
async def test_post_commercial_approve_endpoint(client: AsyncClient, db_session: AsyncSession):
    """Verify 1-tap approval REST endpoint."""
    tenant = Tenant(
        id=uuid.uuid4(),
        name="Apex Commercial Property Solutions",
        slug=f"apex-comm-{uuid.uuid4().hex[:6]}",
        api_key_hash="hash",
        webhook_secret="secret",
        is_active=True,
        settings={},
    )
    db_session.add(tenant)
    await db_session.commit()

    portfolio = commercial_service.get_tenant_portfolios(tenant)[0]
    wo = await commercial_service.process_commercial_tenant_request(
        portfolio=portfolio,
        unit_number="Unit 310",
        tenant_name="Apex Logistics",
        issue_text="Commercial RTU unit blower motor grinding",
        tenant=tenant,
        db=db_session,
    )

    resp = await client.post(
        f"/api/v1/commercial/approve/{wo.order_id}",
        headers={"accept": "application/json"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "APPROVED"
    assert data["work_order"]["approval_status"] == "APPROVED_BY_PM"


@pytest.mark.asyncio
async def test_commercial_portal_not_found(client: AsyncClient):
    """Verify 404 for unknown tenant slug."""
    resp = await client.get("/commercial/unknown-nonexistent-tenant")
    assert resp.status_code == 404
