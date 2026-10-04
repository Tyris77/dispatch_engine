import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_public_landing_page_renders_successfully(client: AsyncClient):
    """Verify that root GET / renders the public landing page with headline, CTAs, and interactive demo."""
    response = await client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")

    html = response.text

    # 1. Branding & Navigation
    assert "DispatchEngine" in html
    assert "/dashboard" in html
    assert "/docs" in html

    # 2. Hero Headline & CTAs
    assert "Never Lose a" in html
    assert "Emergency Call" in html
    assert "Voicemail Again" in html
    assert "Activate Now" in html
    assert "14-Day Free Trial" in html

    # 3. Interactive Call-Splitting Demo
    assert "Interactive Architecture Demo" in html
    assert "scenario-emergency-btn" in html
    assert "scenario-routine-btn" in html
    assert "demo-speech-text" in html

    # 4. ROI Comparison Table
    assert "Traditional Voicemail" in html
    assert "Call Answering Service" in html
    assert "DispatchEngine" in html
    assert "$149/mo flat" in html

    # 5. FAQ Accordion
    assert "Frequently Asked Questions" in html
    assert "How does DispatchEngine bridge emergency calls" in html
    assert "Can we keep our existing business phone number" in html

    # 6. Onboarding Modal & Footer
    assert "onboarding-modal" in html
    assert "System Health" in html
