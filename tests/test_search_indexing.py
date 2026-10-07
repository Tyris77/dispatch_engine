import pytest
from httpx import AsyncClient

from app.core.config import settings
from app.services.autopilot import autopilot_service
from app.services.search_indexing import search_indexing_service


@pytest.mark.asyncio
async def test_indexnow_payload_generation():
    """Verify IndexNow payload format, 32-char hex key, and exact 53 URL count (48 SEO + 5 core)."""
    base_url = "https://dispatchengine-production.up.railway.app"
    payload = search_indexing_service.build_payload(base_url=base_url)

    assert payload["host"] == "dispatchengine-production.up.railway.app"
    assert payload["key"] == settings.INDEXNOW_KEY
    assert len(payload["key"]) == 32
    assert payload["keyLocation"] == f"{base_url}/{settings.INDEXNOW_KEY}.txt"

    url_list = payload["urlList"]
    assert len(url_list) == 53

    # Check 5 core conversion URLs
    assert f"{base_url}/" in url_list
    assert f"{base_url}/solutions" in url_list
    assert f"{base_url}/audit" in url_list
    assert f"{base_url}/widget-demo" in url_list
    assert f"{base_url}/onboard" in url_list

    # Check sample programmatic SEO URLs
    assert f"{base_url}/solutions/plumbing-dispatch-washington-dc" in url_list
    assert f"{base_url}/solutions/hvac-dispatch-arlington-va" in url_list
    assert f"{base_url}/solutions/water-mitigation-dispatch-bethesda-md" in url_list



@pytest.mark.asyncio
async def test_indexnow_key_verification_endpoint(client: AsyncClient):
    """Verify GET /{INDEXNOW_KEY}.txt returns 200 text/plain with key body for search engines."""
    key = settings.INDEXNOW_KEY
    resp = await client.get(f"/{key}.txt")

    assert resp.status_code == 200
    assert resp.text == key
    assert "text/plain" in resp.headers["content-type"]

    # Invalid filename should 404
    resp_invalid = await client.get("/invalid_random_key_999.txt")
    assert resp_invalid.status_code == 404


@pytest.mark.asyncio
async def test_ping_indexnow_service():
    """Verify ping_indexnow executes, generates structured response, and records Autopilot telemetry."""
    initial_log_count = len(autopilot_service.execution_logs)

    result = await search_indexing_service.ping_indexnow(
        base_url="https://dispatchengine-production.up.railway.app",
        record_autopilot_log=True,
    )

    assert result["status"] == "SUCCESS"
    assert result["submitted_urls_count"] == 53
    assert result["host"] == "dispatchengine-production.up.railway.app"
    assert result["key"] == settings.INDEXNOW_KEY
    assert len(result["url_list"]) == 53

    # Verify Autopilot execution log recorded
    assert len(autopilot_service.execution_logs) > initial_log_count
    latest_log = autopilot_service.execution_logs[0]
    assert latest_log.task_name == "Search Engine IndexNow Ping & Sitemap Verification"
    assert latest_log.status == "SUCCESS"
    assert latest_log.items_processed == 53


@pytest.mark.asyncio
async def test_ping_indexnow_api_endpoint(client: AsyncClient):
    """Verify POST /api/v1/seo/ping-indexnow triggers submission and returns telemetry."""
    resp = await client.post("/api/v1/seo/ping-indexnow")
    assert resp.status_code == 200
    data = resp.json()

    assert data["status"] == "SUCCESS"
    assert data["submitted_urls_count"] == 53
    assert data["key"] == settings.INDEXNOW_KEY
    assert data["host"] in ("testserver", "localhost", "127.0.0.1", "dispatchengine-production.up.railway.app")


@pytest.mark.asyncio
async def test_google_site_verification_meta_tags(client: AsyncClient):
    """Verify Google Search Console meta verification tag renders in HTML templates when configured."""
    original_val = settings.GOOGLE_SITE_VERIFICATION
    test_token = "google-site-verification-token-test-12345"

    try:
        settings.GOOGLE_SITE_VERIFICATION = test_token

        # 1. Landing page
        resp_home = await client.get("/")
        assert resp_home.status_code == 200
        assert f'<meta name="google-site-verification" content="{test_token}">' in resp_home.text

        # 2. Solutions directory
        resp_solutions = await client.get("/solutions")
        assert resp_solutions.status_code == 200
        assert f'<meta name="google-site-verification" content="{test_token}">' in resp_solutions.text

        # 3. Programmatic SEO page
        resp_seo = await client.get("/solutions/plumbing-dispatch-washington-dc")
        assert resp_seo.status_code == 200
        assert f'<meta name="google-site-verification" content="{test_token}">' in resp_seo.text

    finally:
        settings.GOOGLE_SITE_VERIFICATION = original_val


@pytest.mark.asyncio
async def test_autopilot_cycle_includes_task7():
    """Verify Autopilot 24/7 background worker includes Task 7 in active tasks and cycle execution."""
    status_report = autopilot_service.get_status_report()
    assert "Search Engine IndexNow Ping & Sitemap Verification" in status_report.active_tasks

    # Execute full autonomous cycle
    res = await autopilot_service.execute_autonomous_cycle(force_all=True)
    assert res.status == "CYCLE_EXECUTED"

    task_names = [log.task_name for log in res.logs]
    assert "Search Engine IndexNow Ping & Sitemap Verification" in task_names

    task7_log = next(log for log in res.logs if log.task_name == "Search Engine IndexNow Ping & Sitemap Verification")
    assert task7_log.status == "SUCCESS"
    assert task7_log.items_processed == 53
