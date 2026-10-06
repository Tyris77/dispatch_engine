from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class DripLeadStatus(str, Enum):
    CONTACTED = "CONTACTED"
    FOLLOWUP_1_DUE = "FOLLOWUP_1_DUE"
    FOLLOWUP_2_DUE = "FOLLOWUP_2_DUE"
    REPLIED = "REPLIED"
    CLOSED = "CLOSED"


class DripContractorLead(BaseModel):
    """Profile of a B2B contractor lead enrolled in territory drip campaign."""
    contractor_id: str
    company_name: str
    trade: str
    contact_name: str
    contact_email: str
    phone: str
    territory: str
    status: DripLeadStatus = Field(default=DripLeadStatus.CONTACTED)
    initial_contact_at: str
    followup_1_due_at: Optional[str] = None
    followup_2_due_at: Optional[str] = None
    followup_1_sent_at: Optional[str] = None
    followup_2_sent_at: Optional[str] = None
    missed_calls_est: int = 35
    revenue_leak_est: float = 42000.0
    audit_url: str = "/audit"
    onboard_url: str = "/onboard"
    last_touch_subject: Optional[str] = None
    last_touch_body: Optional[str] = None
    notes: Optional[str] = None


class DripCampaignStatus(BaseModel):
    """Aggregate telemetry of B2B drip pipeline."""
    total_enrolled: int = 0
    contacted: int = 0
    followup_1_due: int = 0
    followup_2_due: int = 0
    replied: int = 0
    closed: int = 0
    leads: List[DripContractorLead] = Field(default_factory=list)
    last_evaluated_at: Optional[str] = None


class DripTriggerResponse(BaseModel):
    """Outcome of an autonomous or manual follow-up drip evaluation cycle."""
    status: str = "COMPLETED"
    evaluated_count: int = 0
    followups_dispatched: int = 0
    messages_sent: List[Dict[str, Any]] = Field(default_factory=list)
    timestamp: str = ""
