import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.tenant import Tenant
from app.schemas.audit import AuditCalculateRequest, AuditReportResponse
from app.services.audit import audit_service


def test_audit_schemas_and_validation():
    req = AuditCalculateRequest(
        trade="HVAC",
        truck_count=8,
        monthly_call_volume=400,
        average_ticket=1200.0,
        zip_code="20002",
    )
    assert req.trade == "HVAC"
    assert req.truck_count == 8
    assert req.monthly_call_volume == 400
    assert req.average_ticket == 1200.0


def test_audit_service_calculation():
    req = AuditCalculateRequest(
        trade="Plumbing",
        truck_count=5,
        monthly_call_volume=250,
        average_ticket=850.0,
        zip_code="20001",
    )
    report: AuditReportResponse = audit_service.calculate_leakage(req=req)

    # 250 calls * 28% missed = 70 calls
    assert report.missed_call_count == 70
    assert report.missed_call_rate_pct == 28.0
    assert report.competitor_capture_rate_pct == 65.0
    assert report.lost_jobs_count >= 1
    assert report.monthly_leak_revenue > 0
    assert report.annual_lost_profit > 0
    assert report.competitor_capture_index >= 38.0
    assert report.projected_7_day_recovery > 0
    assert len(report.recovery_plan) == 5
    assert "Plumbing" in report.regional_benchmark_notes


@pytest.mark.asyncio
async def test_audit_api_calculate_endpoint(client: AsyncClient):
    payload = {
        "trade": "Electrical",
        "truck_count": 4,
        "monthly_call_volume": 180,
        "average_ticket": 720.0,
        "zip_code": "22201",
    }
    response = await client.post("/api/v1/audit/calculate", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["trade"] == "Electrical"
    assert data["monthly_leak_revenue"] > 0
    assert data["annual_lost_profit"] > 0
    assert data["competitor_capture_index"] > 0
    assert len(data["recovery_plan"]) == 5


@pytest.mark.asyncio
async def test_audit_page_endpoints(client: AsyncClient, db_session: AsyncSession):
    import uuid
    tenant = Tenant(
        id=uuid.uuid4(),
        name="District Leak Shield",
        slug="district-leak-shield",
        api_key_hash="test_hash",
        webhook_secret="test_secret",
        settings={},
    )
    db_session.add(tenant)
    await db_session.commit()

    # 1. GET /audit root page
    res_root = await client.get("/audit")
    assert res_root.status_code == 200
    assert "Revenue Leak Audit" in res_root.text
    assert "Calculate Exactly How Much Revenue" in res_root.text

    # 2. GET /audit/{tenant_slug}
    res_tenant = await client.get("/audit/district-leak-shield")
    assert res_tenant.status_code == 200
    assert "District Leak Shield" in res_tenant.text

    # 3. GET /audit with format=json
    res_json = await client.get("/audit/district-leak-shield?format=json")
    assert res_json.status_code == 200
    data = res_json.json()
    assert "monthly_leak_revenue" in data
    assert data["missed_call_rate_pct"] == 28.0
