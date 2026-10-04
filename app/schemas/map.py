from typing import List, Optional
from pydantic import BaseModel, Field


class MapLeadFeature(BaseModel):
    """Geographic point feature representing an active or recent lead/job in the dispatch map."""
    id: str
    action_id: str
    tenant_name: str
    tenant_slug: str
    caller: str
    lat: float
    lng: float
    urgency: str
    status: str
    status_label: str
    equipment_type: Optional[str] = None
    equipment_brand: Optional[str] = None
    damage: Optional[str] = None
    marker_type: str = Field(..., description="'emergency', 'routine', or 'completed'")
    tracking_url: str
    intake_url: str
    proposal_url: str
    created_at: str


class MapDataResponse(BaseModel):
    """GeoJSON-compatible dataset returned for Leaflet fleet map rendering."""
    center: List[float] = Field(default_factory=lambda: [32.7767, -96.7970], description="[lat, lng] map center")
    zoom: int = Field(default=11, description="Default map zoom level")
    total_active: int
    features: List[MapLeadFeature]
