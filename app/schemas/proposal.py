from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ProposalOption(BaseModel):
    """Individual service tier in a tiered Good-Better-Best estimate."""
    tier_name: str = Field(
        description="Tier identifier (e.g., 'Repair / Patch', 'Standard Replacement', 'Premium System')"
    )
    title: str = Field(
        description="Customer-friendly title of the option"
    )
    price_estimate: float = Field(
        description="Total estimated investment cost in USD",
        ge=0.0,
    )
    scope_bullets: List[str] = Field(
        default_factory=list,
        description="Specific deliverables, parts, materials, and labor items included",
    )
    warranty_info: str = Field(
        description="Warranty coverage terms for parts, labor, and craftsmanship"
    )
    badge: Optional[str] = Field(
        default=None,
        description="Optional marketing badge (e.g., 'MOST POPULAR', 'BUDGET FRIENDLY', 'BEST EFFICIENCY')",
    )
    rebates_available: Optional[float] = Field(
        default=None,
        description="Total qualifying utility rebates and federal tax credits available",
    )
    net_investment: Optional[float] = Field(
        default=None,
        description="Net customer out-of-pocket price after applying qualifying rebates",
    )


class ProposalEstimate(BaseModel):
    """Complete Good-Better-Best tiered proposal generated from visual diagnosis or trade rate-cards."""
    equipment_summary: str = Field(
        description="Summary of the diagnosed equipment, brand, model, and primary failure"
    )
    options: List[ProposalOption] = Field(
        description="Three tiered options: Bronze repair, Silver replacement, Gold premium upgrade",
        min_length=1,
    )
    deposit_required: float = Field(
        default=0.0,
        ge=0.0,
        description="Required deposit amount in USD to lock in scheduling and dispatch",
    )
    deposit_percentage: float = Field(
        default=25.0,
        ge=0.0,
        le=100.0,
        description="Percentage of total selected tier price required as deposit",
    )
    generated_at: str = Field(
        default_factory=lambda: datetime.utcnow().isoformat(),
        description="ISO 8601 timestamp when the proposal was computed",
    )


class ContractSignatureSubmission(BaseModel):
    """Payload submitted when customer accepts and e-signs a tiered proposal."""
    selected_tier: str = Field(
        description="The tier chosen by the homeowner (e.g. 'Repair / Patch', 'Standard Replacement', 'Premium System')"
    )
    signature_base64: str = Field(
        description="Base64 encoded PNG or SVG data URL representing customer handwritten signature"
    )
    customer_name: Optional[str] = Field(
        default=None,
        description="Printed full name of the signing customer",
    )
    customer_phone: Optional[str] = Field(
        default=None,
        description="Customer callback phone number for confirmation SMS",
    )
    deposit_paid: Optional[float] = Field(
        default=None,
        ge=0.0,
        description="Amount paid in deposit (if payment processing was executed)",
    )
    enroll_membership: Optional[bool] = Field(
        default=False,
        description="Whether customer opted in to recurring maintenance membership (MSA)",
    )
    membership_plan_name: Optional[str] = Field(
        default=None,
        description="Selected membership plan name",
    )
    financing_plan: Optional[str] = Field(
        default=None,
        description="Selected consumer financing plan option (e.g. '0% APR 18-Mo Promo')",
    )
    financing_monthly_payment: Optional[float] = Field(
        default=None,
        description="Estimated monthly payment for selected financing plan",
    )


class SignedContractData(BaseModel):
    """Stored record of an accepted, legally e-signed proposal contract."""
    selected_tier: str
    tier_title: str
    price_total: float
    deposit_required: float
    deposit_paid: float
    signature_base64: str
    customer_name: Optional[str] = None
    signed_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    contract_status: str = "SIGNED"
    membership_enrolled: bool = False
    membership_discount: float = 0.0
    membership_plan_name: Optional[str] = None
    final_price: Optional[float] = None
    original_price: Optional[float] = None


class ProposalResponse(BaseModel):
    """API response model for proposal retrieval and e-sign status."""
    action_id: str
    tenant_slug: str
    tenant_name: str
    estimate: ProposalEstimate
    is_signed: bool = False
    signed_contract: Optional[Dict[str, Any]] = None
    membership_plan: Optional[Dict[str, Any]] = None
    membership_offer: Optional[Dict[str, Any]] = None
