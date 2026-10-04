from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class MunicipalPermit(BaseModel):
    """Public municipal building or commercial mechanical permit record."""
    permit_id: str = Field(..., description="Official municipal permit number (e.g. 'DC-B26-0418')")
    jurisdiction: str = Field(..., description="'Washington DC', 'Arlington County', or 'City of Alexandria'")
    permit_type: str = Field(..., description="Permit category (e.g. 'Commercial Mechanical', 'Roofing & Solar')")
    trade_category: str = Field(..., description="'HVAC', 'Plumbing', 'Roofing', or 'Electrical'")
    filing_date: str = Field(..., description="Date filed with the municipal building department")
    job_address: str = Field(..., description="Physical job location or commercial building address")
    estimated_valuation: float = Field(..., ge=0.0, description="Declared construction / mechanical valuation in USD")
    general_contractor: str = Field(..., description="General Contractor (GC) awarded the primary building permit")
    gc_contact_email: Optional[str] = Field(None, description="General Contractor estimating/project contact email")
    gc_contact_phone: Optional[str] = Field(None, description="General Contractor direct office or estimating phone")
    project_description: str = Field(..., description="Official project scope of work from permit application")
    status: str = Field(default="NEW", description="'NEW', 'BID_GENERATED', 'BID_SUBMITTED', or 'WON'")
    generated_bid: Optional[str] = Field(None, description="Cached AI-generated subcontractor bid letter")
    bid_generated_at: Optional[str] = Field(None, description="Timestamp when bid letter was created")


class SubcontractorBidRequest(BaseModel):
    """Payload to generate a tailored subcontractor bid package via Gemini."""
    permit_id: str = Field(..., description="Municipal permit ID to generate bid for")
    tenant_slug: str = Field(..., description="Contractor tenant slug submitting the bid")
    custom_scope_notes: Optional[str] = Field(None, description="Optional custom subcontractor exclusions or notes")


class SubcontractorBidResponse(BaseModel):
    """Tailored subcontractor trade bid letter addressed to the General Contractor."""
    permit_id: str = Field(..., description="Permit identifier")
    general_contractor: str = Field(..., description="Target General Contractor company name")
    subject: str = Field(..., description="Email/Letter subject line")
    bid_letter_markdown: str = Field(..., description="Formal subcontractor bid letter in markdown")
    estimated_bid_amount: float = Field(..., description="Estimated subcontractor bid amount based on trade scope")
    trade_category: str = Field(..., description="Trade (HVAC, Plumbing, Roofing, Electrical)")
    generated_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
