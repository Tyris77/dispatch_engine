import uuid
from datetime import datetime
from typing import Any, Dict, Optional
from pydantic import BaseModel, ConfigDict, Field


class WebhookInbound(BaseModel):
    """Raw incoming webhook structure from external providers."""
    source: str = Field(default="generic", description="Originating provider (e.g. typeform, stripe, zapier)")
    event_type: str = Field(default="lead.created", description="Event name/type")
    idempotency_key: Optional[str] = Field(None, description="Optional unique request key to prevent duplicate processing")
    payload: Dict[str, Any] = Field(..., description="Arbitrary event body")


class WebhookAcknowledge(BaseModel):
    """Immediate response after receiving a webhook."""
    received: bool = True
    event_id: uuid.UUID
    status: str
    message: str


class WebhookEventRead(BaseModel):
    """Full database representation of an ingested webhook event."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    source: str
    event_type: str
    idempotency_key: Optional[str]
    status: str
    payload: Dict[str, Any]
    headers: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime
