from typing import List, Optional
from pydantic import BaseModel, Field


class XactimateLineItem(BaseModel):
    """Individual Xactimate standard line item with unit pricing and code justification."""
    item_code: str = Field(..., description="Xactimate pricing code (e.g., 'WTR DRY', 'RFG DRIP')")
    category: str = Field(..., description="Trade trade category (e.g., 'Water Extraction', 'Roofing Tear-Off')")
    description: str = Field(..., description="Scope of work description")
    quantity: float = Field(..., description="Measured quantity")
    unit: str = Field(..., description="Unit of measurement ('EA', 'SF', 'LF', 'DA', 'HR')")
    unit_price: float = Field(..., description="Regional unit price in USD")
    total_price: float = Field(..., description="Extended total price (quantity * unit_price)")
    code_justification: str = Field(..., description="Statutory building code or IICRC standard citation")


class InsuranceClaimSupplementReport(BaseModel):
    """Complete insurance claim supplement dossier with Xactimate line items and demand letter."""
    action_id: str
    claim_number: Optional[str] = None
    insurance_carrier: str = Field(default="State Farm", description="Insurance carrier name")
    policyholder_name: Optional[str] = None
    property_address: Optional[str] = None
    trade: str = "Water Mitigation"
    original_adjuster_amount: float = 0.0
    supplement_amount: float = 0.0
    total_claim_value: float = 0.0
    line_items: List[XactimateLineItem] = Field(default_factory=list)
    adjuster_demand_letter: str = ""
    code_citations: List[str] = Field(default_factory=list)
    status: str = Field(default="DRAFT", description="DRAFT, SUBMITTED, APPROVED")
    created_at: Optional[str] = None


class ClaimGenerateRequest(BaseModel):
    """Payload to trigger autonomous claim supplement calculation and demand letter generation."""
    insurance_carrier: str = Field(default="State Farm", description="Target insurance carrier")
    claim_number: Optional[str] = Field(None, description="Insurance claim file number")
    policyholder_name: Optional[str] = Field(None, description="Insured customer name")
    original_adjuster_amount: Optional[float] = Field(default=0.0, description="Initial carrier estimate or settlement amount")
