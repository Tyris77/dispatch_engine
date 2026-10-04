from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class CrewAssignment(BaseModel):
    """Subcontractor crew and foreman details assigned to a dispatch job."""
    crew_name: str = Field(..., description="Trade subcontractor crew name (e.g. 'Apex Rapid Shingle Crew Alpha')")
    foreman_name: str = Field(..., description="Crew lead / foreman full name")
    foreman_phone: str = Field(..., description="Foreman mobile phone for SMS dispatches")
    trade_specialty: str = Field(..., description="Trade specialty: 'Roofing', 'Plumbing', 'HVAC', or 'General Restoration'")
    payout_type: str = Field(default="PERCENTAGE", description="'PERCENTAGE', 'PIECE_RATE', or 'FLAT'")
    rate_amount: float = Field(..., ge=0.0, description="Rate value (percentage e.g. 25.0, or unit price e.g. 85.0/SQ, or flat USD)")
    total_crew_payout: float = Field(..., ge=0.0, description="Total computed labor payout due to crew in USD")


class CrewVoucherData(BaseModel):
    """Formal 1099 subcontractor labor settlement voucher and job profitability record."""
    voucher_number: str = Field(..., description="Unique human-readable voucher ID (e.g. 'VOUCH-2026-A1F9')")
    action_id: str = Field(..., description="Associated LeadAction UUID")
    customer_name: str = Field(..., description="Customer / Property Owner name")
    job_address: str = Field(..., description="Physical job site address")
    scope_summary: str = Field(..., description="Summary of work scope executed by the crew")
    crew_assignment: CrewAssignment = Field(..., description="Crew assignment details and payout math")
    contract_revenue: float = Field(..., ge=0.0, description="Gross billed contract revenue in USD")
    material_cost: float = Field(default=0.0, ge=0.0, description="Wholesale material costs deducted from job")
    net_contractor_profit: float = Field(..., description="Contractor true net gross profit after crew and materials")
    margin_percentage: float = Field(..., description="Gross profit margin percentage after subcontractor payout")
    status: str = Field(default="ASSIGNED", description="'ASSIGNED', 'COMPLETED', or 'SETTLED'")
    notes: Optional[str] = Field(None, description="Special job notes, punch-list items, or deduction explanations")
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    settled_at: Optional[str] = Field(None, description="ISO timestamp when voucher was approved and settled")
