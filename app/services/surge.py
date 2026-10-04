import datetime
from typing import Any, Dict, Optional

from app.core.logging import logger
from app.models.lead_action import LeadAction
from app.models.tenant import Tenant
from app.schemas.surge import SurgePricingAssessment
from app.services.weather_dispatch import METEOROLOGICAL_HAZARD_REGISTRY


class SurgePricingService:
    """
    Dynamic Surge & After-Hours Pricing Engine.
    Monitors calendar operating hours, holiday schedules, and active meteorological alerts
    to adjust upfront diagnostic fees and labor multipliers with transparent consumer disclosure.
    """

    def assess_surge_pricing(
        self,
        tenant: Tenant,
        current_dt: Optional[datetime.datetime] = None,
    ) -> SurgePricingAssessment:
        """
        Evaluates current request timestamp against tenant operating hours and active severe weather alerts.
        Emits after-hours diagnostic fees ($199 vs $89 standard), severe weather rates ($249 / 1.75x),
        and transparent disclosures for IVR voice greetings and SMS triage scripts.
        """
        if current_dt is None:
            current_dt = datetime.datetime.now(datetime.timezone.utc)

        # 1. Check for Active Severe Weather Warnings
        active_weather_surge = False
        hazard_title = ""
        for hazard in METEOROLOGICAL_HAZARD_REGISTRY:
            if hazard.get("severity") == "WARNING":
                active_weather_surge = True
                hazard_title = hazard.get("event_title", "Severe Meteorological Hazard")
                break

        if active_weather_surge:
            diagnostic_fee = float(tenant.settings.get("weather_surge_diagnostic_fee", 249.0))
            labor_multiplier = float(tenant.settings.get("weather_surge_labor_multiplier", 1.75))
            surge_disclosure = (
                f"Notice: Emergency hazard surge pricing is currently active due to an official {hazard_title}. "
                f"Emergency diagnostic dispatch is ${diagnostic_fee:.0f} with a {labor_multiplier}x priority labor rate."
            )
            return SurgePricingAssessment(
                is_surge_active=True,
                surge_reason="SEVERE_WEATHER_SURGE",
                diagnostic_fee=diagnostic_fee,
                labor_multiplier=labor_multiplier,
                surge_disclosure=surge_disclosure,
                rate_card={
                    "standard_diagnostic": 89.0,
                    "active_diagnostic": diagnostic_fee,
                    "standard_labor_rate": 145.0,
                    "active_labor_rate": round(145.0 * labor_multiplier, 2),
                    "labor_multiplier": labor_multiplier,
                    "hazard_name": hazard_title,
                },
                assessed_at=current_dt.isoformat(),
            )

        # 2. Check Operating Hours (Default Mon-Fri 8:00 AM - 6:00 PM)
        op_hours = tenant.settings.get("operating_hours", {})
        start_hour = int(op_hours.get("start_hour", 8))
        end_hour = int(op_hours.get("end_hour", 18))
        workdays = op_hours.get("workdays", [0, 1, 2, 3, 4])  # 0=Monday, 6=Sunday

        is_weekend = current_dt.weekday() not in workdays
        is_outside_hours = current_dt.hour < start_hour or current_dt.hour >= end_hour

        if is_weekend or is_outside_hours:
            diagnostic_fee = float(tenant.settings.get("after_hours_diagnostic_fee", 199.0))
            labor_multiplier = float(tenant.settings.get("after_hours_labor_multiplier", 1.5))
            surge_disclosure = (
                f"Notice: After-hours emergency dispatch is currently active. "
                f"Diagnostic dispatch is ${diagnostic_fee:.0f} with a {labor_multiplier}x after-hours labor rate."
            )
            return SurgePricingAssessment(
                is_surge_active=True,
                surge_reason="AFTER_HOURS_WEEKEND",
                diagnostic_fee=diagnostic_fee,
                labor_multiplier=labor_multiplier,
                surge_disclosure=surge_disclosure,
                rate_card={
                    "standard_diagnostic": 89.0,
                    "active_diagnostic": diagnostic_fee,
                    "standard_labor_rate": 145.0,
                    "active_labor_rate": round(145.0 * labor_multiplier, 2),
                    "labor_multiplier": labor_multiplier,
                },
                assessed_at=current_dt.isoformat(),
            )

        # 3. Standard Business Hours
        std_diag = float(tenant.settings.get("standard_diagnostic_fee", 89.0))
        return SurgePricingAssessment(
            is_surge_active=False,
            surge_reason="STANDARD_HOURS",
            diagnostic_fee=std_diag,
            labor_multiplier=1.0,
            surge_disclosure=f"Standard daytime dispatch is active. Diagnostic inspection fee is ${std_diag:.0f}.",
            rate_card={
                "standard_diagnostic": std_diag,
                "active_diagnostic": std_diag,
                "standard_labor_rate": 145.0,
                "active_labor_rate": 145.0,
                "labor_multiplier": 1.0,
            },
            assessed_at=current_dt.isoformat(),
        )

    def apply_surge_to_lead(
        self,
        lead_action: LeadAction,
        tenant: Tenant,
        current_dt: Optional[datetime.datetime] = None,
    ) -> SurgePricingAssessment:
        """Evaluates and stores surge pricing metadata directly on the LeadAction."""
        assessment = self.assess_surge_pricing(tenant=tenant, current_dt=current_dt)
        lead_action.surge_pricing_data = assessment.model_dump()
        logger.info(
            f"Evaluated surge pricing for lead {lead_action.id} ({tenant.slug}): "
            f"Active={assessment.is_surge_active}, Reason={assessment.surge_reason}, "
            f"Fee=${assessment.diagnostic_fee}."
        )
        return assessment


surge_pricing_service = SurgePricingService()
