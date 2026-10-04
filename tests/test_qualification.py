from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from app.core.config import settings
from app.schemas.lead import IntentLevel, LeadQualificationOutput
from app.services.qualification import (
    fallback_keyword_qualification,
    qualification_service,
    qualify_lead_with_gemini,
)


@pytest.mark.asyncio
async def test_gemini_qualification_structured_parser():
    """Verify qualify_lead_with_gemini correctly parses structured outputs from Gemini API."""
    mock_json = """
    {
        "is_qualified": true,
        "qualification_score": 0.92,
        "intent_level": "HIGH",
        "pain_points": ["Operations bottleneck", "Need instant dispatch"],
        "budget_estimate": "$25,000",
        "recommended_action": "SCHEDULE_VIP_DEMO",
        "reasoning": "High budget and urgent operational need identified."
    }
    """
    mock_response = MagicMock()
    mock_response.text = mock_json

    mock_client = MagicMock()
    mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

    with patch("app.services.qualification.settings.GEMINI_API_KEY", "test-gemini-key"):
        with patch("app.services.qualification.genai.Client", return_value=mock_client):
            result = await qualify_lead_with_gemini(
                raw_text="We have a $25k budget and need instant operations dispatch ASAP.",
                tenant_context={"min_qualification_score": 0.5},
            )

    assert isinstance(result, LeadQualificationOutput)
    assert result.is_qualified is True
    assert result.qualification_score == 0.92
    assert result.intent_level == IntentLevel.HIGH
    assert "Operations bottleneck" in result.pain_points
    assert result.recommended_action == "SCHEDULE_VIP_DEMO"


@pytest.mark.asyncio
async def test_gemini_qualification_fallback_on_api_error():
    """Verify that when Gemini API call fails, qualification smoothly falls back to rule engine."""
    mock_client = MagicMock()
    mock_client.aio.models.generate_content = AsyncMock(side_effect=RuntimeError("Google GenAI 503 Service Unavailable"))

    with patch("app.services.qualification.settings.GEMINI_API_KEY", "test-gemini-key"):
        with patch("app.services.qualification.genai.Client", return_value=mock_client):
            result = await qualify_lead_with_gemini(
                raw_text="Urgent: Need immediate pricing and demo for 100 enterprise users.",
                tenant_context={"min_qualification_score": 0.4},
            )

    assert isinstance(result, LeadQualificationOutput)
    assert result.is_qualified is True
    assert result.intent_level == IntentLevel.HIGH
    assert result.qualification_score >= 0.8
    assert "Evaluated with deterministic rules engine" in result.reasoning


def test_fallback_keyword_emergency_detection():
    """Verify that emergency keywords escalate to IntentLevel.EMERGENCY."""
    text = "We have an emergency critical outage with a burst pipe flooding the server room!"
    result = fallback_keyword_qualification(text, {"min_qualification_score": 0.4})

    assert result.is_qualified is True
    assert result.intent_level == IntentLevel.EMERGENCY
    assert result.qualification_score >= 0.95
    assert result.recommended_action == "IMMEDIATE_EMERGENCY_DISPATCH"


def test_fallback_keyword_spam_detection():
    """Verify that spam terms result in immediate disqualification and 0 score."""
    text = "Boost your website with high-DA backlinks and guaranteed seo ranking crypto casino!"
    result = fallback_keyword_qualification(text, {"min_qualification_score": 0.4})

    assert result.is_qualified is False
    assert result.intent_level == IntentLevel.SPAM
    assert result.qualification_score == 0.0
    assert result.recommended_action == "DISQUALIFIED_ARCHIVE"


@pytest.mark.asyncio
async def test_bilingual_spanish_qualification_gemini():
    """Verify Gemini structured parser returns detected_language='es', Spanish caller_response, and English summary."""
    mock_json = """
    {
        "is_qualified": true,
        "qualification_score": 0.98,
        "intent_level": "EMERGENCY",
        "pain_points": ["Active water pipe burst in basement", "Flooding hazard"],
        "budget_estimate": "Emergency Rate",
        "recommended_action": "IMMEDIATE_EMERGENCY_DISPATCH",
        "reasoning": "CRITICAL: Broken pipe in basement with active flooding reported by caller. Immediate plumber bridge required.",
        "detected_language": "es",
        "caller_response": "Conectando con nuestra línea de emergencia ahora mismo. Por favor espere un momento."
    }
    """
    mock_response = MagicMock()
    mock_response.text = mock_json

    mock_client = MagicMock()
    mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

    with patch("app.services.qualification.settings.GEMINI_API_KEY", "test-gemini-key"):
        with patch("app.services.qualification.genai.Client", return_value=mock_client):
            result = await qualify_lead_with_gemini(
                raw_text="¡Hola! Se rompió una tubería en el sótano y hay mucha agua saliendo, necesito un plomero urgente.",
                tenant_context={"min_qualification_score": 0.4},
            )

    assert isinstance(result, LeadQualificationOutput)
    assert result.is_qualified is True
    assert result.detected_language == "es"
    assert result.intent_level == IntentLevel.EMERGENCY
    assert "Conectando con nuestra línea de emergencia" in result.caller_response
    assert "CRITICAL: Broken pipe" in result.reasoning


def test_bilingual_spanish_fallback_emergency():
    """Verify deterministic fallback detects Spanish emergency keywords and generates bilingual triage output."""
    spanish_emergency = "¡Hola! Se rompió una tubería en el sótano y hay mucha agua saliendo, emergencia urgente!"
    result = fallback_keyword_qualification(spanish_emergency, {"min_qualification_score": 0.4})

    assert result.is_qualified is True
    assert result.detected_language == "es"
    assert result.intent_level == IntentLevel.EMERGENCY
    assert result.qualification_score >= 0.95
    assert "Conectando con nuestra línea de emergencia" in result.caller_response
    assert "Spanish emergency inquiry detected" in result.reasoning


def test_bilingual_spanish_fallback_routine():
    """Verify deterministic fallback handles Spanish routine service requests with Spanish confirmation text."""
    spanish_routine = "Hola, buenas tardes. Necesito un presupuesto para reparar el calentador de agua la próxima semana."
    result = fallback_keyword_qualification(spanish_routine, {"min_qualification_score": 0.4})

    assert result.is_qualified is True
    assert result.detected_language == "es"
    assert result.intent_level == IntentLevel.HIGH
    assert "Gracias por llamar" in result.caller_response
    assert "Spanish inquiry evaluated with deterministic rules engine" in result.reasoning
