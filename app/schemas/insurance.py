from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class WeatherVerification(BaseModel):
    """NOAA meteorological telemetry verifying weather peril occurrence on date of loss."""
    event_type: str = Field(..., description="Peril description (e.g. 'Severe Hail & Damaging Wind Gusts')")
    recorded_metrics: Dict[str, Any] = Field(
        default_factory=dict,
        description="Meteorological metrics (e.g. {'hail_diameter_in': 1.75, 'wind_gust_mph': 62})",
    )
    station_location: str = Field(..., description="Observing weather station (e.g. 'NOAA KDCA - Reagan National Airport')")
    recorded_date: str = Field(..., description="Date meteorological event was officially registered")
    noaa_event_id: Optional[str] = Field(None, description="Official NOAA Storm Events Database reference identifier")


class InsuranceLineItem(BaseModel):
    """Xactimate-formatted itemized unit cost line item."""
    xactimate_code: str = Field(..., description="Standard Xactimate selector code (e.g. 'RFG 300S', 'WTR EXTR')")
    description: str = Field(..., description="Comprehensive scope description including material and labor")
    quantity: float = Field(..., ge=0.0, description="Measured quantity in specified unit")
    unit: str = Field(..., description="Unit of measurement (e.g. 'SQ', 'LF', 'EA', 'SF', 'HR')")
    unit_price: float = Field(..., ge=0.0, description="Unit cost in USD according to current price list")
    total_price: float = Field(..., ge=0.0, description="Line item extended total in USD")


class InsuranceClaimDossier(BaseModel):
    """Comprehensive, legally grounded insurance claim dossier for insurance adjusters."""
    claim_reference_id: str = Field(..., description="Unique claim file identifier (e.g. 'CLM-2026-8812')")
    date_of_loss: str = Field(..., description="Date of physical storm damage or sudden peril loss")
    weather_verification: Dict[str, Any] = Field(..., description="NOAA-certified weather verification summary")
    code_compliance_citations: List[str] = Field(
        default_factory=list,
        description="Mandatory statutory building code citations (e.g. IRC R905.1.2 ice barrier, IRC R908.3)",
    )
    xactimate_scope_narrative: str = Field(
        ...,
        description="Formal adjuster justification narrative explaining physical causation and code mandates",
    )
    itemized_line_items: List[InsuranceLineItem] = Field(
        default_factory=list,
        description="Standardized Xactimate schedule of values line items",
    )
    total_claim_estimate: float = Field(..., ge=0.0, description="Total claim scope valuation in USD")
    homeowner_name: str = Field(default="Homeowner", description="Insured property owner full name")
    property_address: str = Field(..., description="Physical loss property address")
    trade_category: str = Field(default="Roofing", description="Trade category (Roofing, Plumbing, HVAC)")
    damage_type: str = Field(default="Storm / Hail Impact", description="Primary peril or damage type")
    insurer_name: Optional[str] = Field(default="Carrier Property & Casualty", description="Insurance provider")
    policy_number: Optional[str] = Field(default=None, description="Policy number if available")
    adjuster_name: Optional[str] = Field(default=None, description="Assigned desk or field insurance adjuster")
    status: str = Field(default="READY_FOR_ADJUSTER", description="'DRAFT', 'READY_FOR_ADJUSTER', or 'SUBMITTED'")
    contractor_license: Optional[str] = Field(default=None, description="Contractor license citation")
    generated_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
