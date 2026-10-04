from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class LienWaiverDocument(BaseModel):
    """Statutory mechanic's lien waiver and unconditional release document."""
    waiver_number: str = Field(..., description="Unique legal waiver reference (e.g. 'LIEN-2026-0081')")
    action_id: str = Field(..., description="Associated LeadAction UUID")
    waiver_type: str = Field(default="FINAL_UNCONDITIONAL_RELEASE", description="'FINAL_UNCONDITIONAL_RELEASE' or 'PROGRESS_PAYMENT'")
    property_address: str = Field(..., description="Physical real property location being released from lien claims")
    customer_name: str = Field(..., description="Property owner or authorized customer name")
    amount_waived: float = Field(..., ge=0.0, description="Exact dollar amount released and satisfied in USD")
    statutory_jurisdiction: str = Field(..., description="'DC', 'VA', 'MD', or 'US_STANDARD'")
    legal_code_citation: str = Field(..., description="Binding municipal statutory code citation for mechanic's lien release")
    contractor_company_name: str = Field(..., description="Licensed prime contractor legal entity name")
    contractor_license_number: str = Field(..., description="State/district trade contractor license number")
    claimant_officer_name: str = Field(default="Authorized Managing Officer", description="Signing contractor executive officer")
    status: str = Field(default="EXECUTED", description="'EXECUTED' or 'PENDING_SIGNATURE'")
    release_text: Optional[str] = Field(None, description="Full binding legal release verbiage")
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
