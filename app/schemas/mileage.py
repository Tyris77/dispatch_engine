from datetime import datetime, timezone
from typing import List
from pydantic import BaseModel, Field


class MileageTripRecord(BaseModel):
    """IRS compliant business mileage trip log entry."""
    trip_id: str = Field(..., description="Unique trip log identifier e.g. TRIP-2026-0012")
    date: str = Field(..., description="Date of dispatch or trip (YYYY-MM-DD)")
    driver_name: str = Field(..., description="Assigned technician or driver name")
    origin_address: str = Field(..., description="Starting point (e.g. contractor shop or supply warehouse)")
    destination_address: str = Field(..., description="Destination point (e.g. client property address)")
    business_purpose: str = Field(
        ...,
        description="IRS qualifying business purpose: 'Emergency Dispatch', 'Will-Call Parts Pickup', 'Estimate Inspection', or 'Service & Warranty Call'",
    )
    miles_driven: float = Field(..., description="Total round-trip road miles driven")
    irs_rate: float = Field(0.67, description="IRS standard business mileage deduction rate in USD/mile")
    deductible_dollars: float = Field(..., description="Total tax deduction amount in USD (miles * irs_rate)")


class FleetMileageReport(BaseModel):
    """Annual IRS business mileage tax compliance ledger for contractor vehicle fleet."""
    tenant_slug: str = Field(..., description="Contractor tenant slug")
    tenant_name: str = Field(..., description="Contractor corporate legal name")
    tax_year: int = Field(2026, description="Filing tax year")
    total_trips: int = Field(0, description="Total logged business vehicle trips")
    total_business_miles: float = Field(0.0, description="Cumulative business road miles driven")
    total_tax_deduction_dollars: float = Field(0.0, description="Total federal tax deduction value in USD")
    irs_rate: float = Field(0.67, description="Applicable IRS mileage rate")
    trips: List[MileageTripRecord] = Field(default_factory=list, description="Itemized trip records")
    generated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="Report generation ISO timestamp",
    )
