from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class MoistureReading(BaseModel):
    """Specific room and structural material moisture meter percentage reading."""
    room_name: str = Field(..., description="Affected containment area (e.g. Master Bedroom, Kitchen, Basement)")
    material_type: str = Field(
        ...,
        description="Material type: Drywall, Subfloor, Baseboard, or Hardwood",
    )
    moisture_percentage: float = Field(..., ge=0.0, description="Measured pin/pinless moisture meter content (%)")
    dry_standard: float = Field(
        default=12.0,
        ge=0.0,
        description="IICRC S500 dry baseline standard percentage for this material",
    )
    drying_status: str = Field(
        default="WET",
        description="Drying status: WET, DRYING, or DRY_STANDARD_MET",
    )


class PsychrometricDayLog(BaseModel):
    """Daily psychrometric chamber condition and moisture meter progress record."""
    day_number: int = Field(..., ge=1, description="Sequential drying day (Day 1, Day 2, Day 3, etc.)")
    date: str = Field(..., description="Inspection date (YYYY-MM-DD)")
    temp_fahrenheit: float = Field(..., description="Chamber ambient temperature in Fahrenheit")
    relative_humidity_pct: float = Field(..., ge=0.0, le=100.0, description="Chamber relative humidity (%)")
    gpp_grains_per_pound: float = Field(..., ge=0.0, description="Calculated moisture grains per pound (GPP)")
    dehumidifiers_running: int = Field(default=2, ge=0, description="Active commercial LGR dehumidifier count")
    air_movers_running: int = Field(default=4, ge=0, description="Active centrifugal air mover count")
    readings: List[MoistureReading] = Field(
        default_factory=list,
        description="Individual structural material moisture readings",
    )


class MitigationDryingReport(BaseModel):
    """Complete adjuster-ready IICRC S500 certified water mitigation drying packet."""
    dossier_id: str = Field(..., description="Unique drying dossier ID (e.g. DRY-2026-8812)")
    action_id: str = Field(..., description="Linked LeadAction UUID string")
    job_address: str = Field(..., description="Property loss location address")
    customer_name: str = Field(..., description="Property owner or policyholder name")
    date_of_loss: str = Field(..., description="Date of water loss or incident")
    daily_logs: List[PsychrometricDayLog] = Field(
        default_factory=list,
        description="Daily psychrometric progression logs",
    )
    iicrc_compliant: bool = Field(default=True, description="Certified IICRC S500 protocol compliance")
    drying_completed: bool = Field(
        default=False,
        description="True if all structural materials have met dry standards and GPP is normalized",
    )
    drying_certificate_number: str = Field(
        default="IICRC-WRT-99214-DMV",
        description="Certified Water Damage Restoration Technician (WRT) certificate number",
    )
    technician_name: str = Field(
        default="Dave Kowalski, IICRC Master Restorer",
        description="Lead certified mitigation specialist",
    )
    restoration_company: str = Field(
        default="Titan Emergency Restoration & Mechanical",
        description="Licensed mitigation contractor legal name",
    )
    generated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        description="Timestamp when dossier was compiled",
    )


class DailyMoistureSubmission(BaseModel):
    """Technician mobile submission payload for a daily drying log."""
    day_number: int = Field(..., ge=1)
    temp_fahrenheit: float = Field(default=72.0)
    relative_humidity_pct: float = Field(default=45.0)
    dehumidifiers_running: int = Field(default=2)
    air_movers_running: int = Field(default=4)
    readings: List[Dict[str, Any]] = Field(default_factory=list)
