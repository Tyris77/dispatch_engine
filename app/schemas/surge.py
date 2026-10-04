from datetime import datetime, timezone
from typing import Any, Dict
from pydantic import BaseModel, Field


class SurgePricingAssessment(BaseModel):
    """Real-time dynamic surge and after-hours pricing evaluation."""
    is_surge_active: bool = Field(
        ...,
        description="Whether emergency surge or after-hours pricing is currently in effect",
    )
    surge_reason: str = Field(
        ...,
        description="Trigger factor: 'STANDARD_HOURS', 'AFTER_HOURS_WEEKEND', or 'SEVERE_WEATHER_SURGE'",
    )
    diagnostic_fee: float = Field(
        ...,
        description="Upfront on-site diagnostic dispatch fee in USD ($89 standard, $199 after-hours, $249 severe weather)",
    )
    labor_multiplier: float = Field(
        default=1.0,
        description="Labor billing multiplier (1.0x standard, 1.5x after-hours, 1.75x severe weather)",
    )
    surge_disclosure: str = Field(
        ...,
        description="Statutory transparent disclosure sentence for IVR voice greeting and SMS qualification",
    )
    rate_card: Dict[str, Any] = Field(
        default_factory=dict,
        description="Itemized comparison of standard vs active rates",
    )
    assessed_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="Timestamp when surge assessment was executed",
    )
