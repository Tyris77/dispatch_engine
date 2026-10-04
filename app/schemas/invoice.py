from datetime import datetime
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field


class InvoiceLineItem(BaseModel):
    """Itemized line item within a contractor job invoice."""
    description: str = Field(..., description="Description of service, equipment, or credit")
    amount: float = Field(..., description="Amount in USD (can be negative for credits/discounts)")


class JobInvoice(BaseModel):
    """Full post-job invoice and receipt model for homeowner text-to-pay."""
    invoice_number: str = Field(..., description="Unique human-readable invoice code (e.g. 'INV-2026-0042')")
    action_id: str = Field(default="", description="LeadAction UUID string")
    tenant_name: str = Field(default="Contractor Services", description="Contractor company name")
    tenant_slug: str = Field(default="", description="Tenant unique slug")
    contractor_name: Optional[str] = Field(None, description="Contractor / company name")
    license_number: Optional[str] = Field(None, description="Trade license number")
    trade: Optional[str] = Field(None, description="Trade category (HVAC, Plumbing, etc.)")
    customer_name: str = Field(default="Homeowner", description="Customer full name")
    customer_phone: str = Field(default="", description="Customer contact phone")
    service_address: Optional[str] = Field(None, description="Customer or job location")
    selected_tier: str = Field(default="Standard Service", description="Accepted proposal option tier")
    line_items: List[Union[InvoiceLineItem, Dict[str, Any]]] = Field(default_factory=list, description="Itemized billing breakdown")
    contract_total: float = Field(default=0.0, ge=0.0, description="Gross contract or service amount before credits")
    deposit_credited: float = Field(default=0.0, ge=0.0, description="Upfront deposit previously paid & credited")
    balance_due: float = Field(default=0.0, ge=0.0, description="Net remaining balance payable by customer")
    payment_status: str = Field(default="PENDING", description="'PENDING', 'PAID', or 'FAILED'")
    before_photo_url: Optional[str] = Field(None, description="URL of initial diagnostic equipment scan")
    after_photo_url: Optional[str] = Field(None, description="URL of technician completed repair photo")
    paid_at: Optional[str] = Field(None, description="ISO timestamp when balance was settled")
    transaction_id: Optional[str] = Field(None, description="Payment processor transaction ID (e.g. Stripe pi_...)")
    payment_method: Optional[str] = Field(None, description="Payment method used (e.g. 'card', 'apple_pay')")
    technician_notes: Optional[str] = Field(None, description="Technician completion notes or warranty sign-off")
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


class InvoiceCompleteSubmission(BaseModel):
    """Payload submitted when technician marks a job finished with an after-photo."""
    after_photo_url: Optional[str] = Field(None, description="Direct URL or data URL of completed work photo")
    technician_notes: Optional[str] = Field(None, description="Technician completion observations")


class InvoicePaymentSubmission(BaseModel):
    """Payload submitted when customer pays invoice balance via Text-to-Pay portal."""
    payment_method: str = Field(default="card", description="'card', 'apple_pay', or 'google_pay'")
    payment_intent_id: Optional[str] = Field(None, description="Optional Stripe PaymentIntent ID")
    customer_name: Optional[str] = Field(None, description="Name on card or digital wallet")
    tip_amount: Optional[float] = Field(default=0.0, description="Optional tip amount")

