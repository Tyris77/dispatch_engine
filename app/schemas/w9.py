from typing import Optional
from pydantic import BaseModel, Field

TAX_CLASSIFICATIONS = (
    "INDIVIDUAL_SOLE_PROPRIETOR",
    "C_CORP",
    "S_CORP",
    "PARTNERSHIP",
    "LLC",
)


class W9FormSubmission(BaseModel):
    """Digital IRS Form W-9 submission from a subcontractor crew."""
    crew_name: str
    foreman_name: str
    business_legal_name: str
    federal_tax_classification: str = Field(
        ..., description="INDIVIDUAL_SOLE_PROPRIETOR, C_CORP, S_CORP, PARTNERSHIP or LLC"
    )
    address: str
    ein_or_ssn: str
    signature_base64: str


class W9CertificationRecord(BaseModel):
    """Stored certification record. The full TIN is never persisted or returned."""
    w9_id: str
    crew_name: str
    tax_classification: str
    tin_masked: str
    signed_at: str
    status: str = "VERIFIED_ON_FILE"


class W9RequestPayload(BaseModel):
    """API payload to text a W-9 request link to a crew foreman."""
    tenant_slug: str
    crew_name: str
    foreman_phone: str
    note: Optional[str] = None
