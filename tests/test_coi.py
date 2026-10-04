import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tenant import Tenant
from app.schemas.coi import CertificateOfInsurance, COIUploadResponse
from app.services.coi import (
    coi_service,
    fallback_coi_audit,
    enrich_coi_compliance,
    audit_coi_document,
)


def test_fallback_coi_audit_active_compliant():
    """Verify fallback audit produces valid, fully compliant $1M/$2M ACORD 25 certificate."""
    coi = fallback_coi_audit(
        file_bytes=b"%PDF-1.4 dummy acord 25 content",
        tenant_name="Apex HVAC Services LLC",
    )

    assert isinstance(coi, CertificateOfInsurance)
    assert coi.insured_entity == "Apex HVAC Services LLC"
    assert coi.general_liability_each_occurrence >= 1000000.0
    assert coi.general_aggregate_limit >= 2000000.0
    assert coi.workers_comp_statutory is True
    assert coi.additional_insured_verified is True
    assert coi.days_until_expiration > 0
    assert coi.compliance_status == "ACTIVE_COMPLIANT"
    assert "Travelers" in coi.insurer_name
    assert coi.coi_id.startswith("COI-2026-")


def test_fallback_coi_audit_expired():
    """Verify fallback audit marks policies expired when past expiration date."""
    coi = fallback_coi_audit(
        file_bytes=b"dummy",
        tenant_name="Apex HVAC Services LLC",
        force_status="EXPIRED",
    )

    assert coi.compliance_status == "EXPIRED"
    assert coi.days_until_expiration <= 0


def test_fallback_coi_audit_deficient_limits():
    """Verify fallback audit identifies deficient coverage limits below $1M/$2M commercial thresholds."""
    coi = fallback_coi_audit(
        file_bytes=b"dummy",
        tenant_name="Apex HVAC Services LLC",
        force_status="DEFICIENT_LIMITS",
    )

    assert coi.compliance_status == "DEFICIENT_LIMITS"
    assert coi.general_liability_each_occurrence < 1000000.0 or coi.general_aggregate_limit < 2000000.0


def test_enrich_coi_compliance_logic():
    """Unit test boundary conditions for enrich_coi_compliance calculation."""
    # Test valid active policy
    coi_good = CertificateOfInsurance(
        coi_id="COI-TEST-001",
        insurer_name="Hartford Fire Insurance",
        insured_entity="Test Contractor Inc",
        general_liability_each_occurrence=1000000.0,
        general_aggregate_limit=2000000.0,
        workers_comp_statutory=True,
        policy_expiration_date="2028-12-31",
        additional_insured_verified=True,
        compliance_status="ACTIVE_COMPLIANT",
        days_until_expiration=100,
    )
    enriched = enrich_coi_compliance(coi_good)
    assert enriched.compliance_status == "ACTIVE_COMPLIANT"
    assert enriched.days_until_expiration > 300

    # Test deficient occurrence limit
    coi_low = CertificateOfInsurance(
        coi_id="COI-TEST-002",
        insurer_name="Liberty Mutual",
        insured_entity="Test Contractor Inc",
        general_liability_each_occurrence=500000.0,
        general_aggregate_limit=2000000.0,
        workers_comp_statutory=True,
        policy_expiration_date="2028-12-31",
        additional_insured_verified=True,
        compliance_status="ACTIVE_COMPLIANT",
        days_until_expiration=100,
    )
    enriched_low = enrich_coi_compliance(coi_low)
    assert enriched_low.compliance_status == "DEFICIENT_LIMITS"


@pytest.mark.asyncio
async def test_coi_service_audit_and_persistence(sample_tenant: dict, db_session: AsyncSession):
    """Verify COIGuardService persists audited certificate to tenant settings."""
    tenant = sample_tenant["tenant"]
    tenant.name = "Apex Mechanical Systems LLC"
    db_session.add(tenant)
    await db_session.commit()

    dummy_pdf = b"%PDF-1.4 Mock commercial ACORD 25 policy form"
    coi = await coi_service.audit_document(
        file_bytes=dummy_pdf,
        mime_type="application/pdf",
        tenant=tenant,
    )

    assert coi.insured_entity == "Apex Mechanical Systems LLC"
    assert tenant.settings is not None
    assert "active_coi" in tenant.settings
    assert tenant.settings["active_coi"]["insured_entity"] == "Apex Mechanical Systems LLC"

    # Test get_tenant_coi retrieves cached active COI
    retrieved = coi_service.get_tenant_coi(tenant)
    assert retrieved.insured_entity == "Apex Mechanical Systems LLC"


@pytest.mark.asyncio
async def test_get_coi_portal_html(sample_tenant: dict, client: AsyncClient):
    """Verify GET /coi/{tenant_slug} renders portal HTML view."""
    tenant = sample_tenant["tenant"]
    response = await client.get(f"/coi/{tenant.slug}")

    assert response.status_code == 200
    html = response.text
    assert "Commercial ACORD Insurance Verification" in html or "Commercial General Liability" in html
    assert tenant.name in html
    assert "ACORD 25" in html


@pytest.mark.asyncio
async def test_get_coi_portal_json_format(sample_tenant: dict, client: AsyncClient):
    """Verify GET /coi/{tenant_slug}?format=json returns structured COI JSON."""
    tenant = sample_tenant["tenant"]
    response = await client.get(f"/coi/{tenant.slug}?format=json")

    assert response.status_code == 200
    data = response.json()
    assert "general_liability_each_occurrence" in data
    assert "compliance_status" in data
    assert data["compliance_status"] in ["ACTIVE_COMPLIANT", "EXPIRED", "DEFICIENT_LIMITS"]


@pytest.mark.asyncio
async def test_get_coi_portal_not_found(client: AsyncClient):
    """Verify 404 response for invalid tenant slug."""
    response = await client.get("/coi/unknown-non-existent-tenant-999")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_portal_upload_coi_redirect(sample_tenant: dict, client: AsyncClient):
    """Verify POST /coi/{tenant_slug}/upload ingests ACORD document and redirects with status."""
    tenant = sample_tenant["tenant"]
    dummy_pdf = b"%PDF-1.4 Mock ACORD 25 Certificate of Insurance"

    response = await client.post(
        f"/coi/{tenant.slug}/upload",
        files={"coi_file": ("acord25.pdf", dummy_pdf, "application/pdf")},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert f"/coi/{tenant.slug}" in response.headers["location"]


@pytest.mark.asyncio
async def test_portal_upload_empty_file_rejected(sample_tenant: dict, client: AsyncClient):
    """Verify empty document submission is rejected with 400 Bad Request."""
    tenant = sample_tenant["tenant"]
    response = await client.post(
        f"/coi/{tenant.slug}/upload",
        files={"coi_file": ("empty.pdf", b"", "application/pdf")},
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_api_upload_coi_endpoint(sample_tenant: dict, client: AsyncClient):
    """Verify POST /api/v1/coi/upload audits certificate and returns COIUploadResponse JSON."""
    tenant = sample_tenant["tenant"]
    dummy_pdf = b"%PDF-1.4 Mock commercial ACORD 25 policy form"

    response = await client.post(
        "/api/v1/coi/upload",
        files={"coi_file": ("acord25.pdf", dummy_pdf, "application/pdf")},
        data={"tenant_slug": tenant.slug},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "SUCCESS"
    assert "coi" in data
    assert data["coi"]["insured_entity"] == tenant.name
    assert data["coi"]["general_liability_each_occurrence"] >= 1000000.0


@pytest.mark.asyncio
async def test_api_get_coi_json_endpoint(sample_tenant: dict, client: AsyncClient):
    """Verify GET /api/v1/coi/{tenant_slug} returns active policy record."""
    tenant = sample_tenant["tenant"]
    response = await client.get(f"/api/v1/coi/{tenant.slug}")

    assert response.status_code == 200
    data = response.json()
    assert data["insured_entity"] == tenant.name
    assert "general_liability_each_occurrence" in data
    assert "days_until_expiration" in data
