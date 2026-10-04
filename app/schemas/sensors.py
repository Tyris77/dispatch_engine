from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class SensorAlertPayload(BaseModel):
    """Payload received from smart home water shutoff, flow meter, or freeze sensor."""
    sensor_id: str = Field(..., description="Unique hardware MAC or device serial (e.g. FLUME-88210-BURST)")
    sensor_type: str = Field(
        ...,
        description="Sensor type: WATER_LEAK_DETECTOR, FREEZE_TEMP_SENSOR, or FLOW_BURST_ALARM",
    )
    property_address: str = Field(..., description="Monitored property street address, city, state, zip")
    customer_name: str = Field(..., description="Homeowner or property contact name")
    customer_phone: str = Field(..., description="Homeowner telephone for automated emergency voice alert")
    reading_value: str = Field(..., description="Telemetry reading value (e.g. '8.2 GPM burst', '28.5°F ambient')")
    severity: str = Field(
        default="CRITICAL_EMERGENCY",
        description="Severity level: CRITICAL_EMERGENCY or WARNING",
    )
    tenant_slug: Optional[str] = Field(None, description="Optional tenant slug target")
    tenant_id: Optional[str] = Field(None, description="Optional tenant UUID string")
    water_shutoff_actuated: Optional[bool] = Field(False, description="Whether automatic shutoff valve has actuated")


class SensorAlertResponse(BaseModel):
    """Response returned upon automated emergency sensor triage and technician cascade."""
    action_id: str = Field(..., description="Created emergency LeadAction UUID string")
    dispatch_status: str = Field(..., description="Dispatch routing status (e.g. DISPATCHED, SCHEDULED)")
    call_triggered: bool = Field(..., description="True if automated outbound emergency call was placed to homeowner")
    tech_alerted: str = Field(..., description="Name of on-call emergency technician dispatched")
    message: str = Field(default="Emergency sensor alert triaged and dispatched successfully")


class ConnectedSensorDevice(BaseModel):
    """Telemetry representation of a registered smart home water shutoff or freeze device."""
    sensor_id: str = Field(..., description="Device serial number")
    sensor_type: str = Field(..., description="Sensor hardware category")
    brand_model: str = Field(..., description="Manufacturer hardware model (e.g. Moen Flo Smart Shutoff, Flume 2)")
    property_name: str = Field(..., description="Customer or property label")
    property_address: str = Field(..., description="Physical installation address")
    current_reading: str = Field(..., description="Latest real-time sensor metric")
    battery_level: int = Field(default=98, description="Battery percentage (0-100)")
    last_heartbeat: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        description="Last verified telemetry check-in",
    )
    status: str = Field(default="ONLINE_NORMAL", description="ONLINE_NORMAL, WARNING, or ALARM_BURST")
