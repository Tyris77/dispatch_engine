from datetime import datetime, timezone
from typing import Optional
from pydantic import BaseModel, Field


class CertificateOfInsurance(BaseModel):
    """Commercial ACORD 25 Certificate of Insurance (COI) audit record."""
    coi_id: str = Field(..., description="Unique certificate identifier e.g. COI-2026-0412")
    insurer_name: str = Field(..., description="Carrier/Underwriter name e.g. Travelers, Hartford, Liberty Mutual")
    insured_entity: str = Field(..., description="Named insured trade contractor entity")
    general_liability_each_occurrence: float = Field(
        ...,
        description="Commercial General Liability per-occurrence limit (typically >= $1,000,000)",
    )
    general_aggregate_limit: float = Field(
        ...,
        description="General Aggregate limit (typically >= $2,000,000)",
    )
    workers_comp_statutory: bool = Field(
        default=True,
        description="Whether statutory Workers' Compensation limits are active",
    )
    policy_expiration_date: str = Field(
        ...,
        description="Expiration date formatted as YYYY-MM-DD",
    )
    additional_insured_verified: bool = Field(
        default=True,
        description="Whether client or property owner is endorsed as Additional Insured",
    )
    compliance_status: str = Field(
        default="ACTIVE_COMPLIANT",
        description="'ACTIVE_COMPLIANT', 'EXPIRED', or 'DEFICIENT_LIMITS'",
    )
    days_until_expiration: int = Field(
        ...,
        description="Days remaining before policy expiration",
    )
    coverage_summary: Optional[str] = Field(
        None,
        description="Human-readable coverage certification summary",
    )
    verified_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="Timestamp of ACORD audit",
    )


class COIUploadResponse(BaseModel):
    """Response returned upon uploading and auditing an ACORD document."""
    status: str = Field(default="SUCCESS", description="Audit status")
    coi: CertificateOfInsurance = Field(..., description="Audited COI record")
    message: str = Field(default="Certificate of Insurance verified successfully.")
