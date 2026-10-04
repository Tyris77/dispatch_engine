import datetime
import re
from typing import Any, Dict, Optional
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import logger
from app.models.lead_action import LeadAction
from app.models.tenant import Tenant
from app.schemas.reputation import ReviewOutcome


async def send_reputation_sms(
    to_phone: str,
    message_body: str,
    from_number: Optional[str] = None,
) -> bool:
    """Dispatches SMS notification to customer or owner for reputation workflows."""
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
            logger.info(f"Dispatched reputation SMS to {to_phone} (SID: {message.sid})")
            return True
        except Exception as exc:
            logger.error(f"Failed to send reputation SMS to {to_phone}: {exc}")
            return False
    else:
        logger.info(f"[Simulation] Reputation SMS to {to_phone}: {message_body}")
        return True


def extract_rating_and_feedback(text: str) -> Optional[tuple[int, str]]:
    """
    Parses customer SMS reply to extract a 1-5 star rating and optional feedback.
    Handles '5', '5 stars', '5/5', '1 - awful leak', '4. Very satisfied', '4 out of 5 stars. Good overall', etc.
    """
    if not text:
        return None

    cleaned = text.strip()
    # Match leading digit 1-5 followed by optional star notation, then remainder
    match = re.match(
        r"^([1-5])(?:\s*(?:stars?|out of 5 stars?|out of 5|/5|[.\-:]))*\s*(.*)$",
        cleaned,
        re.IGNORECASE,
    )
    if match:
        rating = int(match.group(1))
        raw_fb = match.group(2).lstrip("!.,-: ").strip()
        return rating, raw_fb

    # Check for standalone rating anywhere if short text
    if len(cleaned) <= 10:
        match_any = re.search(r"\b([1-5])\b", cleaned)
        if match_any:
            rating = int(match_any.group(1))
            return rating, ""

    return None


class ReputationService:
    """
    5-Star Review Booster & Shield Engine:
    1. Prompts customers for 1-5 star ratings post-job completion.
    2. Automatically routes 4-5 star ratings to Google Review link (Booster).
    3. Intercepts 1-3 star negative reviews, apologizes to customer, and alerts owner immediately (Shield).
    """

    _send_sms = staticmethod(send_reputation_sms)

    async def trigger_post_job_review_request(
        self,
        lead_action: Optional[LeadAction] = None,
        tenant: Optional[Tenant] = None,
        db: Optional[AsyncSession] = None,
        lead: Optional[LeadAction] = None,
        db_session: Optional[AsyncSession] = None,
    ) -> Dict[str, Any]:
        """
        Sends initial 1-5 star survey request to the homeowner.
        """
        target_lead = lead_action or lead
        target_db = db or db_session

        if not target_lead:
            raise ValueError("lead_action must be provided")

        # Resolve customer name and phone
        signed_contract = target_lead.signed_contract or {}
        customer_name = (
            signed_contract.get("customer_name")
            or target_lead.metadata_payload.get("customer_name")
            or "Valued Customer"
        )
        customer_phone = (
            signed_contract.get("customer_phone")
            or target_lead.metadata_payload.get("caller_phone")
            or target_lead.lead_external_id
        )

        if not customer_phone:
            logger.warning(f"Cannot trigger review request for Action {target_lead.id}: No customer phone")
            return {
                "success": False,
                "action_id": str(target_lead.id),
                "error": "No customer phone available",
            }

        tenant_name = tenant.name if tenant else "our team"
        message_body = (
            f"Hi {customer_name}, {tenant_name} here. Our technician completed your service. "
            "How would you rate your experience from 1 to 5 stars?"
        )

        from_phone = tenant.settings.get("twilio_phone_number") if tenant else None
        from_phone = from_phone or settings.TWILIO_FROM_NUMBER
        sms_sent = await self._send_sms(
            to_phone=customer_phone,
            message_body=message_body,
            from_number=from_phone,
        )

        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        target_lead.review_data = {
            "status": "PROMPTED",
            "prompted_at": now_iso,
            "customer_name": customer_name,
            "customer_phone": customer_phone,
            "rating": None,
            "feedback": None,
            "outcome": None,
        }
        if target_db:
            await target_db.commit()
            await target_db.refresh(target_lead)

        return {
            "success": True,
            "action_id": str(target_lead.id),
            "status": "PROMPTED",
            "sms_sent": sms_sent,
            "customer_phone": customer_phone,
        }

    async def process_review_reply(
        self,
        rating: int,
        feedback: str,
        lead_action: Optional[LeadAction] = None,
        tenant: Optional[Tenant] = None,
        db: Optional[AsyncSession] = None,
        lead: Optional[LeadAction] = None,
        db_session: Optional[AsyncSession] = None,
        skip_customer_sms: bool = False,
    ) -> ReviewOutcome:
        """
        Processes rating reply:
        - 4-5 Stars: Sends Google review link to boost public reputation.
        - 1-3 Stars: Insulates negative feedback and alerts owner via SMS immediately.
        """
        target_lead = lead_action or lead
        target_db = db or db_session

        if not target_lead:
            raise ValueError("lead_action must be provided")

        signed_contract = target_lead.signed_contract or {}
        customer_name = (
            (target_lead.review_data.get("customer_name") if target_lead.review_data else None)
            or signed_contract.get("customer_name")
            or (target_lead.metadata_payload or {}).get("customer_name")
            or "Customer"
        )

        customer_phone = (
            (target_lead.review_data.get("customer_phone") if target_lead.review_data else None)
            or signed_contract.get("customer_phone")
            or (target_lead.metadata_payload or {}).get("caller_phone")
            or target_lead.lead_external_id
        )

        from_phone = tenant.settings.get("twilio_phone_number") or settings.TWILIO_FROM_NUMBER
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

        if rating >= 4:
            # 5-STAR BOOSTER PATH
            status = "BOOST_SENT"
            google_url = (
                tenant.settings.get("google_review_url")
                or f"https://g.page/r/{tenant.slug}/review"
            )
            customer_reply = (
                f"Thank you! Would you mind taking 15 seconds to drop that on our Google profile? "
                f"It helps our team tremendously: {google_url}"
            )
            owner_alert = None

            if customer_phone and not skip_customer_sms:
                await self._send_sms(
                    to_phone=customer_phone,
                    message_body=customer_reply,
                    from_number=from_phone,
                )

        else:
            # NEGATIVE INSULATION SHIELD PATH (1, 2, or 3 stars)
            status = "NEGATIVE_INSULATED"
            google_url = None
            customer_reply = (
                "We're so sorry to hear that. What went wrong? "
                "Your message is being sent directly to the owner's personal phone so we can make this right immediately."
            )

            # Send apology to customer if not handled via TwiML webhook reply
            if customer_phone and not skip_customer_sms:
                await self._send_sms(
                    to_phone=customer_phone,
                    message_body=customer_reply,
                    from_number=from_phone,
                )

            # Send urgent alert to owner
            owner_phone = (
                tenant.settings.get("fallback_owner_phone")
                or tenant.settings.get("alert_phone_number")
                or tenant.settings.get("phone")
            )
            owner_alert = (
                f"⚠️ NEGATIVE FEEDBACK ALERT for {customer_name} ({customer_phone or 'No phone'}): "
                f"Rated {rating}/5 stars. Feedback: '{feedback}'. "
                "Call them immediately to resolve before a public review is posted!"
            )
            if owner_phone:
                await self._send_sms(
                    to_phone=owner_phone,
                    message_body=owner_alert,
                    from_number=from_phone,
                )

        # Update LeadAction review_data
        existing_data = target_lead.review_data or {}
        target_lead.review_data = {
            **existing_data,
            "status": status,
            "outcome_status": status,
            "rating": rating,
            "feedback": feedback,
            "resolved_at": now_iso,
            "google_review_url": google_url,
            "owner_alerted": bool(owner_alert),
        }
        if target_db:
            await target_db.commit()
            await target_db.refresh(target_lead)

        return ReviewOutcome(
            status=status,
            rating=rating,
            feedback=feedback,
            customer_reply=customer_reply,
            owner_alert=owner_alert,
            google_review_url=google_url,
            resolved_at=now_iso,
        )

    async def check_and_process_sms_review(
        self,
        from_phone: str,
        body_text: str,
        tenant: Tenant,
        db: AsyncSession,
    ) -> Optional[ReviewOutcome]:
        """
        Intercepts incoming SMS if it is a rating reply for an actively prompted review.
        """
        extracted = extract_rating_and_feedback(body_text)
        if not extracted:
            return None

        rating, feedback = extracted

        # Normalize phone for lookup
        clean_phone = from_phone.replace(" ", "").replace("-", "")

        # Look up recent lead action for this tenant with review status == 'PROMPTED'
        query = (
            select(LeadAction)
            .where(
                LeadAction.tenant_id == tenant.id,
            )
            .order_by(desc(LeadAction.created_at))
        )
        actions = (await db.execute(query)).scalars().all()

        matching_action = None
        for act in actions:
            r_data = act.review_data or {}
            # Match if status is PROMPTED and phone matches
            if r_data.get("status") == "PROMPTED":
                stored_phone = (r_data.get("customer_phone") or act.lead_external_id or "").replace(" ", "").replace("-", "")
                if clean_phone and (clean_phone in stored_phone or stored_phone in clean_phone):
                    matching_action = act
                    break

        if not matching_action:
            # Check if any recent action matches phone regardless of status
            for act in actions:
                stored_phone = (act.lead_external_id or "").replace(" ", "").replace("-", "")
                if clean_phone and (clean_phone in stored_phone or stored_phone in clean_phone):
                    matching_action = act
                    break

        if not matching_action:
            return None

        return await self.process_review_reply(
            rating=rating,
            feedback=feedback,
            lead_action=matching_action,
            tenant=tenant,
            db=db,
            skip_customer_sms=True,
        )


reputation_service = ReputationService()
trigger_post_job_review_request = reputation_service.trigger_post_job_review_request
process_review_reply = reputation_service.process_review_reply
check_and_process_sms_review = reputation_service.check_and_process_sms_review
