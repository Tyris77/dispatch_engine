import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lead_action import LeadAction
from app.models.tenant import Tenant
from app.schemas.mitigation import (
    DailyMoistureSubmission,
    MitigationDryingReport,
    MoistureReading,
    PsychrometricDayLog,
)
from app.services.mitigation import mitigation_service


def test_mitigation_schemas():
    """Verify validation and serialization of IICRC S500 water mitigation schemas."""
    reading = MoistureReading(
        room_name="Basement Rec Room",
        material_type="Drywall",
        moisture_percentage=38.4,
        dry_standard=12.0,
        drying_status="WET",
    )
    assert reading.room_name == "Basement Rec Room"
    assert reading.material_type == "Drywall"
    assert reading.moisture_percentage == 38.4
    assert reading.drying_status == "WET"

    day_log = PsychrometricDayLog(
        day_number=1,
        date="2026-10-01",
        temp_fahrenheit=72.5,
        relative_humidity_pct=65.0,
        gpp_grains_per_pound=76.8,
        dehumidifiers_running=2,
        air_movers_running=6,
        readings=[reading],
    )
    assert day_log.day_number == 1
    assert day_log.gpp_grains_per_pound == 76.8
    assert len(day_log.readings) == 1

    report = MitigationDryingReport(
        dossier_id="DOS-WTR-8812",
        action_id=str(uuid.uuid4()),
        job_address="1401 S Joyce St, Arlington, VA",
        date_of_loss="2026-10-01",
        customer_name="Elena Rostova",
        daily_logs=[day_log],
        iicrc_compliant=True,
        drying_completed=False,
    )
    assert report.iicrc_compliant is True
    assert report.drying_completed is False


def test_psychrometric_gpp_calculation():
    """Verify psychrometric grains per pound (GPP) algorithm."""
    # At 70°F and 50% RH: standard indoor air is ~54-55 GPP
    gpp_70_50 = mitigation_service.calculate_psychrometric_gpp(70.0, 50.0)
    assert 52.0 <= gpp_70_50 <= 57.0

    # At 75°F and 30% RH: dry chamber air is ~38-42 GPP
    gpp_75_30 = mitigation_service.calculate_psychrometric_gpp(75.0, 30.0)
    assert 37.0 <= gpp_75_30 <= 43.0

    # Zero humidity returns 0 GPP
    assert mitigation_service.calculate_psychrometric_gpp(70.0, 0.0) == 0.0


@pytest.mark.asyncio
async def test_get_mitigation_report_synthetic(db_session: AsyncSession):
    """Verify automatic generation of compliant 4-day psychrometric drying progress report."""
    tenant = Tenant(
        id=uuid.uuid4(),
        name="All-Dry Disaster Restoration",
        slug=f"alldry-{uuid.uuid4().hex[:6]}",
        api_key_hash="hash",
        webhook_secret="secret",
        is_active=True,
    )
    db_session.add(tenant)

    lead = LeadAction(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        lead_external_id="LD-WTR-001",
        qualification_score=0.95,
        qualification_summary="Water main line fractured in finished basement",
        action_type="EMERGENCY_DISPATCH",
        dispatch_status="QUEUED",
        crm_sync_status="PENDING",
        metadata_payload={
            "customer_name": "Michael Scott",
            "phone": "+15715550188",
            "email": "michael@dundermifflin.com",
            "address": "1725 Slough Ave, Scranton, PA",
            "source": "voice",
            "priority": "EMERGENCY",
        },
    )
    db_session.add(lead)
    await db_session.commit()

    report = await mitigation_service.get_mitigation_report(lead.id, db_session)
    assert report is not None
    assert report.action_id == str(lead.id)
    assert report.customer_name == "Michael Scott"
    assert report.job_address == "1725 Slough Ave, Scranton, PA"
    assert len(report.daily_logs) == 4
    assert report.iicrc_compliant is True
    assert report.drying_completed is True

    # Verify psychrometric drying curve decreases day over day
    gpps = [log.gpp_grains_per_pound for log in report.daily_logs]
    assert gpps[0] > gpps[1] > gpps[2] > gpps[3]

    # Verify moisture levels reached dry standard by day 4
    for r in report.daily_logs[-1].readings:
        assert r.drying_status == "DRY_STANDARD_MET"


@pytest.mark.asyncio
async def test_record_daily_moisture_log(db_session: AsyncSession):
    """Verify technician can record new daily moisture and chamber logs."""
    tenant = Tenant(
        id=uuid.uuid4(),
        name="Flood Response 247",
        slug=f"flood-{uuid.uuid4().hex[:6]}",
        api_key_hash="hash",
        webhook_secret="secret",
        is_active=True,
    )
    db_session.add(tenant)

    lead = LeadAction(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        lead_external_id="LD-WTR-002",
        qualification_score=0.98,
        qualification_summary="Basement crawlspace water detection alarm",
        action_type="EMERGENCY_DISPATCH",
        dispatch_status="IN_PROGRESS",
        crm_sync_status="PENDING",
        metadata_payload={
            "customer_name": "Jim Halpert",
            "phone": "+15715550199",
            "email": "jim@dunder.com",
            "address": "421 Elm St, Bethesda, MD",
            "source": "iot_sensor",
            "priority": "EMERGENCY",
        },
    )
    db_session.add(lead)
    await db_session.commit()

    submission = {
        "day_number": 5,
        "date": "2026-10-05",
        "temp_fahrenheit": 74.0,
        "relative_humidity_pct": 28.0,
        "dehumidifiers_running": 1,
        "air_movers_running": 3,
        "readings": [
            {
                "room_name": "Finished Basement",
                "material_type": "Drywall",
                "moisture_percentage": 11.2,
                "dry_standard": 12.0,
            },
            {
                "room_name": "Mechanical Room",
                "material_type": "Subfloor",
                "moisture_percentage": 13.0,
                "dry_standard": 14.0,
            },
        ],
    }

    updated_report = await mitigation_service.record_daily_moisture_log(lead.id, submission, db_session)
    assert updated_report is not None
    assert len(updated_report.daily_logs) >= 1
    latest_log = updated_report.daily_logs[-1]
    assert latest_log.day_number == 5
    assert latest_log.temp_fahrenheit == 74.0
    assert latest_log.relative_humidity_pct == 28.0
    assert latest_log.gpp_grains_per_pound < 35.0  # Certified dry air

    # Check that database model holds updated mitigation_data
    await db_session.refresh(lead)
    assert lead.mitigation_data is not None
    assert lead.mitigation_data["drying_completed"] is True


@pytest.mark.asyncio
async def test_mitigation_report_html_view(client: AsyncClient, sample_tenant: dict, db_session: AsyncSession):
    """Verify GET /mitigation/{action_id} renders adjuster-ready certified drying report."""
    tenant = sample_tenant["tenant"]
    lead = LeadAction(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        lead_external_id="LD-ADJ-001",
        qualification_score=0.96,
        qualification_summary="Kitchen supply line pipe rupture",
        action_type="EMERGENCY_DISPATCH",
        dispatch_status="QUEUED",
        crm_sync_status="PENDING",
        metadata_payload={
            "customer_name": "Pam Beesly",
            "phone": "+15715550177",
            "email": "pam@dunder.com",
            "address": "333 Oak St, Arlington, VA",
            "source": "emergency_call",
            "priority": "EMERGENCY",
        },
    )
    db_session.add(lead)
    await db_session.commit()

    res = await client.get(f"/mitigation/{lead.id}")
    assert res.status_code == 200
    html = res.text
    assert "ANSI/IICRC S500 Certified" in html
    assert "Psychrometric Drying & Moisture Log Report" in html
    assert "Psychrometric Chamber Conditions (Daily GPP Progression)" in html
    assert "Pam Beesly" in html
    assert "333 Oak St, Arlington, VA" in html
    assert "Certified ANSI/IICRC S500 Standard Compliance" in html


@pytest.mark.asyncio
async def test_mitigation_post_log_api(client: AsyncClient, sample_tenant: dict, db_session: AsyncSession):
    """Verify POST /mitigation/{action_id}/log updates daily technician moisture readings."""
    tenant = sample_tenant["tenant"]
    lead = LeadAction(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        lead_external_id="LD-ADJ-002",
        qualification_score=0.95,
        qualification_summary="Farmhouse basement irrigation backflow",
        action_type="EMERGENCY_DISPATCH",
        dispatch_status="QUEUED",
        crm_sync_status="PENDING",
        metadata_payload={
            "customer_name": "Dwight Schrute",
            "phone": "+15715550133",
            "email": "dwight@schrute.com",
            "address": "Schrute Farms, Honesdale, PA",
            "source": "iot_sensor",
            "priority": "EMERGENCY",
        },
    )
    db_session.add(lead)
    await db_session.commit()

    payload = {
        "day_number": 2,
        "date": "2026-10-02",
        "temp_fahrenheit": 71.0,
        "relative_humidity_pct": 45.0,
        "dehumidifiers_running": 2,
        "air_movers_running": 4,
        "readings": [
            {
                "room_name": "Cellar",
                "material_type": "Drywall",
                "moisture_percentage": 22.0,
                "dry_standard": 12.0,
            }
        ],
    }

    res = await client.post(f"/mitigation/{lead.id}/log", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["action_id"] == str(lead.id)
    assert len(data["daily_logs"]) >= 1


@pytest.mark.asyncio
async def test_mitigation_report_not_found(client: AsyncClient):
    """Verify GET /mitigation/{random_uuid} returns 404 for unknown lead."""
    random_id = uuid.uuid4()
    res = await client.get(f"/mitigation/{random_id}")
    assert res.status_code == 404
