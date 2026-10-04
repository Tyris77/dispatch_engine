import datetime
from datetime import timezone
from typing import Any, Dict, List, Optional
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.logging import logger
from app.models.lead_action import LeadAction
from app.models.tenant import Tenant
from app.schemas.reactivation import ReactivationBatchResult, ReactivationOffer


class ReactivationService:
    """
    Autonomous engine that revives dormant leads and unsigned proposals:
    1. 48-Hour Unsigned Proposal Reviver: High-urgency route-density SMS with a $250 credit.
    2. 6-Month Seasonal Equipment Reviver: Monitors diagnostic equipment age (10+ yr old systems)
       and triggers pre-season replacement offers.
    """

    @staticmethod
    def _format_phone(phone: Optional[str]) -> str:
        if not phone:
            return "+12025550199"
        phone_clean = "".join(ch for ch in phone if ch.isdigit() or ch == "+")
        if not phone_clean.startswith("+"):
            phone_clean = "+1" + phone_clean
        return phone_clean

    @staticmethod
    def _get_rep_and_city(tenant: Tenant, action: LeadAction) -> tuple[str, str]:
        # Rep name
        rep_name = "Carlos"
        roster = tenant.settings.get("on_call_roster", [])
        if roster and isinstance(roster, list) and len(roster) > 0 and isinstance(roster[0], dict):
            rep_name = roster[0].get("name", "Carlos")
        elif tenant.settings.get("contact_person"):
            rep_name = tenant.settings.get("contact_person")

        # City / Route
        city = (
            action.metadata_payload.get("city")
            or action.metadata_payload.get("service_city")
            or action.metadata_payload.get("neighborhood")
            or "Bethesda"
        )
        return rep_name, city

    async def scan_and_reactivate_dead_leads(
        self,
        db: AsyncSession,
        tenant_id: Optional[uuid.UUID] = None,
        force_all: bool = False,
        base_url: str = "",
    ) -> ReactivationBatchResult:
        """
        Scans all dormant leads across the platform or for a single tenant,
        generating route-credit SMS reactivation campaigns.
        """
        now = datetime.datetime.now(timezone.utc)
        stmt = select(LeadAction).options(selectinload(LeadAction.tenant))
        if tenant_id:
            stmt = stmt.where(LeadAction.tenant_id == tenant_id)

        result = await db.execute(stmt)
        actions = list(result.scalars().all())

        scanned_count = len(actions)
        dispatched_offers: List[ReactivationOffer] = []
        total_revived_value = 0.0

        for action in actions:
            # Skip if already signed or already accepted
            if action.signed_contract:
                continue

            # Skip if already reactivated unless forced
            if action.reactivation_data and not force_all:
                continue

            tenant = action.tenant
            if not tenant:
                continue

            rep_name, city = self._get_rep_and_city(tenant, action)
            company_name = tenant.name or "Apex Roofing"
            customer_name = (
                action.metadata_payload.get("customer_name")
                or action.metadata_payload.get("name")
                or action.metadata_payload.get("caller_name")
                or "John"
            )
            customer_phone = self._format_phone(
                action.lead_external_id
                or action.metadata_payload.get("phone")
                or action.metadata_payload.get("From")
            )

            # --- Campaign 1: 48-Hour Unsigned Proposal Reviver ---
            if action.proposal_data:
                # Check age: >= 48 hours or force_all
                action_dt = action.updated_at or action.created_at
                if action_dt and action_dt.tzinfo is None:
                    action_dt = action_dt.replace(tzinfo=timezone.utc)

                age_hours = (now - action_dt).total_seconds() / 3600.0 if action_dt else 999.0
                if force_all or age_hours >= 48.0:
                    proposal_link = f"{base_url.rstrip('/')}/proposal/{action.id}"
                    # Revenue estimate from proposal
                    options = action.proposal_data.get("options", [])
                    potential_rev = 1250.0
                    if options and isinstance(options, list) and len(options) > 0 and isinstance(options[0], dict):
                        potential_rev = float(options[0].get("price_estimate", 1250.0))

                    sms_copy = (
                        f"Hi {customer_name}, {rep_name} from {company_name}. "
                        f"We're finalizing our route in {city} this week. "
                        f"We can apply a $250 credit if we lock in your repair before Friday: {proposal_link}"
                    )

                    offer = ReactivationOffer(
                        action_id=str(action.id),
                        campaign_type="UNSIGNED_PROPOSAL_48H",
                        customer_name=customer_name,
                        customer_phone=customer_phone,
                        proposal_link=proposal_link,
                        discount_incentive=250.0,
                        expiration_date=(now + datetime.timedelta(days=3)).strftime("%Y-%m-%d"),
                        message_body=sms_copy,
                        status="SENT",
                        potential_recovered_revenue=potential_rev,
                        sent_at=now.isoformat(),
                    )

                    action.reactivation_data = offer.model_dump()
                    dispatched_offers.append(offer)
                    total_revived_value += potential_rev
                    logger.info(f"Dispatched 48h Proposal Reviver SMS to {customer_phone} for lead {action.id}")
                    continue

            # --- Campaign 2: 6-Month Seasonal Equipment Reviver ---
            if action.diagnostic_data:
                equip_age = float(action.diagnostic_data.get("estimated_age_years") or 0.0)
                equip_make = action.diagnostic_data.get("make") or action.diagnostic_data.get("equipment_type") or "Carrier"
                equip_summary = f"{equip_make} ({int(equip_age) if equip_age else 10}+ yr old unit)"

                action_dt = action.created_at
                if action_dt and action_dt.tzinfo is None:
                    action_dt = action_dt.replace(tzinfo=timezone.utc)
                age_days = (now - action_dt).total_seconds() / 86400.0 if action_dt else 999.0

                # Eligible if equipment is 10+ years old or inspection was 180+ days ago
                if force_all or equip_age >= 10.0 or age_days >= 180.0:
                    intake_link = f"{base_url.rstrip('/')}/intake/{tenant.slug}"
                    potential_rev = 1450.0

                    sms_copy = (
                        f"Hi {customer_name}, {rep_name} from {company_name}. "
                        f"Our records show your {equip_make} system is {int(equip_age) if equip_age else 10}+ years old. "
                        f"We're running our pre-season reliability tune-up & replacement credit ($250 off) this week. "
                        f"Claim here: {intake_link}"
                    )

                    offer = ReactivationOffer(
                        action_id=str(action.id),
                        campaign_type="SEASONAL_EQUIPMENT_AGE",
                        customer_name=customer_name,
                        customer_phone=customer_phone,
                        equipment_summary=equip_summary,
                        proposal_link=intake_link,
                        discount_incentive=250.0,
                        expiration_date=(now + datetime.timedelta(days=7)).strftime("%Y-%m-%d"),
                        message_body=sms_copy,
                        status="SENT",
                        potential_recovered_revenue=potential_rev,
                        sent_at=now.isoformat(),
                    )

                    action.reactivation_data = offer.model_dump()
                    dispatched_offers.append(offer)
                    total_revived_value += potential_rev
                    logger.info(f"Dispatched Seasonal Equipment Reviver SMS to {customer_phone} for lead {action.id}")

        if dispatched_offers:
            await db.commit()

        return ReactivationBatchResult(
            scanned_leads_count=scanned_count,
            reactivated_count=len(dispatched_offers),
            total_reactivated_pipeline_value=round(total_revived_value, 2),
            offers_dispatched=dispatched_offers,
        )

    async def trigger_lead_reactivation(
        self,
        action_id: uuid.UUID,
        db: AsyncSession,
        campaign_type: str = "UNSIGNED_PROPOSAL_48H",
        custom_credit: float = 250.0,
        base_url: str = "",
    ) -> ReactivationOffer:
        """
        Manually triggers a single lead reactivation from the operator dashboard or client portal.
        """
        now = datetime.datetime.now(timezone.utc)
        stmt = (
            select(LeadAction)
            .options(selectinload(LeadAction.tenant))
            .where(LeadAction.id == action_id)
        )
        result = await db.execute(stmt)
        action = result.scalar_one_or_none()
        if not action:
            raise ValueError(f"LeadAction {action_id} not found")

        tenant = action.tenant
        rep_name, city = self._get_rep_and_city(tenant, action)
        company_name = tenant.name if tenant else "Apex Roofing"
        customer_name = (
            action.metadata_payload.get("customer_name")
            or action.metadata_payload.get("name")
            or action.metadata_payload.get("caller_name")
            or "John"
        )
        customer_phone = self._format_phone(
            action.lead_external_id
            or action.metadata_payload.get("phone")
            or action.metadata_payload.get("From")
        )

        potential_rev = 1250.0
        if action.proposal_data and "options" in action.proposal_data:
            opts = action.proposal_data["options"]
            if opts and isinstance(opts, list) and isinstance(opts[0], dict):
                potential_rev = float(opts[0].get("price_estimate", 1250.0))

        if campaign_type == "SEASONAL_EQUIPMENT_AGE":
            equip_make = (action.diagnostic_data or {}).get("make") or "Carrier"
            equip_age = (action.diagnostic_data or {}).get("estimated_age_years") or 10
            intake_link = f"{base_url.rstrip('/')}/intake/{tenant.slug if tenant else 'default'}"
            sms_copy = (
                f"Hi {customer_name}, {rep_name} from {company_name}. "
                f"Our records show your {equip_make} system is {int(equip_age)}+ years old. "
                f"We're running our pre-season reliability tune-up & replacement credit (${int(custom_credit)} off) this week. "
                f"Claim here: {intake_link}"
            )
            summary = f"{equip_make} ({int(equip_age)}+ yr old unit)"
            proposal_link = intake_link
        else:
            proposal_link = f"{base_url.rstrip('/')}/proposal/{action.id}"
            sms_copy = (
                f"Hi {customer_name}, {rep_name} from {company_name}. "
                f"We're finalizing our route in {city} this week. "
                f"We can apply a ${int(custom_credit)} credit if we lock in your repair before Friday: {proposal_link}"
            )
            summary = None

        offer = ReactivationOffer(
            action_id=str(action.id),
            campaign_type=campaign_type,
            customer_name=customer_name,
            customer_phone=customer_phone,
            equipment_summary=summary,
            proposal_link=proposal_link,
            discount_incentive=custom_credit,
            expiration_date=(now + datetime.timedelta(days=3)).strftime("%Y-%m-%d"),
            message_body=sms_copy,
            status="SENT",
            potential_recovered_revenue=potential_rev,
            sent_at=now.isoformat(),
        )

        action.reactivation_data = offer.model_dump()
        await db.commit()
        await db.refresh(action)

        return offer


reactivation_service = ReactivationService()
