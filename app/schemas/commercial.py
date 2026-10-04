from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class PropertyPortfolio(BaseModel):
    """Represents a commercial real estate property, multi-family building, or HOA portfolio."""
    portfolio_id: str = Field(..., description="Unique identifier for the property/portfolio")
    property_name: str = Field(..., description="Name of the commercial building or community")
    property_address: str = Field(..., description="Physical street address, city, state, and zip")
    unit_count: int = Field(default=1, ge=1, description="Total number of tenant units in the portfolio")
    manager_name: str = Field(..., description="Assigned property manager or facilities director")
    manager_phone: str = Field(..., description="Property manager phone number for 1-tap SMS approvals")
    manager_email: str = Field(..., description="Property manager official contact email")
    auto_approval_threshold: float = Field(
        default=500.0,
        ge=0.0,
        description="Dollar cap under which work orders are automatically approved without manual signoff",
    )


class CommercialWorkOrder(BaseModel):
    """Commercial tenant maintenance or repair work order with cost estimation and approval status."""
    order_id: str = Field(..., description="Unique commercial work order reference (e.g. WO-70492)")
    property_name: str = Field(..., description="Commercial building name")
    unit_number: str = Field(..., description="Suite or unit number")
    tenant_name: str = Field(..., description="Commercial occupant or residential tenant name")
    issue_description: str = Field(..., description="Reported maintenance issue or symptom")
    estimated_cost: float = Field(..., ge=0.0, description="Estimated labor and materials repair cost")
    approval_status: str = Field(
        default="PENDING_PM_APPROVAL",
        description="Approval state: APPROVED_AUTO, PENDING_PM_APPROVAL, APPROVED_BY_PM, or COMPLETED",
    )
    action_id: str = Field(..., description="Linked LeadAction UUID string")
    portfolio_id: Optional[str] = Field(None, description="Linked PropertyPortfolio ID")
    manager_name: Optional[str] = Field(None, description="Approving manager name")
    approval_link: Optional[str] = Field(None, description="1-tap approval URL link")
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="Timestamp when work order was created",
    )
    completed_at: Optional[str] = Field(None, description="Timestamp when work order was completed")


class ConsolidatedMonthlyStatement(BaseModel):
    """Consolidated end-of-month commercial invoicing statement with Net 30 terms."""
    statement_id: str = Field(..., description="Unique statement reference (e.g. STM-2026-10-881)")
    billing_period: str = Field(..., description="Billing cycle month and year (e.g. October 2026)")
    itemized_orders: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Itemized list of completed work order dictionary records",
    )
    total_billed: float = Field(default=0.0, ge=0.0, description="Total aggregated amount due")
    payment_terms: str = Field(default="NET_30", description="Corporate payment terms")
    portfolio_id: Optional[str] = Field(None, description="Portfolio ID")
    portfolio_name: Optional[str] = Field(None, description="Property/Portfolio name")
    property_address: Optional[str] = Field(None, description="Billing address")
    manager_name: Optional[str] = Field(None, description="Property manager recipient")
    due_date: Optional[str] = Field(None, description="Due date under payment terms")
    generated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        description="Generation timestamp",
    )


class CommercialTenantRequestSubmission(BaseModel):
    """Submission payload for new commercial tenant work order requests."""
    portfolio_id: str
    unit_number: str
    tenant_name: str
    issue_description: str
