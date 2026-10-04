from datetime import datetime, timezone
from typing import List, Optional
from pydantic import BaseModel, Field


class Subcontractor1099Record(BaseModel):
    """Annual IRS Form 1099-NEC nonemployee compensation ledger entry for a subcontractor crew."""
    crew_name: str = Field(..., description="Trade subcontractor or crew business name")
    foreman_name: str = Field(..., description="Lead technician or subcontractor foreman name")
    phone: str = Field(..., description="Contact phone for 1099 tax distribution")
    total_vouchers_count: int = Field(0, description="Total completed settlement vouchers in tax year")
    box1_nonemployee_compensation: float = Field(
        ...,
        description="IRS Form 1099-NEC Box 1 total nonemployee compensation in USD",
    )
    w9_status: str = Field(
        "ON_FILE",
        description="W-9 compliance status: 'ON_FILE' or 'PENDING'",
    )
    ein_or_ssn_masked: str = Field(
        ...,
        description="Masked Tax Identification Number / EIN (e.g., 'XX-XXX4912' or 'XXX-XX-8821')",
    )
    is_reportable: bool = Field(
        True,
        description="Whether compensation meets or exceeds IRS reporting threshold ($600.00)",
    )


class Annual1099Report(BaseModel):
    """Compiled annual 1099-NEC subcontractor audit report for CPA tax filing."""
    tenant_slug: str = Field(..., description="Contractor tenant slug")
    tenant_name: str = Field("", description="Contractor legal entity name")
    tax_year: int = Field(..., description="Calendar tax year e.g. 2026")
    total_subcontractors: int = Field(..., description="Count of 1099 subcontractor entities")
    total_1099_payouts: float = Field(..., description="Sum of Box 1 Nonemployee Compensation in USD")
    filing_threshold: float = Field(600.0, description="IRS statutory minimum reporting threshold ($600.00)")
    generated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="Report compilation timestamp",
    )
    records: List[Subcontractor1099Record] = Field(
        default_factory=list,
        description="Itemized subcontractor 1099 ledger records",
    )
