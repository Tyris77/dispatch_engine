from typing import Optional
from pydantic import BaseModel, Field


class LienNoticeDocument(BaseModel):
    """Statutory Preliminary Notice to Owner or Notice of Intent to Claim a Mechanic's Lien."""
    notice_number: str = Field(..., description="Unique legal notice reference number e.g. NTO-2026-0814")
    notice_type: str = Field(
        "NOTICE_OF_INTENT_TO_LIEN",
        description="Statutory notice category: PRELIMINARY_NOTICE_TO_OWNER or NOTICE_OF_INTENT_TO_LIEN",
    )
    property_address: str = Field(..., description="Physical street address of improved real property")
    customer_name: str = Field(..., description="Property owner or primary customer of record")
    overdue_balance: float = Field(..., description="Delinquent principal balance due and unpaid in USD")
    days_overdue: int = Field(..., description="Number of days elapsed since completion/invoice due date")
    statutory_deadline_date: str = Field(..., description="Calendar date of statutory lien filing expiration (YYYY-MM-DD)")
    statutory_citation: str = Field(..., description="Exact state law statute citation e.g. Md. Real Prop. Code § 9-104")
    certified_mail_tracking: str = Field(..., description="USPS Certified Mail tracking article number")
    statutory_warning_text: str = Field(..., description="Formal legal warning text mandated by jurisdiction")
    claimant_name: str = Field(..., description="Contractor trade business entity asserting claim")
    jurisdiction: str = Field(..., description="Governing state or municipal jurisdiction e.g. MD, VA, DC")
    issued_at: str = Field(..., description="ISO timestamp of notice generation")


class LienNoticeResponse(BaseModel):
    """API response model for generated statutory lien notice."""
    status: str = Field(..., description="Operation status: SUCCESS or FAILED")
    notice: LienNoticeDocument = Field(..., description="Generated legal notice document")
    message: str = Field(..., description="Human-readable summary message")
