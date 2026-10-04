import hashlib
import hmac
import json
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_webhook_ingestion_and_dispatch(client: AsyncClient, sample_tenant: dict):
    """Test receiving a lead webhook, qualifying it, and creating dispatch records."""
    tenant = sample_tenant["tenant"]
    payload = {
        "source": "typeform",
        "event_type": "lead.created",
        "idempotency_key": "test-key-1001",
        "payload": {
            "email": "sarah.connor@cyberdyne.com",
            "company": "Cyberdyne Systems",
            "message": "Urgent enterprise demo requested for operations dispatch.",
            "budget": 50000,
        },
    }

    response = await client.post(
        f"/api/v1/webhooks/{tenant.slug}",
        json=payload,
    )
    assert response.status_code == 202
    data = response.json()
    assert data["received"] is True
    assert data["status"] == "PROCESSED"
    assert "event_id" in data


@pytest.mark.asyncio
async def test_webhook_idempotency(client: AsyncClient, sample_tenant: dict):
    """Test that submitting the same idempotency key flags duplicate and skips processing."""
    tenant = sample_tenant["tenant"]
    payload = {
        "source": "zapier",
        "event_type": "lead.created",
        "idempotency_key": "duplicate-key-999",
        "payload": {
            "email": "alex@example.com",
            "message": "Inquiry about pricing",
        },
    }

    # First submission
    res1 = await client.post(f"/api/v1/webhooks/{tenant.slug}", json=payload)
    assert res1.status_code == 202
    assert res1.json()["status"] == "PROCESSED"

    # Second submission with identical idempotency_key
    res2 = await client.post(f"/api/v1/webhooks/{tenant.slug}", json=payload)
    assert res2.status_code == 202
    assert res2.json()["status"] == "DUPLICATE"


@pytest.mark.asyncio
async def test_tenant_authentication_isolation(client: AsyncClient, sample_tenant: dict):
    """Test that tenant endpoints require valid X-API-Key."""
    # Attempting to fetch events without header should be 401
    res_unauth = await client.get("/api/v1/webhooks/events")
    assert res_unauth.status_code == 401

    # Fetching events with valid header should be 200
    res_auth = await client.get(
        "/api/v1/webhooks/events",
        headers={"X-API-Key": sample_tenant["raw_api_key"]},
    )
    assert res_auth.status_code == 200
    assert isinstance(res_auth.json(), list)
