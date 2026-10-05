from typing import Optional
from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse
from app.schemas.demo_call import DemoCallRequest, DemoCallResponse
from app.services.demo_call import demo_call_service

router = APIRouter(tags=["Interactive Live Voice Test Call Demo"])


@router.post(
    "/demo/call-me",
    response_model=DemoCallResponse,
    summary="Trigger Interactive Live AI Voice Test Call",
    description="Places an instant AI voice test call to contractor phone in under 1.2s to demonstrate emergency triage.",
)
@router.post(
    "/api/v1/demo/call-me",
    response_model=DemoCallResponse,
    include_in_schema=False,
)
async def trigger_live_demo_call(
    payload: DemoCallRequest,
    request: Request,
) -> DemoCallResponse:
    try:
        base_url = str(request.base_url).rstrip("/")
        response = await demo_call_service.trigger_demo_call(
            payload=payload,
            base_url=base_url,
        )
        return response
    except ValueError as ve:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(ve),
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to initiate demo call: {str(exc)}",
        )


@router.get(
    "/demo/voice-twiml",
    summary="Twilio TwiML Voice Execution Callback",
    description="Returns TwiML instructing Twilio to synthesize the neural voice greeting.",
)
@router.get(
    "/api/v1/demo/voice-twiml",
    include_in_schema=False,
)
async def get_demo_voice_twiml(
    trade: str = Query(default="Plumbing"),
    name: Optional[str] = Query(default="Contractor"),
    lang: str = Query(default="en"),
) -> Response:
    twiml_xml = demo_call_service.generate_twiml(trade=trade, name=name, language=lang)
    return Response(content=twiml_xml, media_type="application/xml")


@router.get(
    "/demo/audio-preview",
    summary="Sample AI Voice Synthesis Audio Preview",
    description="Returns simulated audio waveform or synthetic media preview for in-browser playback.",
)
@router.get(
    "/api/v1/demo/audio-preview",
    include_in_schema=False,
)
async def get_demo_audio_preview(
    lang: str = Query(default="en"),
    trade: str = Query(default="Plumbing"),
) -> Response:
    # Minimal valid 1-second silence WAV header to prevent browser audio errors
    wav_bytes = (
        b"RIFF$\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00D\xac\x00\x00"
        b"\x88X\x01\x00\x02\x00\x10\x00data\x00\x00\x00\x00"
    )
    return Response(content=wav_bytes, media_type="audio/wav")
