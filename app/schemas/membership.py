from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class MembershipPlan(BaseModel):
    """Configuration schema for a contractor's recurring maintenance agreement (MSA)."""
    name: str = Field(..., description="Plan title (e.g. 'Comfort Club VIP', 'Total Care Club')")
    monthly_price: float = Field(..., ge=0.0, description="Monthly recurring price in USD")
    discount_pct: float = Field(default=15.0, ge=0.0, le=100.0, description="Percentage discount on all repairs & replacements")
    perks: List[str] = Field(
        default_factory=lambda: [
            "15% Off All Future Repairs & Replacements",
            "$0 Emergency Trip & Diagnostic Fee",
            "Annual 21-Point System Precision Tune-Up Included",
            "Front-of-the-Line Priority VIP Scheduling",
        ],
        description="Key perks and value propositions included in membership",
    )
    billing_interval: str = Field(default="monthly", description="Billing frequency: monthly or annual")


class MembershipEnrollmentRequest(BaseModel):
    """Payload to enroll a customer into an MSA membership plan."""
    plan_name: str = Field(..., description="Selected membership plan name")
    monthly_price: float = Field(..., ge=0.0, description="Agreed monthly price")
    discount_pct: float = Field(default=15.0, ge=0.0, le=100.0, description="Discount percentage applied to repair")
    customer_name: Optional[str] = Field(None, description="Customer full name")
    customer_phone: Optional[str] = Field(None, description="Customer contact phone")
    payment_method_id: Optional[str] = Field(None, description="Optional Stripe PaymentMethod ID")


class MembershipEnrollmentRecord(BaseModel):
    """Database record for an active recurring maintenance membership."""
    status: str = Field(default="ACTIVE", description="ACTIVE, PAUSED, or CANCELLED")
    plan_name: str
    monthly_price: float
    discount_pct: float
    discount_amount: float
    original_price: float
    discounted_price: float
    stripe_subscription_id: Optional[str] = None
    enrolled_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    customer_name: Optional[str] = None
    customer_phone: Optional[str] = None


class MembershipOfferCalculation(BaseModel):
    """Computed discount offer presented on proposal view."""
    plan: MembershipPlan
    tier_price: float
    discount_amount: float
    discounted_price: float
    deposit_required: float
    first_year_savings: float
