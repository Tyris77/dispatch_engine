import asyncio
import re
import uuid
from typing import Optional
from app.core.config import settings
from app.core.logging import logger
from app.schemas.demo_call import DemoCallRequest, DemoCallResponse


class DemoCallService:
    """Service orchestrating real-time AI voice demo test calls to prospective contractors."""

    def _normalize_phone(self, phone: str) -> str:
        clean = re.sub(r"[^\d+]", "", phone)
        if not clean.startswith("+"):
            if len(clean) == 10:
                clean = "+1" + clean
            elif len(clean) == 11 and clean.startswith("1"):
                clean = "+" + clean
            else:
                clean = "+" + clean
        return clean

    def get_greeting_text(self, trade: str, name: Optional[str] = "Contractor", language: str = "en") -> str:
        caller_name = (name or "Contractor").strip()
        trade_label = (trade or "Emergency Services").capitalize()

        if language == "es":
            return (
                f"¡Hola {caller_name}! Esta es su recepcionista de inteligencia artificial de DispatchEngine para {trade_label}. "
                "Le estoy llamando para demostrar cómo atendemos las llamadas de emergencia de sus clientes en menos de 1.2 segundos. "
                "Mientras sus competidores mandan a sus clientes al buzón de voz, nuestro motor neuronal ya califica, "
                "asigna la cuadrilla de guardia y envía el enlace de rastreo en vivo por mensaje de texto. "
                "Gracias por probar DispatchEngine. ¡Que tenga un excelente día de trabajo!"
            )
        else:
            return (
                f"Hi {caller_name}, this is your DispatchEngine AI receptionist for {trade_label}. "
                "I'm calling to demonstrate how we answer your after-hours emergency calls in under 1.2 seconds. "
                "A homeowner calling about an urgent repair right now is already triaged, qualified, and dispatched "
                "to your on-call technician before competitors even check their voicemail. "
                "Thank you for experiencing DispatchEngine. Have a productive day in the field!"
            )

    def generate_twiml(self, trade: str = "Plumbing", name: Optional[str] = "Contractor", language: str = "en") -> str:
        greeting = self.get_greeting_text(trade=trade, name=name, language=language)
        voice_attr = 'voice="Polly.Lupe" language="es-US"' if language == "es" else 'voice="Polly.Danielle" language="en-US"'
        twiml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<Response>\n'
            '    <Pause length="1"/>\n'
            f'    <Say {voice_attr}>{greeting}</Say>\n'
            '    <Pause length="1"/>\n'
            f'    <Say {voice_attr}>Goodbye!</Say>\n'
            '</Response>'
        )
        return twiml

    async def trigger_demo_call(
        self,
        payload: DemoCallRequest,
        base_url: str = "",
    ) -> DemoCallResponse:
        phone_e164 = self._normalize_phone(payload.phone)
        greeting = self.get_greeting_text(
            trade=payload.trade,
            name=payload.name or "Contractor",
            language=payload.language,
        )

        preview = (
            greeting[:160] + "..." if len(greeting) > 160 else greeting
        )

        clean_base = base_url.rstrip("/") if base_url else ""
        twiml_url = f"{clean_base}/api/v1/demo/voice-twiml?trade={payload.trade}&name={payload.name}&lang={payload.language}"

        call_sid = f"CA_demo_{uuid.uuid4().hex[:16]}"
        status = "SIMULATED_SUCCESS"

        # Check if valid live Twilio credentials exist
        is_live_twilio = bool(
            settings.TWILIO_ACCOUNT_SID
            and settings.TWILIO_AUTH_TOKEN
            and not settings.TWILIO_ACCOUNT_SID.startswith("mock_")
            and not settings.TWILIO_ACCOUNT_SID.startswith("default_")
            and len(settings.TWILIO_ACCOUNT_SID) >= 20
        )

        if is_live_twilio:
            try:
                from twilio.rest import Client

                def _place_call():
                    from_num = settings.TWILIO_FROM_NUMBER or "+15005550006"
                    client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
                    call = client.calls.create(
                        to=phone_e164,
                        from_=from_num,
                        url=twiml_url,
                    )
                    return call.sid

                # Non-blocking async execution with 2.5s timeout
                live_sid = await asyncio.wait_for(asyncio.to_thread(_place_call), timeout=2.5)
                call_sid = live_sid
                status = "INITIATED"
                logger.info(f"Live Twilio demo call placed to {phone_e164}: {call_sid}")
            except Exception as twilio_err:
                logger.warning(f"Live Twilio demo call fallback to simulation: {twilio_err}")
                call_sid = f"CA_sim_{uuid.uuid4().hex[:16]}"
                status = "SIMULATED_SUCCESS"
        else:
            logger.info(f"Fast simulated demo call to {phone_e164} (Credentials unconfigured/mock)")

        # Streamable sample audio preview
        demo_audio_url = f"/api/v1/demo/audio-preview?lang={payload.language}&trade={payload.trade}"

        return DemoCallResponse(
            status=status,
            call_sid=call_sid,
            estimated_ring_seconds=3.5,
            transcript_preview=preview,
            audio_demo_url=demo_audio_url,
            dialed_number=phone_e164,
            trade=payload.trade,
            greeting_text=greeting,
            speed_to_answer_seconds=1.18,
        )


demo_call_service = DemoCallService()
