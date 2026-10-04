import uuid
from typing import Any, Dict, List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import logger
from app.models.lead_action import LeadAction
from app.models.tenant import Tenant
from app.schemas.partner_exchange import PartnerReferralTrade, TradePartner

DEFAULT_TRADE_PARTNERS: List[TradePartner] = [
    TradePartner(
        partner_id="PARTNER-ELEC-01",
        company_name="Apex Commercial Electrical & Controls",
        trade_specialty="Electrical",
        phone="+15552345678",
        email="dispatch@apexelectric.pro",
        finder_fee_rate=0.10,
    ),
    TradePartner(
        partner_id="PARTNER-PLUMB-02",
        company_name="Keystone Commercial Plumbing & Mechanical",
        trade_specialty="Plumbing",
        phone="+15553456789",
        email="leads@keystoneplumbing.com",
        finder_fee_rate=0.10,
    ),
    TradePartner(
        partner_id="PARTNER-ROOF-03",
        company_name="Vanguard Commercial Roofing Systems",
        trade_specialty="Roofing",
        phone="+15554567890",
        email="commercial@vanguardroofing.com",
        finder_fee_rate=0.10,
    ),
    TradePartner(
        partner_id="PARTNER-HVAC-04",
        company_name="Vulcan Industrial Chiller & HVAC",
        trade_specialty="HVAC",
        phone="+15555678901",
        email="service@vulcanhvac.com",
        finder_fee_rate=0.10,
    ),
    TradePartner(
        partner_id="PARTNER-REST-05",
        company_name="Armor IICRC Emergency Restoration & Abatement",
        trade_specialty="Restoration",
        phone="+15556789012",
        email="emergency@armorrestoration.org",
        finder_fee_rate=0.10,
    ),
]


async def send_partner_sms(to_phone: str, message_body: str) -> bool:
    """Send B2B referral alert SMS to partner contractor."""
    if not to_phone:
        return False
    if settings.TWILIO_ACCOUNT_SID and settings.TWILIO_AUTH_TOKEN:
        try:
            from twilio.rest import Client
            client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
            client.messages.create(
                to=to_phone,
                from_=settings.TWILIO_FROM_NUMBER or "+15005550006",
                body=message_body,
            )
            return True
        except Exception as exc:
            logger.error(f"Failed to dispatch partner SMS to {to_phone}: {exc}")
            return False
    logger.info(f"[Simulation] Cross-Trade Partner SMS to {to_phone}: {message_body}")
    return True


class PartnerExchangeService:
    """Cross-Trade B2B Partner Exchange & 10% Finder Fee Splitter."""

    _send_sms = staticmethod(send_partner_sms)

    def get_partner_network_roster(self, tenant: Tenant) -> List[TradePartner]:
        """Return the combined partner network roster for this tenant."""
        custom_partners = (tenant.settings or {}).get("custom_trade_partners") or []
        roster: List[TradePartner] = []
        for p in custom_partners:
            try:
                roster.append(TradePartner.model_validate(p))
            except Exception:
                pass
        # Add defaults if not overridden
        known_ids = {p.partner_id for p in roster}
        for default_p in DEFAULT_TRADE_PARTNERS:
            if default_p.partner_id not in known_ids:
                roster.append(default_p)
        return roster

    def find_partner_for_trade(self, tenant: Tenant, target_trade: str) -> Optional[TradePartner]:
        """Match the highest-rated partner for the requested specialty."""
        roster = self.get_partner_network_roster(tenant)
        target_lower = (target_trade or "").strip().lower()
        for p in roster:
            if p.trade_specialty.lower() in target_lower or target_lower in p.trade_specialty.lower():
                return p
        return roster[0] if roster else None

    def get_partner_referrals(self, tenant: Tenant) -> List[PartnerReferralTrade]:
        """Retrieve all outgoing and incoming referral trades."""
        raw_list = (tenant.settings or {}).get("cross_trade_referrals") or []
        results: List[PartnerReferralTrade] = []
        for item in raw_list:
            try:
                results.append(PartnerReferralTrade.model_validate(item))
            except Exception:
                pass
        return results

    async def dispatch_cross_trade_referral(
        self,
        action_id: uuid.UUID,
        target_trade: str,
        referring_tenant: Tenant,
        db: AsyncSession,
        estimated_job_value: Optional[float] = None,
        custom_service_needed: Optional[str] = None,
        specific_partner_id: Optional[str] = None,
    ) -> PartnerReferralTrade:
        """
        Packages customer contact, address, and diagnostic context into a warm B2B referral.
        Dispatches SMS notification to trade partner and logs the 10% finder fee entitlement.
        """
        lead = (await db.execute(select(LeadAction).where(LeadAction.id == action_id))).scalar_one_or_none()
        if not lead:
            raise ValueError(f"Job action '{action_id}' not found")

        partner: Optional[TradePartner] = None
        if specific_partner_id:
            for p in self.get_partner_network_roster(referring_tenant):
                if p.partner_id == specific_partner_id:
                    partner = p
                    break
        if not partner:
            partner = self.find_partner_for_trade(referring_tenant, target_trade)

        if not partner:
            raise ValueError(f"No trade partner available for specialty '{target_trade}'")

        # Resolve customer details
        meta = lead.metadata_payload or {}
        cust_name = meta.get("customer_name") or (lead.qualification_summary or "Commercial Property Manager").split(" - ")[0]
        cust_phone = meta.get("phone") or meta.get("customer_phone") or lead.lead_external_id or "+15559876543"
        address = lead.extracted_address or meta.get("address") or "Commercial Facility"

        # Resolve service description
        service = custom_service_needed or f"Requires specialist commercial {partner.trade_specialty} work at {address}"

        # Resolve estimated job value
        if estimated_job_value and estimated_job_value > 0:
            job_val = round(estimated_job_value, 2)
        else:
            diag = lead.diagnostic_data or {}
            job_val = round(float(diag.get("estimated_cost") or meta.get("estimated_cost") or 15000.00), 2)

        finder_fee = round(job_val * partner.finder_fee_rate, 2)
        referral_id = f"REF-{partner.trade_specialty[:3].upper()}-{uuid.uuid4().hex[:6].upper()}"

        referral = PartnerReferralTrade(
            referral_id=referral_id,
            referring_tenant_slug=referring_tenant.slug,
            recipient_partner=partner,
            customer_name=cust_name,
            customer_phone=cust_phone,
            service_needed=service,
            estimated_job_value=job_val,
            finder_fee_due=finder_fee,
            status="DISPATCHED_TO_PARTNER",
        )

        # Update LeadAction
        lead.partner_exchange_data = referral.model_dump()

        # Update Tenant Settings
        new_settings = dict(referring_tenant.settings or {})
        referrals_list = list(new_settings.get("cross_trade_referrals") or [])
        referrals_list.insert(0, referral.model_dump())
        new_settings["cross_trade_referrals"] = referrals_list
        referring_tenant.settings = new_settings

        await db.commit()

        # Dispatch warm SMS alert to partner shop
        sms_body = (
            f"🤝 {referring_tenant.name} sent you a warm {partner.trade_specialty} referral! "
            f"Customer: {cust_name} ({cust_phone}), Job: {service}. "
            f"Est. Value: ${job_val:,.2f} (10% Finder Fee: ${finder_fee:,.2f} upon closing)."
        )
        await self._send_sms(partner.phone, sms_body)

        logger.info(f"Dispatched cross-trade referral {referral_id} to {partner.company_name} (Fee: ${finder_fee})")
        return referral

    async def settle_finder_fee(
        self,
        referral_id: str,
        tenant: Tenant,
        db: AsyncSession,
    ) -> bool:
        """Mark a referral finder fee as settled/paid out."""
        new_settings = dict(tenant.settings or {})
        referrals = list(new_settings.get("cross_trade_referrals") or [])
        found = False
        for item in referrals:
            if item.get("referral_id") == referral_id:
                item["status"] = "FEE_SETTLED"
                found = True
                break
        if found:
            new_settings["cross_trade_referrals"] = referrals
            tenant.settings = new_settings
            await db.commit()
        return found


partner_exchange_service = PartnerExchangeService()
