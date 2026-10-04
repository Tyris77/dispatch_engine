from datetime import datetime, timezone
import uuid
from typing import Any, Dict, List, Optional
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import generate_api_key, generate_webhook_secret
from app.models.lead_action import LeadAction
from app.models.tenant import Tenant
from app.models.webhook_event import WebhookEvent
from app.schemas.agency import (
    AgencyOverview,
    AgencyProfile,
    AgencyTenantOnboardRequest,
    ManagedTenantSummary,
)

# Global in-memory agency profile singleton with default branding
_GLOBAL_AGENCY_PROFILE = AgencyProfile(
    agency_name="Apex Multi-Trade Growth Partners",
    custom_logo_url=None,
    brand_color="#6366F1",
    contact_email="hq@apexgrowthpartners.com",
    custom_domain="dispatch.apexgrowth.com",
    white_label_active=True,
)


class AgencyService:
    """Enterprise multi-tenant agency franchise management service."""

    def __init__(self) -> None:
        self.profile = _GLOBAL_AGENCY_PROFILE

    def get_agency_profile(self) -> AgencyProfile:
        """Returns the current white-label agency branding profile."""
        return self.profile

    def update_agency_profile(self, profile_data: Dict[str, Any]) -> AgencyProfile:
        """Updates white-label agency branding attributes."""
        current_dict = self.profile.model_dump()
        for k, v in profile_data.items():
            if v is not None and k in current_dict:
                current_dict[k] = v
        self.profile = AgencyProfile.model_validate(current_dict)
        return self.profile

    async def get_agency_overview(self, db: AsyncSession) -> AgencyOverview:
        """
        Aggregates multi-tenant performance analytics across all managed contractor tenants.
        Computes total MRR, total calls ingested, emergencies bridged, and tenant directory summaries.
        """
        stmt_tenants = select(Tenant).order_by(Tenant.created_at.desc())
        result_tenants = await db.execute(stmt_tenants)
        tenants = list(result_tenants.scalars().all())

        total_managed = len(tenants)
        total_calls = 0
        total_emergencies = 0
        aggregate_mrr = 0.0
        managed_summaries: List[ManagedTenantSummary] = []
        recent_activity: List[Dict[str, Any]] = []

        for tenant in tenants:
            settings_dict = tenant.settings or {}
            retainer = float(settings_dict.get("monthly_retainer", 799.0))
            if tenant.is_active:
                aggregate_mrr += retainer

            # Count webhook events for tenant
            stmt_events = select(func.count(WebhookEvent.id)).where(WebhookEvent.tenant_id == tenant.id)
            tenant_event_count = (await db.execute(stmt_events)).scalar() or 0

            # Count lead actions for tenant
            stmt_actions = select(LeadAction).where(LeadAction.tenant_id == tenant.id)
            res_actions = await db.execute(stmt_actions)
            actions = list(res_actions.scalars().all())
            tenant_action_count = len(actions)

            # Ingested calls is maximum or sum of events and direct actions
            calls_ingested = max(tenant_event_count, tenant_action_count)
            total_calls += calls_ingested

            # Count emergencies
            emergency_count = sum(
                1 for a in actions
                if a.action_type == "DISPATCH_EMERGENCY_DISPATCH_QUEUE"
                or (a.metadata_payload and a.metadata_payload.get("priority") == "emergency")
            )
            total_emergencies += emergency_count

            emergency_pct = round((emergency_count / tenant_action_count * 100.0), 1) if tenant_action_count > 0 else 0.0

            # Active COI compliance status
            coi_data = settings_dict.get("active_coi", {})
            coi_status = coi_data.get("compliance_status", "ACTIVE_COMPLIANT")

            trade_cat = settings_dict.get("trade_category", "HVAC")

            managed_summaries.append(
                ManagedTenantSummary(
                    tenant_id=str(tenant.id),
                    tenant_name=tenant.name,
                    tenant_slug=tenant.slug,
                    trade_category=trade_cat,
                    is_active=tenant.is_active,
                    monthly_retainer=retainer,
                    total_calls_ingested=calls_ingested,
                    emergency_rate_pct=emergency_pct,
                    coi_status=coi_status,
                )
            )

            # Add recent lead events to recent_activity feed
            for act in actions[:2]:
                recent_activity.append({
                    "tenant_name": tenant.name,
                    "tenant_slug": tenant.slug,
                    "action_type": act.action_type,
                    "qualification_score": act.qualification_score,
                    "created_at": act.created_at.isoformat() if act.created_at else None,
                })

        return AgencyOverview(
            agency_profile=self.profile,
            total_managed_tenants=total_managed,
            total_calls_ingested=total_calls,
            total_emergencies_bridged=total_emergencies,
            aggregate_mrr=aggregate_mrr,
            active_tenants=managed_summaries,
            recent_activity=recent_activity[:10],
        )

    async def onboard_agency_tenant(
        self,
        db: AsyncSession,
        request: AgencyTenantOnboardRequest,
    ) -> Tenant:
        """
        Provisions a new contractor tenant from the agency console,
        generating API keys, webhook secrets, and initializing trade defaults.
        """
        raw_key, hashed_key = generate_api_key(prefix=f"{request.slug[:3]}_")
        webhook_sec = generate_webhook_secret()

        new_tenant = Tenant(
            id=uuid.uuid4(),
            name=request.name,
            slug=request.slug,
            api_key_hash=hashed_key,
            webhook_secret=webhook_sec,
            is_active=True,
            settings={
                "trade_category": request.trade_category,
                "monthly_retainer": request.monthly_retainer,
                "contact_email": request.contact_email,
                "onboarded_by_agency": self.profile.agency_name,
                "min_qualification_score": 0.5,
                "routing_rules": {
                    "default_route": "general_sales",
                    "high_priority_route": "executive_escalation",
                },
            },
        )
        db.add(new_tenant)
        await db.commit()
        await db.refresh(new_tenant)
        return new_tenant


agency_service = AgencyService()
