from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class AgencyProfile(BaseModel):
    """White-label branding and domain configuration for the managing agency."""
    agency_name: str = Field("Apex Multi-Trade Growth Partners", description="White-label agency or parent franchise name")
    custom_logo_url: Optional[str] = Field(None, description="URL to agency logo graphic")
    brand_color: str = Field("#6366F1", description="Primary hexadecimal brand accent color")
    contact_email: str = Field("hq@apexgrowthpartners.com", description="Agency primary support/operations contact email")
    custom_domain: Optional[str] = Field("dispatch.apexgrowth.com", description="Custom white-label CNAME domain")
    white_label_active: bool = Field(True, description="Whether agency white-label styling is enabled")


class ManagedTenantSummary(BaseModel):
    """Aggregated status and commercial telemetry for an individual managed contractor tenant."""
    tenant_id: str = Field(..., description="Unique tenant UUID")
    tenant_name: str = Field(..., description="Trade business legal or operating name")
    tenant_slug: str = Field(..., description="Unique URL slug")
    trade_category: str = Field("General", description="Primary trade specialization")
    is_active: bool = Field(True, description="Whether tenant account is active")
    monthly_retainer: float = Field(799.0, description="Monthly management retainer in USD")
    total_calls_ingested: int = Field(0, description="Total calls and webhook leads received")
    emergency_rate_pct: float = Field(0.0, description="Percentage of leads classified as high-priority emergencies")
    coi_status: str = Field("ACTIVE_COMPLIANT", description="Commercial ACORD insurance compliance state")


class AgencyOverview(BaseModel):
    """Executive KPI roll-up across all managed contractor client accounts."""
    agency_profile: AgencyProfile = Field(default_factory=AgencyProfile, description="Agency white-label settings")
    total_managed_tenants: int = Field(0, description="Count of managed contractor entities")
    total_calls_ingested: int = Field(0, description="Cumulative inbound calls and webhook events")
    total_emergencies_bridged: int = Field(0, description="Cumulative emergency calls routed directly to techs")
    aggregate_mrr: float = Field(0.0, description="Total Monthly Recurring Revenue across managed accounts")
    active_tenants: List[ManagedTenantSummary] = Field(default_factory=list, description="Directory of contractor tenants")
    recent_activity: List[Dict[str, Any]] = Field(default_factory=list, description="Recent cross-tenant dispatch events")


class AgencyTenantOnboardRequest(BaseModel):
    """Request payload to provision a new contractor tenant from the agency console."""
    name: str = Field(..., min_length=2, max_length=255, description="Contractor company name")
    slug: str = Field(..., min_length=2, max_length=64, description="Unique URL slug")
    trade_category: str = Field("HVAC", description="Primary trade e.g. HVAC, Plumbing, Roofing, Electrical")
    contact_email: str = Field(..., description="Owner or dispatcher notification email")
    monthly_retainer: float = Field(799.0, description="Contracted monthly retainer fee")
