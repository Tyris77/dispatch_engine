from typing import Optional
from pydantic import BaseModel, Field


class TradePartner(BaseModel):
    """Verified B2B trade contractor partner in the cross-trade network."""
    partner_id: str
    company_name: str
    trade_specialty: str = Field(..., description="Plumbing, HVAC, Roofing, Electrical, Restoration")
    phone: str
    email: str
    finder_fee_rate: float = Field(default=0.10, ge=0.0, le=0.50)


class PartnerReferralTrade(BaseModel):
    """Cross-trade reciprocal job referral and finder fee record."""
    referral_id: str
    referring_tenant_slug: str
    recipient_partner: TradePartner
    customer_name: str
    customer_phone: str
    service_needed: str
    estimated_job_value: float = Field(..., ge=0)
    finder_fee_due: float = Field(..., ge=0)
    status: str = Field(default="DISPATCHED_TO_PARTNER", description="DISPATCHED_TO_PARTNER, IN_PROGRESS, CLOSED_WON, FEE_SETTLED")


class PartnerReferralDispatchPayload(BaseModel):
    """Payload to trigger a cross-trade warm referral to a partner shop."""
    target_trade: str
    estimated_job_value: Optional[float] = None
    service_needed: Optional[str] = None
    recipient_partner_id: Optional[str] = None
