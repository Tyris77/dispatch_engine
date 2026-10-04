import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lead_action import LeadAction
from app.models.tenant import Tenant
from app.schemas.warranty import WarrantyCertificate, WarrantyResponse
from app.services.warranty import warranty_service


@pytest.fixture
async def warranty_test_lead(sample_tenant: dict, db_session: AsyncSession) -> dict:
    """Fixture providing a tenant and a signed LeadAction with vision diagnostic data."""
    tenant = sample_tenant["tenant"]
    tenant.name = "Carrier Master Elite Mechanical LLC"
    tenant.settings = {
        "contractor_license": "MD-MHIC #149204 / VA #2705189920",
        "epa_certification": "EPA Section 608 Universal: EPA-608-49210",
    }
    db_session.add(tenant)

    action = LeadAction(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        lead_external_id="+15557778899",
        qualification_score=0.94,
        qualification_summary="Emergency high-efficiency variable-speed heat pump installation.",
        action_type="DISPATCH_EMERGENCY_DISPATCH_QUEUE",
        dispatch_status="COMPLETED",
        crm_sync_status="SYNCED",
        metadata_payload={
            "customer_name": "Dr. Eleanor Vance",
            "address": "4200 Wisconsin Ave NW, Washington, DC 20016",
            "trade_type": "HVAC",
        },
        diagnostic_data={
            "equipment_type": "Variable-Speed Heat Pump",
            "brand_manufacturer": "Carrier",
            "model_number": "24VNA648A003",
            "serial_number": "3826A19240",
            "damage_assessment": "Replaced burned compressor and acid-contaminated reversing valve.",
        },
        signed_contract={
            "tier_title": "Best - Carrier Infinity 24 System",
            "total_amount": 8200.0,
            "signed_at": "2026-09-28T14:30:00Z",
            "status": "SIGNED",
        },
    )

    db_session.add(action)
    await db_session.commit()
    await db_session.refresh(action)
    return {"tenant": tenant, "action": action}


def test_warranty_certificate_schemas():
    """Verify WarrantyCertificate and WarrantyResponse serialization."""
    cert = WarrantyCertificate(
        certificate_number="WARR-2026-0042",
        equipment_brand="Carrier",
        model_number="24VNA648A003",
        serial_number="3826A19240",
        install_date="2026-09-28",
        warranty_duration_years=10,
        coverage_scope="10-Year Parts & Compressor, 2-Year Labor Guarantee",
        contractor_license_number="MD-MHIC #149204",
        epa_certification_number="EPA-608-49210",
        cpsc_safety_recall_status="CLEARED_NO_RECALLS",
        verification_qr_url="https://verify.tradeops.io/warranty/WARR-2026-0042",
    )
    assert cert.certificate_number == "WARR-2026-0042"
    assert cert.warranty_duration_years == 10
    assert cert.cpsc_safety_recall_status == "CLEARED_NO_RECALLS"

    resp = WarrantyResponse(
        status="SUCCESS",
        certificate=cert,
        message="Registered successfully",
    )
    assert resp.status == "SUCCESS"
    assert resp.certificate.model_number == "24VNA648A003"


def test_generate_warranty_certificate_service(warranty_test_lead: dict):
    """Verify warranty service extracts diagnostic equipment specs and attaches contractor license."""
    tenant = warranty_test_lead["tenant"]
    action = warranty_test_lead["action"]

    cert = warranty_service.generate_warranty_certificate(action, tenant)

    assert isinstance(cert, WarrantyCertificate)
    assert cert.certificate_number.startswith("WARR-2026-")
    assert cert.equipment_brand == "Carrier"
    assert cert.model_number == "24VNA648A003"
    assert cert.serial_number == "3826A19240"
    assert cert.customer_name == "Dr. Eleanor Vance"
    assert "Wisconsin Ave" in cert.property_address
    assert "MD-MHIC" in cert.contractor_license_number
    assert cert.cpsc_safety_recall_status == "CLEARED_NO_RECALLS"
    assert cert.certificate_number in cert.verification_qr_url
    assert action.warranty_data is not None


def test_generate_warranty_certificate_fallback(sample_tenant: dict):
    """Verify warranty service provides enterprise defaults when lead action has minimal data."""
    tenant = sample_tenant["tenant"]
    action = LeadAction(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        metadata_payload={"customer_name": "Standard Client"},
    )

    cert = warranty_service.generate_warranty_certificate(action, tenant)
    assert cert.equipment_brand == "Carrier"
    assert cert.warranty_duration_years == 10
    assert cert.serial_number.startswith("3826A")
    assert action.warranty_data is not None


@pytest.mark.asyncio
async def test_get_warranty_certificate_html(warranty_test_lead: dict, client: AsyncClient):
    """GET /warranty/{action_id} renders formal printable gold warranty deed certificate."""
    action = warranty_test_lead["action"]
    resp = await client.get(f"/warranty/{action.id}")
    assert resp.status_code == 200
    html = resp.text
    assert "CERTIFICATE OF LIMITED WARRANTY" in html
    assert "Dr. Eleanor Vance" in html
    assert "24VNA648A003" in html
    assert "3826A19240" in html
    assert "CLEARED_NO_RECALLS" in html
    assert "Print Warranty Certificate" in html or "Print" in html


@pytest.mark.asyncio
async def test_get_warranty_certificate_json_format(warranty_test_lead: dict, client: AsyncClient):
    """GET /warranty/{action_id}?format=json returns WarrantyCertificate JSON."""
    action = warranty_test_lead["action"]
    resp = await client.get(f"/warranty/{action.id}?format=json")
    assert resp.status_code == 200
    data = resp.json()
    assert data["equipment_brand"] == "Carrier"
    assert data["model_number"] == "24VNA648A003"
    assert data["serial_number"] == "3826A19240"


@pytest.mark.asyncio
async def test_get_warranty_certificate_not_found(client: AsyncClient):
    """GET /warranty/{unknown_uuid} returns 404."""
    resp = await client.get(f"/warranty/{uuid.uuid4()}")
    assert resp.status_code == 404
    assert "not found" in resp.text.lower()


@pytest.mark.asyncio
async def test_post_generate_warranty_redirect(warranty_test_lead: dict, client: AsyncClient):
    """POST /warranty/{action_id}/generate triggers generation and redirects to certificate view."""
    action = warranty_test_lead["action"]
    resp = await client.post(
        f"/warranty/{action.id}/generate",
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == f"/warranty/{action.id}"


@pytest.mark.asyncio
async def test_post_generate_warranty_json(warranty_test_lead: dict, client: AsyncClient):
    """POST /warranty/{action_id}/generate?format=json returns WarrantyResponse."""
    action = warranty_test_lead["action"]
    resp = await client.post(f"/warranty/{action.id}/generate?format=json")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "SUCCESS"
    assert "certificate" in data
    assert data["certificate"]["equipment_brand"] == "Carrier"


@pytest.mark.asyncio
async def test_api_get_warranty_certificate(warranty_test_lead: dict, client: AsyncClient):
    """GET /api/v1/warranty/{action_id} returns structured certificate JSON via REST."""
    action = warranty_test_lead["action"]
    resp = await client.get(f"/api/v1/warranty/{action.id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["model_number"] == "24VNA648A003"
    assert data["serial_number"] == "3826A19240"
    assert data["certificate_number"].startswith("WARR-2026-")


@pytest.mark.asyncio
async def test_api_get_warranty_not_found(client: AsyncClient):
    """GET /api/v1/warranty/{unknown_uuid} returns 404 via REST."""
    resp = await client.get(f"/api/v1/warranty/{uuid.uuid4()}")
    assert resp.status_code == 404
