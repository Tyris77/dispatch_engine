import json
import uuid
from typing import Any, Dict, List, Optional
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    Form,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)
import stripe
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from app.api.deps import get_current_tenant, get_db, get_tenant_by_slug
from app.core.config import settings
from app.core.logging import logger
from app.core.security import verify_webhook_signature
from app.models.lead_action import LeadAction
from app.models.tenant import Tenant
from app.models.webhook_event import WebhookEvent
from app.schemas.lead import IntentLevel
from app.services.outbound_voice import outbound_voice_service

from app.schemas.webhook import WebhookAcknowledge, WebhookEventRead, WebhookInbound
from app.services.dispatch import (
    broadcast_unanswered_emergency_sms,
    dispatch_service,
    generate_dial_status_response,
    generate_voice_response,
    get_active_on_call_technicians,
    send_caller_followup_sms,
)
from app.services.reputation import check_and_process_sms_review
from app.services.provisioning import (
    deactivate_tenant_by_stripe_customer,
    provision_new_tenant_from_stripe,
)
from app.services.qualification import (
    qualification_service,
    qualify_lead_with_gemini,
)

router = APIRouter()


@router.post(
    "/twilio/sms",
    status_code=status.HTTP_200_OK,
    summary="Twilio Inbound SMS Webhook",
    description="Accepts x-www-form-urlencoded Twilio webhook data, ingests it as a WebhookEvent, and returns TwiML.",
)
async def twilio_inbound_sms(
    request: Request,
    db: AsyncSession = Depends(get_db),
    tenant_slug: Optional[str] = Query(None, description="Optional tenant identifier"),
) -> Response:
    """
    Inbound adapter for Twilio SMS webhooks.
    Parses x-www-form-urlencoded data (From, Body, MessageSid, To), creates WebhookEvent,
    triggers real-time qualification and dispatch, and responds with valid TwiML.
    """
    form_data = await request.form()
    payload = dict(form_data)

    from_number = payload.get("From") or ""
    body_text = payload.get("Body") or ""
    message_sid = payload.get("MessageSid") or str(uuid.uuid4())
    to_number = payload.get("To") or ""

    # 1. Resolve Tenant
    tenant: Optional[Tenant] = None
    if tenant_slug:
        query = select(Tenant).where(Tenant.slug == tenant_slug, Tenant.is_active == True)
        tenant = (await db.execute(query)).scalar_one_or_none()
    elif request.headers.get("X-Tenant-Slug"):
        header_slug = request.headers.get("X-Tenant-Slug")
        query = select(Tenant).where(Tenant.slug == header_slug, Tenant.is_active == True)
        tenant = (await db.execute(query)).scalar_one_or_none()
    else:
        # Fallback to the first active tenant in DB
        query = select(Tenant).where(Tenant.is_active == True).order_by(Tenant.created_at.asc())
        tenant = (await db.execute(query)).scalars().first()

    if not tenant:
        logger.error("No active tenant found to handle Twilio inbound SMS")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active tenant found to process SMS",
        )

    # 2. Check Idempotency using MessageSid
    query = select(WebhookEvent).where(
        WebhookEvent.tenant_id == tenant.id,
        WebhookEvent.idempotency_key == message_sid,
    )
    existing_event = (await db.execute(query)).scalar_one_or_none()
    if existing_event:
        logger.info(f"Duplicate Twilio SMS {message_sid} received; returning cached TwiML.")
        twiml_duplicate = '<?xml version="1.0" encoding="UTF-8"?><Response></Response>'
        return Response(content=twiml_duplicate, media_type="application/xml")

    # 3. Persist WebhookEvent
    event_id = uuid.uuid4()
    event = WebhookEvent(
        id=event_id,
        tenant_id=tenant.id,
        source="twilio_sms",
        event_type="sms.received",
        idempotency_key=message_sid,
        status="PROCESSED",
        payload=payload,
        headers=dict(request.headers),
    )
    db.add(event)
    await db.flush()

    # 4. Check if incoming SMS is a rating response to a prompted review
    review_outcome = await check_and_process_sms_review(
        from_phone=from_number,
        body_text=body_text,
        tenant=tenant,
        db=db,
    )
    if review_outcome:
        logger.info(f"Inbound SMS from {from_number} processed as reputation review ({review_outcome.status})")
        event.payload = {
            **event.payload,
            "reputation_review": review_outcome.model_dump(),
        }
        await db.commit()
        if review_outcome.customer_reply:
            twiml_response = (
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                '<Response>\n'
                f'    <Message>{review_outcome.customer_reply}</Message>\n'
                '</Response>'
            )
        else:
            twiml_response = '<?xml version="1.0" encoding="UTF-8"?><Response></Response>'
        return Response(content=twiml_response, media_type="application/xml")

    # 5. Trigger Real-Time Qualification & Dispatch
    try:
        qualification = await qualification_service.qualify_lead(
            tenant_settings=tenant.settings,
            lead_payload=payload,
        )

        plan = dispatch_service.create_dispatch_plan(
            tenant=tenant,
            qualification=qualification,
            lead_payload=payload,
        )

        await dispatch_service.execute_dispatch(
            db=db,
            tenant=tenant,
            event=event,
            qualification=qualification,
            plan=plan,
        )
    except Exception as exc:
        logger.error(f"Error executing dispatch for Twilio SMS {event_id}: {exc}")
        event.status = "FAILED"
        event.error_message = str(exc)

    twiml_response = '<?xml version="1.0" encoding="UTF-8"?><Response></Response>'
    return Response(content=twiml_response, media_type="application/xml")


@router.post(
    "/twilio/voice",
    status_code=status.HTTP_200_OK,
    summary="Twilio Inbound Voice Webhook",
    description="Greets caller with Neural voice and gathers spoken input for automated AI qualification.",
)
async def twilio_inbound_voice(
    request: Request,
    db: AsyncSession = Depends(get_db),
    tenant_slug: Optional[str] = Query(None, description="Optional tenant identifier"),
) -> Response:
    """
    Inbound adapter for Twilio Voice calls.
    Accepts form data (CallSid, From, To), identifies tenant, and returns
    TwiML with Polly.Danielle-Neural greeting and <Gather input="speech"> verb.
    """
    form_data = await request.form()
    payload = dict(form_data)

    # 1. Resolve Tenant
    tenant: Optional[Tenant] = None
    if tenant_slug:
        query = select(Tenant).where(Tenant.slug == tenant_slug, Tenant.is_active == True)
        tenant = (await db.execute(query)).scalar_one_or_none()
    elif request.headers.get("X-Tenant-Slug"):
        header_slug = request.headers.get("X-Tenant-Slug")
        query = select(Tenant).where(Tenant.slug == header_slug, Tenant.is_active == True)
        tenant = (await db.execute(query)).scalar_one_or_none()
    elif payload.get("tenant_slug"):
        query = select(Tenant).where(Tenant.slug == payload["tenant_slug"], Tenant.is_active == True)
        tenant = (await db.execute(query)).scalar_one_or_none()
    else:
        query = select(Tenant).where(Tenant.is_active == True).order_by(Tenant.created_at.asc())
        tenant = (await db.execute(query)).scalars().first()

    if not tenant:
        logger.error("No active tenant found to handle Twilio inbound voice call")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active tenant found to process call",
        )

    action_url = f"/api/v1/webhooks/twilio/voice/process?tenant_slug={tenant.slug}"
    greeting_message = (
        f"Thank you for calling {tenant.name}. "
        "Please describe the service you need or your emergency after the tone."
    )

    twiml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<Response>\n'
        f'    <Say voice="Polly.Danielle-Neural">{greeting_message}</Say>\n'
        f'    <Gather input="speech" action="{action_url}" timeout="5">\n'
        '    </Gather>\n'
        '    <Say voice="Polly.Danielle-Neural">We did not receive any input. Goodbye.</Say>\n'
        '    <Hangup/>\n'
        '</Response>'
    )
    return Response(content=twiml, media_type="application/xml")


@router.post(
    "/twilio/voice/process",
    status_code=status.HTTP_200_OK,
    summary="Twilio Process Voice Speech",
    description="Processes caller spoken transcript, qualifies lead urgency, and bridges emergency calls or texts scheduling links.",
)
async def twilio_process_voice(
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    tenant_slug: Optional[str] = Query(None, description="Optional tenant identifier"),
) -> Response:
    """
    Ingests SpeechResult, CallSid, and From number from Twilio speech gather.
    Qualifies speech using Gemini, persists WebhookEvent & LeadAction with channel='voice', and
    returns TwiML to either bridge the call to the emergency alert line or hang up
    and send a follow-up SMS.
    """
    form_data = await request.form()
    payload = dict(form_data)

    call_sid = payload.get("CallSid") or str(uuid.uuid4())
    from_number = payload.get("From") or ""
    to_number = payload.get("To") or ""
    speech_result = payload.get("SpeechResult") or payload.get("TranscriptionText") or ""

    # 1. Resolve Tenant
    tenant: Optional[Tenant] = None
    if tenant_slug:
        query = select(Tenant).where(Tenant.slug == tenant_slug, Tenant.is_active == True)
        tenant = (await db.execute(query)).scalar_one_or_none()
    elif request.headers.get("X-Tenant-Slug"):
        header_slug = request.headers.get("X-Tenant-Slug")
        query = select(Tenant).where(Tenant.slug == header_slug, Tenant.is_active == True)
        tenant = (await db.execute(query)).scalar_one_or_none()
    elif payload.get("tenant_slug"):
        query = select(Tenant).where(Tenant.slug == payload["tenant_slug"], Tenant.is_active == True)
        tenant = (await db.execute(query)).scalar_one_or_none()
    else:
        query = select(Tenant).where(Tenant.is_active == True).order_by(Tenant.created_at.asc())
        tenant = (await db.execute(query)).scalars().first()

    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active tenant found to process voice transcript",
        )

    # 2. Check Idempotency using CallSid
    idempotency_key = f"voice_{call_sid}"
    query = select(WebhookEvent).where(
        WebhookEvent.tenant_id == tenant.id,
        WebhookEvent.idempotency_key == idempotency_key,
    )
    existing_event = (await db.execute(query)).scalar_one_or_none()
    if existing_event:
        logger.info(f"Duplicate voice event {call_sid} received; returning cached TwiML.")
        twiml_duplicate = '<?xml version="1.0" encoding="UTF-8"?><Response><Hangup/></Response>'
        return Response(content=twiml_duplicate, media_type="application/xml")

    # 3. Persist WebhookEvent with channel="voice"
    event_id = uuid.uuid4()
    enriched_payload = {
        **payload,
        "channel": "voice",
        "raw_text": speech_result,
        "SpeechResult": speech_result,
        "caller_phone": from_number,
        "From": from_number,
        "To": to_number,
        "CallSid": call_sid,
    }
    event = WebhookEvent(
        id=event_id,
        tenant_id=tenant.id,
        source="twilio_voice",
        event_type="voice.received",
        idempotency_key=idempotency_key,
        status="PROCESSED",
        payload=enriched_payload,
        headers=dict(request.headers),
    )
    db.add(event)
    await db.flush()

    # 4. Qualify Spoken Transcript with Gemini
    try:
        raw_text_for_eval = speech_result if speech_result.strip() else "No spoken inquiry detected."
        qualification = await qualify_lead_with_gemini(
            raw_text=raw_text_for_eval,
            tenant_context=tenant.settings,
        )

        plan = dispatch_service.create_dispatch_plan(
            tenant=tenant,
            qualification=qualification,
            lead_payload=enriched_payload,
        )

        action = await dispatch_service.execute_dispatch(
            db=db,
            tenant=tenant,
            event=event,
            qualification=qualification,
            plan=plan,
        )
        action.metadata_payload = {
            **action.metadata_payload,
            "channel": "voice",
            "speech_result": speech_result,
        }
        await db.flush()

        # 5. Generate Voice TwiML
        twiml_response = generate_voice_response(qualification=qualification, tenant=tenant)

        # 6. If not emergency/high urgency, asynchronously send follow-up scheduling SMS
        is_urgent = (
            qualification.intent_level in [IntentLevel.HIGH, IntentLevel.EMERGENCY]
            or qualification.qualification_score >= 0.80
        )
        if not is_urgent and from_number:
            background_tasks.add_task(
                send_caller_followup_sms,
                from_number,
                tenant,
                language=getattr(qualification, "detected_language", "en"),
            )

        return Response(content=twiml_response, media_type="application/xml")

    except Exception as exc:
        logger.error(f"Error processing voice lead for CallSid {call_sid}: {exc}")
        event.status = "FAILED"
        event.error_message = str(exc)
        fallback_twiml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<Response>\n'
            '    <Say>Thank you for calling. We have recorded your message and will follow up shortly. Goodbye.</Say>\n'
            '    <Hangup/>\n'
            '</Response>'
        )
        return Response(content=fallback_twiml, media_type="application/xml")


@router.post(
    "/twilio/voice/dial-status",
    status_code=status.HTTP_200_OK,
    summary="Twilio Voice Dial Status Callback",
    description="Handles cascading multi-tech escalation when a dial leg completes, fails, or misses.",
)
async def twilio_voice_dial_status(
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    tenant_slug: Optional[str] = Query(None, description="Tenant identifier"),
    step: int = Query(1, description="Current escalation tier step (1=primary, 2=backup, 3=owner)"),
) -> Response:
    """
    Callback endpoint triggered by Twilio when a <Dial> leg terminates.
    If DialCallStatus is no-answer, busy, or failed:
    - Step 1: dials backup technician (Step 2).
    - Step 2: dials operations manager / owner (Step 3).
    - Step 3+: drops emergency voicemail box (<Record>) and blasts priority SMS alerts to all on-call technicians.
    """
    form_data = await request.form()
    payload = dict(form_data)

    dial_call_status = payload.get("DialCallStatus") or payload.get("CallStatus") or "no-answer"
    caller_phone = payload.get("From") or payload.get("caller_phone") or ""
    step_val = int(payload.get("step") or step or 1)

    # 1. Resolve Tenant
    tenant: Optional[Tenant] = None
    if tenant_slug:
        query = select(Tenant).where(Tenant.slug == tenant_slug, Tenant.is_active == True)
        tenant = (await db.execute(query)).scalar_one_or_none()
    elif request.headers.get("X-Tenant-Slug"):
        header_slug = request.headers.get("X-Tenant-Slug")
        query = select(Tenant).where(Tenant.slug == header_slug, Tenant.is_active == True)
        tenant = (await db.execute(query)).scalar_one_or_none()
    elif payload.get("tenant_slug"):
        query = select(Tenant).where(Tenant.slug == payload["tenant_slug"], Tenant.is_active == True)
        tenant = (await db.execute(query)).scalar_one_or_none()
    else:
        query = select(Tenant).where(Tenant.is_active == True).order_by(Tenant.created_at.asc())
        tenant = (await db.execute(query)).scalars().first()

    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active tenant found to handle dial-status escalation",
        )

    # 2. Check if dial was answered/completed
    status_lower = dial_call_status.lower()
    if status_lower in ["completed", "answered"]:
        twiml = '<?xml version="1.0" encoding="UTF-8"?>\n<Response>\n    <Hangup/>\n</Response>'
        return Response(content=twiml, media_type="application/xml")

    # 3. If final step failed, trigger emergency SMS blast to all technicians
    active_techs = get_active_on_call_technicians(tenant)
    owner_phone = (
        tenant.settings.get("fallback_owner_phone")
        or tenant.settings.get("alert_phone_number")
        or tenant.settings.get("phone")
    )

    is_final_step = (
        step_val >= 3
        or (step_val == 2 and not owner_phone)
        or (step_val == 1 and len(active_techs) <= 1 and not owner_phone)
    )

    if is_final_step:
        background_tasks.add_task(
            broadcast_unanswered_emergency_sms,
            tenant,
            caller_phone,
        )

    # 4. Generate next escalation TwiML
    twiml = generate_dial_status_response(
        tenant=tenant,
        step=step_val,
        dial_call_status=dial_call_status,
        caller_phone=caller_phone,
    )
    return Response(content=twiml, media_type="application/xml")


@router.post(
    "/twilio/voice/outbound-confirm",
    status_code=status.HTTP_200_OK,
    summary="Outbound Voice Arrival Confirmation Greeting",
    description="Speaks neural greeting to customer when technician is en route, gathering DTMF 1 (confirmed) or 2 (call tech).",
)
async def twilio_voice_outbound_confirm(
    request: Request,
    db: AsyncSession = Depends(get_db),
    action_id: Optional[uuid.UUID] = Query(None),
    eta: int = Query(20),
) -> Response:
    """
    Called by Twilio when customer answers outbound pre-arrival call.
    Emits Amazon Polly Neural speech greeting and <Gather> for DTMF response.
    """
    if not action_id:
        form_data = await request.form()
        raw_id = form_data.get("action_id") or request.query_params.get("action_id")
        if raw_id:
            try:
                action_id = uuid.UUID(str(raw_id))
            except ValueError:
                pass

    tenant = None
    if action_id:
        stmt = (
            select(LeadAction)
            .options(selectinload(LeadAction.tenant))
            .where(LeadAction.id == action_id)
        )
        action = (await db.execute(stmt)).scalar_one_or_none()
        if action:
            tenant = action.tenant

    if not tenant:
        query = select(Tenant).where(Tenant.is_active == True).order_by(Tenant.created_at.asc())
        tenant = (await db.execute(query)).scalars().first()

    twiml = outbound_voice_service.generate_outbound_confirm_twiml(
        tenant=tenant,
        eta=eta,
        action_id=str(action_id) if action_id else "",
    )
    return Response(content=twiml, media_type="application/xml")


@router.post(
    "/twilio/voice/outbound-confirm/process",
    status_code=status.HTTP_200_OK,
    summary="Process Outbound Voice Arrival Confirmation DTMF",
    description="Processes DTMF 1 (homeowner confirmed) or DTMF 2 (direct dial technician).",
)
async def twilio_voice_outbound_confirm_process(
    request: Request,
    db: AsyncSession = Depends(get_db),
    action_id: Optional[uuid.UUID] = Query(None),
) -> Response:
    """
    Handles DTMF gather from outbound confirmation call:
    - Digits 1: Confirms homeowner is on site, sets flag, alerts technician via SMS.
    - Digits 2: Bridges call to technician's mobile phone.
    """
    form_data = await request.form()
    payload = dict(form_data)
    digits = payload.get("Digits") or request.query_params.get("Digits") or ""

    if not action_id:
        raw_id = payload.get("action_id") or request.query_params.get("action_id")
        if raw_id:
            try:
                action_id = uuid.UUID(str(raw_id))
            except ValueError:
                pass

    if not action_id:
        fallback = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<Response>\n'
            '    <Say voice="Polly.Danielle-Neural">Action reference missing. Goodbye.</Say>\n'
            '    <Hangup/>\n'
            '</Response>'
        )
        return Response(content=fallback, media_type="application/xml")

    stmt = (
        select(LeadAction)
        .options(selectinload(LeadAction.tenant))
        .where(LeadAction.id == action_id)
    )
    action = (await db.execute(stmt)).scalar_one_or_none()
    if not action:
        fallback = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<Response>\n'
            '    <Say voice="Polly.Danielle-Neural">Dispatch record not found. Goodbye.</Say>\n'
            '    <Hangup/>\n'
            '</Response>'
        )
        return Response(content=fallback, media_type="application/xml")

    tenant = action.tenant
    twiml = await outbound_voice_service.process_confirmation_selection(
        lead_action=action,
        tenant=tenant,
        digits=digits,
        db=db,
    )
    return Response(content=twiml, media_type="application/xml")


@router.post(
    "/stripe",
    status_code=status.HTTP_200_OK,
    summary="Stripe Webhook Receiver",
    description="Processes automated tenant provisioning on checkout completion and deactivation on subscription cancellation.",
)
async def stripe_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
    stripe_signature: Optional[str] = Header(None, alias="stripe-signature"),
) -> Dict[str, Any]:
    raw_body = await request.body()

    # 1. Verify Stripe Webhook Signature if secret configured
    if settings.STRIPE_WEBHOOK_SECRET:
        if not stripe_signature:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing stripe-signature header",
            )
        try:
            event = stripe.Webhook.construct_event(
                payload=raw_body,
                sig_header=stripe_signature,
                secret=settings.STRIPE_WEBHOOK_SECRET,
            )
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid payload",
            )
        except stripe.SignatureVerificationError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid signature",
            )
    else:
        # Development / Sandbox fallback without secret
        try:
            event = json.loads(raw_body.decode("utf-8"))
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid JSON payload",
            )

    event_type = event.get("type")
    data_object = event.get("data", {}).get("object", {})

    logger.info(f"Received Stripe webhook event: {event_type}")

    # 2. Handle Checkout Completed (Self-Serve Auto-Provisioning)
    if event_type == "checkout.session.completed":
        tenant = await provision_new_tenant_from_stripe(data_object, db)
        return {
            "status": "success",
            "event_type": event_type,
            "tenant_slug": tenant.slug,
            "tenant_id": str(tenant.id),
        }

    # 3. Handle Subscription Cancellation / Deletion
    elif event_type == "customer.subscription.deleted":
        customer_id = data_object.get("customer") or ""
        subscription_id = data_object.get("id") or ""
        tenant = await deactivate_tenant_by_stripe_customer(
            customer_id=customer_id,
            subscription_id=subscription_id,
            db_session=db,
        )
        return {
            "status": "success",
            "event_type": event_type,
            "deactivated": tenant is not None,
            "tenant_slug": tenant.slug if tenant else None,
        }

    return {"status": "success", "event_type": event_type}


@router.post(
    "/{tenant_slug}",
    response_model=WebhookAcknowledge,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Ingest inbound webhook for tenant",
    description="Secure webhook receiver with HMAC signature validation, idempotency checks, and automated dispatch pipeline.",
)
async def ingest_webhook(
    tenant_slug: str,
    webhook_in: WebhookInbound,
    request: Request,
    tenant: Tenant = Depends(get_tenant_by_slug),
    db: AsyncSession = Depends(get_db),
    x_signature_256: Optional[str] = Header(None, alias="X-Signature-256"),
    x_hub_signature_256: Optional[str] = Header(None, alias="X-Hub-Signature-256"),
) -> WebhookAcknowledge:
    # 1. Verify HMAC Signature if provided or if enforced in tenant settings
    signature = x_signature_256 or x_hub_signature_256
    raw_body = await request.body()

    require_signature = tenant.settings.get("require_webhook_signature", False)
    if signature:
        if not verify_webhook_signature(raw_body, tenant.webhook_secret, signature):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid HMAC signature",
            )
    elif require_signature:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing required HMAC signature (X-Signature-256)",
        )

    # 2. Check Idempotency Key
    if webhook_in.idempotency_key:
        query = select(WebhookEvent).where(
            WebhookEvent.tenant_id == tenant.id,
            WebhookEvent.idempotency_key == webhook_in.idempotency_key,
        )
        existing_event = (await db.execute(query)).scalar_one_or_none()
        if existing_event:
            return WebhookAcknowledge(
                received=True,
                event_id=existing_event.id,
                status="DUPLICATE",
                message="Duplicate webhook event received; ignored via idempotency key.",
            )

    # 3. Persist Event
    event_id = uuid.uuid4()
    event = WebhookEvent(
        id=event_id,
        tenant_id=tenant.id,
        source=webhook_in.source,
        event_type=webhook_in.event_type,
        idempotency_key=webhook_in.idempotency_key,
        status="PROCESSED",
        payload=webhook_in.payload,
        headers=dict(request.headers),
    )
    db.add(event)
    await db.flush()

    # 4. Trigger Qualification & Dispatch
    try:
        qualification = await qualification_service.qualify_lead(
            tenant_settings=tenant.settings,
            lead_payload=webhook_in.payload,
        )

        plan = dispatch_service.create_dispatch_plan(
            tenant=tenant,
            qualification=qualification,
            lead_payload=webhook_in.payload,
        )

        await dispatch_service.execute_dispatch(
            db=db,
            tenant=tenant,
            event=event,
            qualification=qualification,
            plan=plan,
        )

        return WebhookAcknowledge(
            received=True,
            event_id=event.id,
            status="PROCESSED",
            message=f"Event ingested and dispatched to '{plan.target_route}'.",
        )
    except Exception as exc:
        logger.error(f"Error processing webhook event {event.id}: {exc}")
        event.status = "FAILED"
        event.error_message = str(exc)
        return WebhookAcknowledge(
            received=True,
            event_id=event.id,
            status="FAILED",
            message=f"Event stored but dispatch failed: {exc}",
        )


@router.get(
    "/events",
    response_model=List[WebhookEventRead],
    summary="List tenant webhook events",
)
async def list_webhook_events(
    limit: int = 50,
    offset: int = 0,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> List[WebhookEventRead]:
    query = (
        select(WebhookEvent)
        .where(WebhookEvent.tenant_id == tenant.id)
        .order_by(WebhookEvent.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    result = await db.execute(query)
    return list(result.scalars().all())
