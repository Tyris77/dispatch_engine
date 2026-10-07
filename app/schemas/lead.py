import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field


class IntentLevel(str, Enum):
    EMERGENCY = "EMERGENCY"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    SPAM = "SPAM"


class LeadQualificationOutput(BaseModel):
    """
    Pydantic schema designed specifically for LLM Structured Outputs
    (e.g., via OpenAI function calling, Gemini response_schema, Claude JSON mode).
    """
    is_qualified: bool = Field(
        ...,
        description="Whether this lead meets the minimum threshold for active sales engagement",
    )
    qualification_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence score from 0.0 (unqualified) to 1.0 (ideal customer profile)",
    )
    intent_level: IntentLevel = Field(
        ...,
        description="Categorized purchase intent level",
    )
    pain_points: List[str] = Field(
        default_factory=list,
        description="Extracted customer pain points or needs mentioned in the inquiry",
    )
    budget_estimate: Optional[str] = Field(
        None,
        description="Estimated budget or company tier if identifiable from the submission",
    )
    recommended_action: str = Field(
        ...,
        description="Next operational step (e.g. 'SCHEDULE_DEMO', 'AUTOMATED_NURTURE', 'DROP')",
    )
    reasoning: str = Field(
        ...,
        description="Detailed explanation of the qualification decision",
    )
    detected_language: str = Field(
        default="en",
        description="Detected language code of the submission (e.g. 'en', 'es')",
    )
    caller_response: Optional[str] = Field(
        default=None,
        description="Natural, professional response in the caller's spoken language (e.g. Spanish confirmation)",
    )


class LeadDispatchPlan(BaseModel):
    """Operational dispatch plan determining routing destination and CRM targets."""
    target_route: str = Field(..., description="Target queue or webhook URL")
    priority_tier: str = Field(default="NORMAL", description="URGENT, NORMAL, or LOW")
    assigned_rep: Optional[str] = Field(None, description="Assigned sales rep or agent ID")
    sync_destinations: List[str] = Field(
        default_factory=lambda: ["crm", "slack"],
        description="List of systems to notify or synchronize",
    )
    enrichment_data: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional context appended during qualification",
    )


class LeadActionCreate(BaseModel):
    """Schema to record or trigger a lead action."""
    lead_external_id: Optional[str] = Field(None, description="External CRM lead ID or email")
    qualification_score: Optional[float] = Field(None, ge=0.0, le=1.0)
    qualification_summary: Optional[str] = None
    action_type: str = Field(default="DISPATCH_ROUTED")
    dispatch_status: str = Field(default="QUEUED")
    crm_sync_status: str = Field(default="PENDING")
    metadata_payload: Dict[str, Any] = Field(default_factory=dict)
    diagnostic_data: Optional[Dict[str, Any]] = None
    proposal_data: Optional[Dict[str, Any]] = None
    signed_contract: Optional[Dict[str, Any]] = None
    review_data: Optional[Dict[str, Any]] = None
    tracking_data: Optional[Dict[str, Any]] = None
    membership_enrollment: Optional[Dict[str, Any]] = None
    invoice_data: Optional[Dict[str, Any]] = None
    material_po: Optional[Dict[str, Any]] = None
    profitability_data: Optional[Dict[str, Any]] = None
    reactivation_data: Optional[Dict[str, Any]] = None
    insurance_data: Optional[Dict[str, Any]] = None
    crew_data: Optional[Dict[str, Any]] = None
    safety_data: Optional[Dict[str, Any]] = None
    lien_waiver_data: Optional[Dict[str, Any]] = None
    voice_notes_data: Optional[Dict[str, Any]] = None
    lien_notice_data: Optional[Dict[str, Any]] = None
    warranty_data: Optional[Dict[str, Any]] = None
    financing_selection: Optional[Dict[str, Any]] = None
    trip_mileage: Optional[float] = None
    referral_data: Optional[Dict[str, Any]] = None
    route_stop_data: Optional[Dict[str, Any]] = None
    surge_pricing_data: Optional[Dict[str, Any]] = None
    rebate_data: Optional[Dict[str, Any]] = None
    commercial_data: Optional[Dict[str, Any]] = None
    sensor_data: Optional[Dict[str, Any]] = None
    mitigation_data: Optional[Dict[str, Any]] = None
    backfill_data: Optional[Dict[str, Any]] = None
    arbitrage_data: Optional[Dict[str, Any]] = None
    storyboard_data: Optional[Dict[str, Any]] = None
    partner_exchange_data: Optional[Dict[str, Any]] = None
    speed_to_lead_data: Optional[Dict[str, Any]] = None
    claim_supplement_data: Optional[Dict[str, Any]] = None
    locker_reservation_data: Optional[Dict[str, Any]] = None
    surge_crew_bid_data: Optional[Dict[str, Any]] = None


class LeadActionRead(BaseModel):
    """Full database representation of a lead action record."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    webhook_event_id: Optional[uuid.UUID]
    lead_external_id: Optional[str]
    qualification_score: Optional[float]
    qualification_summary: Optional[str]
    action_type: str
    dispatch_status: str
    crm_sync_status: str
    metadata_payload: Dict[str, Any]
    diagnostic_data: Optional[Dict[str, Any]] = None
    proposal_data: Optional[Dict[str, Any]] = None
    signed_contract: Optional[Dict[str, Any]] = None
    review_data: Optional[Dict[str, Any]] = None
    tracking_data: Optional[Dict[str, Any]] = None
    membership_enrollment: Optional[Dict[str, Any]] = None
    invoice_data: Optional[Dict[str, Any]] = None
    material_po: Optional[Dict[str, Any]] = None
    profitability_data: Optional[Dict[str, Any]] = None
    reactivation_data: Optional[Dict[str, Any]] = None
    insurance_data: Optional[Dict[str, Any]] = None
    crew_data: Optional[Dict[str, Any]] = None
    safety_data: Optional[Dict[str, Any]] = None
    lien_waiver_data: Optional[Dict[str, Any]] = None
    voice_notes_data: Optional[Dict[str, Any]] = None
    lien_notice_data: Optional[Dict[str, Any]] = None
    warranty_data: Optional[Dict[str, Any]] = None
    financing_selection: Optional[Dict[str, Any]] = None
    trip_mileage: Optional[float] = None
    referral_data: Optional[Dict[str, Any]] = None
    route_stop_data: Optional[Dict[str, Any]] = None
    surge_pricing_data: Optional[Dict[str, Any]] = None
    rebate_data: Optional[Dict[str, Any]] = None
    commercial_data: Optional[Dict[str, Any]] = None
    sensor_data: Optional[Dict[str, Any]] = None
    mitigation_data: Optional[Dict[str, Any]] = None
    backfill_data: Optional[Dict[str, Any]] = None
    arbitrage_data: Optional[Dict[str, Any]] = None
    storyboard_data: Optional[Dict[str, Any]] = None
    partner_exchange_data: Optional[Dict[str, Any]] = None
    speed_to_lead_data: Optional[Dict[str, Any]] = None
    claim_supplement_data: Optional[Dict[str, Any]] = None
    locker_reservation_data: Optional[Dict[str, Any]] = None
    surge_crew_bid_data: Optional[Dict[str, Any]] = None
    created_at: datetime
    updated_at: datetime



