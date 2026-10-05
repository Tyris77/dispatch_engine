import re
import secrets
import uuid
from datetime import datetime, timezone
from typing import Dict, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import settings
from app.core.logging import logger
from app.core.security import generate_api_key, generate_webhook_secret
from app.models.tenant import Tenant
from app.schemas.autopilot import AutopilotTaskLog
from app.schemas.onboard import OnboardRequest, OnboardResponse
from app.services.autopilot import autopilot_service
from app.services.provisioning import allocate_twilio_number, slugify


class OnboardingService:
    """Service executing self-serve contractor registration and automated AI dispatcher activation."""

    async def generate_unique_slug(self, base_name: str, db: AsyncSession) -> str:
        """Generates a clean URL-safe slug and guarantees zero database collision."""
        base_slug = slugify(base_name)
        slug = base_slug
        attempt = 1

        while True:
            existing = (await db.execute(select(Tenant).where(Tenant.slug == slug))).scalar_one_or_none()
            if not existing:
                return slug
            slug = f"{base_slug}-{secrets.token_hex(2)}"
            attempt += 1
            if attempt > 15:
                return f"{base_slug}-{uuid.uuid4().hex[:6]}"

    def generate_carrier_instructions(self, forwarding_number: str) -> Dict[str, str]:
        """Formats standard mobile carrier star codes for call-forwarding."""
        digits = re.sub(r"\D", "", forwarding_number)
        if len(digits) == 11 and digits.startswith("1"):
            clean_10 = digits[1:]
        else:
            clean_10 = digits

        return {
            "verizon": f"*72 {forwarding_number} (Dial *72{clean_10} then press Call)",
            "att": f"*21* {forwarding_number} # (Dial *21*{clean_10}# then press Call)",
            "t_mobile": f"**21* {forwarding_number} # (Dial **21*{clean_10}# then press Call)",
            "landline": f"*72 + {forwarding_number} (Wait for dial tone, enter {forwarding_number}, listen for confirmation beep)",
        }

    async def provision_contractor(
        self,
        payload: OnboardRequest,
        db: AsyncSession,
        base_url: str = "",
    ) -> OnboardResponse:
        """
        Asynchronously creates Tenant, assigns local AI voice line, generates widget tag,
        configures multi-tier escalation, and logs activation.
        """
        # 1. Generate unique collision-free slug
        slug = await self.generate_unique_slug(payload.company_name, db)

        # 2. Generate secure authentication keys
        raw_api_key, api_key_hash = generate_api_key()
        webhook_secret = generate_webhook_secret()

        # 3. Allocate or assign dedicated forwarding line
        forwarding_number = allocate_twilio_number(
            slug=slug,
            business_name=payload.company_name,
            alert_phone=payload.on_call_phone,
        )

        # 4. Multi-tier cascading escalation tree
        owner_disp_name = payload.owner_name or f"{payload.company_name} Lead"
        cascading_escalation = {
            "tier_1": {
                "role": "Primary On-Call Technician",
                "phone": payload.on_call_phone,
                "timeout_seconds": 15,
            },
            "tier_2": {
                "role": "Backup Service Technician",
                "phone": payload.on_call_phone,
                "timeout_seconds": 15,
            },
            "tier_3": {
                "role": "Executive Fallback & Emergency SMS Blast",
                "phone": payload.on_call_phone,
                "action": "BLAST_SMS",
            },
        }

        # 5. Populate comprehensive operational settings
        tenant_settings = {
            "trade": payload.trade,
            "service_area": payload.service_area,
            "on_call_phone": payload.on_call_phone,
            "owner_email": str(payload.owner_email),
            "owner_name": owner_disp_name,
            "area_code_preference": payload.area_code_preference or "202",
            "stripe_session_id": payload.stripe_session_id,
            "assigned_twilio_number": forwarding_number,
            "twilio_phone_number": forwarding_number,
            "on_call_roster": [
                {
                    "name": owner_disp_name,
                    "role": "Lead On-Call Tech",
                    "phone": payload.on_call_phone,
                    "priority": 1,
                    "active": True,
                }
            ],
            "cascading_escalation": cascading_escalation,
            "business_hours": {
                "mode": "24/7_AFTER_HOURS",
                "after_hours_ai_enabled": True,
                "triage_urgency_filter": "high_and_emergency",
            },
            "qualification_rules": {
                "emergency_auto_dispatch": True,
                "routine_sms_scheduling": True,
                "bilingual_triage_enabled": True,
            },
        }

        # 6. Persist new Tenant record in database
        tenant = Tenant(
            id=uuid.uuid4(),
            name=payload.company_name,
            slug=slug,
            api_key_hash=api_key_hash,
            webhook_secret=webhook_secret,
            is_active=True,
            settings=tenant_settings,
        )

        db.add(tenant)
        await db.commit()
        await db.refresh(tenant)

        # 7. Format production URLs and script tags
        app_domain = (
            base_url.rstrip("/")
            if base_url
            else "https://dispatchengine-production.up.railway.app"
        )
        widget_script_tag = f'<script src="{app_domain}/api/v1/widget/{slug}.js"></script>'
        portal_url = f"{app_domain}/portal/{slug}"
        dashboard_url = f"{app_domain}/dashboard?tenant_slug={slug}"

        carrier_instructions = self.generate_carrier_instructions(forwarding_number)

        # 8. Log activation event in Autopilot telemetry feed
        try:
            autopilot_service.execution_logs.insert(
                0,
                AutopilotTaskLog(
                    task_name="Instant Contractor Activation",
                    executed_at=datetime.now(timezone.utc).isoformat(),
                    items_processed=1,
                    status="SUCCESS",
                    details=(
                        f"Activated AI Dispatcher for {payload.company_name} ({slug}). "
                        f"Assigned line: {forwarding_number}. Escalation to {payload.on_call_phone}."
                    ),
                ),
            )
            # Retain up to 50 logs
            autopilot_service.execution_logs = autopilot_service.execution_logs[:50]
        except Exception as log_err:
            logger.warning(f"Autopilot telemetry logging warning: {log_err}")

        logger.info(f"Self-serve onboarding completed for tenant '{slug}' ({payload.company_name})")

        return OnboardResponse(
            tenant_slug=slug,
            tenant_id=str(tenant.id),
            forwarding_phone_number=forwarding_number,
            widget_script_tag=widget_script_tag,
            portal_url=portal_url,
            dashboard_url=dashboard_url,
            status="ACTIVE",
            carrier_forwarding_instructions=carrier_instructions,
        )


onboarding_service = OnboardingService()
