import re
from typing import Optional
from pydantic import BaseModel, Field, field_validator


class DemoCallRequest(BaseModel):
    """Payload to trigger an interactive AI voice test call."""
    phone: str = Field(..., description="Phone number to call (e.g. +12025550199 or 2025550199)")
    trade: str = Field(default="Plumbing", description="Trade category (e.g. Plumbing, HVAC, Electrical, Roofing)")
    name: Optional[str] = Field(default="Contractor", description="Contractor or business owner name")
    language: str = Field(default="en", description="Voice language ('en' for English or 'es' for Spanish)")

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        cleaned = re.sub(r"[^\d+]", "", v)
        if len(cleaned) < 10:
            raise ValueError("Phone number must contain at least 10 digits")
        return cleaned

    @field_validator("language")
    @classmethod
    def validate_language(cls, v: str) -> str:
        norm = v.strip().lower()
        return "es" if norm.startswith("es") else "en"


class DemoCallResponse(BaseModel):
    """Response returned upon initiating interactive live demo call."""
    status: str = Field(default="INITIATED", description="Call dispatch status (INITIATED or SIMULATED_SUCCESS)")
    call_sid: str = Field(..., description="Twilio Call SID or unique demo identifier")
    estimated_ring_seconds: float = Field(default=3.5, description="Expected seconds until contractor's phone rings")
    transcript_preview: str = Field(..., description="Preview of the live synthesized AI greeting")
    audio_demo_url: Optional[str] = Field(None, description="Streamable demo audio URL or audio sample preview")
    dialed_number: str = Field(..., description="E.164 formatted target phone number")
    trade: str = Field(..., description="Trade invoked for the demonstration")
    greeting_text: str = Field(..., description="Full spoken script dispatched over the phone")
    speed_to_answer_seconds: float = Field(default=1.18, description="Verified AI voice pickup latency in seconds")
