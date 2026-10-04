import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tenant import Tenant
from app.schemas.compliance import (
    RegulatoryCompliancePacket,
    TradeLicenseRecord,
)
from app.services.compliance import compliance_service


def test_compliance_schemas():
    """Verify validation and serialization of trade license and compliance packet schemas."""
    license_rec = TradeLicenseRecord(
        license_type="VA_DPOR_CLASS_A",
        license_number="2705-184920A",
        jurisdiction="Commonwealth of Virginia",
        holder_name="Titan Mechanical Services",
        expiration_date="2027-11-30",
        status="ACTIVE",
        classification_scope="Commercial General Contractor",
        verification_authority="DPOR",
    )
    assert license_rec.license_type == "VA_DPOR_CLASS_A"
    assert license_rec.status == "ACTIVE"

    packet = RegulatoryCompliancePacket(
        contractor_legal_name="Titan Mechanical Contracting LLC",
        verified_licenses=[license_rec],
        active_coi={"general_liability_each_occurrence": 1000000.0, "general_aggregate_limit": 2000000.0},
        osha_safety_score=98.5,
        verification_qr_url="http://testserver/compliance/titan-mech",
        standing_status="GOOD_STANDING",
        surety_bond_amount=50000.0,
    )
    assert packet.osha_safety_score == 98.5
    assert packet.standing_status == "GOOD_STANDING"
    assert len(packet.verified_licenses) == 1


def test_get_compliance_packet_defaults():
    """Verify compliance service generates full tri-state licenses, COI limits, and OSHA ratings."""
    tenant = Tenant(
        id=uuid.uuid4(),
        name="Titan Premier Contractors",
        slug="titan-premier",
        api_key_hash="hash",
        webhook_secret="secret",
        is_active=True,
        settings={"base_url": "https://dispatch.titan.com"},
    )

    packet = compliance_service.get_compliance_packet(tenant)
    assert packet.contractor_legal_name == "Titan Premier Contractors"
    assert packet.osha_safety_score == 98.5
    assert packet.standing_status == "GOOD_STANDING"
    assert packet.verification_qr_url == "https://dispatch.titan.com/compliance/titan-premier"

    # Verify tri-state licenses
    license_types = [lic.license_type for lic in packet.verified_licenses]
    assert "VA_DPOR_CLASS_A" in license_types
    assert "MD_MHIC_CONTRACTOR" in license_types
    assert "DC_BBL_TRADE" in license_types
    assert "EPA_608_UNIVERSAL" in license_types
    assert "MASTER_PLUMBER_STAMP" in license_types

    # Verify insurance limits
    assert packet.active_coi["general_liability_each_occurrence"] == 1000000.0
    assert packet.active_coi["general_aggregate_limit"] == 2000000.0
    assert packet.active_coi["workers_comp_statutory"] is True


def test_get_compliance_packet_custom_settings():
    """Verify compliance packet respects custom tenant settings."""
    tenant = Tenant(
        id=uuid.uuid4(),
        name="Custom Mechanical Corp",
        slug="custom-mech",
        api_key_hash="hash",
        webhook_secret="secret",
        is_active=True,
        settings={
            "osha_safety_score": 99.2,
            "surety_bond_amount": 100000.0,
            "trade_licenses": [
                {
                    "license_type": "VA_DPOR_CLASS_A",
                    "license_number": "2705-999999A",
                    "jurisdiction": "Commonwealth of Virginia",
                    "holder_name": "Custom Qualifier",
                    "expiration_date": "2029-01-01",
                    "status": "ACTIVE",
                }
            ],
            "active_coi": {
                "insurer_name": "Hartford Underwriters",
                "general_liability_each_occurrence": 2000000.0,
                "general_aggregate_limit": 4000000.0,
            },
        },
    )

    packet = compliance_service.get_compliance_packet(tenant)
    assert packet.osha_safety_score == 99.2
    assert packet.surety_bond_amount == 100000.0
    assert len(packet.verified_licenses) == 1
    assert packet.verified_licenses[0].license_number == "2705-999999A"
    assert packet.active_coi["insurer_name"] == "Hartford Underwriters"
    assert packet.active_coi["general_liability_each_occurrence"] == 2000000.0


@pytest.mark.asyncio
async def test_get_compliance_packet_html(client: AsyncClient, db_session: AsyncSession):
    """Verify printable compliance packet HTML endpoint."""
    tenant = Tenant(
        id=uuid.uuid4(),
        name="Apex Commercial General Contractor",
        slug=f"apex-gc-{uuid.uuid4().hex[:6]}",
        api_key_hash="hash",
        webhook_secret="secret",
        is_active=True,
        settings={},
    )
    db_session.add(tenant)
    await db_session.commit()

    resp = await client.get(f"/compliance/{tenant.slug}")
    assert resp.status_code == 200
    assert "Regulatory Compliance & Trade License Packet" in resp.text
    assert tenant.name in resp.text
    assert "Official Regulatory Submittal Packet" in resp.text
    assert "VA_DPOR_CLASS_A" in resp.text


@pytest.mark.asyncio
async def test_get_compliance_packet_json(client: AsyncClient, db_session: AsyncSession):
    """Verify compliance packet JSON query mode."""
    tenant = Tenant(
        id=uuid.uuid4(),
        name="Apex Commercial General Contractor",
        slug=f"apex-gc-{uuid.uuid4().hex[:6]}",
        api_key_hash="hash",
        webhook_secret="secret",
        is_active=True,
        settings={},
    )
    db_session.add(tenant)
    await db_session.commit()

    resp = await client.get(f"/compliance/{tenant.slug}?format=json")
    assert resp.status_code == 200
    data = resp.json()
    assert data["contractor_legal_name"] == tenant.name
    assert len(data["verified_licenses"]) >= 5
    assert data["osha_safety_score"] == 98.5
    assert "active_coi" in data


@pytest.mark.asyncio
async def test_get_compliance_packet_rest_api(client: AsyncClient, db_session: AsyncSession):
    """Verify REST API endpoint /api/v1/compliance/{tenant_slug}."""
    tenant = Tenant(
        id=uuid.uuid4(),
        name="Apex Commercial General Contractor",
        slug=f"apex-gc-{uuid.uuid4().hex[:6]}",
        api_key_hash="hash",
        webhook_secret="secret",
        is_active=True,
        settings={},
    )
    db_session.add(tenant)
    await db_session.commit()

    resp = await client.get(f"/api/v1/compliance/{tenant.slug}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["standing_status"] == "GOOD_STANDING"
    assert data["surety_bond_amount"] == 50000.0


@pytest.mark.asyncio
async def test_compliance_packet_not_found(client: AsyncClient):
    """Verify 404 for unknown tenant slug."""
    resp = await client.get("/compliance/non-existent-tenant-xyz")
    assert resp.status_code == 404
