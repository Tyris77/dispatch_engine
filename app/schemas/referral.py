from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ReferralVoucher(BaseModel):
    """Personalized customer neighbor referral voucher and rewards ledger."""
    referral_code: str = Field(..., description="Unique referral token e.g. 'REF-APEX-A8F192'")
    referrer_name: str = Field(..., description="Name of referring homeowner or business customer")
    referrer_phone: str = Field(..., description="Mobile phone number of referrer")
    discount_amount: float = Field(150.0, description="Discount amount in USD for the neighbor")
    reward_amount: float = Field(100.0, description="Cash or credit reward in USD for the referrer upon completed booking")
    shareable_url: str = Field(..., description="Direct link for neighbor to view and redeem voucher")
    conversions_count: int = Field(0, description="Number of neighbors who have booked via this voucher")
    rewards_earned: float = Field(0.0, description="Cumulative reward dollars earned by referrer")
    tenant_name: str = Field(..., description="Contractor trade legal name")
    tenant_slug: str = Field(..., description="Contractor tenant slug")
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="Voucher creation timestamp",
    )
    conversions: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Itemized log of referred neighbor claims",
    )


class ReferralClaimSubmission(BaseModel):
    """Neighbor claim booking submission requesting service with referral discount."""
    referral_code: str = Field(..., description="Voucher code provided by neighbor")
    neighbor_name: str = Field(..., description="Referred neighbor full name")
    neighbor_phone: str = Field(..., description="Referred neighbor contact mobile phone")
    service_needed: str = Field(..., description="Description of issue or required trade service")
    address: str = Field(..., description="Property address for technician dispatch")
    photo_notes: Optional[str] = Field(None, description="Optional diagnostic notes or photo description")


class ReferralClaimResponse(BaseModel):
    """Outcome of neighbor voucher redemption."""
    success: bool = Field(..., description="Whether referral claim was accepted and booked")
    message: str = Field(..., description="Status summary for neighbor")
    referral_code: str = Field(..., description="Referral code used")
    new_action_id: Optional[str] = Field(None, description="Created LeadAction ID for dispatch")
    discount_applied: float = Field(150.0, description="Instant voucher deduction applied in USD")
    neighbor_name: str = Field(..., description="Referred customer name")
