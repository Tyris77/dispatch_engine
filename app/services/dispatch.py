import asyncio
import datetime
import uuid
from typing import Any, Dict, List, Optional
import httpx
from sqlalchemy.ext.asyncio import AsyncSession


from app.core.config import settings
from app.core.logging import logger
from app.models.lead_action import LeadAction
from app.models.tenant import Tenant
from app.models.webhook_event import WebhookEvent
from app.schemas.lead import IntentLevel, LeadDispatchPlan, LeadQualificationOutput
from app.services.crm_sync import crm_sync_service


class DispatchService:
    """Calculates operational routing plans and orchestrates downstream action execution."""

    def create_dispatch_plan(
        self,
        tenant: Tenant,
        qualification: LeadQualificationOutput,
        lead_payload: Dict[str, Any],
    ) -> LeadDispatchPlan:
        """Derive routing destination, priority tier, and target systems based on tenant rules."""
        rules = tenant.settings.get("routing_rules", {})
        default_route = rules.get("default_route", "general_inbox")

        if qualification.intent_level == IntentLevel.SPAM or not qualification.is_qualified:
            return LeadDispatchPlan(
                target_route="disqualified_archive",
                priority_tier="LOW",
                sync_destinations=[],
                enrichment_data={"reason": qualification.reasoning},
            )

        if qualification.intent_level == IntentLevel.EMERGENCY:
            priority = "EMERGENCY"
            target_route = rules.get("emergency_route", "emergency_dispatch_queue")
        elif qualification.qualification_score >= 0.75 or qualification.intent_level == IntentLevel.HIGH:
            priority = "HIGH"
            target_route = rules.get("high_priority_route", "vip_sales_queue")
        else:
            priority = "NORMAL"
            target_route = default_route

        # Assign rep based on geography, round-robin, or tenant config
        assigned_rep = rules.get("default_rep_id")

        return LeadDispatchPlan(
            target_route=target_route,
            priority_tier=priority,
            assigned_rep=assigned_rep,
            sync_destinations=rules.get("sync_destinations", ["crm", "webhook"]),
            enrichment_data={
                "qualification_score": qualification.qualification_score,
                "recommended_action": qualification.recommended_action,
                "pain_points": qualification.pain_points,
            },
        )

    async def execute_dispatch_plan(
        self,
        lead_action: LeadAction,
        tenant: Tenant,
        lead_payload: Optional[Dict[str, Any]] = None,
    ) -> LeadAction:
        """
        Executes immediate dispatch actions based on urgency:
        1. If urgency is HIGH or EMERGENCY, trigger Twilio outbound SMS notification to tenant's alert phone.
        2. If configured, dispatch an asynchronous HTTP POST with the full lead payload to tenant's endpoint.
        """
        qualification_meta = lead_action.metadata_payload.get("qualification", {})
        intent_level = qualification_meta.get("intent_level")
        score = lead_action.qualification_score or 0.0

        is_high_urgency = (
            intent_level in [IntentLevel.HIGH.value, IntentLevel.EMERGENCY.value, "HIGH", "EMERGENCY"]
            or score >= 0.8
            or "EMERGENCY" in lead_action.action_type
        )

        # Dynamic Surge & After-Hours Pricing Assessment
        from app.services.surge import surge_pricing_service
        surge_assessment = surge_pricing_service.apply_surge_to_lead(lead_action=lead_action, tenant=tenant)

        # 1. Trigger Twilio outbound SMS notification if HIGH or EMERGENCY
        if is_high_urgency:
            alert_phone = tenant.settings.get("alert_phone_number") or tenant.settings.get("phone")
            base_url = tenant.settings.get("base_url") or "http://localhost:8000"
            tracking_link = f"{base_url}/track/{lead_action.id}"
            surge_note = f"\nSurge Active: ${surge_assessment.diagnostic_fee:.0f} ({surge_assessment.surge_reason})" if surge_assessment.is_surge_active else ""
            if alert_phone:
                message_body = (
                    f"[URGENT DISPATCH ALERT] Tenant: {tenant.name}\n"
                    f"Lead: {lead_action.lead_external_id}\n"
                    f"Urgency: {intent_level or 'HIGH'}\n"
                    f"Action: {lead_action.action_type}\n"
                    f"Track your technician's arrival live: {tracking_link}"
                    f"{surge_note}"
                )
                is_valid_twilio = bool(
                    settings.TWILIO_ACCOUNT_SID
                    and settings.TWILIO_AUTH_TOKEN
                    and not settings.TWILIO_ACCOUNT_SID.startswith("your-")
                    and not settings.TWILIO_ACCOUNT_SID.startswith("AC_mock")
                    and settings.TWILIO_ACCOUNT_SID not in ("mock", "placeholder", "test", "none")
                )
                if is_valid_twilio:
                    try:
                        from twilio.rest import Client

                        def _send_twilio_sms():
                            twilio_client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
                            from_number = settings.TWILIO_FROM_NUMBER or "+15005550006"
                            return twilio_client.messages.create(
                                to=alert_phone,
                                from_=from_number,
                                body=message_body,
                            )

                        message = await asyncio.wait_for(asyncio.to_thread(_send_twilio_sms), timeout=3.0)
                        logger.info(f"Twilio alert SMS dispatched to {alert_phone} (SID: {message.sid})")
                        lead_action.metadata_payload.setdefault("notifications", {})["twilio_sms_sid"] = message.sid
                        lead_action.metadata_payload.setdefault("notifications", {})["tracking_url"] = tracking_link
                    except Exception as twilio_err:
                        logger.error(f"Twilio SMS dispatch failed: {twilio_err}")
                        lead_action.metadata_payload.setdefault("notifications", {})["twilio_sms_error"] = str(twilio_err)
                else:
                    logger.info(f"[Simulation] Twilio SMS alert queued for {alert_phone}: {message_body}")
                    lead_action.metadata_payload.setdefault("notifications", {})["twilio_sms"] = "simulated"
                    lead_action.metadata_payload.setdefault("notifications", {})["tracking_url"] = tracking_link

        # 2. Dispatch asynchronous HTTP POST with full lead payload to external webhook/CRM if configured
        destination_url = (
            tenant.settings.get("webhook_url")
            or tenant.settings.get("crm_webhook_url")
            or tenant.settings.get("destination_url")
        )

        if destination_url:
            try:
                async with httpx.AsyncClient(timeout=3.0) as http_client:
                    post_payload = {
                        "event_id": str(lead_action.webhook_event_id),
                        "action_id": str(lead_action.id),
                        "lead_external_id": lead_action.lead_external_id,
                        "qualification_score": lead_action.qualification_score,
                        "qualification": qualification_meta,
                        "action_type": lead_action.action_type,
                        "payload": lead_payload or {},
                    }
                    response = await http_client.post(destination_url, json=post_payload)
                    lead_action.metadata_payload.setdefault("dispatch_http", {})["status_code"] = response.status_code
                    lead_action.crm_sync_status = "SYNCED" if response.is_success else "FAILED"
                    logger.info(f"Dispatched HTTP POST to {destination_url} (Status: {response.status_code})")
            except Exception as http_err:
                logger.error(f"Failed HTTP POST dispatch to {destination_url}: {http_err}")
                lead_action.crm_sync_status = "FAILED"
                lead_action.metadata_payload.setdefault("dispatch_http", {})["error"] = str(http_err)

        lead_action.dispatch_status = "COMPLETED"

        return lead_action

    async def execute_dispatch(
        self,
        db: AsyncSession,
        tenant: Tenant,
        event: WebhookEvent,
        qualification: LeadQualificationOutput,
        plan: LeadDispatchPlan,
    ) -> LeadAction:
        """Persist LeadAction and execute dispatch plan."""
        lead_id = str(event.payload.get("From") or event.payload.get("email") or event.payload.get("lead_id") or event.id)

        action = LeadAction(
            id=uuid.uuid4(),
            tenant_id=tenant.id,
            webhook_event_id=event.id,
            lead_external_id=lead_id,
            qualification_score=qualification.qualification_score,
            qualification_summary=qualification.reasoning,
            action_type=f"DISPATCH_{plan.target_route.upper()}",
            dispatch_status="QUEUED",
            crm_sync_status="PENDING",
            metadata_payload={
                "plan": plan.model_dump(),
                "qualification": qualification.model_dump(),
            },
        )
        db.add(action)
        await db.flush()

        logger.info(
            f"Tenant {tenant.slug}: Created LeadAction {action.id} (Route: '{plan.target_route}', "
            f"Priority: {plan.priority_tier}, Score: {qualification.qualification_score})"
        )

        # Run execute_dispatch_plan for SMS alerts & HTTP POST fanout
        await self.execute_dispatch_plan(action, tenant, event.payload)

        # Optional secondary CRM sync if enabled in plan destinations
        if "crm" in plan.sync_destinations and action.crm_sync_status == "PENDING":
            crm_result = await crm_sync_service.sync_lead(tenant, action, event.payload)
            action.crm_sync_status = "SYNCED" if crm_result else "FAILED"

        return action


def get_active_on_call_technicians(
    tenant: Tenant,
    current_dt: Optional[datetime.datetime] = None,
) -> List[Dict[str, Any]]:
    """
    Filters and prioritizes technicians from tenant.settings['on_call_roster'].
    Determines active status based on the current day of the week, sorted by priority ascending.
    """
    roster = tenant.settings.get("on_call_roster", [])
    if not roster or not isinstance(roster, list):
        return []

    now = current_dt or datetime.datetime.now(datetime.timezone.utc)
    current_day = now.strftime("%A")  # e.g., 'Monday', 'Friday'

    active_techs = []
    for tech in roster:
        if not isinstance(tech, dict) or not tech.get("phone"):
            continue
        active_days = tech.get("active_days")
        # If active_days is not specified or current day is in active_days
        if not active_days or any(current_day.lower() == str(d).strip().lower() for d in active_days):
            active_techs.append(tech)

    # Sort by priority ascending (1 = primary on-call, 2 = backup, etc.)
    active_techs.sort(key=lambda t: int(t.get("priority", 99)))
    return active_techs


def generate_voice_response(
    qualification: LeadQualificationOutput,
    tenant: Tenant,
    current_dt: Optional[datetime.datetime] = None,
) -> str:
    """
    Generate TwiML response based on lead qualification:
    - High/Emergency:
      - If on_call_roster configured: resolves active priority technician and initiates cascading escalation.
      - Else: Bridges caller to tenant's emergency alert phone via <Dial timeout="25">.
    - Normal/Low/Spam: Confirms request receipt, advises follow-up SMS sent, and hangs up.
    - Supports bilingual Amazon Polly Lupe Neural voice when Spanish is detected.
    """
    is_urgent = (
        qualification.intent_level in [IntentLevel.HIGH, IntentLevel.EMERGENCY]
        or qualification.qualification_score >= 0.80
    )
    is_spanish = getattr(qualification, "detected_language", "en") == "es"

    roster_configured = bool(tenant.settings.get("on_call_roster"))
    active_techs = get_active_on_call_technicians(tenant, current_dt=current_dt) if roster_configured else []

    if is_spanish:
        if is_urgent:
            if roster_configured and active_techs:
                primary_tech = active_techs[0]
                action_url = f"/api/v1/webhooks/twilio/voice/dial-status?tenant_slug={tenant.slug}&amp;step=1"
                say_text = qualification.caller_response or "Conectando con nuestro técnico de emergencia de guardia ahora mismo."
                return (
                    '<?xml version="1.0" encoding="UTF-8"?>\n'
                    '<Response>\n'
                    f'    <Say voice="Polly.Lupe-Neural" language="es-US">{say_text}</Say>\n'
                    f'    <Dial timeout="15" action="{action_url}"><Number>{primary_tech["phone"]}</Number></Dial>\n'
                    '</Response>'
                )
            else:
                alert_phone = (
                    tenant.settings.get("alert_phone_number")
                    or tenant.settings.get("phone")
                    or "+15005550006"
                )
                say_text = qualification.caller_response or "Conectando con nuestra línea de emergencia ahora mismo."
                return (
                    '<?xml version="1.0" encoding="UTF-8"?>\n'
                    '<Response>\n'
                    f'    <Say voice="Polly.Lupe-Neural" language="es-US">{say_text}</Say>\n'
                    f'    <Dial timeout="25"><Number>{alert_phone}</Number></Dial>\n'
                    '</Response>'
                )
        else:
            say_text = (
                qualification.caller_response
                or "Gracias. Hemos recibido su solicitud y le hemos enviado un mensaje de texto para programar una visita técnica. Hasta luego."
            )
            return (
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                '<Response>\n'
                f'    <Say voice="Polly.Lupe-Neural" language="es-US">{say_text}</Say>\n'
                '    <Hangup/>\n'
                '</Response>'
            )

    # Standard English Flow
    if is_urgent:
        if roster_configured and active_techs:
            primary_tech = active_techs[0]
            action_url = f"/api/v1/webhooks/twilio/voice/dial-status?tenant_slug={tenant.slug}&amp;step=1"
            return (
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                '<Response>\n'
                '    <Say>Connecting you to our emergency line now.</Say>\n'
                f'    <Dial timeout="15" action="{action_url}"><Number>{primary_tech["phone"]}</Number></Dial>\n'
                '</Response>'
            )
        else:
            alert_phone = (
                tenant.settings.get("alert_phone_number")
                or tenant.settings.get("phone")
                or "+15005550006"
            )
            return (
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                '<Response>\n'
                '    <Say>Connecting you to our emergency line now.</Say>\n'
                f'    <Dial timeout="25"><Number>{alert_phone}</Number></Dial>\n'
                '</Response>'
            )
    else:
        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<Response>\n'
            '    <Say>Thank you. We have received your request and sent a text to your phone to schedule an estimate. Goodbye.</Say>\n'
            '    <Hangup/>\n'
            '</Response>'
        )


def generate_dial_status_response(
    tenant: Tenant,
    step: int,
    dial_call_status: str,
    caller_phone: Optional[str] = None,
    current_dt: Optional[datetime.datetime] = None,
) -> str:
    """
    Handles Twilio <Dial> action callbacks for the multi-tech escalation tree:
    - If answered/completed: Hangup.
    - If missed (no-answer, busy, failed, canceled):
      - step 1: dial backup technician (step 2) or advance to owner.
      - step 2: dial fallback owner phone (step 3).
      - step 3+: drop emergency voicemail box (<Record>) and blast priority SMS to all technicians.
    """
    status_lower = (dial_call_status or "").lower()
    if status_lower in ["completed", "answered"]:
        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<Response>\n'
            '    <Hangup/>\n'
            '</Response>'
        )

    active_techs = get_active_on_call_technicians(tenant, current_dt=current_dt)
    owner_phone = (
        tenant.settings.get("fallback_owner_phone")
        or tenant.settings.get("alert_phone_number")
        or tenant.settings.get("phone")
    )

    # Step 1 missed -> Dial Backup Tech (step 2) or Owner
    if step == 1:
        if len(active_techs) > 1:
            backup_tech = active_techs[1]
            action_url = f"/api/v1/webhooks/twilio/voice/dial-status?tenant_slug={tenant.slug}&amp;step=2"
            return (
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                '<Response>\n'
                '    <Say voice="Polly.Danielle-Neural">Primary technician unavailable. Connecting to backup emergency technician.</Say>\n'
                f'    <Dial timeout="15" action="{action_url}"><Number>{backup_tech["phone"]}</Number></Dial>\n'
                '</Response>'
            )
        elif owner_phone:
            action_url = f"/api/v1/webhooks/twilio/voice/dial-status?tenant_slug={tenant.slug}&amp;step=3"
            return (
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                '<Response>\n'
                '    <Say voice="Polly.Danielle-Neural">Technician unavailable. Transferring your call to our emergency operations manager.</Say>\n'
                f'    <Dial timeout="15" action="{action_url}"><Number>{owner_phone}</Number></Dial>\n'
                '</Response>'
            )

    # Step 2 missed -> Dial Owner (step 3)
    if step == 2:
        if owner_phone:
            action_url = f"/api/v1/webhooks/twilio/voice/dial-status?tenant_slug={tenant.slug}&amp;step=3"
            return (
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                '<Response>\n'
                '    <Say voice="Polly.Danielle-Neural">Backup technician unavailable. Escalating to our operations manager.</Say>\n'
                f'    <Dial timeout="15" action="{action_url}"><Number>{owner_phone}</Number></Dial>\n'
                '</Response>'
            )

    # Step 3+ missed or no further escalation targets -> Emergency Voicemail Box
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<Response>\n'
        '    <Say voice="Polly.Danielle-Neural">All emergency technicians are currently responding to active jobs. Please leave your name, address, and emergency description after the tone, and our team will be dispatched immediately.</Say>\n'
        '    <Record maxLength="60" timeout="5"/>\n'
        '    <Say voice="Polly.Danielle-Neural">Thank you. Your emergency message has been received.</Say>\n'
        '    <Hangup/>\n'
        '</Response>'
    )


async def broadcast_unanswered_emergency_sms(
    tenant: Tenant,
    caller_phone: str,
) -> List[str]:
    """
    Blasts priority SMS alert to all on-call technicians and the owner when all voice tiers fail.
    """
    phones = set()
    for tech in tenant.settings.get("on_call_roster", []):
        if isinstance(tech, dict) and tech.get("phone"):
            phones.add(tech["phone"])
    owner_phone = tenant.settings.get("fallback_owner_phone") or tenant.settings.get("alert_phone_number")
    if owner_phone:
        phones.add(owner_phone)

    msg = f"🚨 UNANSWERED EMERGENCY CALL from {caller_phone or 'Unknown'}! All escalation tiers failed to connect. Call customer immediately!"
    dispatched = []
    from_phone = tenant.settings.get("twilio_phone_number") or settings.TWILIO_FROM_NUMBER or "+15005550006"

    for phone in phones:
        if settings.TWILIO_ACCOUNT_SID and settings.TWILIO_AUTH_TOKEN:
            try:
                from twilio.rest import Client
                client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
                client.messages.create(to=phone, from_=from_phone, body=msg)
                dispatched.append(phone)
            except Exception as exc:
                logger.error(f"Failed to blast emergency SMS to {phone}: {exc}")
        else:
            logger.info(f"[Simulation] Emergency SMS blast to {phone}: {msg}")
            dispatched.append(phone)

    return dispatched


async def send_caller_followup_sms(
    to_number: str,
    tenant: Tenant,
    message_body: Optional[str] = None,
    neighborhood_context: Optional[str] = None,
    language: str = "en",
) -> bool:
    """
    Asynchronously fires a follow-up scheduling SMS to the caller's phone number.
    Uses Twilio API if credentials are configured, or logs simulated outbound dispatch.
    Appends neighborhood route-density clustering suggestion when context is provided.
    """
    if not to_number:
        return False

    tenant_name = tenant.name or "our team"
    booking_url = f"https://schedule.example.com/{tenant.slug}"

    if message_body:
        body = message_body
    elif language == "es":
        body = f"Hola, gracias por llamar a {tenant_name}! Puede elegir un horario conveniente para una visita técnica aquí: {booking_url}"
        if neighborhood_context:
            body += f" Tenemos una cuadrilla programada en su zona este jueves por la mañana. Toque aquí para reservar su turno de ruta: {booking_url}"
    else:
        body = f"Hi, thank you for calling {tenant_name}! You can pick a convenient time for an on-site estimate here: {booking_url}"
        if neighborhood_context:
            body += f" We have a crew scheduled in your area on Thursday morning. Tap here to lock in that route slot: {booking_url}"

    if settings.TWILIO_ACCOUNT_SID and settings.TWILIO_AUTH_TOKEN:
        try:
            from twilio.rest import Client

            client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
            from_number = (
                tenant.settings.get("twilio_phone_number")
                or settings.TWILIO_FROM_NUMBER
                or "+15005550006"
            )
            message = client.messages.create(
                to=to_number,
                from_=from_number,
                body=body,
            )
            logger.info(f"Sent follow-up SMS to {to_number} (SID: {message.sid})")
            return True
        except Exception as exc:
            logger.error(f"Failed to send follow-up SMS to {to_number}: {exc}")
            return False
    else:
        logger.info(f"[Simulation] Follow-up SMS queued for {to_number}: {body}")
        return True


dispatch_service = DispatchService()
