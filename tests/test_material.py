import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lead_action import LeadAction
from app.models.tenant import Tenant
from app.schemas.material import JobProfitability, PurchaseOrder, PurchaseOrderItem
from app.services.material import dispatch_po_to_supplier, generate_material_purchase_order


def test_material_schemas():
    """Verify PurchaseOrderItem, PurchaseOrder, and JobProfitability schemas validate correctly."""
    item = PurchaseOrderItem(
        part_name="Dual Run Capacitor 45/5 uF 440V",
        quantity=2,
        estimated_unit_cost=28.50,
        line_total=57.00,
    )
    assert item.part_name == "Dual Run Capacitor 45/5 uF 440V"
    assert item.quantity == 2
    assert item.line_total == 57.00

    po = PurchaseOrder(
        po_number="PO-2026-0104",
        action_id=str(uuid.uuid4()),
        supplier_name="Johnstone Supply",
        supplier_branch="Branch #118 - North Metro",
        items=[item],
        total_material_cost=57.00,
        pickup_address="10405 Metric Blvd, Austin, TX 78758",
        nav_link="https://www.google.com/maps/dir/?api=1&destination=Johnstone%20Supply",
        status="DRAFT",
        customer_name="Alice Smith",
    )
    assert po.po_number == "PO-2026-0104"
    assert po.status == "DRAFT"
    assert len(po.items) == 1
    assert po.total_material_cost == 57.00

    prof = JobProfitability(
        contract_revenue=850.0,
        material_costs=57.0,
        estimated_labor_cost=187.0,
        net_profit=606.0,
        margin_percentage=71.3,
        margin_tier="EXCELLENT",
    )
    assert prof.net_profit == 606.0
    assert prof.margin_percentage == 71.3
    assert prof.margin_tier == "EXCELLENT"


def test_generate_material_purchase_order_hvac():
    """Verify generate_material_purchase_order assigns wholesale pricing and computes profitability for HVAC."""
    tenant = Tenant(
        id=uuid.uuid4(),
        name="Apex Comfort Heating & Air",
        slug="apex-comfort",
        api_key_hash="hash",
        webhook_secret="whsec_test",
        is_active=True,
        settings={"license_number": "HVAC-LIC-84920", "trade": "HVAC"},
    )

    lead_action = LeadAction(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        lead_external_id="+15559876543",
        action_type="EMERGENCY_DISPATCH",
        qualification_score=0.9,
        signed_contract={
            "selected_tier": "Repair / Patch",
            "tier_title": "Capacitor & Contactor Overhaul",
            "price_total": 450.0,
            "deposit_paid": 100.0,
            "customer_name": "Tony Stark",
            "customer_phone": "+15559876543",
        },
        diagnostic_data={
            "equipment_type": "HVAC Condenser",
            "brand_manufacturer": "Carrier",
            "recommended_parts_tools": ["45/5 uF Dual Run Capacitor", "Single Pole 30A Contactor"],
        },
    )

    po, prof = generate_material_purchase_order(lead_action=lead_action, tenant=tenant)

    assert po.po_number.startswith("PO-")
    assert "Johnstone Supply" in po.supplier_name
    assert "Metric Blvd" in po.pickup_address
    assert len(po.items) == 2

    # Check wholesale items: Capacitor (~28.50) + Contactor (~34.00) = ~62.50
    assert po.total_material_cost == 62.50
    assert prof.contract_revenue == 450.0
    assert prof.material_costs == 62.50
    assert prof.net_profit > 0
    assert prof.margin_percentage > 50.0
    assert lead_action.material_po is not None
    assert lead_action.profitability_data is not None


def test_generate_material_purchase_order_plumbing():
    """Verify plumbing diagnostics route to Ferguson Plumbing Supply with wholesale plumbing pricing."""
    tenant = Tenant(
        id=uuid.uuid4(),
        name="Precision Flow Plumbing",
        slug="precision-plumbing",
        api_key_hash="hash",
        webhook_secret="whsec_test",
        is_active=True,
        settings={"license_number": "PLUMB-7721", "trade": "Plumbing"},
    )

    lead_action = LeadAction(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        lead_external_id="+15554443333",
        action_type="BOOKING_NOTIFICATION",
        qualification_score=0.88,
        signed_contract={
            "selected_tier": "Standard Replacement",
            "tier_title": "Water Heater Replacement & Valve Pack",
            "price_total": 2400.0,
            "customer_name": "Peter Parker",
        },
        diagnostic_data={
            "equipment_type": "Water Heater",
            "brand_manufacturer": "Rheem",
            "recommended_parts_tools": [
                "4500W Heating Element",
                "3/4-in Brass Ball Valve",
                "Copper Fitting Pack",
            ],
        },
    )

    po, prof = generate_material_purchase_order(lead_action=lead_action, tenant=tenant)

    assert "Ferguson Plumbing Supply" in po.supplier_name
    assert "Industrial Blvd" in po.pickup_address
    assert len(po.items) == 3
    assert po.total_material_cost == 32.00 + 24.50 + 35.00  # 91.50
    assert prof.contract_revenue == 2400.0
    assert prof.margin_tier == "EXCELLENT"
    assert "https://www.google.com/maps/dir/?api=1&destination=" in po.nav_link


def test_generate_material_purchase_order_fallback_parts():
    """Verify fallback wholesale bill of materials when diagnostic scan has no explicit parts listed."""
    tenant = Tenant(
        id=uuid.uuid4(),
        name="General Tech Services",
        slug="general-tech",
        api_key_hash="hash",
        webhook_secret="whsec_test",
        is_active=True,
        settings={"avg_job_value": 750.0},
    )

    lead_action = LeadAction(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        lead_external_id="+15551234567",
        action_type="DISPATCH_ROUTED",
        qualification_score=0.75,
        diagnostic_data={},  # No parts listed
    )

    po, prof = generate_material_purchase_order(lead_action=lead_action, tenant=tenant)

    assert len(po.items) >= 1
    assert po.total_material_cost > 0
    assert prof.contract_revenue == 750.0
    assert prof.net_profit > 0


@pytest.mark.asyncio
async def test_dispatch_po_to_supplier(db_session: AsyncSession, sample_tenant: dict):
    """Verify dispatch_po_to_supplier transitions PO to ORDERED, timestamps, and formats SMS."""
    tenant = sample_tenant["tenant"]

    lead_action = LeadAction(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        lead_external_id="+15558889999",
        action_type="EMERGENCY_DISPATCH",
        qualification_score=0.92,
        signed_contract={
            "price_total": 1200.0,
            "customer_name": "Bruce Wayne",
        },
        diagnostic_data={
            "equipment_type": "HVAC Heat Pump",
            "recommended_parts_tools": ["Dual Run Capacitor 45/5 uF", "Hard Start Kit"],
        },
    )
    db_session.add(lead_action)
    await db_session.commit()
    await db_session.refresh(lead_action)

    # Dispatch PO
    updated_po = await dispatch_po_to_supplier(action_id=lead_action.id, db=db_session)

    assert updated_po.status == "ORDERED"
    assert updated_po.ordered_at is not None
    assert updated_po.customer_name == "Bruce Wayne"

    # Verify database persistence
    await db_session.refresh(lead_action)
    assert lead_action.material_po["status"] == "ORDERED"
    assert lead_action.material_po["ordered_at"] is not None


@pytest.mark.asyncio
async def test_api_get_po_html_and_json(client: AsyncClient, db_session: AsyncSession, sample_tenant: dict):
    """Verify GET /po/{action_id} serves both printable dark HTML view and structured JSON."""
    tenant = sample_tenant["tenant"]

    lead_action = LeadAction(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        lead_external_id="+15557771234",
        action_type="EMERGENCY_DISPATCH",
        qualification_score=0.9,
        signed_contract={
            "price_total": 950.0,
            "customer_name": "Diana Prince",
        },
        diagnostic_data={
            "equipment_type": "HVAC Air Handler",
            "recommended_parts_tools": ["Blower Motor 1/2 HP"],
        },
    )
    db_session.add(lead_action)
    await db_session.commit()

    # 1. 404 for unknown action
    resp_404 = await client.get(f"/po/{uuid.uuid4()}")
    assert resp_404.status_code == 404

    # 2. HTML View
    resp_html = await client.get(f"/po/{lead_action.id}")
    assert resp_html.status_code == 200
    assert "text/html" in resp_html.headers.get("content-type", "")
    assert "Material PO #" in resp_html.text
    assert "Diana Prince" in resp_html.text
    assert "Wholesale Bill of Materials" in resp_html.text
    assert "Real-Time Job Profitability" in resp_html.text
    assert "Print / Save PDF" in resp_html.text

    # 3. JSON Mode
    resp_json = await client.get(f"/po/{lead_action.id}?format=json")
    assert resp_json.status_code == 200
    data = resp_json.json()
    assert "purchase_order" in data
    assert "profitability" in data
    assert data["purchase_order"]["customer_name"] == "Diana Prince"
    assert data["profitability"]["contract_revenue"] == 950.0


@pytest.mark.asyncio
async def test_api_dispatch_po_endpoint(client: AsyncClient, db_session: AsyncSession, sample_tenant: dict):
    """Verify POST /po/{action_id}/dispatch endpoint transitions status to ORDERED and returns payload."""
    tenant = sample_tenant["tenant"]

    lead_action = LeadAction(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        lead_external_id="+15559990000",
        action_type="EMERGENCY_DISPATCH",
        qualification_score=0.95,
        signed_contract={
            "price_total": 650.0,
            "customer_name": "Clark Kent",
        },
        diagnostic_data={
            "equipment_type": "Electrical Panel",
            "recommended_parts_tools": ["Circuit Breaker 50A", "Surge Protective Device"],
        },
    )
    db_session.add(lead_action)
    await db_session.commit()

    # POST dispatch via JSON
    resp = await client.post(f"/po/{lead_action.id}/dispatch", headers={"Accept": "application/json"})
    assert resp.status_code == 200
    res_data = resp.json()
    assert res_data["success"] is True
    assert res_data["status"] == "ORDERED"
    assert res_data["po"]["status"] == "ORDERED"

    # Re-fetch HTML to verify ordered status banner
    get_resp = await client.get(f"/po/{lead_action.id}")
    assert get_resp.status_code == 200
    assert "ORDERED • WILL-CALL READY" in get_resp.text
    assert "Will-Call Order Dispatched" in get_resp.text


@pytest.mark.asyncio
async def test_dashboard_and_portal_margin_badges(client: AsyncClient, db_session: AsyncSession, sample_tenant: dict):
    """Verify that operator dashboard and client portal display Job Margin badges and Supply PO buttons."""
    tenant = sample_tenant["tenant"]

    lead_action = LeadAction(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        lead_external_id="+15553216549",
        action_type="EMERGENCY_DISPATCH",
        qualification_score=0.9,
        signed_contract={
            "price_total": 2500.0,
            "customer_name": "Barry Allen",
        },
        profitability_data={
            "contract_revenue": 2500.0,
            "material_costs": 185.0,
            "estimated_labor_cost": 550.0,
            "net_profit": 1765.0,
            "margin_percentage": 70.6,
            "margin_tier": "EXCELLENT",
        },
    )
    db_session.add(lead_action)
    await db_session.commit()

    # 1. Operator Dashboard
    dash_resp = await client.get(f"/dashboard?tenant_slug={tenant.slug}")
    assert dash_resp.status_code == 200
    assert "70.6%" in dash_resp.text
    assert "$1,765" in dash_resp.text
    assert f"/po/{lead_action.id}" in dash_resp.text

    # 2. Client Portal
    portal_resp = await client.get(f"/portal/{tenant.slug}?api_key={sample_tenant['raw_api_key']}")
    assert portal_resp.status_code == 200
    assert "70.6%" in portal_resp.text
    assert "$1,765" in portal_resp.text
    assert f"/po/{lead_action.id}" in portal_resp.text
