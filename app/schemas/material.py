from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class PurchaseOrderItem(BaseModel):
    """Line item for a required part, material, or tool in a purchase order."""
    part_name: str = Field(..., description="Description or part number of wholesale material")
    quantity: int = Field(default=1, ge=1, description="Quantity required")
    estimated_unit_cost: float = Field(..., ge=0.0, description="Estimated wholesale unit price in USD")
    line_total: float = Field(..., ge=0.0, description="Total cost for this part line item (qty * unit cost)")


class PurchaseOrder(BaseModel):
    """Will-call material purchase order for supply house counter pickup."""
    po_number: str = Field(..., description="Unique human-readable PO number (e.g. 'PO-2026-0104')")
    action_id: str = Field(default="", description="Associated LeadAction UUID")
    supplier_name: str = Field(..., description="Supply house name (e.g. 'Ferguson Plumbing Supply', 'Johnstone Supply')")
    supplier_branch: Optional[str] = Field(None, description="Specific local distributor branch identifier")
    items: List[PurchaseOrderItem] = Field(default_factory=list, description="Itemized bill of materials")
    total_material_cost: float = Field(default=0.0, ge=0.0, description="Total wholesale materials cost in USD")
    pickup_address: str = Field(..., description="Physical address of the supply house will-call counter")
    nav_link: str = Field(..., description="Google Maps turn-by-turn driving directions URL")
    status: str = Field(default="DRAFT", description="'DRAFT', 'ORDERED', 'READY_FOR_PICKUP', or 'FULFILLED'")
    customer_name: Optional[str] = Field(None, description="Customer or job name for will-call boxing")
    customer_phone: Optional[str] = Field(None, description="Customer contact phone")
    service_address: Optional[str] = Field(None, description="Job site address")
    equipment_summary: Optional[str] = Field(None, description="Equipment make/model being repaired")
    ordered_at: Optional[str] = Field(None, description="ISO timestamp when PO was sent to distributor")
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


class JobProfitability(BaseModel):
    """Real-time job profitability and gross margin analysis."""
    contract_revenue: float = Field(..., ge=0.0, description="Gross revenue billed to customer")
    material_costs: float = Field(..., ge=0.0, description="Total wholesale cost of required parts")
    estimated_labor_cost: float = Field(..., ge=0.0, description="Estimated technician labor burden")
    net_profit: float = Field(..., description="Net gross profit (revenue - materials - labor)")
    margin_percentage: float = Field(..., description="Gross margin percentage (net_profit / revenue * 100)")
    margin_tier: str = Field(default="HEALTHY", description="'EXCELLENT', 'HEALTHY', or 'LOW'")
