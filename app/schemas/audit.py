from typing import List, Optional
from pydantic import BaseModel, Field


class AuditCalculateRequest(BaseModel):
    """Input parameters to model missed call revenue leakage."""
    trade: str = Field(default="Plumbing", description="Trade trade specialty: Plumbing, HVAC, Electrical, Roofing, Restoration")
    truck_count: int = Field(default=5, ge=1, le=200, description="Active fleet vehicle count")
    monthly_call_volume: int = Field(default=250, ge=10, le=20000, description="Estimated monthly inbound phone calls")
    average_ticket: float = Field(default=850.0, ge=50.0, le=50000.0, description="Average revenue per completed service call")
    zip_code: str = Field(default="20001", description="Contractor primary market ZIP code")


class AuditReportResponse(BaseModel):
    """Comprehensive revenue leak assessment and recovery roadmap."""
    trade: str
    truck_count: int
    monthly_call_volume: int
    average_ticket: float
    zip_code: str
    missed_call_rate_pct: float = Field(default=28.0, description="Regional industry benchmark missed call rate (28%)")
    missed_call_count: int
    competitor_capture_rate_pct: float = Field(default=65.0, description="Percentage of missed callers who immediately dial a competitor (65%)")
    lost_jobs_count: int
    monthly_leak_revenue: float
    annual_lost_profit: float
    competitor_capture_index: float = Field(..., description="Vulnerability score from 0 to 100")
    projected_7_day_recovery: float
    projected_annual_recovered_revenue: float
    regional_benchmark_notes: str
    recovery_plan: List[str]
