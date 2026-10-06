import pytest
from httpx import AsyncClient

from app.schemas.drip import (
    DripCampaignStatus,
    DripContractorLead,
    DripLeadStatus,
    DripTriggerResponse,
)
from app.services.drip import drip_service, INITIAL_DMV_CONTRACTORS


def test_drip_schemas():
    """Verify validation and serialization of B2B Drip schemas."""
    lead = DripContractorLead(
        contractor_id="lead_test_01",
        company_name="John C. Flood",
        trade="Plumbing & HVAC",
        contact_name="Cliff Flood",
        contact_email="cflood@johncflood.com",
        phone="+17032731100",
        territory="Arlington, VA & Washington, DC",
        status=DripLeadStatus.CONTACTED,
        initial_contact_at="2026-10-04 12:00:00 UTC",
        missed_calls_est=48,
        revenue_leak_est=57600.0,
        audit_url="/audit?trade=plumbing",
        onboard_url="/onboard",
    )
    assert lead.company_name == "John C. Flood"
    assert lead.status == DripLeadStatus.CONTACTED
    assert lead.revenue_leak_est == 57600.0

    status_report = DripCampaignStatus(
        total_enrolled=12,
        contacted=4,
        followup_1_due=4,
        followup_2_due=4,
        leads=[lead],
    )
    assert status_report.total_enrolled == 12
    assert len(status_report.leads) == 1

    resp = DripTriggerResponse(
        status="COMPLETED",
        evaluated_count=12,
        followups_dispatched=5,
        messages_sent=[{"subject": "Follow-up"}],
        timestamp="2026-10-06 12:00:00 UTC",
    )
    assert resp.status == "COMPLETED"
    assert resp.followups_dispatched == 5


def test_initial_dmv_contractors_enrollment():
    """Verify all 12 initial DMV target contractors are enrolled and tracked."""
    pipeline = drip_service.get_pipeline()
    assert pipeline.total_enrolled == 12
    assert len(pipeline.leads) == 12

    companies = [lead.company_name for lead in pipeline.leads]
    assert "John C. Flood" in companies
    assert "The Drain Guys" in companies
    assert "Superior Air Systems" in companies
    assert "AZA Mechanical" in companies
    assert "Cardinal Emergency Plumbing" in companies
    assert "F.H. Furr Plumbing & HVAC" in companies
    assert "Michael & Son Services" in companies
    assert "CroppMetcalfe" in companies
    assert "Magnolia Plumbing & Heating" in companies
    assert "4-Star Emergency Restoration" in companies
    assert "Capitol Commercial Roofing" in companies
    assert "District Electric & Generator" in companies


def test_generate_48h_followup_links_audit():
    """Verify 48h Follow-up #1 generates value email linking to territory Missed Call Audit Calculator."""
    lead = list(drip_service.leads.values())[0]
    msg = drip_service.generate_48h_followup(lead)

    assert "FOLLOWUP_1_AUDIT" == msg["type"]
    assert lead.company_name in msg["subject"]
    assert "after-hours call leak" in msg["subject"].lower()
    assert "/audit" in msg["body"]
    assert "https://dispatchengine-production.up.railway.app" in msg["body"]
    assert lead.contact_name in msg["body"]
    assert f"${lead.revenue_leak_est:,.0f}" in msg["body"]


def test_generate_day5_followup_links_onboard():
    """Verify Day 5 Follow-up #2 generates clean closing email linking to 1-click self-serve setup."""
    lead = list(drip_service.leads.values())[0]
    msg = drip_service.generate_day5_followup(lead)

    assert "FOLLOWUP_2_ONBOARD" == msg["type"]
    assert "1-Click Autonomous Dispatch Setup" in msg["subject"]
    assert lead.company_name in msg["subject"]
    assert "/onboard" in msg["body"]
    assert "60 seconds" in msg["body"]
    assert "zero credit card" in msg["body"].lower()


@pytest.mark.asyncio
async def test_evaluate_drip_schedules():
    """Verify autonomous schedule evaluation advances stages and dispatches follow-ups."""
    drip_service.reset_pipeline()
    result = await drip_service.evaluate_drip_schedules(force_all=True)
    assert result.status == "COMPLETED"
    assert result.evaluated_count == 12
    assert result.followups_dispatched > 0
    assert len(result.messages_sent) > 0


@pytest.mark.asyncio
async def test_api_drip_pipeline(client: AsyncClient):
    """Test GET /api/v1/drip/pipeline endpoint."""
    response = await client.get("/api/v1/drip/pipeline")
    assert response.status_code == 200
    data = response.json()

    assert data["total_enrolled"] == 12
    assert "leads" in data
    assert len(data["leads"]) == 12
    lead_names = [l["company_name"] for l in data["leads"]]
    assert "John C. Flood" in lead_names


@pytest.mark.asyncio
async def test_api_drip_trigger(client: AsyncClient):
    """Test POST /api/v1/drip/trigger manual cycle override."""
    response = await client.post("/api/v1/drip/trigger?force_all=true")
    assert response.status_code == 200
    data = response.json()

    assert data["status"] == "COMPLETED"
    assert data["evaluated_count"] == 12
    assert "messages_sent" in data


@pytest.mark.asyncio
async def test_api_drip_lead_status_update(client: AsyncClient):
    """Test PATCH /api/v1/drip/leads/{contractor_id}/status transition endpoint."""
    lead_id = list(drip_service.leads.keys())[0]
    response = await client.patch(
        f"/api/v1/drip/leads/{lead_id}/status?new_status=REPLIED&notes=Answered+positive+to+audit"
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "UPDATED"
    assert data["lead"]["status"] == "REPLIED"
    assert "Answered positive" in data["lead"]["notes"]
