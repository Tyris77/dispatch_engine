import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.tenant import Tenant
from app.schemas.speed_to_lead import SpeedToLeadPayload, SpeedToLeadResponse, SpeedToLeadMetrics
from app.services.speed_to_lead import speed_to_lead_service


@pytest.mark.asyncio
async def test_speed_to_lead_schemas():
    payload = SpeedToLeadPayload(
        platform="google_lsa",
        customer_name="Eleanor Vance",
        customer_phone="+12025550143",
        trade="Plumbing",
        job_description="Water heater leaking profusely across basement",
        ad_cost=55.0,
    )
    assert payload.platform == "google_lsa"
    assert payload.customer_name == "Eleanor Vance"
    assert payload.ad_cost == 55.0


@pytest.mark.asyncio
async def test_speed_to_lead_service_execution(db_session: AsyncSession):
    import uuid
    # Ensure tenant exists
    tenant = Tenant(
        id=uuid.uuid4(),
        name="Apex Test Roofing & Mechanical",
        slug="apex-test-speed",
        api_key_hash="test_hash",
        webhook_secret="test_secret",
        settings={
            "on_call_roster": [
                {"name": "Marcus Vance", "role": "Lead Tech", "phone": "+12025550188"}
            ]
        },
    )
    db_session.add(tenant)
    await db_session.commit()

    payload = SpeedToLeadPayload(
        platform="google_lsa",
        customer_name="Sarah Jenkins",
        customer_phone="+12025550199",
        trade="Plumbing",
        job_description="Burst pipe in kitchen",
        tenant_slug="apex-test-speed",
        ad_cost=55.0,
    )

    response: SpeedToLeadResponse = await speed_to_lead_service.ingest_lead(
        payload=payload,
        db=db_session,
    )

    assert response.status == "INSTANT_DISPATCHED"
    assert response.latency_seconds < 5.0
    assert response.sms_sent is True
    assert "Sarah Jenkins" in response.sms_preview
    assert response.technician_assigned == "Marcus Vance"
    assert response.platform == "google_lsa"

    # Verify metrics aggregation
    metrics: SpeedToLeadMetrics = await speed_to_lead_service.get_metrics(
        tenant_slug="apex-test-speed",
        db=db_session,
    )
    assert metrics.total_leads_ingested >= 1
    assert metrics.average_response_time_seconds <= 5.0
    assert metrics.leads_under_5s_pct == 100.0
    assert metrics.ad_spend_preserved >= 55.0


@pytest.mark.asyncio
async def test_speed_to_lead_api_endpoints(client: AsyncClient, db_session: AsyncSession):
    import uuid
    tenant = Tenant(
        id=uuid.uuid4(),
        name="Speedy Contractor Co",
        slug="speedy-contractor",
        api_key_hash="test_hash",
        webhook_secret="test_secret",
        settings={},
    )
    db_session.add(tenant)
    await db_session.commit()

    # 1. Google LSA ingestion
    lsa_payload = {
        "customer_name": "Thomas Edison",
        "customer_phone": "+1 (202) 555-0177",
        "trade": "Electrical",
        "job_description": "Main electrical panel spark and smoke",
        "tenant_slug": "speedy-contractor",
    }
    res_lsa = await client.post("/api/v1/leads/ingest/google-lsa", json=lsa_payload)
    assert res_lsa.status_code == 200
    data_lsa = res_lsa.json()
    assert data_lsa["platform"] == "google_lsa"
    assert data_lsa["latency_seconds"] < 5.0
    assert data_lsa["status"] == "INSTANT_DISPATCHED"

    # 2. Angi ingestion
    angi_payload = {
        "customer_name": "Alexander Bell",
        "customer_phone": "+1 (301) 555-0155",
        "trade": "HVAC",
        "job_description": "Furnace stopped blowing heat in freeze",
        "tenant_slug": "speedy-contractor",
    }
    res_angi = await client.post("/api/v1/leads/ingest/angi", json=angi_payload)
    assert res_angi.status_code == 200
    assert res_angi.json()["platform"] == "angi"

    # 3. Thumbtack ingestion
    thumbtack_payload = {
        "customer_name": "Marie Curie",
        "customer_phone": "+1 (703) 555-0122",
        "trade": "Restoration",
        "job_description": "Sump pump failure backup water",
        "tenant_slug": "speedy-contractor",
    }
    res_thumb = await client.post("/api/v1/leads/ingest/thumbtack", json=thumbtack_payload)
    assert res_thumb.status_code == 200
    assert res_thumb.json()["platform"] == "thumbtack"

    # 4. Generic ingestion
    gen_payload = {
        "platform": "generic",
        "customer_name": "Nikola Tesla",
        "customer_phone": "+1 (202) 555-0111",
        "trade": "Electrical",
        "job_description": "Emergency transformer hum",
        "tenant_slug": "speedy-contractor",
    }
    res_gen = await client.post("/api/v1/leads/ingest/generic", json=gen_payload)
    assert res_gen.status_code == 200

    # 5. Telemetry dashboard HTML page
    page_resp = await client.get("/speed-to-lead/speedy-contractor")
    assert page_resp.status_code == 200
    assert "Speed-to-Lead" in page_resp.text
    assert "Sub-5s Guarantee" in page_resp.text

    # 6. JSON metrics endpoint
    metrics_resp = await client.get("/api/v1/speed-to-lead/speedy-contractor/metrics")
    assert metrics_resp.status_code == 200
    m_data = metrics_resp.json()
    assert m_data["total_leads_ingested"] >= 4
    assert m_data["average_response_time_seconds"] < 5.0
