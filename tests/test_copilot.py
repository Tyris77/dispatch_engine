import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lead_action import LeadAction
from app.models.tenant import Tenant
from app.schemas.copilot import CopilotQueryRequest, CopilotQueryResponse
from app.services.copilot import copilot_service


@pytest.fixture
async def copilot_test_env(sample_tenant: dict, db_session: AsyncSession) -> dict:
    """Fixture providing a seeded tenant with closed contracts and emergency calls."""
    tenant = sample_tenant["tenant"]
    tenant.name = "Apex Metro Mechanical Group"
    db_session.add(tenant)

    # Urgent lead
    action1 = LeadAction(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        lead_external_id="+15551113333",
        qualification_score=0.96,
        qualification_summary="Emergency gas line rupture and furnace flame rollout.",
        action_type="DISPATCH_EMERGENCY_DISPATCH_QUEUE",
        dispatch_status="QUEUED",
        crm_sync_status="SYNCED",
        metadata_payload={
            "customer_name": "Montgomery Hospital",
            "priority_tier": "URGENT",
            "assigned_technician": "Marcus Vance",
        },
        tracking_data={"technician_name": "Marcus Vance"},
    )

    # Closed job with signed contract & invoice
    action2 = LeadAction(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        lead_external_id="+15552224444",
        qualification_score=0.89,
        qualification_summary="Dual heat pump replacement with 10-year warranty.",
        action_type="DISPATCH_EMERGENCY_DISPATCH_QUEUE",
        dispatch_status="COMPLETED",
        crm_sync_status="SYNCED",
        metadata_payload={
            "customer_name": "Arthur Pendelton",
            "assigned_technician": "Marcus Vance",
        },
        tracking_data={"technician_name": "Marcus Vance"},
        signed_contract={
            "selected_tier": "Better",
            "total_amount": 5400.0,
            "status": "SIGNED",
        },
        invoice_data={
            "contract_total": 5400.0,
            "balance_due": 1200.0,
            "status": "OVERDUE",
        },
    )

    db_session.add_all([action1, action2])
    await db_session.commit()
    await db_session.refresh(tenant)

    return {"tenant": tenant, "actions": [action1, action2]}


def test_copilot_schemas():
    """Verify CopilotQueryRequest and CopilotQueryResponse validation."""
    req = CopilotQueryRequest(query_text="What is our total revenue?", tenant_slug="apex-demo")
    assert req.query_text == "What is our total revenue?"
    assert req.tenant_slug == "apex-demo"

    resp = CopilotQueryResponse(
        answer_text="Total revenue is $5,400.00.",
        intent="METRICS",
        suggested_actions=[{"label": "View Portal", "url": "/portal/apex-demo"}],
        data_payload={"revenue": 5400.0},
    )
    assert resp.intent == "METRICS"
    assert len(resp.suggested_actions) == 1
    assert resp.data_payload["revenue"] == 5400.0


@pytest.mark.asyncio
async def test_copilot_service_revenue_intent(copilot_test_env: dict, db_session: AsyncSession):
    """Verify revenue/financial queries categorize as METRICS and return live financial stats."""
    tenant = copilot_test_env["tenant"]
    resp = await copilot_service.execute_copilot_query(
        query="What is our gross revenue and overdue invoices?",
        tenant=tenant,
        db=db_session,
    )
    assert isinstance(resp, CopilotQueryResponse)
    assert resp.intent == "METRICS"
    assert "Financial" in resp.answer_text or "Revenue" in resp.answer_text
    assert "5,400" in resp.answer_text
    assert any(a["url"].startswith(f"/portal/{tenant.slug}") for a in resp.suggested_actions)


@pytest.mark.asyncio
async def test_copilot_service_technician_intent(copilot_test_env: dict, db_session: AsyncSession):
    """Verify technician queries categorize as TECHNICIAN_KPI and highlight top performer."""
    tenant = copilot_test_env["tenant"]
    resp = await copilot_service.execute_copilot_query(
        query="Who is our top technician and what is their closing rate?",
        tenant=tenant,
        db=db_session,
    )
    assert isinstance(resp, CopilotQueryResponse)
    assert resp.intent == "TECHNICIAN_KPI"
    assert "Marcus Vance" in resp.answer_text
    assert any("technicians" in a["url"] for a in resp.suggested_actions)


@pytest.mark.asyncio
async def test_copilot_service_emergency_intent(copilot_test_env: dict, db_session: AsyncSession):
    """Verify emergency queue queries categorize as EMERGENCY_SUMMARY and provide map links."""
    tenant = copilot_test_env["tenant"]
    resp = await copilot_service.execute_copilot_query(
        query="How many active emergency calls and dispatches do we have right now?",
        tenant=tenant,
        db=db_session,
    )
    assert isinstance(resp, CopilotQueryResponse)
    assert resp.intent == "EMERGENCY_SUMMARY"
    assert "Emergency" in resp.answer_text
    assert any("map" in a["url"] or "dashboard" in a["url"] for a in resp.suggested_actions)


@pytest.mark.asyncio
async def test_copilot_service_weather_intent(copilot_test_env: dict, db_session: AsyncSession):
    """Verify weather inquiries categorize as WEATHER_RISK and link to weather radar."""
    tenant = copilot_test_env["tenant"]
    resp = await copilot_service.execute_copilot_query(
        query="Are there any severe weather hazards or freeze storm warnings?",
        tenant=tenant,
        db=db_session,
    )
    assert isinstance(resp, CopilotQueryResponse)
    assert resp.intent == "WEATHER_RISK"
    assert any("weather" in a["url"] for a in resp.suggested_actions)


@pytest.mark.asyncio
async def test_copilot_service_general_intent(copilot_test_env: dict, db_session: AsyncSession):
    """Verify general operational questions categorize as GENERAL."""
    tenant = copilot_test_env["tenant"]
    resp = await copilot_service.execute_copilot_query(
        query="Give me a high-level operational overview.",
        tenant=tenant,
        db=db_session,
    )
    assert isinstance(resp, CopilotQueryResponse)
    assert resp.intent == "GENERAL"
    assert "Operational Overview" in resp.answer_text or "DispatchEngine" in resp.answer_text


@pytest.mark.asyncio
async def test_api_copilot_query_endpoint(copilot_test_env: dict, client: AsyncClient):
    """POST /api/v1/copilot/query returns structured response with actions."""
    tenant = copilot_test_env["tenant"]
    resp = await client.post(
        "/api/v1/copilot/query",
        json={"query_text": "What is our current revenue?", "tenant_slug": tenant.slug},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["intent"] == "METRICS"
    assert len(data["suggested_actions"]) > 0
    assert "5,400" in data["answer_text"]


@pytest.mark.asyncio
async def test_api_copilot_query_fallback_tenant(copilot_test_env: dict, client: AsyncClient):
    """POST /api/v1/copilot/query without tenant_slug falls back to active tenant."""
    resp = await client.post(
        "/api/v1/copilot/query",
        json={"query_text": "Who is leading technician KPIs?"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["intent"] == "TECHNICIAN_KPI"
    assert "Marcus Vance" in data["answer_text"]
