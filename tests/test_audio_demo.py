import io
import wave
import pytest
from httpx import AsyncClient

from app.services.audio_demo import generate_synthesized_demo_wav, get_sample_call_scenario


def test_audio_demo_scenario_structure():
    """Verify 2:15 AM homeowner burst-pipe flood call scenario structure."""
    scenario = get_sample_call_scenario()

    assert scenario["duration_seconds"] == 32
    assert "Mrs. Eleanor Higgins" in scenario["caller_name"]
    assert "Danielle" in scenario["agent_name"]
    assert len(scenario["turns"]) == 3

    turn1 = scenario["turns"][0]
    assert turn1["start_seconds"] == 0.0
    assert turn1["end_seconds"] == 4.0
    assert "Mrs. Higgins" in turn1["speaker"]
    assert "water pouring through my living room ceiling" in turn1["text"].lower()

    turn2 = scenario["turns"][1]
    assert turn2["start_seconds"] == 4.0
    assert turn2["end_seconds"] == 18.0
    assert "Danielle" in turn2["speaker"]
    assert "$189" in turn2["text"]
    assert "instant photo upload link" in turn2["text"].lower()

    turn3 = scenario["turns"][2]
    assert turn3["start_seconds"] == 18.0
    assert turn3["end_seconds"] == 32.0
    assert "Danielle" in turn3["speaker"]
    assert "Carlos Gomez" in turn3["text"]
    assert "18 minutes" in turn3["text"]


def test_synthesized_wav_audio_validity():
    """Verify synthesized audio generator outputs a valid, readable WAV byte stream."""
    wav_bytes = generate_synthesized_demo_wav(duration_seconds=32, sample_rate=8000)
    assert len(wav_bytes) > 1000

    # Parse with standard library wave module to ensure headers are 100% valid
    buf = io.BytesIO(wav_bytes)
    with wave.open(buf, "rb") as w:
        assert w.getnchannels() == 1  # Mono
        assert w.getsampwidth() == 2  # 16-bit
        assert w.getframerate() == 8000
        n_frames = w.getnframes()
        duration = n_frames / w.getframerate()
        assert abs(duration - 32.0) < 0.1


@pytest.mark.asyncio
async def test_api_sample_audio_stream(client: AsyncClient):
    """Test GET /api/v1/demo/sample-audio endpoint."""
    response = await client.get("/api/v1/demo/sample-audio")
    assert response.status_code == 200
    assert "audio/wav" in response.headers["content-type"]
    assert "bytes" in response.headers.get("accept-ranges", "")
    assert len(response.content) > 10000


@pytest.mark.asyncio
async def test_api_call_scenario_json(client: AsyncClient):
    """Test GET /api/v1/demo/call-scenario endpoint."""
    response = await client.get("/api/v1/demo/call-scenario")
    assert response.status_code == 200
    data = response.json()
    assert data["duration_seconds"] == 32
    assert "turns" in data
    assert len(data["turns"]) == 3
    assert data["metrics"]["assigned_tech"] == "Carlos Gomez (Truck #09)"


@pytest.mark.asyncio
async def test_demo_audio_html_page(client: AsyncClient):
    """Test GET /demo/audio page rendering."""
    response = await client.get("/demo/audio")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    text = response.text
    assert "2:15 AM Live Emergency Audio Receptionist Simulator" in text
    assert "Mrs. Eleanor Higgins" in text
    assert "/api/v1/demo/sample-audio" in text
    assert "Synchronized Live Dialogue Transcript" in text
