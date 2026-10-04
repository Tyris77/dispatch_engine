import datetime
import uuid
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lead_action import LeadAction
from app.models.tenant import Tenant
from app.schemas.surge import SurgePricingAssessment
from app.services.dispatch import dispatch_service
from app.services.surge import surge_pricing_service


@pytest.fixture
async def surge_test_tenant(sample_tenant: dict, db_session: AsyncSession) -> Tenant:
    """Fixture providing a tenant with standard operating hours and pricing settings."""
    tenant = sample_tenant["tenant"]
    tenant.name = "Apex Climate and Plumbing Solutions LLC"
    tenant.settings = {
        "operating_hours": {
            "start_hour": 8,
            "end_hour": 18,
            "workdays": [0, 1, 2, 3, 4],  # Mon - Fri
        },
        "standard_diagnostic_fee": 89.0,
        "after_hours_diagnostic_fee": 199.0,
        "after_hours_labor_multiplier": 1.5,
        "weather_surge_diagnostic_fee": 249.0,
        "weather_surge_labor_multiplier": 1.75,
    }
    db_session.add(tenant)
    await db_session.commit()
    await db_session.refresh(tenant)
    return tenant


def test_surge_pricing_schemas():
    """Verify validation and serialization of SurgePricingAssessment."""
    assessment = SurgePricingAssessment(
        is_surge_active=True,
        surge_reason="AFTER_HOURS_WEEKEND",
        diagnostic_fee=199.0,
        labor_multiplier=1.5,
        surge_disclosure="After-hours emergency dispatch fee is $199 with 1.5x labor rate.",
        rate_card={
            "standard_diagnostic": 89.0,
            "active_diagnostic": 199.0,
            "standard_labor_rate": 145.0,
            "active_labor_rate": 217.50,
            "labor_multiplier": 1.5,
        },
    )
    assert assessment.is_surge_active is True
    assert assessment.surge_reason == "AFTER_HOURS_WEEKEND"
    assert assessment.diagnostic_fee == 199.0
    assert assessment.labor_multiplier == 1.5
    assert assessment.rate_card["active_labor_rate"] == 217.50


def test_standard_hours_pricing(surge_test_tenant: Tenant, monkeypatch):
    """Verify standard daytime pricing during Monday-Friday regular hours without weather hazard."""
    monkeypatch.setattr("app.services.surge.METEOROLOGICAL_HAZARD_REGISTRY", [])

    # Wednesday 2:00 PM UTC
    wednesday_daytime = datetime.datetime(2026, 10, 7, 14, 0, 0, tzinfo=datetime.timezone.utc)
    assessment = surge_pricing_service.assess_surge_pricing(
        tenant=surge_test_tenant,
        current_dt=wednesday_daytime,
    )

    assert assessment.is_surge_active is False
    assert assessment.surge_reason == "STANDARD_HOURS"
    assert assessment.diagnostic_fee == 89.0
    assert assessment.labor_multiplier == 1.0
    assert "Standard daytime dispatch" in assessment.surge_disclosure


def test_after_hours_weekday_evening_pricing(surge_test_tenant: Tenant, monkeypatch):
    """Verify after-hours surge fee ($199 / 1.5x) on weekday evenings."""
    monkeypatch.setattr("app.services.surge.METEOROLOGICAL_HAZARD_REGISTRY", [])

    # Wednesday 9:30 PM UTC
    wednesday_night = datetime.datetime(2026, 10, 7, 21, 30, 0, tzinfo=datetime.timezone.utc)
    assessment = surge_pricing_service.assess_surge_pricing(
        tenant=surge_test_tenant,
        current_dt=wednesday_night,
    )

    assert assessment.is_surge_active is True
    assert assessment.surge_reason == "AFTER_HOURS_WEEKEND"
    assert assessment.diagnostic_fee == 199.0
    assert assessment.labor_multiplier == 1.5
    assert "after-hours emergency dispatch" in assessment.surge_disclosure.lower()


def test_weekend_surge_pricing(surge_test_tenant: Tenant, monkeypatch):
    """Verify weekend surge pricing on Saturdays and Sundays."""
    monkeypatch.setattr("app.services.surge.METEOROLOGICAL_HAZARD_REGISTRY", [])

    # Saturday 1:00 PM UTC
    saturday_noon = datetime.datetime(2026, 10, 10, 13, 0, 0, tzinfo=datetime.timezone.utc)
    assessment = surge_pricing_service.assess_surge_pricing(
        tenant=surge_test_tenant,
        current_dt=saturday_noon,
    )

    assert assessment.is_surge_active is True
    assert assessment.surge_reason == "AFTER_HOURS_WEEKEND"
    assert assessment.diagnostic_fee == 199.0
    assert assessment.labor_multiplier == 1.5


def test_severe_weather_surge_pricing(surge_test_tenant: Tenant, monkeypatch):
    """Verify severe weather hazard warning overrides regular daytime hours with emergency rates ($249 / 1.75x)."""
    mock_hazards = [
        {
            "alert_id": "ALERT-TEST-01",
            "event_title": "Severe Tornado & Hail Warning",
            "severity": "WARNING",
        }
    ]
    monkeypatch.setattr("app.services.surge.METEOROLOGICAL_HAZARD_REGISTRY", mock_hazards)

    # Wednesday 2:00 PM UTC (standard business hours)
    daytime = datetime.datetime(2026, 10, 7, 14, 0, 0, tzinfo=datetime.timezone.utc)
    assessment = surge_pricing_service.assess_surge_pricing(
        tenant=surge_test_tenant,
        current_dt=daytime,
    )

    assert assessment.is_surge_active is True
    assert assessment.surge_reason == "SEVERE_WEATHER_SURGE"
    assert assessment.diagnostic_fee == 249.0
    assert assessment.labor_multiplier == 1.75
    assert "hazard surge pricing is currently active" in assessment.surge_disclosure.lower()


def test_apply_surge_to_lead(surge_test_tenant: Tenant, monkeypatch):
    """Verify apply_surge_to_lead attaches surge_pricing_data to LeadAction."""
    monkeypatch.setattr("app.services.surge.METEOROLOGICAL_HAZARD_REGISTRY", [])

    lead = LeadAction(
        id=uuid.uuid4(),
        tenant_id=surge_test_tenant.id,
        lead_external_id="+15559998888",
        action_type="EMERGENCY_DISPATCH",
    )

    sunday_evening = datetime.datetime(2026, 10, 11, 20, 0, 0, tzinfo=datetime.timezone.utc)
    assessment = surge_pricing_service.apply_surge_to_lead(
        lead_action=lead,
        tenant=surge_test_tenant,
        current_dt=sunday_evening,
    )

    assert lead.surge_pricing_data is not None
    assert lead.surge_pricing_data["is_surge_active"] is True
    assert lead.surge_pricing_data["surge_reason"] == "AFTER_HOURS_WEEKEND"
    assert lead.surge_pricing_data["diagnostic_fee"] == 199.0
    assert assessment.is_surge_active is True


@pytest.mark.asyncio
async def test_lead_action_columns_persistence(
    surge_test_tenant: Tenant,
    db_session: AsyncSession,
):
    """Verify route_stop_data and surge_pricing_data columns persist cleanly in the database."""
    lead = LeadAction(
        id=uuid.uuid4(),
        tenant_id=surge_test_tenant.id,
        lead_external_id="+15557778888",
        qualification_score=0.92,
        qualification_summary="Emergency HVAC furnace explosion odor.",
        action_type="EMERGENCY_DISPATCH",
        dispatch_status="CONFIRMED",
        crm_sync_status="SYNCED",
        route_stop_data={
            "assigned_technician": "Marcus Vance",
            "truck_id": "TRUCK-01",
            "stop_order": 1,
            "scheduled_time": "08:30 AM",
            "nav_link": "https://maps.google.com/?q=Austin",
        },
        surge_pricing_data={
            "is_surge_active": True,
            "surge_reason": "AFTER_HOURS_WEEKEND",
            "diagnostic_fee": 199.0,
            "labor_multiplier": 1.5,
            "surge_disclosure": "Emergency after-hours fee is $199.",
        },
    )

    db_session.add(lead)
    await db_session.commit()
    await db_session.refresh(lead)

    assert lead.route_stop_data["assigned_technician"] == "Marcus Vance"
    assert lead.route_stop_data["stop_order"] == 1
    assert lead.surge_pricing_data["is_surge_active"] is True
    assert lead.surge_pricing_data["diagnostic_fee"] == 199.0


@pytest.mark.asyncio
async def test_dispatch_plan_execution_attaches_surge_pricing(
    surge_test_tenant: Tenant,
    db_session: AsyncSession,
    monkeypatch,
):
    """Verify dispatch_service.execute_dispatch_plan evaluates and attaches surge pricing."""
    monkeypatch.setattr("app.services.surge.METEOROLOGICAL_HAZARD_REGISTRY", [])

    lead = LeadAction(
        id=uuid.uuid4(),
        tenant_id=surge_test_tenant.id,
        lead_external_id="+15552223333",
        qualification_score=0.96,
        qualification_summary="Emergency pipe burst flooding basement.",
        action_type="DISPATCH_EMERGENCY_DISPATCH_QUEUE",
        dispatch_status="PENDING",
        metadata_payload={
            "qualification": {
                "intent_level": "EMERGENCY",
            }
        },
    )
    db_session.add(lead)
    await db_session.commit()
    await db_session.refresh(lead)

    await dispatch_service.execute_dispatch_plan(lead_action=lead, tenant=surge_test_tenant)

    assert lead.surge_pricing_data is not None
    assert "is_surge_active" in lead.surge_pricing_data
    assert "diagnostic_fee" in lead.surge_pricing_data
