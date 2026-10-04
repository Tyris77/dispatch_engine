from typing import List
from pydantic import BaseModel, Field


class DailyProgressMilestone(BaseModel):
    """One day of jobsite progress documentation."""
    day_number: int = Field(..., ge=1)
    date: str
    photo_urls: List[str] = Field(default_factory=list)
    summary: str = ""
    completion_percentage: int = Field(default=0, ge=0, le=100)
    weather_tight_verified: bool = False
    customer_notes: str = ""


class JobStoryboardData(BaseModel):
    """Customer-facing multi-day progress storyboard."""
    action_id: str
    project_title: str
    total_days_estimated: int = Field(default=3, ge=1)
    current_completion_pct: int = Field(default=0, ge=0, le=100)
    is_weather_tight: bool = False
    milestones: List[DailyProgressMilestone] = Field(default_factory=list)


class StoryboardVisionAssessment(BaseModel):
    """Structured Gemini Vision output for a day's jobsite photos."""
    progress_percentage: int = Field(..., ge=0, le=100, description="Overall job completion estimate 0-100")
    weather_tight: bool = Field(..., description="True if the structure is protected from rain/wind/intrusion at end of day")
    summary: str = Field(..., description="One or two plain-English sentences for the homeowner")
