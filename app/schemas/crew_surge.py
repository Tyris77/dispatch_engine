from typing import Optional
from pydantic import BaseModel, Field


class CrewSubcontractor(BaseModel):
    """Enrolled 1099 trade subcontractor profile in the contractor surge network."""
    subcontractor_id: str = Field(..., description="Unique subcontractor identifier (e.g., 'sub-dmv-mendez')")
    name: str = Field(..., description="Trade subcontractor or foreman business name")
    trade: str = Field(..., description="Trade specialty ('plumbing', 'hvac', 'roofing', 'water_mitigation', 'electrical')")
    phone: str = Field(..., description="E.164 formatted SMS dispatch mobile number")
    email: str = Field(..., description="Business email for billing and tax correspondence")
    w9_verified: bool = Field(default=False, description="Whether IRS Form W-9 has been digitally executed and verified")
    coi_verified: bool = Field(default=False, description="Whether an active ACORD 25 Certificate of Insurance is on file")
    rating: float = Field(default=4.8, description="Customer quality and craftsmanship rating (1.0 to 5.0)")
    active_jobs_count: int = Field(default=0, description="Currently dispatched open jobs")


class SurgeBidBroadcast(BaseModel):
    """Real-time on-demand surge job dispatch broadcast packet sent to vetted 1099 crews."""
    bid_id: str = Field(..., description="Unique surge broadcast identifier (e.g., 'BID-2026-9042')")
    action_id: str = Field(..., description="Associated dispatch lead action UUID")
    trade: str = Field(..., description="Trade discipline required")
    location_summary: str = Field(..., description="Anonymized cross-street and municipality (e.g., 'McLean, VA 22101')")
    job_scope: str = Field(..., description="Summary of required on-site work and diagnostic findings")
    estimated_ticket_value: float = Field(..., description="Total homeowner customer billing price in USD")
    subcontractor_payout: float = Field(..., description="Guaranteed labor payout to claiming crew (typically 65%)")
    contractor_margin: float = Field(..., description="Contractor retained gross margin in USD (typically 35%)")
    arrival_sla_minutes: int = Field(default=45, description="Required response time window in minutes")
    expires_at: str = Field(..., description="ISO 8601 timestamp (15 minutes from surge creation)")
    status: str = Field(default="OPEN", description="Bid status: 'OPEN', 'CLAIMED', 'EXPIRED'")
    claimed_by: Optional[str] = Field(default=None, description="Subcontractor ID or name that locked this bid")
    claimed_at: Optional[str] = Field(default=None, description="Timestamp when job was locked")
    broadcast_sms: Optional[str] = Field(default=None, description="Formatted SMS push notification text")
    full_customer_address: Optional[str] = Field(default=None, description="Exact street address unlocked upon accepted claim")
    gate_codes: Optional[str] = Field(default=None, description="Access security codes unlocked upon accepted claim")
    tenant_slug: Optional[str] = Field(default=None, description="Contractor company slug")
    created_at: Optional[str] = Field(default=None, description="ISO timestamp of broadcast creation")


class CrewBidClaimRequest(BaseModel):
    """Payload submitted by a 1099 subcontractor tapping to claim an open surge shift."""
    subcontractor_id: str = Field(..., description="Enrolled subcontractor identifier")
    subcontractor_phone: str = Field(..., description="Claimant verified phone number")
    estimated_eta_minutes: int = Field(default=35, description="Claimant projected arrival time in minutes")


class CrewBidClaimResponse(BaseModel):
    """Result of surge shift claim including compliance validation and job site unlocking."""
    status: str = Field(..., description="'ACCEPTED', 'REJECTED_COMPLIANCE', 'ALREADY_CLAIMED', 'EXPIRED'")
    bid_id: str = Field(..., description="Surge bid identifier")
    action_id: str = Field(..., description="Associated dispatch lead action UUID")
    subcontractor_name: str = Field(..., description="Subcontractor entity name")
    voucher_url: str = Field(..., description="Direct link to digital 1099 labor settlement voucher")
    tracking_url: str = Field(..., description="Customer arrival tracker link")
    full_customer_address: Optional[str] = Field(default=None, description="Unlocked jobsite address (only if ACCEPTED)")
    gate_codes: Optional[str] = Field(default=None, description="Unlocked entrance codes (only if ACCEPTED)")
    w9_portal_url: Optional[str] = Field(default=None, description="Onboarding portal link if rejected for compliance")
    message: Optional[str] = Field(default=None, description="Detailed status notice or error explanation")


class SurgeBidCreateRequest(BaseModel):
    """Request payload to manually or autonomously trigger an emergency crew surge broadcast."""
    ticket_value: Optional[float] = Field(default=None, description="Override estimated customer invoice total")
    split_percentage: Optional[float] = Field(default=0.65, description="Subcontractor revenue share percentage (0.0 to 1.0)")
    arrival_sla_minutes: Optional[int] = Field(default=45, description="Response SLA window in minutes")
