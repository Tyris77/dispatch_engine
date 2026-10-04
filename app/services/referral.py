import datetime
import uuid
from typing import Any, Dict, List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.core.config import settings
from app.core.logging import logger
from app.models.lead_action import LeadAction
from app.models.tenant import Tenant
from app.schemas.referral import (
    ReferralClaimResponse,
    ReferralClaimSubmission,
    ReferralVoucher,
)


def send_referral_sms(
    to_phone: str,
    message_body: str,
    from_number: Optional[str] = None,
) -> bool:

    """Dispatches SMS notification to customer or referred neighbor."""
    if not to_phone:
        return False

    if settings.TWILIO_ACCOUNT_SID and settings.TWILIO_AUTH_TOKEN:
        try:
            from twilio.rest import Client

            client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
            from_num = from_number or settings.TWILIO_FROM_NUMBER or "+15005550006"
            message = client.messages.create(
                to=to_phone,
                from_=from_num,
                body=message_body,
            )
            logger.info(f"Dispatched referral SMS to {to_phone} (SID: {message.sid})")
            return True
        except Exception as exc:
            logger.error(f"Failed to send referral SMS to {to_phone}: {exc}")
            return False
    else:
        logger.info(f"[Simulation] Referral SMS to {to_phone}: {message_body}")
        return True


class ReferralService:
    """Customer Neighbor Referral Engine for viral homeowner acquisition and automatic discount booking."""

    _send_sms = staticmethod(send_referral_sms)

    def generate_referral_voucher(
        self,
        lead_action: LeadAction,
        tenant: Tenant,
        base_url: str = "",
    ) -> ReferralVoucher:
        """
        Generates or retrieves unique referral voucher for a customer LeadAction.
        Persists voucher token in lead_action.referral_data and dispatches SMS:
        "Share your neighbor link: give a neighbor $150 off their repair and earn $100 when they book: {shareable_url}"
        """
        ref_data = lead_action.referral_data or {}
        signed = lead_action.signed_contract or {}
        meta = lead_action.metadata_payload or {}

        # Resolve customer details
        referrer_name = (
            ref_data.get("referrer_name")
            or signed.get("customer_name")
            or meta.get("customer_name")
            or meta.get("caller_name")
            or "Valued Customer"
        )
        referrer_phone = (
            ref_data.get("referrer_phone")
            or signed.get("customer_phone")
            or meta.get("customer_phone")
            or meta.get("caller_phone")
            or lead_action.lead_external_id
            or ""
        )

        # Generate or reuse referral code
        referral_code = ref_data.get("referral_code")
        if not referral_code:
            clean_slug = "".join(ch for ch in tenant.slug.upper() if ch.isalnum())[:4] or "REF"
            token_suffix = str(lead_action.id).replace("-", "")[:6].upper()
            referral_code = f"REF-{clean_slug}-{token_suffix}"

        shareable_url = f"{base_url}/refer/{lead_action.id}"
        conversions_count = int(ref_data.get("conversions_count", 0))
        rewards_earned = float(ref_data.get("rewards_earned", 0.0))
        conversions = ref_data.get("conversions", [])

        voucher = ReferralVoucher(
            referral_code=referral_code,
            referrer_name=referrer_name,
            referrer_phone=referrer_phone,
            discount_amount=150.0,
            reward_amount=100.0,
            shareable_url=shareable_url,
            conversions_count=conversions_count,
            rewards_earned=rewards_earned,
            tenant_name=tenant.name,
            tenant_slug=tenant.slug,
            conversions=conversions,
        )

        # Store in lead_action.referral_data
        ref_dict = voucher.model_dump()
        ref_dict["last_generated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        lead_action.referral_data = ref_dict

        # Dispatch customer SMS
        if referrer_phone:
            sms_text = (
                f"Share your neighbor link: give a neighbor $150 off their repair and earn $100 "
                f"when they book: {shareable_url}"
            )
            self._send_sms(referrer_phone, sms_text)

        return voucher

    async def get_referral_voucher_by_action_id(
        self,
        action_id: str,
        tenant: Tenant,
        db: AsyncSession,
    ) -> Optional[ReferralVoucher]:
        """Looks up or generates a ReferralVoucher for a given LeadAction ID."""
        try:
            target_uuid = uuid.UUID(str(action_id))
        except ValueError:
            return None

        stmt = select(LeadAction).where(
            LeadAction.id == target_uuid,
            LeadAction.tenant_id == tenant.id,
        )
        result = await db.execute(stmt)
        lead = result.scalar_one_or_none()
        if not lead:
            return None

        if lead.referral_data and lead.referral_data.get("referral_code"):
            try:
                return ReferralVoucher(**lead.referral_data)
            except Exception:
                pass

        voucher = self.generate_referral_voucher(lead, tenant)
        flag_modified(lead, "referral_data")
        await db.commit()
        await db.refresh(lead)
        return voucher

    async def process_referral_claim(
        self,
        submission: ReferralClaimSubmission,
        tenant: Tenant,
        db: AsyncSession,
    ) -> ReferralClaimResponse:
        """
        Processes neighbor voucher claim:
        1. Identifies referring customer LeadAction and credits them $100.
        2. Creates new LeadAction attributed to referrer with $150 discount applied.
        3. Alerts contractor and dispatches confirmation SMS to neighbor and referrer.
        """
        # Find referrer lead by matching referral_code
        stmt = select(LeadAction).where(LeadAction.tenant_id == tenant.id)
        result = await db.execute(stmt)
        all_leads = result.scalars().all()

        referrer_lead: Optional[LeadAction] = None
        for lead in all_leads:
            if lead.referral_data and isinstance(lead.referral_data, dict):
                if lead.referral_data.get("referral_code") == submission.referral_code:
                    referrer_lead = lead
                    break

        referrer_name = "Neighbor Referral Partner"
        referrer_phone = ""
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

        if referrer_lead:
            ref_data = dict(referrer_lead.referral_data or {})
            referrer_name = ref_data.get("referrer_name", "Neighbor Referral Partner")
            referrer_phone = ref_data.get("referrer_phone", "")

            # Update referrer rewards
            ref_data["conversions_count"] = int(ref_data.get("conversions_count", 0)) + 1
            ref_data["rewards_earned"] = float(ref_data.get("rewards_earned", 0.0)) + 100.0

            conversions = list(ref_data.get("conversions", []))
            conversions.append(
                {
                    "neighbor_name": submission.neighbor_name,
                    "neighbor_phone": submission.neighbor_phone,
                    "service_needed": submission.service_needed,
                    "address": submission.address,
                    "claimed_at": now_iso,
                    "reward_earned": 100.0,
                    "discount_given": 150.0,
                }
            )
            ref_data["conversions"] = conversions
            referrer_lead.referral_data = ref_data
            flag_modified(referrer_lead, "referral_data")

            # Alert referring customer
            if referrer_phone:
                self._send_sms(
                    referrer_phone,
                    f"Great news {referrer_name}! Your neighbor {submission.neighbor_name} just booked "
                    f"with {tenant.name}. You've earned a $100 referral reward!",
                )

        # Create new LeadAction for neighbor
        new_action_id = uuid.uuid4()
        new_lead = LeadAction(
            id=new_action_id,
            tenant_id=tenant.id,
            lead_external_id=submission.neighbor_phone,
            qualification_score=0.95,
            qualification_summary=(
                f"VIP Neighbor Referral from {referrer_name} ($150 Voucher Applied). "
                f"Service: {submission.service_needed} at {submission.address}"
            ),
            action_type="NEIGHBOR_REFERRAL",
            dispatch_status="QUEUED",
            crm_sync_status="PENDING",
            metadata_payload={
                "customer_name": submission.neighbor_name,
                "customer_phone": submission.neighbor_phone,
                "address": submission.address,
                "service_address": submission.address,
                "service_needed": submission.service_needed,
                "source": "NEIGHBOR_REFERRAL",
                "referral_code": submission.referral_code,
                "referrer_name": referrer_name,
                "discount_amount": 150.0,
                "photo_notes": submission.photo_notes,
            },
            referral_data={
                "referred_by_code": submission.referral_code,
                "referred_by_name": referrer_name,
                "discount_applied": 150.0,
                "claimed_at": now_iso,
                "service_needed": submission.service_needed,
                "photo_notes": submission.photo_notes,
            },
        )
        db.add(new_lead)
        await db.commit()
        await db.refresh(new_lead)

        # Notify neighbor via SMS
        if submission.neighbor_phone:
            self._send_sms(
                submission.neighbor_phone,
                f"Hi {submission.neighbor_name}! Your $150 voucher from {referrer_name} has been applied. "
                f"A certified technician from {tenant.name} will contact you shortly to confirm your service!",
            )

        logger.info(
            f"Processed neighbor referral claim: {submission.neighbor_name} ({submission.neighbor_phone}) "
            f"with code {submission.referral_code} from {referrer_name} for tenant {tenant.slug}."
        )

        return ReferralClaimResponse(
            success=True,
            message=(
                f"Voucher successfully claimed! An exclusive $150 discount has been applied to "
                f"your service with {tenant.name}."
            ),
            referral_code=submission.referral_code,
            new_action_id=str(new_lead.id),
            discount_applied=150.0,
            neighbor_name=submission.neighbor_name,
        )

    async def get_tenant_referral_metrics(
        self,
        tenant: Tenant,
        db: AsyncSession,
    ) -> Dict[str, Any]:
        """Calculates aggregate referral metrics for the tenant dashboard."""
        stmt = select(LeadAction).where(LeadAction.tenant_id == tenant.id)
        result = await db.execute(stmt)
        leads = result.scalars().all()

        total_vouchers = 0
        total_conversions = 0
        total_rewards = 0.0

        for lead in leads:
            if lead.referral_data and isinstance(lead.referral_data, dict):
                if "referral_code" in lead.referral_data:
                    total_vouchers += 1
                    total_conversions += int(lead.referral_data.get("conversions_count", 0))
                    total_rewards += float(lead.referral_data.get("rewards_earned", 0.0))

        return {
            "total_vouchers_issued": total_vouchers,
            "total_conversions": total_conversions,
            "total_rewards_paid": total_rewards,
            "total_discounts_granted": total_conversions * 150.0,
        }


referral_service = ReferralService()
