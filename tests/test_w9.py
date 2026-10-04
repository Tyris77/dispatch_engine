import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tenant import Tenant
from app.schemas.w9 import (
    W9CertificationRecord,
    W9FormSubmission,
    W9RequestPayload,
)
from app.services.w9 import mask_tin, w9_service


def test_w9_schemas():
    """Verify validation of digital Form W-9 submission and certification record."""
    submission = W9FormSubmission(
        crew_name="Apex Framing Crew",
        foreman_name="Juan Rodriguez",
        business_legal_name="Rodriguez Framing LLC",
        federal_tax_classification="LLC",
        address="4500 Industrial Pkwy, Dallas, TX 75201",
        ein_or_ssn="12-3456789",
        signature_base64="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
    )
    assert submission.crew_name == "Apex Framing Crew"
    assert submission.federal_tax_classification == "LLC"

    record = W9CertificationRecord(
        w9_id="W9-8812A",
        crew_name="Apex Framing Crew",
        tax_classification="LLC",
        tin_masked="XX-XXX6789",
        signed_at="2026-10-04 12:00:00 UTC",
        status="VERIFIED_ON_FILE",
    )
    assert record.status == "VERIFIED_ON_FILE"
    assert record.tin_masked == "XX-XXX6789"


def test_mask_tin():
    """Verify EIN and SSN parsing and masking rules."""
    # EIN with hyphen
    assert mask_tin("12-3456789") == "XX-XXX6789"
    # EIN without hyphen
    assert mask_tin("123456789") == "XX-XXX6789"
    # SSN with hyphens
    assert mask_tin("123-45-6789") == "XXX-XX-6789"

    # Invalid TINs
    with pytest.raises(ValueError):
        mask_tin("12345")
    with pytest.raises(ValueError):
        mask_tin("invalid-id-number")


@pytest.mark.asyncio
async def test_submit_digital_w9_service(db_session: AsyncSession):
    """Test service processing, settings persistence, and masking."""
    tenant = Tenant(
        id=uuid.uuid4(),
        name="Vanguard Builders",
        slug=f"vanguard-{uuid.uuid4().hex[:6]}",
        api_key_hash="hash",
        webhook_secret="secret",
        settings={"tax_vault_w9s": {}},
    )
    db_session.add(tenant)
    await db_session.commit()

    submission = W9FormSubmission(
        crew_name="Timberline Carpentry",
        foreman_name="Luke Skywalker",
        business_legal_name="Timberline Woodworks Inc",
        federal_tax_classification="S_CORP",
        address="100 Mill Road, Portland, OR 97201",
        ein_or_ssn="98-7654321",
        signature_base64="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
    )

    record = await w9_service.submit_digital_w9(
        submission=submission,
        tenant=tenant,
        db=db_session,
    )
    assert record.tin_masked == "XX-XXX4321"
    assert record.status == "VERIFIED_ON_FILE"

    # Verify updated tenant settings
    w9_entry = w9_service.get_w9_entry(tenant, "Timberline Carpentry")
    assert w9_entry is not None
    assert w9_entry["w9_status"] == "ON_FILE"
    assert w9_entry["tax_classification"] == "S_CORP"
    assert w9_entry["business_legal_name"] == "Timberline Woodworks Inc"


@pytest.mark.asyncio
async def test_request_w9_via_sms_service(db_session: AsyncSession):
    """Test W-9 SMS request generation."""
    tenant = Tenant(
        id=uuid.uuid4(),
        name="BuildCraft Pro",
        slug=f"buildcraft-{uuid.uuid4().hex[:6]}",
        api_key_hash="hash",
        webhook_secret="secret",
        settings={"base_url": "https://dispatch.buildcraft.com"},
    )
    db_session.add(tenant)
    await db_session.commit()

    result = await w9_service.request_w9_via_sms(
        crew_name="Rapid Masonry",
        foreman_phone="+15557778899",
        tenant=tenant,
    )
    assert result["sent"] is True
    assert f"/w9/{tenant.slug}/Rapid%20Masonry" in result["link"]


@pytest.mark.asyncio
async def test_w9_endpoints(client: AsyncClient, db_session: AsyncSession):
    """Test W-9 form GET, POST submission, and SMS dispatch endpoints."""
    tenant = Tenant(
        id=uuid.uuid4(),
        name="Precision HVAC & Plumbing",
        slug=f"precision-{uuid.uuid4().hex[:6]}",
        api_key_hash="hash",
        webhook_secret="secret",
        settings={},
    )
    db_session.add(tenant)
    await db_session.commit()

    # 1. GET W-9 HTML Form
    resp_get = await client.get(f"/w9/{tenant.slug}/Alpha%20Piping")
    assert resp_get.status_code == 200
    assert "IRS Form W-9 Digital Certification" in resp_get.text
    assert "Alpha Piping" in resp_get.text

    # 2. POST W-9 via JSON API
    payload = {
        "crew_name": "Alpha Piping",
        "foreman_name": "Marcus Vance",
        "business_legal_name": "Alpha Piping & Mechanical LLC",
        "federal_tax_classification": "LLC",
        "address": "1200 Commerce Dr, Denver, CO 80202",
        "ein_or_ssn": "84-1234567",
        "signature_base64": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
    }
    resp_post = await client.post(
        f"/w9/{tenant.slug}/Alpha%20Piping",
        json=payload,
    )
    assert resp_post.status_code == 200
    res_data = resp_post.json()
    assert res_data["status"] == "VERIFIED_ON_FILE"
    assert res_data["tin_masked"] == "XX-XXX4567"

    # 3. POST trigger SMS request endpoint
    req_payload = {
        "tenant_slug": tenant.slug,
        "crew_name": "Bravo Electric",
        "foreman_phone": "+15556667788",
    }
    resp_sms = await client.post("/api/v1/tax-vault/request-w9", json=req_payload)
    assert resp_sms.status_code == 200
    assert resp_sms.json()["status"] in ("SMS_DISPATCHED", "SIMULATED")
    assert "Bravo%20Electric" in resp_sms.json()["link"]

    # 4. 404 for unknown tenant
    resp_404 = await client.get("/w9/unknown-tenant-slug/Crew%20X")
    assert resp_404.status_code == 404
