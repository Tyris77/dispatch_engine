import datetime
from datetime import timezone
from typing import Any, Dict, Optional
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import logger
from app.models.lead_action import LeadAction
from app.models.tenant import Tenant
from app.services.dispatch import get_active_on_call_technicians


class OutboundVoiceService:
    """
    Manages automated outbound voice IVR calls to homeowners prior to technician arrival:
    - Initiates pre-arrival outbound call when tech is en route.
    - Prompts customer with Amazon Polly Neural voice greeting.
    - Processes DTMF 1 (confirms on-site) and DTMF 2 (direct dial bridge to tech).
    """

    @staticmethod
    def _resolve_customer_phone(lead_action: LeadAction) -> str:
        phone = (
            lead_action.lead_external_id
            or lead_action.metadata_payload.get("phone")
            or lead_action.metadata_payload.get("From")
            or lead_action.metadata_payload.get("caller_phone")
            or "+12025550199"
        )
        clean = "".join(ch for ch in phone if ch.isdigit() or ch == "+")
        if not clean.startswith("+"):
            clean = "+1" + clean
        return clean

    async def trigger_outbound_arrival_call(
        self,
        lead_action: LeadAction,
        tenant: Tenant,
        eta_minutes: int = 20,
        base_url: str = "",
        db: Optional[AsyncSession] = None,
    ) -> Dict[str, Any]:
        """
        Places an outbound IVR confirmation call to the homeowner via Twilio REST API.
        """
        customer_phone = self._resolve_customer_phone(lead_action)
        from_phone = (
            tenant.settings.get("twilio_phone_number")
            or settings.TWILIO_FROM_NUMBER
            or "+15005550006"
        )

        clean_base = base_url.rstrip("/")
        callback_url = (
            f"{clean_base}/api/v1/webhooks/twilio/voice/outbound-confirm"
            f"?action_id={lead_action.id}&eta={eta_minutes}"
        )

        call_sid = None
        if settings.TWILIO_ACCOUNT_SID and settings.TWILIO_AUTH_TOKEN:
            try:
                from twilio.rest import Client
                client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
                call = client.calls.create(
                    to=customer_phone,
                    from_=from_phone,
                    url=callback_url,
                )
                call_sid = call.sid
                logger.info(f"Twilio outbound arrival call created: {call_sid} to {customer_phone}")
            except Exception as exc:
                logger.error(f"Failed to place Twilio outbound call: {exc}")
                call_sid = f"CA_sim_err_{uuid.uuid4().hex[:12]}"
        else:
            call_sid = f"CA_sim_{uuid.uuid4().hex[:16]}"
            logger.info(f"[Simulation] Outbound arrival call to {customer_phone} -> {callback_url} (SID: {call_sid})")

        # Update lead tracking state
        current_tracking = dict(lead_action.tracking_data or {})
        current_tracking["outbound_call_sid"] = call_sid
        current_tracking["outbound_call_status"] = "IN_PROGRESS"
        current_tracking["outbound_call_eta"] = eta_minutes
        current_tracking["outbound_call_at"] = datetime.datetime.now(timezone.utc).isoformat()
        lead_action.tracking_data = current_tracking

        if db:
            await db.commit()

        return {
            "success": True,
            "call_sid": call_sid,
            "to": customer_phone,
            "from": from_phone,
            "eta_minutes": eta_minutes,
            "callback_url": callback_url,
        }

    def generate_outbound_confirm_twiml(self, tenant: Tenant, eta: int, action_id: str) -> str:
        """
        Generates the initial greeting TwiML prompting the homeowner to confirm on-site presence.
        """
        company_name = tenant.name or "Apex Contractors"
        gather_action = f"/api/v1/webhooks/twilio/voice/outbound-confirm/process?action_id={action_id}"

        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<Response>\n'
            f'    <Say voice="Polly.Danielle-Neural">Hello, this is the automated dispatch assistant for {company_name}. '
            f'Our technician is en route and arriving in approximately {eta} minutes. '
            'Press 1 to confirm you are on site, or press 2 to speak directly with your technician.</Say>\n'
            f'    <Gather numDigits="1" timeout="7" action="{gather_action}">\n'
            '    </Gather>\n'
            '    <Say voice="Polly.Danielle-Neural">We did not receive your input. Your technician is still en route. Goodbye.</Say>\n'
            '    <Hangup/>\n'
            '</Response>'
        )

    async def process_confirmation_selection(
        self,
        lead_action: LeadAction,
        tenant: Tenant,
        digits: str,
        db: AsyncSession,
    ) -> str:
        """
        Processes DTMF input from the homeowner:
        - Digits '1': confirms presence, marks tracking_data["homeowner_confirmed"] = True,
          and sends notification SMS to on-call technician.
        - Digits '2': live dials active on-call technician phone.
        """
        tracking = dict(lead_action.tracking_data or {})

        if digits == "1":
            tracking["homeowner_confirmed"] = True
            tracking["homeowner_confirmed_at"] = datetime.datetime.now(timezone.utc).isoformat()
            lead_action.tracking_data = tracking
            await db.commit()

            # Notify active technician via SMS
            active_techs = get_active_on_call_technicians(tenant)
            tech_phone = active_techs[0]["phone"] if active_techs else (tenant.settings.get("phone") or "+15005550006")
            customer_name = lead_action.metadata_payload.get("customer_name") or "Homeowner"
            address = (
                lead_action.metadata_payload.get("address")
                or lead_action.metadata_payload.get("job_address")
                or "customer location"
            )
            alert_msg = f"✅ Homeowner confirmed on-site! {customer_name} at {address} is ready for arrival."
            
            from_phone = (
                tenant.settings.get("twilio_phone_number")
                or settings.TWILIO_FROM_NUMBER
                or "+15005550006"
            )
            if settings.TWILIO_ACCOUNT_SID and settings.TWILIO_AUTH_TOKEN:
                try:
                    from twilio.rest import Client
                    client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
                    client.messages.create(to=tech_phone, from_=from_phone, body=alert_msg)
                except Exception as exc:
                    logger.error(f"Failed to send confirmation SMS to tech: {exc}")
            else:
                logger.info(f"[Simulation] Confirmation SMS to tech {tech_phone}: {alert_msg}")

            return (
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                '<Response>\n'
                '    <Say voice="Polly.Danielle-Neural">Thank you, your technician has been notified that you are ready. Goodbye.</Say>\n'
                '    <Hangup/>\n'
                '</Response>'
            )

        elif digits == "2":
            active_techs = get_active_on_call_technicians(tenant)
            tech_phone = (
                active_techs[0]["phone"]
                if active_techs
                else (tenant.settings.get("phone") or "+15005550006")
            )
            return (
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                '<Response>\n'
                '    <Say voice="Polly.Danielle-Neural">Connecting you directly to your technician now.</Say>\n'
                f'    <Dial timeout="20"><Number>{tech_phone}</Number></Dial>\n'
                '</Response>'
            )

        else:
            return (
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                '<Response>\n'
                '    <Say voice="Polly.Danielle-Neural">We did not recognize that option. Your technician remains en route. Goodbye.</Say>\n'
                '    <Hangup/>\n'
                '</Response>'
            )


outbound_voice_service = OutboundVoiceService()
