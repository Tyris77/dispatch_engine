import asyncio
import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tenant import Tenant
from app.models.lead_action import LeadAction
from app.schemas.autopilot import (
    AutopilotRunNowResponse,
    AutopilotStatusReport,
    AutopilotTaskLog,
    AutonomousOutreachTarget,
)
from app.services.autopilot import autopilot_service
from tests.conftest import TestingSessionLocal


def test_autopilot_schemas():
    """Verify validation and serialization of autopilot telemetry schemas."""
    log = AutopilotTaskLog(
        task_name="48h Dead Lead Reactivation Scan",
        executed_at="2026-10-04T19:00:00Z",
        items_processed=4,
        status="SUCCESS",
        details="Reactivated 4 dormant estimates.",
    )
    assert log.task_name == "48h Dead Lead Reactivation Scan"
    assert log.items_processed == 4
    assert log.status == "SUCCESS"

    target = AutonomousOutreachTarget(
        company_name="Potomac Elite Plumbing LLC",
        trade="Plumbing & Mechanical",
        contact_email="dispatch@potomacelite.com",
        city="Bethesda, MD",
        status="DISCOVERED",
    )
    assert target.company_name == "Potomac Elite Plumbing LLC"
    assert target.status == "DISCOVERED"

    report = AutopilotStatusReport(
        is_running=True,
        last_cycle_time="2026-10-04T19:00:00Z",
        active_tasks=["Task 1", "Task 2"],
        recent_logs=[log],
        next_scheduled_run="2026-10-04T19:15:00Z",
    )
    assert report.is_running is True
    assert len(report.recent_logs) == 1

    resp = AutopilotRunNowResponse(
        cycle_status="COMPLETED",
        executed_at="2026-10-04T19:00:00Z",
        total_tasks_run=5,
        logs=[log],
    )
    assert resp.cycle_status == "COMPLETED"
    assert resp.total_tasks_run == 5


@pytest.mark.asyncio
async def test_autopilot_cycle_execution(db_session: AsyncSession):
    """Test full execution of all 5 autonomous autopilot tasks with simulated tenant."""
    # Seed a tenant to ensure tenant iteration works cleanly
    tenant = Tenant(
        id=uuid.uuid4(),
        name="Apex Autopilot Test HVAC",
        slug=f"autopilot-test-{uuid.uuid4().hex[:6]}",
        api_key_hash="hash",
        webhook_secret="secret",
        settings={},
    )
    db_session.add(tenant)
    await db_session.commit()

    # Execute cycle forcing all time-gated tasks (routing and weekly digest)
    result = await autopilot_service.execute_autonomous_cycle(
        session_factory=TestingSessionLocal,
        force_all=True,
    )

    assert result.cycle_status == "COMPLETED"
    assert result.total_tasks_run == 7
    assert len(result.logs) == 7

    task_names = [log.task_name for log in result.logs]
    assert "48h Dead Lead Reactivation" in task_names
    assert "NOAA Severe Weather Radar & Warnings" in task_names
    assert "Next-Day Fleet Route Clustering" in task_names
    assert "Weekly Executive ROI Digest" in task_names
    assert "Zero-Touch Contractor Discovery & Outreach" in task_names
    assert "Autonomous B2B Drip & Territory Follow-Up" in task_names
    assert "Search Engine IndexNow Ping & Sitemap Verification" in task_names


    # Check status report was updated
    report = autopilot_service.get_status_report()
    assert report.last_cycle_time is not None
    assert len(report.recent_logs) >= 5
    assert "48h Dead Lead Reactivation" in report.active_tasks[0]


@pytest.mark.asyncio
async def test_autopilot_background_loop_graceful_stop():
    """Verify background worker loop starts and stops cleanly via stop_event."""
    stop_event = asyncio.Event()

    # Spawn loop with ultra-short interval
    loop_task = asyncio.create_task(
        autopilot_service.start_autopilot_background_loop(
            app=None,
            stop_event=stop_event,
            interval_seconds=1,
            session_factory=TestingSessionLocal,
        )
    )

    # Let loop initialize and run first step
    await asyncio.sleep(0.05)
    assert autopilot_service.is_running is True

    # Signal graceful shutdown
    stop_event.set()
    await loop_task
    assert autopilot_service.is_running is False


@pytest.mark.asyncio
async def test_api_autopilot_status(client: AsyncClient):
    """Test GET /api/v1/autopilot/status endpoint."""
    response = await client.get("/api/v1/autopilot/status")
    assert response.status_code == 200
    data = response.json()
    assert "is_running" in data
    assert "active_tasks" in data
    assert "recent_logs" in data
    assert "next_scheduled_run" in data
    assert isinstance(data["active_tasks"], list)
    assert len(data["active_tasks"]) == 7


@pytest.mark.asyncio
async def test_api_autopilot_run_now(client: AsyncClient, db_session: AsyncSession):
    """Test POST /api/v1/autopilot/run-now operator manual trigger."""
    # Ensure a tenant exists in DB for this test
    tenant = Tenant(
        id=uuid.uuid4(),
        name="Apex Autopilot API Tenant",
        slug=f"autopilot-api-{uuid.uuid4().hex[:6]}",
        api_key_hash="hash",
        webhook_secret="secret",
        settings={},
    )
    db_session.add(tenant)
    await db_session.commit()

    response = await client.post("/api/v1/autopilot/run-now?force_all=true")
    assert response.status_code == 200
    data = response.json()
    assert data["cycle_status"] == "COMPLETED"
    assert data["total_tasks_run"] == 7
    assert len(data["logs"]) == 7

