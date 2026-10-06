import os
from fastapi import APIRouter, Request, Response, status
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from app.services.audio_demo import generate_synthesized_demo_wav, get_sample_call_scenario

router = APIRouter(tags=["In-Browser Live Audio Receptionist Simulator"])

TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "templates")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

# Cache generated WAV stream in-memory so subsequent requests are instant
_CACHED_DEMO_WAV = None


@router.get(
    "/api/v1/demo/sample-audio",
    summary="Stream Sample Emergency Call Audio",
    description="Returns dynamic, synthesized 32-second playable audio stream of the 2:15 AM burst pipe flood emergency call.",
)
async def get_sample_audio_stream() -> Response:
    global _CACHED_DEMO_WAV
    if _CACHED_DEMO_WAV is None:
        _CACHED_DEMO_WAV = generate_synthesized_demo_wav(duration_seconds=32)

    return Response(
        content=_CACHED_DEMO_WAV,
        media_type="audio/wav",
        headers={
            "Accept-Ranges": "bytes",
            "Content-Length": str(len(_CACHED_DEMO_WAV)),
            "Content-Disposition": 'inline; filename="215am_emergency_call_sample.wav"',
            "Cache-Control": "public, max-age=3600",
        },
    )


@router.get(
    "/api/v1/demo/call-scenario",
    summary="Get Timestamped Emergency Call Scenario",
    description="Returns structured dialogue turns, speaker roles, timestamps, and dispatch metrics for the 2:15 AM demo call.",
)
async def get_call_scenario_json() -> JSONResponse:
    scenario = get_sample_call_scenario()
    return JSONResponse(content=scenario)


@router.get(
    "/demo/audio",
    response_class=HTMLResponse,
    summary="Interactive In-Browser Audio Receptionist Player",
    description="Dedicated visual simulator with animated waveform, synchronized transcript stepper, and instant 1-click playback.",
)
async def get_audio_demo_page(request: Request) -> Response:
    scenario = get_sample_call_scenario()
    return templates.TemplateResponse(
        request=request,
        name="audio_demo.html",
        context={
            "scenario": scenario,
            "project_name": "DispatchEngine",
        },
    )
