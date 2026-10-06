from typing import Optional
from pydantic import BaseModel, Field


class TechnicianSmsPayload(BaseModel):
    """Payload received from Twilio inbound SMS webhook or simulated reply."""
    From: str = Field(..., description="Sender phone number (technician)")
    Body: str = Field(..., description="Message body (e.g. '1', '2', 'ACCEPT', 'PASS')")
    To: Optional[str] = Field(None, description="Twilio receiver number")
    MessageSid: Optional[str] = Field(None, description="Twilio unique message SID")


class SmsDispatchAction(BaseModel):
    """Status record of a dispatched two-way SMS technician request."""
    action_id: str
    tenant_name: str = "Apex Plumbing"
    technician_name: str
    technician_phone: str
    backup_technician_name: Optional[str] = None
    backup_technician_phone: Optional[str] = None
    dispatch_text: str
    status: str = Field(default="PENDING", description="PENDING, ACCEPTED, PASSED, ESCALATED")
    homeowner_phone: str
    homeowner_sms_sent: bool = False
    tracking_url: str
    dispatched_at: str
    accepted_at: Optional[str] = None


class SmsBridgeResponse(BaseModel):
    """Structured result of processing a technician SMS reply."""
    status: str = "PROCESSED"
    action_id: Optional[str] = None
    technician: str = ""
    reply_interpreted: str = Field(..., description="ACCEPT, PASS, UNKNOWN")
    dispatch_status: str
    homeowner_notified: bool = False
    backup_notified: bool = False
    response_message: str
    twiml_response: Optional[str] = None
