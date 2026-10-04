from datetime import datetime, timezone
from typing import Optional
from pydantic import BaseModel, Field


class WarrantyCertificate(BaseModel):
    """Formal manufacturer and contractor warranty deed certificate for installed trade equipment."""
    certificate_number: str = Field(..., description="Unique warranty certificate ID e.g. WARR-2026-0042")
    equipment_brand: str = Field("Carrier", description="Manufacturer brand e.g. Carrier, Trane, Rheem, Lennox")
    model_number: str = Field(..., description="Factory equipment model number")
    serial_number: str = Field(..., description="Factory equipment serial number")
    install_date: str = Field(..., description="Installation completion date (YYYY-MM-DD)")
    warranty_duration_years: int = Field(10, description="Total warranty duration in years")
    coverage_scope: str = Field(
        "10-Year Parts & Compressor, 2-Year Labor Guarantee",
        description="Warranty coverage scope description",
    )
    contractor_license_number: str = Field(
        ...,
        description="State contractor license / master certification number",
    )
    epa_certification_number: str = Field(
        "EPA Section 608 Universal: EPA-608-49210",
        description="EPA Section 608 refrigerant handling certification number",
    )
    cpsc_safety_recall_status: str = Field(
        "CLEARED_NO_RECALLS",
        description="US Consumer Product Safety Commission recall clearinghouse status",
    )
    verification_qr_url: str = Field(
        ...,
        description="Official online deed verification QR URL",
    )
    customer_name: Optional[str] = Field("Property Owner of Record", description="Registered warranty beneficiary")
    property_address: Optional[str] = Field("Subject Real Property", description="Physical installation address")
    contractor_name: Optional[str] = Field(None, description="Installing contractor entity name")
    trade_type: Optional[str] = Field("HVAC", description="Trade category (HVAC, Plumbing, Electrical, Roofing)")
    issued_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="ISO timestamp of certificate issuance",
    )


class WarrantyResponse(BaseModel):
    """API response model for warranty generation actions."""
    status: str = Field("SUCCESS", description="Operation status code")
    certificate: WarrantyCertificate = Field(..., description="Generated warranty certificate document")
    message: str = Field(..., description="Human-readable confirmation message")
