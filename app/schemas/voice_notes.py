from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class DictatedWorkOrderSummary(BaseModel):
    """Structured work order summary generated from technician voice dictation."""
    work_completed_bullets: List[str] = Field(
        default_factory=list,
        description="Itemized list of diagnostic tests, repairs, and labor performed",
    )
    technical_readings: Dict[str, Any] = Field(
        default_factory=dict,
        description="Extracted quantitative measurements e.g. subcooling, superheat, pressures, voltages, static pressure",
    )
    parts_installed: List[str] = Field(
        default_factory=list,
        description="Parts, truck stock, materials, or consumables installed on-site",
    )
    customer_recommendations: List[str] = Field(
        default_factory=list,
        description="Recommended preventive maintenance or future equipment replacements discussed with homeowner",
    )
    system_condition: str = Field(
        default="OPERATIONAL",
        description="Overall equipment status: 'OPERATIONAL', 'NEEDS_MONITORING', or 'ATTENTION_REQUIRED'",
    )
    formatted_invoice_narrative: str = Field(
        ...,
        description="Warranty-proof, professional narrative write-up ready for the customer invoice",
    )
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="Timestamp of dictation processing",
    )


class VoiceNotesSubmissionRequest(BaseModel):
    """Payload for submitting spoken technician dictation."""
    transcript_or_text: str = Field(..., description="Spoken voice transcript or technician notes")
    trade_category: Optional[str] = Field(None, description="Trade context e.g. HVAC, Plumbing, Roofing, Electrical")


class VoiceNotesSubmissionResponse(BaseModel):
    """API response for voice notes processing."""
    action_id: str = Field(..., description="Associated LeadAction UUID")
    status: str = Field(default="SUCCESS", description="Processing status")
    summary: DictatedWorkOrderSummary = Field(..., description="Processed work order breakdown")
    invoice_updated: bool = Field(default=False, description="Whether the parent invoice was updated with the narrative")
