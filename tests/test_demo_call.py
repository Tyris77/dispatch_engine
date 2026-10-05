import pytest
from httpx import AsyncClient
from app.schemas.demo_call import DemoCallRequest, DemoCallResponse
from app.services.demo_call import demo_call_service


@pytest.mark.asyncio
async def test_demo_call_schemas_and_validation():
    req = DemoCallRequest(
        phone="+12025550199",
        trade="HVAC",
        name="John Builder",
        language="en",
    )
    assert req.phone == "+12025550199"
    assert req.trade == "HVAC"
    assert req.name == "John Builder"
    assert req.language == "en"

    # Spanish normalizer
    req_es = DemoCallRequest(
        phone="202-555-0144",
        language="es-US",
    )
    assert req_es.language == "es"
    assert "2025550144" in req_es.phone

    # Invalid phone
    with pytest.raises(ValueError):
        DemoCallRequest(phone="123")


@pytest.mark.asyncio
async def test_demo_call_service_english():
    req = DemoCallRequest(
        phone="+12025550123",
        trade="Plumbing",
        name="Marcus",
        language="en",
    )
    resp: DemoCallResponse = await demo_call_service.trigger_demo_call(
        payload=req,
        base_url="https://dispatch.railway.app",
    )
    assert resp.status in ("INITIATED", "SIMULATED_SUCCESS")
    assert resp.call_sid.startswith("CA_")
    assert resp.estimated_ring_seconds == 3.5
    assert "DispatchEngine AI receptionist" in resp.greeting_text
    assert "1.2 seconds" in resp.greeting_text
    assert resp.speed_to_answer_seconds <= 1.2
    assert resp.trade == "Plumbing"
    assert resp.audio_demo_url is not None


@pytest.mark.asyncio
async def test_demo_call_service_spanish():
    req = DemoCallRequest(
        phone="+13015550188",
        trade="Electricidad",
        name="Carlos",
        language="es",
    )
    resp: DemoCallResponse = await demo_call_service.trigger_demo_call(
        payload=req,
        base_url="https://dispatch.railway.app",
    )
    assert resp.status in ("INITIATED", "SIMULATED_SUCCESS")
    assert "recepcionista de inteligencia artificial" in resp.greeting_text
    assert "1.2 segundos" in resp.greeting_text


@pytest.mark.asyncio
async def test_demo_call_twiml_and_audio_endpoints(client: AsyncClient):
    # Test TwiML XML endpoint
    twiml_resp = await client.get("/api/v1/demo/voice-twiml?trade=HVAC&name=Dave&lang=en")
    assert twiml_resp.status_code == 200
    assert "application/xml" in twiml_resp.headers["content-type"]
    assert "<Response>" in twiml_resp.text
    assert "Polly.Danielle" in twiml_resp.text

    # Spanish TwiML
    twiml_es = await client.get("/api/v1/demo/voice-twiml?trade=Plomeria&name=Juan&lang=es")
    assert twiml_es.status_code == 200
    assert "Polly.Lupe" in twiml_es.text

    # Audio sample preview
    audio_resp = await client.get("/api/v1/demo/audio-preview?lang=en&trade=Plumbing")
    assert audio_resp.status_code == 200
    assert "audio/wav" in audio_resp.headers["content-type"]


@pytest.mark.asyncio
async def test_demo_call_api_endpoint(client: AsyncClient):
    payload = {
        "phone": "+1 (202) 555-0199",
        "trade": "Roofing",
        "name": "Sarah Connor",
        "language": "en",
    }
    response = await client.post("/api/v1/demo/call-me", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] in ("INITIATED", "SIMULATED_SUCCESS")
    assert data["call_sid"].startswith("CA_")
    assert data["estimated_ring_seconds"] == 3.5
    assert "Roofing" in data["greeting_text"]
    assert "+12025550199" in data["dialed_number"]
