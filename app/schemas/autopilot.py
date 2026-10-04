from typing import List, Optional
from pydantic import BaseModel, Field


class AutopilotTaskLog(BaseModel):
    """Execution telemetry record for an autonomous cycle task."""
    task_name: str
    executed_at: str
    items_processed: int = 0
    status: str = Field(default="SUCCESS", description="SUCCESS, SKIPPED, ERROR")
    details: str = ""


class AutopilotStatusReport(BaseModel):
    """Structured telemetry report of the 24/7 autonomous worker status."""
    is_running: bool = True
    last_cycle_time: str = ""
    active_tasks: List[str] = Field(default_factory=list)
    recent_logs: List[AutopilotTaskLog] = Field(default_factory=list)
    next_scheduled_run: str = ""


class AutonomousOutreachTarget(BaseModel):
    """Local trade contractor business target discovered for zero-touch partner growth."""
    company_name: str
    trade: str
    contact_email: str
    city: str
    status: str = Field(default="DISCOVERED", description="DISCOVERED, QUEUED, SENT")


class AutopilotRunNowResponse(BaseModel):
    """Response returned upon operator-triggered immediate cycle execution."""
    status: str = "CYCLE_EXECUTED"
    cycle_status: str = "COMPLETED"
    executed_tasks: int = 0
    total_tasks_run: int = 0
    total_items_processed: int = 0
    logs: List[AutopilotTaskLog] = Field(default_factory=list)

