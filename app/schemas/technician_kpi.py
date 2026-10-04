from datetime import datetime, timezone
from typing import List, Optional
from pydantic import BaseModel, Field


class TechnicianMetrics(BaseModel):
    """Productivity, closing rate, revenue, and commission metrics for an individual service technician."""
    tech_name: str = Field(..., description="Technician legal or operating name")
    phone: str = Field(..., description="Mobile dispatch contact number")
    jobs_dispatched: int = Field(0, description="Total assignments dispatched to technician")
    jobs_completed: int = Field(0, description="Jobs successfully serviced or invoiced")
    proposals_closed: int = Field(0, description="Number of customer proposals accepted")
    closing_rate_pct: float = Field(0.0, description="Proposals closed over completed jobs percentage")
    revenue_generated: float = Field(0.0, description="Gross contract revenue generated in USD")
    memberships_sold: int = Field(0, description="Annual maintenance agreement enrollments sold")
    safety_score_avg: float = Field(100.0, description="Average OSHA jobsite safety score percentage")
    commission_earned: float = Field(0.0, description="Total commission accrued from revenue and membership bonuses")


class CommissionJobItem(BaseModel):
    """Individual closed job line item on a technician weekly commission statement."""
    job_id: str = Field(..., description="Lead action or job UUID")
    customer_name: str = Field(..., description="Customer or homeowner name")
    trade: str = Field("HVAC", description="Trade category")
    contract_total: float = Field(..., description="Accepted contract or invoice total in USD")
    commission_rate_pct: float = Field(6.0, description="Applied commission rate percentage")
    commission_amount: float = Field(..., description="Earned commission payout in USD")


class WeeklyCommissionStatement(BaseModel):
    """Itemized weekly commission pay statement for a field technician."""
    statement_id: str = Field(..., description="Unique payroll voucher number e.g. COMM-2026-W40-01")
    tech_name: str = Field(..., description="Technician full name")
    pay_period: str = Field(..., description="Payroll period description e.g. Week 40 (Sep 28 - Oct 04, 2026)")
    itemized_jobs: List[CommissionJobItem] = Field(default_factory=list, description="Itemized completed customer jobs")
    membership_bonuses: float = Field(0.0, description="Lump sum bonuses for membership plan enrollments")
    total_commission_payout: float = Field(0.0, description="Net payable commission payout")
    generated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="ISO generation timestamp",
    )
