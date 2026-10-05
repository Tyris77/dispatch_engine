import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.tenant import Tenant
from app.schemas.onboard import OnboardRequest, OnboardResponse
from app.services.onboarding import onboarding_service


def test_onboard_request_validation():
    # Valid request
    req = OnboardRequest(
        company_name="Apex Mechanical Systems",
        trade="HVAC",
        service_area="Washington, DC / Northern VA",
        on_call_phone="(202) 555-0199",
        owner_email="owner@apexmechanical.com",
        owner_name="Dave Kowalski",
        area_code_preference="202",
    )
    assert req.company_name == "Apex Mechanical Systems"
    assert req.trade == "hvac"
    assert req.on_call_phone == "+12025550199"
    assert str(req.owner_email) == "owner@apexmechanical.com"

    # Trade normalizer for non-standard string
    req_plumb = OnboardRequest(
        company_name="Capital Plumbing",
        trade="Master Plumber & Rooter",
        service_area="DC Metro",
        on_call_phone="2025550144",
        owner_email="info@capitalplumbing.com",
    )
    assert req_plumb.trade == "plumbing"
    assert req_plumb.on_call_phone == "+12025550144"

    # Invalid short name
    with pytest.raises(ValueError):
        OnboardRequest(
            company_name="A",
            trade="plumbing",
            service_area="DC",
            on_call_phone="2025550199",
            owner_email="test@test.com",
        )

    # Invalid short phone
    with pytest.raises(ValueError):
        OnboardRequest(
            company_name="Valid Co",
            trade="plumbing",
            service_area="DC",
            on_call_phone="123",
            owner_email="test@test.com",
        )


@pytest.mark.asyncio
async def test_slug_generation_and_collision_handling(db_session: AsyncSession):
    # Create an initial tenant
    existing = Tenant(
        id=uuid.uuid4(),
        name="Monumental Roofing",
        slug="monumental-roofing",
        api_key_hash="hash",
        webhook_secret="secret",
        settings={},
    )
    db_session.add(existing)
    await db_session.commit()

    # Generate unique slug for same name
    slug = await onboarding_service.generate_unique_slug("Monumental Roofing", db_session)
    assert slug.startswith("monumental-roofing-")
    assert slug != "monumental-roofing"


@pytest.mark.asyncio
async def test_onboarding_service_provisioning(db_session: AsyncSession):
    req = OnboardRequest(
        company_name="Patriot Water Mitigation",
        trade="water_mitigation",
        service_area="Fairfax / Arlington / Alexandria",
        on_call_phone="+17035550188",
        owner_email="dispatch@patriotwater.com",
        owner_name="Brian O'Connor",
        area_code_preference="703",
    )

    resp: OnboardResponse = await onboarding_service.provision_contractor(
        payload=req,
        db=db_session,
        base_url="https://dispatch.railway.app",
    )

    assert resp.status == "ACTIVE"
    assert "patriot-water-mitigation" in resp.tenant_slug
    assert resp.forwarding_phone_number is not None
    assert f"/api/v1/widget/{resp.tenant_slug}.js" in resp.widget_script_tag
    assert f"/portal/{resp.tenant_slug}" in resp.portal_url
    assert f"/dashboard?tenant_slug={resp.tenant_slug}" in resp.dashboard_url
    assert "verizon" in resp.carrier_forwarding_instructions
    assert "*72" in resp.carrier_forwarding_instructions["verizon"]
    assert "*21*" in resp.carrier_forwarding_instructions["att"]
    assert "**21*" in resp.carrier_forwarding_instructions["t_mobile"]


@pytest.mark.asyncio
async def test_onboarding_api_endpoints(client: AsyncClient):
    # 1. GET /onboard page rendering
    page_resp = await client.get("/onboard")
    assert page_resp.status_code == 200
    assert "Activate Your Autonomous" in page_resp.text
    assert "Company & Trade" in page_resp.text

    # 2. POST /api/v1/onboard/provision API endpoint
    payload = {
        "company_name": "District Electrical Contractors",
        "trade": "electrical",
        "service_area": "Washington, DC Metro",
        "on_call_phone": "+1 (202) 555-0155",
        "owner_email": "owner@districtelectric.com",
        "owner_name": "Nikola Vance",
        "area_code_preference": "202",
    }
    prov_resp = await client.post("/api/v1/onboard/provision", json=payload)
    assert prov_resp.status_code == 200
    data = prov_resp.json()
    assert data["status"] == "ACTIVE"
    assert "district-electrical-contractors" in data["tenant_slug"]
    assert "widget_script_tag" in data
    assert "forwarding_phone_number" in data
    assert "carrier_forwarding_instructions" in data

    # 3. GET /onboard/success/{tenant_slug} page rendering
    slug = data["tenant_slug"]
    succ_resp = await client.get(f"/onboard/success/{slug}")
    assert succ_resp.status_code == 200
    assert "Activation" in succ_resp.text or "Instant Contractor Activation" in succ_resp.text

    # 4. GET /onboard/success/{tenant_slug}?format=json
    json_resp = await client.get(f"/onboard/success/{slug}?format=json")
    assert json_resp.status_code == 200
    json_data = json_resp.json()
    assert json_data["tenant_slug"] == slug
    assert json_data["status"] == "ACTIVE"
