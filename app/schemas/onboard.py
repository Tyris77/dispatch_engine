import re
from typing import Dict, Optional
from pydantic import BaseModel, Field, field_validator


class OnboardRequest(BaseModel):
    """Payload submitted by prospective contractor to self-serve onboard and activate."""
    company_name: str = Field(
        ...,
        min_length=2,
        max_length=100,
        description="Legal or trade business name (e.g. Apex Mechanical Services)",
    )
    trade: str = Field(
        default="plumbing",
        description="Primary trade specialty: plumbing, hvac, roofing, water_mitigation, electrical, general",
    )
    service_area: str = Field(
        default="Washington, DC / Northern VA / Montgomery County",
        min_length=2,
        max_length=200,
        description="Primary operating service region and surrounding counties",
    )
    on_call_phone: str = Field(
        ...,
        description="Direct mobile number for on-call emergency technician dispatch alerts",
    )
    owner_email: str = Field(
        ...,
        description="Executive email for daily triage dossiers, billing, and system notifications",
    )
    owner_name: Optional[str] = Field(
        default=None,
        description="Name of the business owner or lead dispatcher",
    )
    area_code_preference: Optional[str] = Field(
        default="202",
        description="Preferred local area code for call-forwarding number (e.g. 202, 703, 240)",
    )
    stripe_session_id: Optional[str] = Field(
        default=None,
        description="Optional Stripe checkout session ID if activating from paid landing flow",
    )

    @field_validator("company_name")
    @classmethod
    def validate_company_name(cls, v: str) -> str:
        cleaned = v.strip()
        if len(cleaned) < 2:
            raise ValueError("Company name must contain at least 2 characters")
        return cleaned

    @field_validator("owner_email")
    @classmethod
    def validate_owner_email(cls, v: str) -> str:
        clean = v.strip().lower()
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", clean):
            raise ValueError("Invalid email address format")
        return clean

    @field_validator("on_call_phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        digits = re.sub(r"[^\d+]", "", v)
        if digits.startswith("+"):
            raw = digits[1:]
        else:
            raw = digits

        if len(raw) == 10:
            return f"+1{raw}"
        elif len(raw) == 11 and raw.startswith("1"):
            return f"+{raw}"
        elif len(raw) >= 11:
            return f"+{raw}"
        else:
            raise ValueError("Phone number must contain at least 10 valid digits")

    @field_validator("trade")
    @classmethod
    def normalize_trade(cls, v: str) -> str:
        trade_clean = v.strip().lower().replace(" ", "_").replace("-", "_")
        allowed = {"plumbing", "hvac", "roofing", "water_mitigation", "electrical", "general"}
        if trade_clean not in allowed:
            # Map common variations or fallback to general
            if "plumb" in trade_clean:
                return "plumbing"
            elif "air" in trade_clean or "heat" in trade_clean or "ac" in trade_clean:
                return "hvac"
            elif "roof" in trade_clean:
                return "roofing"
            elif "water" in trade_clean or "flood" in trade_clean or "mitigat" in trade_clean:
                return "water_mitigation"
            elif "electr" in trade_clean:
                return "electrical"
            return "general"
        return trade_clean


class OnboardResponse(BaseModel):
    """Output returned upon successful automated tenant provisioning and dispatcher activation."""
    tenant_slug: str = Field(..., description="Unique URL slug assigned to the contractor")
    tenant_id: str = Field(..., description="UUID primary key of the new Tenant entity")
    forwarding_phone_number: str = Field(..., description="Dedicated AI voice answering phone number")
    widget_script_tag: str = Field(..., description="Copy-paste HTML script tag for the embeddable chat widget")
    portal_url: str = Field(..., description="Deep-link URL to customer self-service booking portal")
    dashboard_url: str = Field(..., description="Deep-link URL to contractor operations console")
    status: str = Field(default="ACTIVE", description="Account provisioning status")
    carrier_forwarding_instructions: Dict[str, str] = Field(
        ...,
        description="One-tap star codes to forward office lines by mobile carrier (Verizon, AT&T, T-Mobile)",
    )
