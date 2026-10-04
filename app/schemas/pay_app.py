from typing import List, Optional
from pydantic import BaseModel, Field


class ScheduleOfValuesItem(BaseModel):
    """Line item in AIA Document G703 Continuation Sheet / Schedule of Values."""
    item_number: str
    description: str
    scheduled_value: float = Field(..., ge=0)
    work_completed_previous: float = Field(default=0.0, ge=0)
    work_completed_this_period: float = Field(default=0.0, ge=0)
    materials_stored: float = Field(default=0.0, ge=0)
    total_completed_stored: float = Field(default=0.0, ge=0)
    percent_complete: float = Field(default=0.0, ge=0, le=100)
    balance_to_finish: float = Field(default=0.0)
    retainage_rate_pct: float = Field(default=10.0, ge=0, le=100)
    retainage_amount: float = Field(default=0.0, ge=0)


class AIAContractProgressPayment(BaseModel):
    """AIA Document G702 Application and Certificate for Payment summary."""
    application_number: int = Field(default=1, ge=1)
    period_to: str
    project_name: str
    contractor_name: str
    architect_name: str = "Studio Architecture & Engineering P.C."
    original_contract_sum: float = Field(..., ge=0)
    net_change_orders: float = Field(default=0.0)
    contract_sum_to_date: float = Field(..., ge=0)
    total_completed_stored: float = Field(..., ge=0)
    total_retainage: float = Field(..., ge=0)
    less_previous_certificates: float = Field(default=0.0, ge=0)
    current_payment_due: float = Field(..., ge=0)
    balance_to_finish_plus_retainage: float = Field(..., ge=0)
    line_items: List[ScheduleOfValuesItem] = Field(default_factory=list)


class PayAppGenerateRequest(BaseModel):
    """Payload to regenerate or adjust AIA G702 progress billing parameters."""
    progress_pct: float = Field(default=65.0, ge=0, le=100)
    retainage_pct: float = Field(default=10.0, ge=0, le=100)
    application_number: int = Field(default=1, ge=1)
    architect_name: Optional[str] = None
