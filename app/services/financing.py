from typing import Any, Dict, List, Optional
from app.schemas.financing import FinancingBreakdown, FinancingPlanOption


class FinancingService:
    """Customer installment loan and promotional financing amortization engine for service proposals."""

    @staticmethod
    def _compute_amortized_monthly(principal: float, apr_pct: float, months: int) -> float:
        """Standard amortization formula: M = P * [r(1+r)^n] / [(1+r)^n - 1]."""
        if principal <= 0 or months <= 0:
            return 0.0
        if apr_pct <= 0.0:
            return round(principal / float(months), 2)

        monthly_rate = (apr_pct / 100.0) / 12.0
        compound = (1.0 + monthly_rate) ** months
        monthly = principal * (monthly_rate * compound) / (compound - 1.0)
        return round(monthly, 2)

    def calculate_financing_plans(
        self,
        cash_price: float,
        deposit: float = 0.0,
        tenant_settings: Optional[Dict[str, Any]] = None,
    ) -> FinancingBreakdown:
        """
        Calculates consumer financing options for a given estimate cash price and optional deposit.
        Returns 0% promotional, 60-month fixed, and 120-month long-term payment options.
        """
        principal = max(0.0, round(cash_price - deposit, 2))
        settings_dict = tenant_settings or {}
        lender = settings_dict.get("financing_lender_partner", "Wisetack / TradeOps Consumer Finance")

        plans: List[FinancingPlanOption] = []

        if principal > 0:
            # Plan 1: 0% APR 18-Month Same-As-Cash Promotional Plan
            p1_monthly = self._compute_amortized_monthly(principal, apr_pct=0.0, months=18)
            plans.append(
                FinancingPlanOption(
                    plan_name="0% APR 18-Mo Promo",
                    interest_rate_pct=0.0,
                    term_months=18,
                    monthly_payment_estimate=p1_monthly,
                    total_financed_amount=principal,
                    lender_partner=lender,
                )
            )

            # Plan 2: Low Monthly 60-Month Fixed Rate Plan (7.99% APR)
            p2_apr = float(settings_dict.get("financing_fixed_60_apr", 7.99))
            p2_monthly = self._compute_amortized_monthly(principal, apr_pct=p2_apr, months=60)
            plans.append(
                FinancingPlanOption(
                    plan_name="Low Monthly 60-Mo Fixed",
                    interest_rate_pct=p2_apr,
                    term_months=60,
                    monthly_payment_estimate=p2_monthly,
                    total_financed_amount=round(p2_monthly * 60, 2),
                    lender_partner=lender,
                )
            )

            # Plan 3: Standard 120-Month Long-Term Low Payment Plan (9.99% APR)
            p3_apr = float(settings_dict.get("financing_long_term_120_apr", settings_dict.get("financing_long_term_apr", 9.99)))
            p3_monthly = self._compute_amortized_monthly(principal, apr_pct=p3_apr, months=120)
            plans.append(
                FinancingPlanOption(
                    plan_name="Standard 120-Mo",
                    interest_rate_pct=p3_apr,
                    term_months=120,
                    monthly_payment_estimate=p3_monthly,
                    total_financed_amount=round(p3_monthly * 120, 2),
                    lender_partner=lender,
                )
            )

        return FinancingBreakdown(
            cash_price=cash_price,
            deposit_required=deposit,
            financed_principal=principal,
            plans=plans,
        )


financing_service = FinancingService()
