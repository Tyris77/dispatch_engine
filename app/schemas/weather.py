from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field


class WeatherAlert(BaseModel):
    """Active or imminent severe meteorological hazard alert."""
    alert_id: str = Field(..., description="Unique alert identifier (e.g. 'ALERT-2026-FREEZE-01')")
    event_title: str = Field(..., description="e.g. 'Severe Freeze Warning', 'Severe Thunderstorm / High Wind Alert', 'Extreme Heat Advisory'")
    severity: str = Field(default="WARNING", description="'WARNING', 'WATCH', or 'ADVISORY'")
    trade_category: str = Field(..., description="Primary affected trade: 'Plumbing', 'Roofing', 'HVAC'")
    affected_counties: List[str] = Field(default_factory=list, description="Counties and metro regions under alert")
    metric_detail: str = Field(..., description="Critical telemetry metric (e.g. '14°F Low / 36 hrs Sub-Freezing', '60+ mph Gusts & Hail')")
    safety_guidance: str = Field(..., description="Actionable homeowner preventative instructions")
    issued_at: str = Field(default_factory=lambda: datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"))
    expires_at: Optional[str] = Field(None, description="Expiration timestamp of the alert")


class WeatherBroadcastRequest(BaseModel):
    """Payload to trigger proactive emergency preparedness SMS blast."""
    alert_id: str = Field(..., description="Alert identifier to broadcast")
    trade_category: str = Field(default="Plumbing", description="'Plumbing', 'Roofing', or 'HVAC'")
    custom_note: Optional[str] = Field(None, description="Optional custom contractor note to append to the SMS")


class WeatherBroadcastResponse(BaseModel):
    """Results of proactive weather alert broadcast."""
    alert_id: str = Field(..., description="Associated alert ID")
    trade_category: str = Field(..., description="Target trade category")
    recipients_contacted: int = Field(..., description="Number of customer contacts SMS was dispatched to")
    status: str = Field(default="DISPATCHED", description="'DISPATCHED', 'SIMULATED', or 'FAILED'")
    sample_message: str = Field(..., description="Sample SMS message dispatched to homeowners")
    broadcast_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
