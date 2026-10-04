import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_root_health_check(client: AsyncClient):
    """Verify that root GET /health returns 200 OK and healthy status."""
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] in ["healthy", "degraded"]
    assert "database" in data
    assert "version" in data
    assert "environment" in data


@pytest.mark.asyncio
async def test_api_v1_health_check(client: AsyncClient):
    """Verify that GET /api/v1/health returns 200 OK."""
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] in ["healthy", "degraded"]
