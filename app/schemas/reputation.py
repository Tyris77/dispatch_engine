import datetime
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field


class ReviewRatingSubmission(BaseModel):
    """Payload submitted when customer replies with a rating or submits review form."""
    rating: int = Field(
        ...,
        ge=1,
        le=5,
        description="Customer satisfaction rating between 1 and 5 stars",
    )
    feedback: Optional[str] = Field(
        default=None,
        description="Optional customer explanation or comment",
    )
    customer_phone: Optional[str] = Field(
        default=None,
        description="Callback phone number of the customer submitting feedback",
    )


class ReviewOutcome(BaseModel):
    """Structured outcome from the 5-Star Booster & Shield engine."""
    status: str = Field(
        ...,
        description="'BOOST_SENT' for 4-5 stars, or 'NEGATIVE_INSULATED' for 1-3 stars",
    )
    rating: int
    feedback: Optional[str] = None
    customer_reply: str = Field(
        ...,
        description="SMS text message sent back to the homeowner",
    )
    owner_alert: Optional[str] = Field(
        default=None,
        description="Urgent escalation SMS sent to the contractor owner if shielded",
    )
    google_review_url: Optional[str] = None
    resolved_at: str = Field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()
    )


class ReviewRequestTriggerResponse(BaseModel):
    """Response returned when a review sequence is triggered for a lead."""
    action_id: str
    tenant_slug: str
    status: str
    sms_sent: bool
    customer_phone: Optional[str] = None
