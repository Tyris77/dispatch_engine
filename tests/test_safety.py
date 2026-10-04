import io
import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lead_action import LeadAction
from app.models.tenant import Tenant
from app.schemas.safety import SafetyAuditReport
from app.services.safety import safety_service, fallback_safety_audit


@pytest.fixture
async def seeded_safety_lead(sample_tenant: dict, db_session: AsyncSession) -> LeadAction:
    """Fixture providing a seeded LeadAction ready for safety auditing."""
    tenant = sample_tenant["tenant"]
    tenant.name = "Apex Roofing & Building Solutions"
    db_session.add(tenant)

    action = LeadAction(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        lead_external_id="+15558883456",
        qualification_score=0.92,
        qualification_summary="Steep slope commercial roof repair and replacement.",
        action_type="DISPATCH_EMERGENCY_DISPATCH_QUEUE",
        dispatch_status="QUEUED",
        crm_sync_status="PENDING",
        metadata_payload={
            "customer_name": "Marcus Kane",
            "address": "7400 Wisconsin Ave, Bethesda, MD 20814",
            "trade_type": "Roofing",
            "category": "Roofing",
        },
    )
    db_session.add(action)
    await db_session.commit()
    await db_session.refresh(action)
    return action


def test_fallback_safety_audit_roofing():
    """Verify fallback safety audit produces compliant report with OSHA 1926 citations for roofing."""
    report = fallback_safety_audit(trade_type="Roofing")
    assert isinstance(report, SafetyAuditReport)
    assert 0 <= report.safety_score <= 100
    assert report.compliance_status in ("COMPLIANT", "HAZARDS_DETECTED")
    assert any("Harness" in ppe or "Hard Hat" in ppe for ppe in report.detected_ppe)
    assert any("1926" in mit for mit in report.osha_mitigations)
    assert "Daily Tailgate Topic" != ""
    assert len(report.daily_tailgate_topic) > 10


def test_fallback_safety_audit_plumbing():
    """Verify fallback safety audit for plumbing detects trench and chemical hazards."""
    report = fallback_safety_audit(trade_type="Plumbing")
    assert isinstance(report, SafetyAuditReport)
    assert report.safety_score > 0
    assert any("Gloves" in ppe or "Boots" in ppe for ppe in report.detected_ppe)
    assert any("1926" in mit for mit in report.osha_mitigations)


@pytest.mark.asyncio
async def test_audit_jobsite_safety_service():
    """Verify audit_jobsite_safety service processes image bytes and trade type."""
    dummy_bytes = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00H\x00H\x00\x00"
    report = await safety_service.audit_jobsite_safety(
        image_bytes=dummy_bytes,
        trade_type="HVAC",
    )
    assert isinstance(report, SafetyAuditReport)
    assert any("Safety Glasses" in ppe or "Gloves" in ppe for ppe in report.detected_ppe)
    assert any("1926" in mit for mit in report.osha_mitigations)


@pytest.mark.asyncio
async def test_get_safety_view_initial(client: AsyncClient, seeded_safety_lead: LeadAction):
    """Verify GET /safety/{action_id} renders initial upload screen when no audit exists."""
    response = await client.get(f"/safety/{seeded_safety_lead.id}")
    assert response.status_code == 200
    assert "Jobsite Safety &amp; OSHA Auditor" in response.text or "Jobsite Safety" in response.text
    assert "Run AI OSHA Safety Audit" in response.text


@pytest.mark.asyncio
async def test_post_safety_audit_upload(
    client: AsyncClient,
    seeded_safety_lead: LeadAction,
    db_session: AsyncSession,
):
    """Verify POST /safety/{action_id}/audit ingests photo, updates DB, and records safety_data."""
    dummy_file = ("jobsite.jpg", io.BytesIO(b"fake-image-bytes-for-safety-check"), "image/jpeg")
    
    response = await client.post(
        f"/safety/{seeded_safety_lead.id}/audit",
        files={"image": dummy_file},
        data={"trade_type": "Roofing"},
        headers={"accept": "application/json"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "SUCCESS"
    assert "report" in data
    assert data["report"]["safety_score"] >= 0

    # Verify database persistence
    query = select(LeadAction).where(LeadAction.id == seeded_safety_lead.id)
    refreshed = (await db_session.execute(query)).scalar_one()
    assert refreshed.safety_data is not None
    assert refreshed.safety_data["safety_score"] == data["report"]["safety_score"]
    assert len(refreshed.safety_data["detected_ppe"]) > 0


@pytest.mark.asyncio
async def test_get_safety_audit_json_api(
    client: AsyncClient,
    seeded_safety_lead: LeadAction,
    db_session: AsyncSession,
):
    """Verify GET /api/v1/safety/{action_id} returns the structured SafetyAuditReport."""
    # Seed audit data into lead action
    sample_report = fallback_safety_audit("Roofing")
    seeded_safety_lead.safety_data = sample_report.model_dump()
    await db_session.commit()

    response = await client.get(f"/api/v1/safety/{seeded_safety_lead.id}")
    assert response.status_code == 200
    data = response.json()
    validated = SafetyAuditReport.model_validate(data)
    assert validated.compliance_status in ("COMPLIANT", "HAZARDS_DETECTED")
    assert validated.safety_score == sample_report.safety_score
