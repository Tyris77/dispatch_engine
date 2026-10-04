from typing import Optional
from pydantic import BaseModel, Field


class WidgetChatRequest(BaseModel):
    """Payload sent from the embeddable customer website widget."""
    message: str = Field(..., min_length=1, description="Customer inquiry or problem description")
    sender_phone: Optional[str] = Field(None, description="Optional callback phone number provided by user")
    sender_name: Optional[str] = Field(None, description="Optional name of the user")
    language: Optional[str] = Field("en", description="Optional language preference")


class WidgetChatResponse(BaseModel):
    """Response returned to the embeddable website widget chat interface."""
    response_text: str = Field(..., description="AI conversational reply")
    intent_level: str = Field(..., description="Categorized intent level (EMERGENCY, HIGH, MEDIUM, LOW, SPAM)")
    qualification_score: float = Field(..., description="Qualification confidence score (0.0 to 1.0)")
    action_id: Optional[str] = Field(None, description="Created LeadAction UUID if dispatched")
    tracking_url: Optional[str] = Field(None, description="Live technician tracking URL if emergency dispatched")
    intake_url: Optional[str] = Field(None, description="Direct link to camera equipment photo scanner")
    is_emergency: bool = Field(False, description="Whether the request triggered emergency dispatch")


class WidgetLeadRequest(BaseModel):
    """Flexible inbound lead submission from website widget, forms, or API callers."""
    tenant_slug: Optional[str] = Field(None, description="Target contractor tenant slug")
    message: Optional[str] = Field(None, description="Customer message or emergency description")
    notes: Optional[str] = Field(None, description="Alternative field for message or notes")
    service_needed: Optional[str] = Field(None, description="Requested trade or service")
    name: Optional[str] = Field(None, description="Customer name")
    sender_name: Optional[str] = Field(None, description="Alternative field for name")
    phone: Optional[str] = Field(None, description="Customer callback phone number")
    sender_phone: Optional[str] = Field(None, description="Alternative field for phone")
    email: Optional[str] = Field(None, description="Customer email address")
    address: Optional[str] = Field(None, description="Customer service address")
    language: Optional[str] = Field("en", description="Language preference")

