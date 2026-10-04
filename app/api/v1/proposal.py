import datetime
import os
import uuid
from typing import Any, Dict, Optional
from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, Response, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.api.deps import get_db
from app.core.config import settings
from app.core.logging import logger
from app.models.lead_action import LeadAction
from app.models.tenant import Tenant
from app.schemas.proposal import (
    ContractSignatureSubmission,
    ProposalEstimate,
    ProposalResponse,
    SignedContractData,
)
from app.schemas.vision import EquipmentDiagnosticReport
from app.services.crm_sync import sync_lead_to_external_crm
from app.services.financing import financing_service
from app.services.proposal import calculate_membership_offer, generate_tiered_proposal


router = APIRouter()

# Locate templates directory
TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "templates")
templates = Jinja2Templates(directory=TEMPLATES_DIR)


async def send_proposal_sms(
    to_phone: str,
    message_body: str,
    from_number: Optional[str] = None,
) -> bool:
    """Dispatches SMS notification to customer or contractor alert phone."""
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
            logger.info(f"Dispatched proposal SMS to {to_phone} (SID: {message.sid})")
            return True
        except Exception as exc:
            logger.error(f"Failed to send proposal SMS to {to_phone}: {exc}")
            return False
    else:
        logger.info(f"[Simulation] Proposal SMS to {to_phone}: {message_body}")
        return True


@router.get(
    "/proposal/{action_id}",
    response_class=HTMLResponse,
    summary="Good-Better-Best Proposal View",
    description="Renders mobile-first tiered proposal with touch/mouse e-signature pad.",
)
async def get_proposal(
    action_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    format: Optional[str] = Query(None),
) -> Response:
    # 1. Fetch LeadAction
    query = select(LeadAction).where(LeadAction.id == action_id)
    lead_action = (await db.execute(query)).scalar_one_or_none()

    if not lead_action:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Lead action '{action_id}' not found",
        )

    # 2. Fetch associated Tenant
    tenant_query = select(Tenant).where(Tenant.id == lead_action.tenant_id)
    tenant = (await db.execute(tenant_query)).scalar_one_or_none()

    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Associated tenant not found",
        )

    # 3. Check / parse diagnostic report
    report_dict = lead_action.diagnostic_data or lead_action.metadata_payload.get("diagnostic_report")
    diagnostic = None
    if report_dict:
        try:
            diagnostic = EquipmentDiagnosticReport.model_validate(report_dict)
        except Exception as exc:
            logger.warning(f"Error parsing diagnostic data for proposal {action_id}: {exc}")

    # 4. Generate or load ProposalEstimate
    if lead_action.proposal_data:
        try:
            estimate = ProposalEstimate.model_validate(lead_action.proposal_data)
        except Exception:
            estimate = generate_tiered_proposal(diagnostic, tenant.settings)
            lead_action.proposal_data = estimate.model_dump()
            await db.commit()
    else:
        estimate = generate_tiered_proposal(diagnostic, tenant.settings)
        lead_action.proposal_data = estimate.model_dump()
        await db.commit()

    is_signed = bool(lead_action.signed_contract)
    signed_contract = lead_action.signed_contract or {}

    # 5. Compute default membership offer
    default_price = estimate.options[0].price_estimate if estimate.options else 500.0
    membership_offer = calculate_membership_offer(default_price, tenant.settings)

    # 5b. Compute customer financing breakdowns for each tier
    financing_breakdowns: Dict[str, Any] = {}
    for opt in estimate.options:
        breakdown = financing_service.calculate_financing_plans(
            cash_price=opt.price_estimate,
            deposit=0.0,
            tenant_settings=tenant.settings,
        )
        financing_breakdowns[opt.tier_name] = breakdown.model_dump()

    # 6. Handle JSON format request
    accept_header = request.headers.get("accept", "").lower()
    if format == "json" or "application/json" in accept_header:
        resp = ProposalResponse(
            action_id=str(lead_action.id),
            tenant_slug=tenant.slug,
            tenant_name=tenant.name,
            estimate=estimate,
            is_signed=is_signed,
            signed_contract=signed_contract if is_signed else None,
            membership_plan=membership_offer["plan"],
            membership_offer=membership_offer,
        )
        content_dict = resp.model_dump()
        content_dict["financing_breakdowns"] = financing_breakdowns
        content_dict["financing_selection"] = lead_action.financing_selection
        return JSONResponse(content=content_dict)

    # 7. Render HTML view
    return templates.TemplateResponse(
        request=request,
        name="proposal.html",
        context={
            "lead_action": lead_action,
            "tenant": tenant,
            "estimate": estimate,
            "diagnostic": diagnostic,
            "is_signed": is_signed,
            "signed_contract": signed_contract,
            "membership_offer": membership_offer,
            "membership_plan": membership_offer["plan"],
            "financing_breakdowns": financing_breakdowns,
            "financing_selection": lead_action.financing_selection,
        },
    )


@router.post(
    "/proposal/{action_id}/accept",
    summary="Accept & Sign Proposal",
    description="Captures customer handwritten e-signature and selected tier, locks contract, dispatches dual confirmation SMS, and syncs to CRM.",
)
async def accept_proposal(
    action_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    selected_tier: Optional[str] = Form(None),
    signature_base64: Optional[str] = Form(None),
    customer_name: Optional[str] = Form(None),
    customer_phone: Optional[str] = Form(None),
    deposit_paid: Optional[float] = Form(None),
    enroll_membership: Optional[bool] = Form(False),
    membership_plan_name: Optional[str] = Form(None),
    financing_plan: Optional[str] = Form(None),
    financing_monthly_payment: Optional[float] = Form(None),
) -> Response:
    # 1. Fetch LeadAction
    query = select(LeadAction).where(LeadAction.id == action_id)
    lead_action = (await db.execute(query)).scalar_one_or_none()

    if not lead_action:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Lead action '{action_id}' not found",
        )

    # 2. Fetch associated Tenant
    tenant_query = select(Tenant).where(Tenant.id == lead_action.tenant_id)
    tenant = (await db.execute(tenant_query)).scalar_one_or_none()

    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Associated tenant not found",
        )

    # 3. Check for JSON submission if form data empty
    content_type = request.headers.get("content-type", "").lower()
    if "application/json" in content_type:
        try:
            body_json = await request.json()
            submission = ContractSignatureSubmission.model_validate(body_json)
            selected_tier = submission.selected_tier
            signature_base64 = submission.signature_base64
            customer_name = submission.customer_name
            customer_phone = submission.customer_phone
            deposit_paid = submission.deposit_paid
            enroll_membership = submission.enroll_membership
            membership_plan_name = submission.membership_plan_name
            if submission.financing_plan is not None:
                financing_plan = submission.financing_plan
            if submission.financing_monthly_payment is not None:
                financing_monthly_payment = submission.financing_monthly_payment
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid JSON signature submission: {exc}",
            )

    # Validate inputs
    if not selected_tier or not signature_base64:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="selected_tier and signature_base64 are required",
        )

    # 4. Resolve proposal estimate to get pricing & option title
    if lead_action.proposal_data:
        estimate = ProposalEstimate.model_validate(lead_action.proposal_data)
    else:
        report_dict = lead_action.diagnostic_data or lead_action.metadata_payload.get("diagnostic_report")
        diagnostic = EquipmentDiagnosticReport.model_validate(report_dict) if report_dict else None
        estimate = generate_tiered_proposal(diagnostic, tenant.settings)
        lead_action.proposal_data = estimate.model_dump()

    # Find the chosen option
    chosen_option = None
    for opt in estimate.options:
        if opt.tier_name.lower() == selected_tier.lower() or opt.title.lower() == selected_tier.lower():
            chosen_option = opt
            break

    if not chosen_option:
        # Fallback to first option if tier name format varies
        chosen_option = estimate.options[0]

    price_total = chosen_option.price_estimate

    # 4b. Apply Membership Discount if selected
    membership_discount = 0.0
    membership_plan_info = None
    if enroll_membership:
        membership_plan_info = calculate_membership_offer(price_total, tenant.settings)
        membership_discount = membership_plan_info["discount_amount"]
        price_total = membership_plan_info["discounted_price"]

    deposit_req = round(price_total * (estimate.deposit_percentage / 100.0), 2)
    deposit_amt = deposit_paid if deposit_paid is not None else deposit_req

    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

    signed_contract_record = {
        "selected_tier": chosen_option.tier_name,
        "tier_title": chosen_option.title,
        "price_total": price_total,
        "deposit_required": deposit_req,
        "deposit_paid": deposit_amt,
        "signature_base64": signature_base64,
        "customer_name": customer_name or "Authorized Customer",
        "customer_phone": customer_phone or lead_action.metadata_payload.get("caller_phone"),
        "signed_at": now_iso,
        "contract_status": "SIGNED",
        "membership_enrolled": bool(enroll_membership),
        "membership_discount": membership_discount,
        "membership_plan_name": membership_plan_info["plan_name"] if membership_plan_info else None,
        "final_price": price_total,
        "original_price": chosen_option.price_estimate,
        "financing_plan": financing_plan,
        "financing_monthly_payment": float(financing_monthly_payment) if financing_monthly_payment is not None else None,
    }

    # 4c. Record Financing Selection if chosen
    financing_selection_record = None
    if financing_plan:
        financing_selection_record = {
            "plan_name": financing_plan,
            "monthly_payment": float(financing_monthly_payment or 0.0),
            "selected_at": now_iso,
            "tier_name": chosen_option.tier_name,
            "total_financed_amount": price_total,
            "status": "APPROVED_PREQUALIFIED",
        }
        lead_action.financing_selection = financing_selection_record
        flag_modified(lead_action, "financing_selection")
        signed_contract_record["financing_selection"] = financing_selection_record

    # 5. Update LeadAction & Membership Enrollment
    lead_action.signed_contract = signed_contract_record
    flag_modified(lead_action, "signed_contract")
    lead_action.action_type = "CONTRACT_SIGNED"
    lead_action.dispatch_status = "CONFIRMED"

    if enroll_membership and membership_plan_info:
        sub_id = f"sub_sim_{uuid.uuid4().hex[:12]}"
        lead_action.membership_enrollment = {
            "status": "ACTIVE",
            "plan_name": membership_plan_info["plan_name"],
            "monthly_price": membership_plan_info["monthly_price"],
            "discount_pct": membership_plan_info["discount_pct"],
            "discount_amount": membership_discount,
            "discount_applied": membership_discount,
            "original_price": chosen_option.price_estimate,
            "discounted_price": price_total,
            "stripe_subscription_id": sub_id,
            "subscription_id": sub_id,
            "enrolled_at": now_iso,
            "customer_name": customer_name or "Authorized Customer",
            "customer_phone": customer_phone or lead_action.metadata_payload.get("caller_phone"),
        }
        flag_modified(lead_action, "membership_enrollment")

    meta = dict(lead_action.metadata_payload or {})
    meta.update({
        "contract_signed": True,
        "contract_signed_at": now_iso,
        "selected_tier": chosen_option.tier_name,
        "contract_amount": price_total,
        "membership_enrolled": bool(enroll_membership),
        "financing_selected": bool(financing_plan),
        "financing_plan": financing_plan,
        "financing_monthly_payment": float(financing_monthly_payment or 0.0) if financing_plan else None,
    })
    lead_action.metadata_payload = meta
    flag_modified(lead_action, "metadata_payload")

    # 6. Dispatch Dual SMS Notifications
    from_phone = tenant.settings.get("twilio_phone_number") or settings.TWILIO_FROM_NUMBER
    contractor_alert_phone = tenant.settings.get("alert_phone_number") or tenant.settings.get("phone")
    homeowner_phone = customer_phone or lead_action.metadata_payload.get("caller_phone")

    # A. SMS to Homeowner
    if homeowner_phone:
        m_msg = f" (Includes {membership_plan_info['plan_name']} activation with ${membership_discount:,.2f} instant savings!)" if enroll_membership and membership_plan_info else ""
        fin_msg = f" [Financed via {financing_plan} at ${float(financing_monthly_payment or 0.0):.2f}/mo]" if financing_plan else ""
        homeowner_sms = (
            f"Thank you for approving the {chosen_option.tier_name} proposal with {tenant.name}! "
            f"Total Investment: ${price_total:,.2f}{m_msg}{fin_msg}. Our dispatch coordinator will reach out shortly to schedule."
        )
        await send_proposal_sms(to_phone=homeowner_phone, message_body=homeowner_sms, from_number=from_phone)

    # B. SMS to Contractor Alert Phone
    if contractor_alert_phone:
        contractor_sms = (
            f"🎉 PROPOSAL ACCEPTED: {customer_name or 'Homeowner'} signed {chosen_option.tier_name} "
            f"(${price_total:,.2f}) for {tenant.name}. Contract locked & confirmed."
        )
        if enroll_membership and membership_plan_info:
            contractor_sms += f" ⭐ Customer enrolled in {membership_plan_info['plan_name']} (${membership_plan_info['monthly_price']:.2f}/mo MRR)!"
        if financing_plan:
            contractor_sms += f" 💳 Monthly Financing Selected: {financing_plan} (${float(financing_monthly_payment or 0.0):.2f}/mo)!"
        await send_proposal_sms(to_phone=contractor_alert_phone, message_body=contractor_sms, from_number=from_phone)


    # 7. Sync to external CRM (Jobber, ServiceTitan, HubSpot)
    crm_result = await sync_lead_to_external_crm(lead_action, tenant, db=db)
    crm_synced = crm_result.get("success", False)

    await db.commit()
    await db.refresh(lead_action)

    # 8. Return JSON or redirect
    accept_header = request.headers.get("accept", "").lower()
    if "application/json" in content_type or "application/json" in accept_header or request.query_params.get("format") == "json":
        return JSONResponse(
            content={
                "success": True,
                "action_id": str(lead_action.id),
                "tenant_slug": tenant.slug,
                "contract": signed_contract_record,
                "membership_enrolled": bool(lead_action.membership_enrollment),
                "membership_details": lead_action.membership_enrollment,
                "financing_selected": bool(lead_action.financing_selection),
                "financing_selection": lead_action.financing_selection,
                "crm_synced": crm_synced,
            }
        )

    return RedirectResponse(
        url=f"/proposal/{lead_action.id}?signed=true",
        status_code=status.HTTP_303_SEE_OTHER,
    )
