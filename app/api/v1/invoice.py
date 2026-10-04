import base64
import os
import uuid
from typing import Any, Dict, Optional
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, Response, UploadFile, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.core.config import settings
from app.core.logging import logger
from app.models.lead_action import LeadAction
from app.models.tenant import Tenant
from app.schemas.invoice import InvoiceCompleteSubmission, InvoicePaymentSubmission, JobInvoice
from app.services.invoicing import generate_job_invoice, process_invoice_payment, send_invoice_sms

router = APIRouter()

TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "templates")
templates = Jinja2Templates(directory=TEMPLATES_DIR)


@router.get(
    "/invoice/{action_id}",
    response_class=HTMLResponse,
    summary="View Post-Job Invoice & Text-to-Pay Receipt",
    description="Renders mobile-optimized dark receipt with Before/After photos and itemized statement, or returns structured JSON.",
)
async def get_job_invoice_view(
    action_id: uuid.UUID,
    request: Request,
    format: Optional[str] = Query(None, description="Set to 'json' to receive structured payload"),
    completed: Optional[str] = Query(None),
    paid: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
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

    # 3. Generate or retrieve invoice
    if lead_action.invoice_data:
        try:
            invoice = JobInvoice.model_validate(lead_action.invoice_data)
        except Exception:
            invoice = generate_job_invoice(lead_action, tenant)
            await db.commit()
    else:
        invoice = generate_job_invoice(lead_action, tenant)
        await db.commit()

    # 4. Handle JSON response
    accept_header = request.headers.get("accept", "").lower()
    if format == "json" or "application/json" in accept_header:
        return JSONResponse(content=invoice.model_dump())

    # 5. Render HTML view
    return templates.TemplateResponse(
        request=request,
        name="invoice.html",
        context={
            "lead_action": lead_action,
            "tenant": tenant,
            "invoice": invoice,
            "is_paid": invoice.payment_status == "PAID" or bool(paid),
            "is_completed": bool(completed),
        },
    )


@router.post(
    "/invoice/{action_id}/complete",
    summary="Technician Complete Job & Dispatch Text-to-Pay Link",
    description="Marks service call finished, attaches technician After photo, generates invoice, and texts customer payment link.",
)
async def complete_job_and_send_invoice(
    action_id: uuid.UUID,
    request: Request,
    after_photo_url: Optional[str] = Form(None),
    technician_notes: Optional[str] = Form(None),
    photo: Optional[UploadFile] = File(None),
    db: AsyncSession = Depends(get_db),
) -> Response:
    # 1. Fetch LeadAction
    query = select(LeadAction).where(LeadAction.id == action_id)
    lead_action = (await db.execute(query)).scalar_one_or_none()
    if not lead_action:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead action not found")

    tenant_query = select(Tenant).where(Tenant.id == lead_action.tenant_id)
    tenant = (await db.execute(tenant_query)).scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")

    # 2. Check JSON payload fallback
    content_type = request.headers.get("content-type", "").lower()
    if "application/json" in content_type:
        try:
            body = await request.json()
            after_photo_url = body.get("after_photo_url") or after_photo_url
            technician_notes = body.get("technician_notes") or technician_notes
        except Exception:
            pass

    # 3. Process optional file upload to base64 data-URI if provided
    resolved_after_photo = after_photo_url
    if photo and photo.filename:
        photo_bytes = await photo.read()
        mime = photo.content_type or "image/jpeg"
        b64 = base64.b64encode(photo_bytes).decode("utf-8")
        resolved_after_photo = f"data:{mime};base64,{b64}"

    after_data = {
        "after_photo_url": resolved_after_photo,
        "technician_notes": technician_notes,
    }

    # 4. Generate invoice & update dispatch status
    invoice = generate_job_invoice(lead_action, tenant, after_photo_data=after_data)
    lead_action.dispatch_status = "COMPLETED"
    await db.commit()
    await db.refresh(lead_action)

    # 5. Dispatch Text-to-Pay SMS link to customer
    customer_phone = invoice.customer_phone
    if customer_phone:
        base_url = str(request.base_url).rstrip("/")
        invoice_link = f"{base_url}/invoice/{action_id}"
        from_phone = tenant.settings.get("twilio_phone_number") or settings.TWILIO_FROM_NUMBER
        sms_msg = (
            f"✅ Service Completed! {tenant.name} has finished your repair. "
            f"View your Before/After inspection receipt and pay remaining balance (${invoice.balance_due:,.2f}) here: {invoice_link}"
        )
        await send_invoice_sms(to_phone=customer_phone, message_body=sms_msg, from_number=from_phone)

    # 6. Response
    accept_header = request.headers.get("accept", "").lower()
    base_url = str(request.base_url).rstrip("/")
    invoice_link = f"{base_url}/invoice/{action_id}"
    if "application/json" in content_type or "application/json" in accept_header or request.query_params.get("format") == "json":
        return JSONResponse(
            content={
                "success": True,
                "status": "COMPLETED",
                "pay_link": invoice_link,
                "invoice": invoice.model_dump(),
            }
        )

    return RedirectResponse(url=f"/invoice/{action_id}?completed=true", status_code=status.HTTP_303_SEE_OTHER)


@router.post(
    "/invoice/{action_id}/settle",
    summary="Settle Invoice Payment & Launch Review Booster",
    description="Processes Text-to-Pay settlement, marks invoice PAID, dispatches receipt SMS, and fires automated 5-star Google review prompt.",
)
async def settle_invoice_payment(
    action_id: uuid.UUID,
    request: Request,
    customer_name: Optional[str] = Form(None),
    payment_method: Optional[str] = Form("card"),
    payment_intent_id: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
) -> Response:
    content_type = request.headers.get("content-type", "").lower()
    if "application/json" in content_type:
        try:
            body = await request.json()
            customer_name = body.get("customer_name") or customer_name
            payment_method = body.get("payment_method") or payment_method or "card"
            payment_intent_id = body.get("payment_intent_id") or payment_intent_id
        except Exception:
            pass

    try:
        invoice = await process_invoice_payment(
            action_id=action_id,
            db=db,
            payment_intent_id=payment_intent_id,
            payment_method=payment_method or "card",
            customer_name=customer_name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))

    accept_header = request.headers.get("accept", "").lower()
    if "application/json" in content_type or "application/json" in accept_header or request.query_params.get("format") == "json":
        return JSONResponse(
            content={
                "success": True,
                "payment_status": "PAID",
                "review_prompt_sent": True,
                "invoice": invoice.model_dump(),
            }
        )

    return RedirectResponse(url=f"/invoice/{action_id}?paid=true", status_code=status.HTTP_303_SEE_OTHER)
