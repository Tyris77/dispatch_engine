from typing import List, Optional
from pydantic import BaseModel, Field


class FinancingPlanOption(BaseModel):
    """Specific installment loan or promotional customer financing option."""
    plan_name: str = Field(..., description="Marketing title of the financing plan (e.g. '0% APR 18-Mo Promo')")
    interest_rate_pct: float = Field(..., description="Annual Percentage Rate (APR) e.g. 0.0, 7.99, 9.99")
    term_months: int = Field(..., description="Repayment duration in months (e.g. 18, 60, 120)")
    monthly_payment_estimate: float = Field(..., description="Estimated monthly payment in USD")
    total_financed_amount: float = Field(..., description="Total principal financed after deposit")
    lender_partner: str = Field("Wisetack / TradeOps Consumer Finance", description="Financing partner or platform")


class FinancingBreakdown(BaseModel):
    """Full financing tier calculation for a proposal estimate option."""
    cash_price: float = Field(..., description="Total cash price for the service tier")
    deposit_required: float = Field(0.0, description="Initial deposit required")
    financed_principal: float = Field(0.0, description="Amount financed after deposit")
    plans: List[FinancingPlanOption] = Field(default_factory=list, description="Available consumer loan products")


class FinancingSelectionSubmission(BaseModel):
    """Customer financing choice recorded upon contract signature."""
    plan_name: str = Field(..., description="Name of selected loan product")
    monthly_payment: float = Field(..., description="Agreed monthly payment")
    term_months: int = Field(60, description="Repayment duration in months")
    tier_name: Optional[str] = Field(None, description="Selected tier option name")
    interest_rate_pct: Optional[float] = Field(None, description="Applicable loan APR")
    total_financed_amount: Optional[float] = Field(None, description="Total amount financed")
    pre_qualified: bool = Field(True, description="Soft credit check pre-qualification status")
