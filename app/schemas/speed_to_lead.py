import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class SpeedToLeadPayload(BaseModel):
    """Payload representing an inbound ad lead from Google LSA, Angi, Thumbtack, or generic webhook."""
    platform: str = Field(default="google_lsa", description="Ad channel source: google_lsa, angi, thumbtack, generic")
    external_lead_id: Optional[str] = Field(None, description="External platform ID or lead GUID")
    customer_name: str = Field(..., description="Customer full name")
    customer_phone: str = Field(..., description="Customer direct contact phone")
    customer_email: Optional[str] = Field(None, description="Customer email address if provided")
    customer_address: Optional[str] = Field(None, description="Physical address or metro neighborhood")
    trade: str = Field(default="Plumbing", description="Trade category (Plumbing, HVAC, Electrical, Roofing)")
    job_description: str = Field(..., description="Inquiry details or homeowner notes")
    ad_cost: Optional[float] = Field(None, description="Cost per lead paid to ad network in USD")
    received_at: Optional[datetime] = Field(None, description="Timestamp lead was registered by ad platform")
    tenant_slug: Optional[str] = Field(default="apex-roofing", description="Tenant routing slug")


class SpeedToLeadResponse(BaseModel):
    """Output dispatched within <5.0 seconds of lead ingestion."""
    action_id: uuid.UUID = Field(..., description="Database UUID for the generated LeadAction")
    platform: str = Field(..., description="Ingestion channel")
    latency_seconds: float = Field(..., description="Total elapsed seconds from webhook ingestion to dispatch")
    status: str = Field(default="INSTANT_DISPATCHED", description="Operational execution status")
    sms_sent: bool = Field(default=True, description="Whether 2-way qualification SMS was successfully triggered")
    sms_preview: str = Field(..., description="Preview text of the automated SMS sent to homeowner")
    technician_assigned: str = Field(..., description="Name or callsign of assigned on-call tech")
    eta_minutes: int = Field(default=20, description="Estimated arrival window sent to customer")
    details: Dict[str, Any] = Field(default_factory=dict, description="Metadata and telemetry diagnostics")


class SpeedToLeadMetrics(BaseModel):
    """Real-time performance metrics tracking sub-5 second lead response telemetry."""
    total_leads_ingested: int
    average_response_time_seconds: float
    fastest_response_time_seconds: float
    leads_under_5s_pct: float
    ad_spend_preserved: float
    platform_breakdown: Dict[str, int]
    recent_dispatches: List[Dict[str, Any]]
