import asyncio
import json
from typing import Any, Dict, Optional
from google import genai
from google.genai import types

from app.core.config import settings
from app.core.logging import logger
from app.schemas.lead import IntentLevel, LeadQualificationOutput


async def qualify_lead_with_gemini(
    raw_text: str,
    tenant_context: Optional[Dict[str, Any]] = None,
) -> LeadQualificationOutput:
    """
    Qualify an inbound lead inquiry using the official google-genai SDK
    with structured outputs targeting LeadQualificationOutput.
    Includes fast 3.0s timeout and graceful fallback to deterministic keyword extraction
    if GEMINI_API_KEY is not configured or if the API call fails or times out.
    """
    tenant_context = tenant_context or {}

    is_valid_gemini_key = bool(
        settings.GEMINI_API_KEY
        and not settings.GEMINI_API_KEY.startswith("your-")
        and not settings.GEMINI_API_KEY.startswith("mock")
        and settings.GEMINI_API_KEY not in ("placeholder", "test", "none")
    )

    if is_valid_gemini_key:
        try:
            client = genai.Client(api_key=settings.GEMINI_API_KEY)
            prompt = (
                f"You are an operational lead qualification, multilingual auto-triage, and dispatch engine.\n\n"
                f"Tenant Configuration & Routing Rules:\n{json.dumps(tenant_context, indent=2)}\n\n"
                f"Inbound Lead Submission:\n{raw_text}\n\n"
                f"Analyze the lead text and provide a structured qualification assessment targeting LeadQualificationOutput.\n"
                f"- Detect the caller's language code ('en', 'es', etc.) and assign detected_language.\n"
                f"- If the caller speaks or texts in Spanish:\n"
                f"  1. Set detected_language to 'es'.\n"
                f"  2. Generate caller_response: A natural, polite, and professional Spanish response for the caller (e.g., 'Conectando con nuestra línea de emergencia ahora mismo' for emergencies, or confirmation that an estimate text has been sent).\n"
                f"  3. Generate reasoning: A clear, standardized English translation and technical breakdown for the contractor's dispatch alert and CRM.\n"
                f"- If English, set detected_language to 'en' and provide appropriate English caller_response and reasoning."
            )
            response = await asyncio.wait_for(
                client.aio.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=LeadQualificationOutput,
                        temperature=0.1,
                    ),
                ),
                timeout=3.0,
            )
            if response.text:
                return LeadQualificationOutput.model_validate_json(response.text)
        except Exception as exc:
            logger.warning(
                f"Gemini API qualification failed or timed out ({exc}), falling back to deterministic keyword extraction."
            )

    return fallback_keyword_qualification(raw_text, tenant_context)



def fallback_keyword_qualification(
    raw_text: str,
    tenant_context: Dict[str, Any],
) -> LeadQualificationOutput:
    """
    Deterministic rule and keyword-based qualification engine used offline,
    for low-latency operations, or as resilient fallback.
    Supports bilingual English & Spanish auto-triage.
    """
    text_lower = raw_text.lower()
    min_threshold = tenant_context.get("min_qualification_score", 0.4)

    # Detect language (Spanish keywords)
    spanish_markers = [
        "hola", "buenas", "buenos días", "buenas tardes", "por favor", "gracias",
        "tubería", "tuberia", "fuga", "agua", "inundando", "inundación", "inundacion",
        "calentador", "roto", "reparar", "ayuda", "urgente", "emergencia", "presupuesto",
        "cotización", "cotizacion", "necesito", "techo", "gotera", "electricista", "plomero",
        "se rompió", "se rompio", "sótano", "sotano", "cuánto", "cuanto cuesta"
    ]
    is_spanish = any(term in text_lower for term in spanish_markers)
    detected_lang = "es" if is_spanish else "en"

    # 1. Spam filter check
    spam_terms = ["seo ranking", "backlink", "crypto", "forex", "viagra", "casino", "free money"]
    if any(spam in text_lower for spam in spam_terms):
        return LeadQualificationOutput(
            is_qualified=False,
            qualification_score=0.0,
            intent_level=IntentLevel.SPAM,
            pain_points=["Spam or promotional submission"],
            budget_estimate="N/A",
            recommended_action="DISQUALIFIED_ARCHIVE",
            reasoning="Detected spam or blacklisted keywords in lead payload.",
            detected_language=detected_lang,
            caller_response=None,
        )

    # 2. Emergency check (English & Spanish)
    emergency_terms = [
        "emergency",
        "critical",
        "outage",
        "broken",
        "immediate dispatch",
        "burst pipe",
        "leak",
        "power down",
        "system down",
        "flooding",
        "emergencia",
        "urgente",
        "fuga",
        "inundando",
        "inundación",
        "inundacion",
        "se rompió",
        "se rompio",
        "tubería rota",
        "tuberia rota",
    ]
    if any(term in text_lower for term in emergency_terms):
        caller_resp = (
            "Conectando con nuestra línea de emergencia ahora mismo."
            if is_spanish
            else "Connecting you to our emergency line now."
        )
        reasoning = (
            "Spanish emergency inquiry detected: active water leak or failure reported by caller. Escalated to immediate contractor dispatch."
            if is_spanish
            else "Emergency keywords detected; escalated to immediate high-urgency dispatch."
        )
        return LeadQualificationOutput(
            is_qualified=True,
            qualification_score=0.98,
            intent_level=IntentLevel.EMERGENCY,
            pain_points=["Immediate emergency dispatch required" + (" (Spanish Bilingual Caller)" if is_spanish else "")],
            budget_estimate="Emergency Rate",
            recommended_action="IMMEDIATE_EMERGENCY_DISPATCH",
            reasoning=reasoning,
            detected_language=detected_lang,
            caller_response=caller_resp,
        )

    # 3. High urgency / intent
    urgent_terms = [
        "urgent", "asap", "pricing", "enterprise", "demo", "quote", "hire", "proposal", "contract",
        "presupuesto", "cotización", "cotizacion", "precio", "estimado", "cuanto cuesta"
    ]
    is_urgent = any(term in text_lower for term in urgent_terms)

    # Base scoring
    score = 0.5
    pain_points = []

    if is_urgent:
        score += 0.3
        pain_points.append("High urgency operational request" if not is_spanish else "Solicitud de servicio urgente")
        intent = IntentLevel.HIGH
    else:
        intent = IntentLevel.MEDIUM

    # Budget signal analysis
    budget_estimate = "Unspecified"
    if any(b in text_lower for b in ["$", "budget", "10k", "50k", "100k", "enterprise", "dólares", "dolares"]):
        score += 0.15
        budget_estimate = "Identified in inquiry"
        if intent != IntentLevel.HIGH:
            intent = IntentLevel.HIGH

    final_score = max(0.0, min(1.0, round(score, 2)))
    is_qualified = final_score >= min_threshold

    if not is_qualified:
        recommended_action = "NURTURE_SEQUENCE"
    elif final_score >= 0.8:
        recommended_action = "IMMEDIATE_REP_ROUTING"
    else:
        recommended_action = "STANDARD_FOLLOWUP"

    caller_resp = (
        "Gracias por llamar. Hemos recibido su solicitud y le hemos enviado un mensaje de texto para programar una visita técnica. Hasta luego."
        if is_spanish
        else "Thank you. We have received your request and sent a text to your phone to schedule an estimate. Goodbye."
    )
    reasoning_text = (
        f"Spanish inquiry evaluated with deterministic rules engine. Final score {final_score} vs threshold {min_threshold}."
        if is_spanish
        else f"Evaluated with deterministic rules engine. Final score {final_score} vs threshold {min_threshold}."
    )

    return LeadQualificationOutput(
        is_qualified=is_qualified,
        qualification_score=final_score,
        intent_level=intent,
        pain_points=pain_points or ["General operational inquiry"],
        budget_estimate=budget_estimate,
        recommended_action=recommended_action,
        reasoning=reasoning_text,
        detected_language=detected_lang,
        caller_response=caller_resp,
    )


class QualificationService:
    """Evaluates and scores inbound leads using Gemini structured outputs or rule-based fallback."""

    async def qualify_lead(
        self,
        tenant_settings: Dict[str, Any],
        lead_payload: Dict[str, Any],
    ) -> LeadQualificationOutput:
        """Extract text content and qualify lead via Gemini or rule engine."""
        raw_text = (
            lead_payload.get("body")
            or lead_payload.get("message")
            or json.dumps(lead_payload)
        )
        return await qualify_lead_with_gemini(raw_text, tenant_settings)

    async def qualify_lead_with_gemini(
        self,
        raw_text: str,
        tenant_context: Optional[Dict[str, Any]] = None,
    ) -> LeadQualificationOutput:
        """Direct access to Gemini qualification."""
        return await qualify_lead_with_gemini(raw_text, tenant_context)


qualification_service = QualificationService()
