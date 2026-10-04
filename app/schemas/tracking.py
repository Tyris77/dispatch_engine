from typing import List, Optional
from pydantic import BaseModel, Field


class TechnicianInfo(BaseModel):
    """Profile of the dispatched technician."""
    name: str = Field(..., description="Technician full name")
    phone: Optional[str] = Field(None, description="Contact phone number")
    role: str = Field(default="Lead Emergency Technician", description="Job title / role")
    truck_number: Optional[str] = Field(default="Truck #14", description="Vehicle identifier")
    certifications: List[str] = Field(
        default_factory=lambda: ["EPA Universal", "NATE Certified", "Master Specialist"],
        description="Technician industry licenses and credentials",
    )
    photo_url: Optional[str] = Field(None, description="Avatar image URL")
    rating: float = Field(default=4.98, description="Customer satisfaction rating")


class EntryNoteSubmission(BaseModel):
    """Payload when a homeowner submits gate codes, access notes, or parking instructions."""
    notes: str = Field(..., min_length=1, max_length=1000, description="Gate code, dog warning, parking instructions")
    sender_name: Optional[str] = Field(None, description="Homeowner name")


class TrackingStatusUpdate(BaseModel):
    """Payload to advance tracking status."""
    status: str = Field(..., description="DISPATCHED, EN_ROUTE, ON_SITE, or COMPLETED")
    eta_minutes: Optional[int] = Field(None, ge=0, description="Updated ETA minutes")


class TrackingViewResponse(BaseModel):
    """Structured response for live technician ETA tracker."""
    action_id: str
    tenant_name: str
    tenant_phone: Optional[str] = None
    status: str = Field(default="EN_ROUTE", description="Current dispatch status")
    eta_minutes: int = Field(default=18, description="Estimated arrival time in minutes")
    technician: TechnicianInfo
    equipment_brand: Optional[str] = None
    equipment_model: Optional[str] = None
    equipment_type: Optional[str] = None
    parts_packed: List[str] = Field(default_factory=list)
    notes: List[str] = Field(default_factory=list)
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
