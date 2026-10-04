from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ReactivationOffer(BaseModel):
    """Personalized revival offer dispatched to a dormant or aging equipment lead."""
    action_id: str = Field(..., description="Target LeadAction UUID string")
    campaign_type: str = Field(
        ...,
        description="'UNSIGNED_PROPOSAL_48H' or 'SEASONAL_EQUIPMENT_AGE'",
    )
    customer_name: str = Field(default="Homeowner", description="Customer full name")
    customer_phone: str = Field(..., description="Destination SMS phone number")
    equipment_summary: Optional[str] = Field(None, description="Diagnosed equipment make/model")
    proposal_link: Optional[str] = Field(None, description="1-Tap Good-Better-Best proposal URL")
    discount_incentive: float = Field(default=250.0, description="Promotional route credit in USD")
    expiration_date: str = Field(..., description="Expiration date or cutoff day for the discount")
    message_body: str = Field(..., description="Complete SMS copy sent to customer")
    status: str = Field(default="SENT", description="'SCHEDULED', 'SENT', 'ACCEPTED', or 'EXPIRED'")
    potential_recovered_revenue: float = Field(default=0.0, description="Gross value of reactivated pipeline")
    sent_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


class ReactivationBatchResult(BaseModel):
    """Telemetry report after running an autonomous dead lead reactivation sweep."""
    scanned_leads_count: int = Field(..., description="Number of leads evaluated in the sweep")
    reactivated_count: int = Field(..., description="Number of dormant leads sent revival offers")
    total_reactivated_pipeline_value: float = Field(..., description="Sum of recovered pipeline value in USD")
    offers_dispatched: List[ReactivationOffer] = Field(default_factory=list, description="List of generated offers")
