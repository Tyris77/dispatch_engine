from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field


class SafetyAuditReport(BaseModel):
    """OSHA 1926 jobsite safety audit assessment generated from multimodal vision inspection."""
    safety_score: int = Field(..., ge=0, le=100, description="Overall compliance safety score from 0 to 100")
    compliance_status: str = Field(default="COMPLIANT", description="'COMPLIANT' or 'HAZARDS_DETECTED'")
    detected_ppe: List[str] = Field(default_factory=list, description="List of recognized personal protective equipment items")
    observed_hazards: List[str] = Field(default_factory=list, description="List of recognized jobsite safety hazards or code violations")
    osha_mitigations: List[str] = Field(default_factory=list, description="OSHA 1926 statutory mitigations and corrective action mandates")
    daily_tailgate_topic: str = Field(..., description="Recommended daily safety tailgate briefing topic based on observed site conditions")
    inspected_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


class SafetySubmissionResponse(BaseModel):
    """API response for field photo safety inspection."""
    action_id: str = Field(..., description="Associated LeadAction UUID")
    status: str = Field(default="SUCCESS", description="Submission processing status")
    report: SafetyAuditReport = Field(..., description="Audit analysis result")
    message: str = Field(default="Jobsite safety audit processed successfully.")
