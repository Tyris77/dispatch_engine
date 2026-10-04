from datetime import datetime, timezone
from typing import List, Optional
from pydantic import BaseModel, Field


class OptimizedRouteStop(BaseModel):
    """An individual waypoint stop assigned to a technician's daily service itinerary."""
    stop_order: int = Field(..., description="Sequence order for the stop (1, 2, 3...)")
    action_id: str = Field(..., description="LeadAction UUID")
    customer_name: str = Field(..., description="Customer or facility name")
    address: str = Field(..., description="Destination street address")
    scheduled_time: str = Field(..., description="Estimated arrival time window (e.g., '08:30 AM')")
    service_type: str = Field(..., description="Trade specialty or job description")
    estimated_duration_min: int = Field(default=60, description="Estimated on-site service time in minutes")
    nav_link: str = Field(..., description="Turn-by-turn navigation link (Google Maps / Apple Maps)")
    status: str = Field(default="SCHEDULED", description="'SCHEDULED', 'EN_ROUTE', 'COMPLETED'")


class TechnicianDailyRoute(BaseModel):
    """Complete day itinerary for an individual trade service vehicle and technician."""
    tech_name: str = Field(..., description="Technician or driver full name")
    truck_id: str = Field(..., description="Vehicle ID or license plate (e.g., 'VAN-01', 'TRUCK-APEX-4')")
    phone: Optional[str] = Field(None, description="Driver mobile phone for dispatch SMS")
    corridor_zone: str = Field(default="Central", description="Assigned geographic service sector")
    stops: List[OptimizedRouteStop] = Field(default_factory=list, description="Sequenced route stops")
    total_miles: float = Field(..., description="Computed driving distance for route in miles")
    total_drive_time_minutes: int = Field(..., description="Total driving duration in minutes")
    fuel_saved_dollars: float = Field(..., description="Estimated fuel dollars saved via waypoint optimization")


class DailyFleetOptimizationReport(BaseModel):
    """Comprehensive daily multi-vehicle route optimization ledger."""
    date: str = Field(..., description="Target dispatch date in YYYY-MM-DD")
    tenant_slug: str = Field(..., description="Contractor tenant slug")
    tenant_name: str = Field(default="", description="Contractor legal entity name")
    total_stops: int = Field(..., description="Total scheduled stops across all routes")
    total_fleet_miles: float = Field(..., description="Aggregate miles driven by all fleet trucks")
    total_fuel_saved_dollars: float = Field(..., description="Total estimated fleet fuel savings in USD")
    routes_by_tech: List[TechnicianDailyRoute] = Field(default_factory=list, description="Itineraries grouped by technician")
    generated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="Optimization run timestamp",
    )
