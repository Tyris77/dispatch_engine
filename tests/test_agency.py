import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tenant import Tenant
from app.schemas.agency import (
    AgencyOverview,
    AgencyProfile,
    AgencyTenantOnboardRequest,
    ManagedTenantSummary,
)
from app.services.agency import agency_service


def test_agency_schemas():
    """Verify agency white-label and franchise management schema validations."""
    profile = AgencyProfile(
        agency_name="Apex Trade Accelerator",
        brand_color="#10B981",
        contact_email="partners@apextrades.com",
        custom_domain="dispatch.apextrades.com",
    )
    assert profile.agency_name == "Apex Trade Accelerator"
    assert profile.brand_color == "#10B981"
    assert profile.white_label_active is True

    req = AgencyTenantOnboardRequest(
        name="Apex Heat Pump Masters LLC",
        slug="apex-heat-pumps",
        trade_category="HVAC",
        contact_email="service@apexheatpumps.com",
        monthly_retainer=999.0,
    )
    assert req.slug == "apex-heat-pumps"
    assert req.monthly_retainer == 999.0


@pytest.mark.asyncio
async def test_get_agency_overview_service(sample_tenant: dict, db_session: AsyncSession):
    """Verify agency_service aggregates multi-tenant metrics across all contractor accounts."""
    overview = await agency_service.get_agency_overview(db_session)

    assert isinstance(overview, AgencyOverview)
    assert overview.total_managed_tenants >= 1
    assert overview.aggregate_mrr >= 799.0
    assert len(overview.active_tenants) >= 1
    tenant_slugs = [t.tenant_slug for t in overview.active_tenants]
    assert sample_tenant["tenant"].slug in tenant_slugs


@pytest.mark.asyncio
async def test_onboard_agency_tenant_service(db_session: AsyncSession):
    """Verify agency_service provisions isolated contractor tenant with valid credentials."""
    req = AgencyTenantOnboardRequest(
        name="Blue Ridge Plumbing Pros",
        slug="blue-ridge-plumbing",
        trade_category="Plumbing",
        contact_email="dispatch@blueridgeplumbing.com",
        monthly_retainer=850.0,
    )
    new_tenant = await agency_service.onboard_agency_tenant(db_session, req)

    assert isinstance(new_tenant, Tenant)
    assert new_tenant.name == "Blue Ridge Plumbing Pros"
    assert new_tenant.slug == "blue-ridge-plumbing"
    assert new_tenant.is_active is True
    assert new_tenant.api_key_hash is not None
    assert new_tenant.webhook_secret.startswith("whsec_")
    assert new_tenant.settings["monthly_retainer"] == 850.0
    assert new_tenant.settings["trade_category"] == "Plumbing"


def test_update_agency_profile_service():
    """Verify update_agency_profile alters white-label branding configuration."""
    updated = agency_service.update_agency_profile({
        "agency_name": "Apex Elite Commercial Services",
        "brand_color": "#8B5CF6",
        "custom_domain": "dispatch.apexelite.io",
    })

    assert updated.agency_name == "Apex Elite Commercial Services"
    assert updated.brand_color == "#8B5CF6"
    assert updated.custom_domain == "dispatch.apexelite.io"


@pytest.mark.asyncio
async def test_get_agency_dashboard_html(sample_tenant: dict, client: AsyncClient):
    """Verify GET /agency renders executive franchise management dashboard HTML."""
    response = await client.get("/agency")

    assert response.status_code == 200
    html = response.text
    assert "Contractor Client Directory" in html
    assert "Aggregate MRR" in html
    assert "Provision New Contractor Account" in html or "Contractor Onboarding" in html
    assert "White-Label Branding" in html


@pytest.mark.asyncio
async def test_get_agency_dashboard_json_format(sample_tenant: dict, client: AsyncClient):
    """Verify GET /agency?format=json returns structured AgencyOverview JSON."""
    response = await client.get("/agency?format=json")

    assert response.status_code == 200
    data = response.json()
    assert "total_managed_tenants" in data
    assert "aggregate_mrr" in data
    assert "active_tenants" in data
    assert len(data["active_tenants"]) >= 1


@pytest.mark.asyncio
async def test_post_agency_onboard_form_redirect(client: AsyncClient):
    """Verify POST /agency/onboard provisions tenant via form and redirects."""
    response = await client.post(
        "/agency/onboard",
        data={
            "name": "Cascade Electrical Specialists",
            "slug": "cascade-electrical",
            "trade_category": "Electrical",
            "contact_email": "ops@cascadeelec.com",
            "monthly_retainer": "899.00",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert "/agency" in response.headers["location"]


@pytest.mark.asyncio
async def test_post_agency_branding_form_redirect(client: AsyncClient):
    """Verify POST /agency/branding updates profile and redirects."""
    response = await client.post(
        "/agency/branding",
        data={
            "agency_name": "Apex Global Trades Corp",
            "brand_color": "#06B6D4",
            "custom_domain": "portal.apexglobal.com",
            "contact_email": "admin@apexglobal.com",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert "/agency" in response.headers["location"]


@pytest.mark.asyncio
async def test_api_get_agency_overview(client: AsyncClient):
    """Verify GET /api/v1/agency/overview returns AgencyOverview model."""
    response = await client.get("/api/v1/agency/overview")

    assert response.status_code == 200
    data = response.json()
    assert "agency_profile" in data
    assert "total_managed_tenants" in data
    assert "active_tenants" in data


@pytest.mark.asyncio
async def test_api_onboard_tenant_endpoint(client: AsyncClient):
    """Verify POST /api/v1/agency/onboard creates tenant and returns 201 status."""
    response = await client.post(
        "/api/v1/agency/onboard",
        json={
            "name": "Frontier Roofing Partners",
            "slug": "frontier-roofing",
            "trade_category": "Roofing",
            "contact_email": "contact@frontierroofing.com",
            "monthly_retainer": 950.0,
        },
    )

    assert response.status_code == 201
    data = response.json()
    assert data["status"] == "SUCCESS"
    assert data["name"] == "Frontier Roofing Partners"
    assert data["slug"] == "frontier-roofing"
    assert "tenant_id" in data
