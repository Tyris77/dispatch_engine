import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lead_action import LeadAction
from app.models.tenant import Tenant
from app.schemas.supply_arbitrage import DistributorQuote, SupplyArbitrageComparison
from app.services.supply_arbitrage import supply_arbitrage_service


def _tenant() -> Tenant:
    return Tenant(
        id=uuid.uuid4(),
        name="Arbitrage Pros",
        slug=f"arb-{uuid.uuid4().hex[:6]}",
        api_key_hash="hash",
        webhook_secret="secret",
        is_active=True,
        settings={},
    )


def _lead(tenant: Tenant, **kw) -> LeadAction:
    return LeadAction(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        lead_external_id=f"LD-{uuid.uuid4().hex[:6]}",
        qualification_score=0.9,
        qualification_summary="Compressor replacement",
        action_type="DISPATCH_ROUTED",
        dispatch_status="QUEUED",
        crm_sync_status="PENDING",
        metadata_payload={"customer_name": "Pat", "address": "1 Main St, Arlington, VA"},
        **kw,
    )


def test_arbitrage_schemas():
    q = DistributorQuote(
        distributor_name="Ferguson Supply",
        branch_address="1 Branch Rd",
        in_stock=True,
        line_items_cost=100.0,
        total_material_cost=106.0,
        potential_savings=10.0,
    )
    comp = SupplyArbitrageComparison(
        action_id="a",
        parts_required=["Capacitor"],
        quotes=[q],
        recommended_distributor="Ferguson Supply",
        max_savings_dollars=10.0,
    )
    assert comp.quotes[0].in_stock is True
    assert comp.max_savings_dollars == 10.0


def test_compare_hvac_prefers_johnstone():
    tenant = _tenant()
    lead = _lead(tenant, diagnostic_data={"equipment_type": "Heat Pump", "recommended_parts_tools": ["Capacitor", "Contactor"]})
    comp = supply_arbitrage_service.compare_distributor_pricing(lead, tenant)
    names = [q.distributor_name for q in comp.quotes]
    assert set(names) == {"Ferguson Supply", "Johnstone Supply", "ABC Supply Co.", "Hajoca Corporation"}
    assert comp.recommended_distributor == "Johnstone Supply"
    assert comp.max_savings_dollars > 0
    assert comp.parts_required == ["Capacitor", "Contactor"]


def test_compare_roofing_prefers_abc():
    tenant = _tenant()
    lead = _lead(tenant, diagnostic_data={"equipment_type": "Architectural Shingle Roof", "recommended_parts_tools": ["Shingles bundle"]})
    comp = supply_arbitrage_service.compare_distributor_pricing(lead, tenant)
    assert comp.recommended_distributor == "ABC Supply Co."
    johnstone = next(q for q in comp.quotes if q.distributor_name == "Johnstone Supply")
    assert johnstone.in_stock is False


def test_compare_fallback_parts():
    tenant = _tenant()
    comp = supply_arbitrage_service.compare_distributor_pricing(_lead(tenant), tenant)
    assert len(comp.parts_required) >= 1
    assert len(comp.quotes) == 4


@pytest.mark.asyncio
async def test_switch_po_distributor_updates_po(db_session: AsyncSession):
    tenant = _tenant()
    lead = _lead(tenant, material_po={"supply_house": "Ferguson Supply", "material_cost": 400.0})
    db_session.add_all([tenant, lead])
    await db_session.commit()

    comp = await supply_arbitrage_service.switch_po_distributor(lead.id, "Hajoca Corporation", db_session)
    assert comp.current_distributor == "Hajoca Corporation"
    await db_session.refresh(lead)
    assert lead.material_po["supply_house"] == "Hajoca Corporation"
    assert lead.material_po["arbitrage_optimized"] is True
    assert "google.com/maps" in lead.material_po["nav_link"]
    assert lead.arbitrage_data["current_distributor"] == "Hajoca Corporation"


@pytest.mark.asyncio
async def test_switch_po_distributor_not_found(db_session: AsyncSession):
    with pytest.raises(ValueError):
        await supply_arbitrage_service.switch_po_distributor(uuid.uuid4(), "Ferguson Supply", db_session)


@pytest.mark.asyncio
async def test_supply_compare_html_and_json(client: AsyncClient, sample_tenant: dict, db_session: AsyncSession):
    lead = _lead(sample_tenant["tenant"])
    db_session.add(lead)
    await db_session.commit()

    res = await client.get(f"/supply-compare/{lead.id}")
    assert res.status_code == 200
    assert "Wholesale Counter Comparison Matrix" in res.text
    assert "Johnstone Supply" in res.text

    res = await client.get(f"/supply-compare/{lead.id}?format=json")
    assert res.status_code == 200
    assert len(res.json()["quotes"]) == 4


@pytest.mark.asyncio
async def test_supply_compare_not_found(client: AsyncClient):
    res = await client.get(f"/supply-compare/{uuid.uuid4()}")
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_switch_endpoint_json_and_form(client: AsyncClient, sample_tenant: dict, db_session: AsyncSession):
    lead = _lead(sample_tenant["tenant"])
    db_session.add(lead)
    await db_session.commit()

    res = await client.post(f"/api/v1/supply-compare/switch/{lead.id}", json={"target_distributor": "Ferguson Supply"})
    assert res.status_code == 200
    assert res.json()["current_distributor"] == "Ferguson Supply"

    res = await client.post(
        f"/api/v1/supply-compare/switch/{lead.id}",
        data={"target_distributor": "Hajoca Corporation"},
        follow_redirects=False,
    )
    assert res.status_code == 303
    assert res.headers["location"].startswith(f"/supply-compare/{lead.id}")
