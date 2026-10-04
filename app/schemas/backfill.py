from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class BackfillCandidate(BaseModel):
    """A qualified customer or pending estimate lead situated within the same geographic corridor."""
    action_id: str = Field(..., description="LeadAction UUID string")
    customer_name: str = Field(..., description="Customer full name")
    phone: str = Field(..., description="Contact phone for SMS broadcast offer")
    address: str = Field(..., description="Service street address")
    corridor: str = Field(..., description="Geographic corridor (e.g. 'Arlington / Alexandria Corridor')")
    service_needed: str = Field(..., description="Trade or service category requested")
    distance_miles: float = Field(default=2.4, description="Estimated distance from technician's cancelled stop")
    discount_amount: float = Field(default=50.0, description="Instant route credit / same-day incentive in dollars")


class BackfillBroadcastResult(BaseModel):
    """Results from an automated cancellation slot broadcast to nearby corridor leads."""
    canceled_action_id: str = Field(..., description="UUID of the appointment that was cancelled")
    original_slot_time: str = Field(..., description="Original arrival window (e.g. 'Today 2:00 PM - 4:00 PM')")
    candidates_contacted: int = Field(default=0, description="Number of corridor leads sent SMS broadcast")
    claimed_by_name: Optional[str] = Field(None, description="Name of customer who claimed the slot, if backfilled")
    status: str = Field(
        default="BROADCAST_SENT",
        description="Status: BROADCAST_SENT, SLOT_BACKFILLED, or EXPIRED",
    )
    candidates: List[BackfillCandidate] = Field(
        default_factory=list,
        description="List of corridor candidate leads identified",
    )
    recovered_revenue: float = Field(
        default=0.0,
        description="Estimated gross billable value preserved by filling the technician's gap",
    )
    broadcast_message: str = Field(
        default="",
        description="SMS copy transmitted to candidate homeowners",
    )
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="Timestamp of broadcast dispatch",
    )
