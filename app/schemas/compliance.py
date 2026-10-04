from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class TradeLicenseRecord(BaseModel):
    """Verified state or federal professional trade contractor license."""
    license_type: str = Field(
        ...,
        description="License designation: VA_DPOR_CLASS_A, MD_MHIC_CONTRACTOR, DC_BBL_TRADE, EPA_608_UNIVERSAL, or MASTER_PLUMBER_STAMP",
    )
    license_number: str = Field(..., description="Official state board or regulatory registry license number")
    jurisdiction: str = Field(..., description="Issuing state or federal regulatory agency / jurisdiction")
    holder_name: str = Field(..., description="Licensed entity or Master Tradesman qualifier name")
    expiration_date: str = Field(..., description="License expiration date (YYYY-MM-DD)")
    status: str = Field(
        default="ACTIVE",
        description="License validity: ACTIVE, RENEWAL_DUE, or EXPIRED",
    )
    classification_scope: Optional[str] = Field(
        None,
        description="Statutory monetary limits and trade classifications (e.g. Commercial General Building / HVAC)",
    )
    verification_authority: Optional[str] = Field(
        None,
        description="Verification portal or issuing board name",
    )


class RegulatoryCompliancePacket(BaseModel):
    """Comprehensive commercial contractor compliance submittal packet."""
    contractor_legal_name: str = Field(..., description="Full legal corporate entity name")
    verified_licenses: List[TradeLicenseRecord] = Field(
        default_factory=list,
        description="Verified state and trade licenses in good standing",
    )
    active_coi: Dict[str, Any] = Field(
        default_factory=dict,
        description="Audited ACORD 25 Certificate of Insurance limits ($1M/$2M, statutory workers' comp)",
    )
    osha_safety_score: float = Field(
        default=98.5,
        ge=0.0,
        le=100.0,
        description="OSHA jobsite safety compliance index score (0-100)",
    )
    verification_qr_url: str = Field(
        ...,
        description="Public or authenticated QR validation URL to verify standing",
    )
    standing_status: str = Field(
        default="GOOD_STANDING",
        description="Regulatory standing status: GOOD_STANDING, CONDITIONAL, or SUSPENDED",
    )
    surety_bond_amount: float = Field(
        default=50000.0,
        ge=0.0,
        description="Commercial surety bonding coverage amount",
    )
    generated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        description="Timestamp when compliance packet was compiled",
    )
