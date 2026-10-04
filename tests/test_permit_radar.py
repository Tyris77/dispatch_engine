import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tenant import Tenant
from app.schemas.permit import SubcontractorBidRequest
from app.services.permit_radar import permit_radar_service


@pytest.mark.asyncio
async def test_territory_permits_feed_filtering():
    # 1. Fetch all
    all_permits = permit_radar_service.get_territory_permits()
    assert len(all_permits) >= 6

    # 2. Filter by Jurisdiction
    dc_permits = permit_radar_service.get_territory_permits(jurisdiction="Washington DC")
    assert len(dc_permits) >= 2
    for p in dc_permits:
        assert p.jurisdiction == "Washington DC"

    arl_permits = permit_radar_service.get_territory_permits(jurisdiction="Arlington County")
    assert len(arl_permits) >= 2
    for p in arl_permits:
        assert p.jurisdiction == "Arlington County"

    alx_permits = permit_radar_service.get_territory_permits(jurisdiction="City of Alexandria")
    assert len(alx_permits) >= 2
    for p in alx_permits:
        assert p.jurisdiction == "City of Alexandria"

    # 3. Filter by Trade Category
    hvac_permits = permit_radar_service.get_territory_permits(trade="HVAC")
    assert len(hvac_permits) >= 2
    for p in hvac_permits:
        assert p.trade_category == "HVAC"

    # 4. Filter by Minimum Valuation
    high_val_permits = permit_radar_service.get_territory_permits(min_valuation=200000.0)
    for p in high_val_permits:
        assert p.estimated_valuation >= 200000.0


@pytest.mark.asyncio
async def test_subcontractor_bid_generation_service(sample_tenant: dict):
    tenant: Tenant = sample_tenant["tenant"]
    tenant.name = "Apex Mechanical & Commercial Systems"

    permit = permit_radar_service.get_permit_by_id("DC-B26-08412")
    assert permit is not None
    assert permit.general_contractor == "Davis Construction"

    bid_response = await permit_radar_service.generate_subcontractor_bid(
        permit=permit,
        tenant=tenant,
        custom_scope_notes="Includes 10-year compressor warranty and 24/7 priority emergency response.",
    )

    assert bid_response.permit_id == "DC-B26-08412"
    assert bid_response.general_contractor == "Davis Construction"
    assert "SUB-BID:" in bid_response.subject
    assert bid_response.estimated_bid_amount > 0
    assert "DC-B26-08412" in bid_response.bid_letter_markdown
    assert "Davis Construction" in bid_response.bid_letter_markdown
    assert "Commercial General Liability" in bid_response.bid_letter_markdown
    assert "Apex Mechanical" in bid_response.bid_letter_markdown


@pytest.mark.asyncio
async def test_permit_radar_html_view(client: AsyncClient, sample_tenant: dict):
    tenant: Tenant = sample_tenant["tenant"]

    resp = await client.get(f"/permits/{tenant.slug}")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    html = resp.text
    assert "Municipal Permit B2B Radar" in html
    assert "Washington DC" in html
    assert "Arlington County" in html
    assert "City of Alexandria" in html
    assert "Davis Construction" in html
    assert "Draft Bid with Gemini" in html


@pytest.mark.asyncio
async def test_permit_feed_json_api(client: AsyncClient, sample_tenant: dict):
    tenant: Tenant = sample_tenant["tenant"]

    resp = await client.get(f"/api/v1/permits/{tenant.slug}", params={"trade": "HVAC"})
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) >= 1
    assert all(item["trade_category"] == "HVAC" for item in data)


@pytest.mark.asyncio
async def test_generate_bid_api(client: AsyncClient, sample_tenant: dict):
    tenant: Tenant = sample_tenant["tenant"]

    payload = {
        "permit_id": "ARL-26-M4920",
        "tenant_slug": tenant.slug,
        "custom_scope_notes": "Backflow test certification and grease trap layout included.",
    }
    resp = await client.post("/api/v1/permits/generate-bid", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["permit_id"] == "ARL-26-M4920"
    assert data["general_contractor"] == "HITT Contracting"
    assert data["trade_category"] == "Plumbing"
    assert data["estimated_bid_amount"] > 0
    assert "HITT Contracting" in data["bid_letter_markdown"]
