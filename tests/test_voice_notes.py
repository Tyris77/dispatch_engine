import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lead_action import LeadAction
from app.models.tenant import Tenant
from app.schemas.voice_notes import DictatedWorkOrderSummary
from app.services.voice_notes import (
    voice_notes_service,
    fallback_voice_notes_parser,
)


@pytest.fixture
async def seeded_voice_lead(sample_tenant: dict, db_session: AsyncSession) -> LeadAction:
    """Fixture providing a seeded LeadAction with an invoice ready for voice dictation."""
    tenant = sample_tenant["tenant"]
    tenant.name = "Apex Climate Pros LLC"
    db_session.add(tenant)

    action = LeadAction(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        lead_external_id="+15559994321",
        qualification_score=0.94,
        qualification_summary="Emergency AC blowing warm air on second floor.",
        action_type="DISPATCH_EMERGENCY_DISPATCH_QUEUE",
        dispatch_status="QUEUED",
        crm_sync_status="PENDING",
        metadata_payload={
            "customer_name": "David Wallace",
            "address": "900 Rockville Pike, Rockville, MD 20852",
            "trade_type": "HVAC",
            "category": "HVAC",
        },
        invoice_data={
            "invoice_number": "INV-2026-0419",
            "contract_total": 485.0,
            "balance_due": 485.0,
            "payment_status": "PENDING",
        },
    )
    db_session.add(action)
    await db_session.commit()
    await db_session.refresh(action)
    return action


def test_fallback_voice_notes_hvac():
    """Verify fallback parser extracts subcooling, amps, capacitor part, and narrative for HVAC dictation."""
    sample_speech = (
        "Replaced swollen 45/5 dual run capacitor. Subcooling was 10.5 degrees. "
        "Compressor is drawing 13.8 amps. Replaced contactor and cleaned outdoor coil. "
        "Temp split is 19 degrees. System is operational."
    )
    summary = fallback_voice_notes_parser(raw_text=sample_speech, trade="HVAC")

    assert isinstance(summary, DictatedWorkOrderSummary)
    assert summary.system_condition == "OPERATIONAL"
    assert "10.5°F" in summary.technical_readings.get("subcooling", "")
    assert "13.8A" in summary.technical_readings.get("compressor_amps", "")
    assert "19°F" in summary.technical_readings.get("temperature_split", "")
    assert any("Capacitor" in p or "Contactor" in p for p in summary.parts_installed)
    assert len(summary.work_completed_bullets) >= 2
    assert len(summary.formatted_invoice_narrative) > 30


def test_fallback_voice_notes_plumbing():
    """Verify plumbing dictation extracts water pressure PSI and PRV replacement."""
    sample_speech = "Tested static water pressure at 92 psi. Replaced pressure reducing valve and adjusted pressure to 65 psi."
    summary = fallback_voice_notes_parser(raw_text=sample_speech, trade="Plumbing")

    assert isinstance(summary, DictatedWorkOrderSummary)
    assert "PSI" in str(summary.technical_readings)
    assert any("Pressure" in p or "Valve" in p for p in summary.parts_installed)


@pytest.mark.asyncio
async def test_process_technician_dictation_service():
    """Verify voice_notes_service.process_dictation handles spoken dictation."""
    summary = await voice_notes_service.process_dictation(
        raw_text_or_audio="Replaced thermocouple and cleaned pilot orifice. Gas pressure set at 3.5 inches W.C.",
        trade_context={"trade_category": "Plumbing"},
    )
    assert isinstance(summary, DictatedWorkOrderSummary)
    assert summary.system_condition in ("OPERATIONAL", "NEEDS_MONITORING", "ATTENTION_REQUIRED")


@pytest.mark.asyncio
async def test_attach_notes_to_lead_enriches_invoice(
    seeded_voice_lead: LeadAction,
    db_session: AsyncSession,
):
    """Verify attaching voice notes updates lead_action.voice_notes_data and enriches invoice_data."""
    summary = fallback_voice_notes_parser("Replaced run cap, tested 10F subcooling, 14A amps.", "HVAC")
    voice_notes_service.attach_notes_to_lead(seeded_voice_lead, summary)
    await db_session.commit()
    await db_session.refresh(seeded_voice_lead)

    assert seeded_voice_lead.voice_notes_data is not None
    assert seeded_voice_lead.invoice_data is not None
    assert "work_order_summary" in seeded_voice_lead.invoice_data
    assert len(seeded_voice_lead.invoice_data["work_order_summary"]) > 20


@pytest.mark.asyncio
async def test_post_voice_notes_form_redirects(
    client: AsyncClient,
    seeded_voice_lead: LeadAction,
    db_session: AsyncSession,
):
    """Verify POST /track/{action_id}/voice-notes processes form submission and redirects."""
    response = await client.post(
        f"/track/{seeded_voice_lead.id}/voice-notes",
        data={
            "notes_text": "Swapped out defective capacitor and contactor. Checked subcooling at 11 degrees. System running cold.",
            "trade_category": "HVAC",
        },
    )
    assert response.status_code == 303
    assert response.headers["location"] == f"/track/{seeded_voice_lead.id}"

    # Verify DB persistence
    query = select(LeadAction).where(LeadAction.id == seeded_voice_lead.id)
    refreshed = (await db_session.execute(query)).scalar_one()
    assert refreshed.voice_notes_data is not None
    assert len(refreshed.voice_notes_data["parts_installed"]) > 0


@pytest.mark.asyncio
async def test_post_voice_notes_json_mode(
    client: AsyncClient,
    seeded_voice_lead: LeadAction,
):
    """Verify POST /track/{action_id}/voice-notes returns structured JSON when requested."""
    payload = {
        "transcript_or_text": "Cleared condensate drain line with nitrogen blow out. Treated drain pan with biocide tablets.",
        "trade_category": "HVAC",
    }
    response = await client.post(
        f"/track/{seeded_voice_lead.id}/voice-notes",
        json=payload,
        headers={"accept": "application/json"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "SUCCESS"
    assert "summary" in data
    assert data["invoice_updated"] is True


@pytest.mark.asyncio
async def test_get_voice_notes_api(
    client: AsyncClient,
    seeded_voice_lead: LeadAction,
    db_session: AsyncSession,
):
    """Verify GET /api/v1/voice-notes/{action_id} returns structured work order summary."""
    summary = fallback_voice_notes_parser("Replaced PRV, verified 65 psi water pressure.", "Plumbing")
    seeded_voice_lead.voice_notes_data = summary.model_dump()
    await db_session.commit()

    response = await client.get(f"/api/v1/voice-notes/{seeded_voice_lead.id}")
    assert response.status_code == 200
    data = response.json()
    validated = DictatedWorkOrderSummary.model_validate(data)
    assert validated.system_condition == "OPERATIONAL"
    assert len(validated.formatted_invoice_narrative) > 20
