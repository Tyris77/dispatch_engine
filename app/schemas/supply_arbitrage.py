from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class DistributorQuote(BaseModel):
    """Comparative wholesale quote from a specific trade supply house branch."""
    distributor_name: str = Field(..., description="Wholesale distributor name (e.g. Ferguson Supply, Johnstone Supply)")
    branch_address: str = Field(..., description="Physical will-call branch address")
    in_stock: bool = Field(default=True, description="Whether all requested line items are in-stock at branch")
    line_items_cost: float = Field(..., description="Wholesale materials total for matched line items")
    total_material_cost: float = Field(..., description="Total will-call cost including local sales tax & fees")
    potential_savings: float = Field(default=0.0, description="Cost savings vs highest-cost distributor in dollars")
    branch_phone: str = Field(default="+17035550118", description="Will-call counter phone number")
    branch_hours: str = Field(default="6:00 AM - 5:00 PM (M-F)", description="Counter operating hours")
    will_call_nav_link: str = Field(default="", description="Turn-by-turn navigation link to distributor counter")


class SupplyArbitrageComparison(BaseModel):
    """Multi-distributor pricing matrix and margin lift analysis for a job's parts list."""
    action_id: str = Field(..., description="Associated LeadAction UUID string")
    parts_required: List[str] = Field(default_factory=list, description="List of required parts/materials")
    quotes: List[DistributorQuote] = Field(default_factory=list, description="Distributor branch price quotes")
    recommended_distributor: str = Field(..., description="Best value distributor with immediate stock availability")
    max_savings_dollars: float = Field(default=0.0, description="Maximum potential wholesale cost reduction")
    current_distributor: str = Field(default="Ferguson Supply", description="Currently selected PO distributor")
    generated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        description="Timestamp of comparison matrix generation",
    )
