import json
import xml.etree.ElementTree as ET
import pytest
from httpx import AsyncClient
from app.services.seo import SEOService, TRADES, HUBS


def test_48_slug_resolution_and_metadata():
    """Verify all 48 combinations of trade x hub properly resolve and generate compliant SEO metadata."""
    all_pages = SEOService.get_all_pages()
    assert len(all_pages) == 48

    for page in all_pages:
        slug = page["slug"]
        assert slug.startswith(("plumbing-dispatch-", "hvac-dispatch-", "roofing-dispatch-", "water-mitigation-dispatch-"))
        assert page["meta_title"].endswith("| DispatchEngine")
        assert len(page["meta_description"]) > 50
        assert page["city_display"] in page["meta_title"]
        assert page["trade"]["avg_ticket"] > 0
        assert len(page["hub"]["local_pain_points"]) > 20
        assert len(page["nearby_hubs"]) > 0
        assert len(page["cross_trades"]) == 3

        # Validate JSON-LD Schema
        schema = json.loads(page["json_ld_schema"])
        assert schema["@context"] == "https://schema.org"
        assert "@graph" in schema
        types = [item["@type"] for item in schema["@graph"]]
        assert "SoftwareApplication" in types
        assert "Service" in types
        assert "BreadcrumbList" in types


def test_invalid_slug_handling():
    """Verify invalid slugs return None from service."""
    assert SEOService.get_page_data("random-nonexistent-slug") is None
    assert SEOService.get_page_data("plumbing-dispatch-miami-fl") is None
    assert SEOService.get_page_data("electrical-dispatch-washington-dc") is None


@pytest.mark.asyncio
async def test_solutions_hub_directory_endpoint(client: AsyncClient):
    """Verify GET /solutions renders directory hub with all trades and regional hubs."""
    response = await client.get("/solutions")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")

    html = response.text
    assert "Solutions Directory &amp; 24/7 AI Dispatch Hub" in html or "Solutions Directory" in html
    assert "Plumbing" in html
    assert "HVAC" in html
    assert "Roofing" in html
    assert "Water Mitigation" in html
    assert "District of Columbia" in html
    assert "Northern Virginia" in html
    assert "Maryland Suburbs" in html
    assert "/solutions/plumbing-dispatch-washington-dc" in html


@pytest.mark.asyncio
async def test_programmatic_landing_page_endpoint(client: AsyncClient):
    """Verify GET /solutions/{slug} renders localized programmatic landing page with conversion blocks."""
    # Test Plumbing in Washington DC
    res_dc = await client.get("/solutions/plumbing-dispatch-washington-dc")
    assert res_dc.status_code == 200
    html_dc = res_dc.text
    assert "24/7 Emergency Plumbing Dispatch Software in Washington, DC" in html_dc
    assert "Speed-to-Answer" in html_dc
    assert "$1,200" in html_dc
    assert "Experience the 1.2-Second Plumbing Answer" in html_dc
    assert "How Much Are Washington Plumbing After-Hours Voicemails Costing You?" in html_dc
    assert "application/ld+json" in html_dc
    assert "/onboard" in html_dc

    # Test HVAC in Arlington VA
    res_va = await client.get("/solutions/hvac-dispatch-arlington-va")
    assert res_va.status_code == 200
    html_va = res_va.text
    assert "Arlington, VA" in html_va
    assert "$8,500" in html_va
    assert "Experience the 1.2-Second HVAC Answer" in html_va

    # Test Water Mitigation in Annapolis MD
    res_md = await client.get("/solutions/water-mitigation-dispatch-annapolis-md")
    assert res_md.status_code == 200
    html_md = res_md.text
    assert "Annapolis, MD" in html_md
    assert "$4,500" in html_md
    assert "Experience the 1.2-Second Water Mitigation Answer" in html_md

    # Test 404 for unknown slug
    res_404 = await client.get("/solutions/unknown-trade-unknown-city")
    assert res_404.status_code == 404


@pytest.mark.asyncio
async def test_sitemap_xml_structure_and_count(client: AsyncClient):
    """Verify GET /sitemap.xml returns valid RFC-compliant XML indexing >= 52 URLs."""
    response = await client.get("/sitemap.xml")
    assert response.status_code == 200
    assert "application/xml" in response.headers.get("content-type", "")

    xml_text = response.text
    assert '<?xml version="1.0" encoding="UTF-8"?>' in xml_text
    assert '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' in xml_text

    # Parse XML
    root = ET.fromstring(xml_text)
    # namespace strip
    urls = [elem.text for elem in root.findall(".//{http://www.sitemaps.org/schemas/sitemap/0.9}loc")]
    assert len(urls) >= 52  # 48 solutions + 5 core pages (/, /solutions, /audit, /widget-demo, /onboard)

    assert any(u.endswith("/solutions/plumbing-dispatch-washington-dc") for u in urls)
    assert any(u.endswith("/solutions/hvac-dispatch-fairfax-va") for u in urls)
    assert any(u.endswith("/solutions/water-mitigation-dispatch-annapolis-md") for u in urls)
    assert any(u.endswith("/audit") for u in urls)
    assert any(u.endswith("/widget-demo") for u in urls)
    assert any(u.endswith("/onboard") for u in urls)


@pytest.mark.asyncio
async def test_robots_txt_format(client: AsyncClient):
    """Verify GET /robots.txt returns plain-text directives with sitemap reference."""
    response = await client.get("/robots.txt")
    assert response.status_code == 200
    assert "text/plain" in response.headers.get("content-type", "")

    txt = response.text
    assert "User-agent: *" in txt
    assert "Allow: /" in txt
    assert "Disallow: /api/" in txt
    assert "Sitemap:" in txt
    assert txt.strip().endswith("/sitemap.xml")


@pytest.mark.asyncio
async def test_seo_matrix_api(client: AsyncClient):
    """Verify GET /api/v1/seo/matrix returns categorized structure."""
    response = await client.get("/api/v1/seo/matrix")
    assert response.status_code == 200
    data = response.json()
    assert data["total_pages"] == 48
    assert "by_trade" in data
    assert "by_region" in data
    assert len(data["by_trade"]) == 4
    assert len(data["by_region"]) == 3
