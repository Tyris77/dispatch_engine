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
from app.schemas.invoice import InvoiceLineItem, JobInvoice
from app.services.reputation import trigger_post_job_review_request


async def send_invoice_sms(
    to_phone: str,
    message_body: str,
    from_number: Optional[str] = None,
) -> bool:
    """Dispatches SMS notification to customer for invoice and receipt delivery."""
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
            logger.info(f"Dispatched invoice SMS to {to_phone} (SID: {message.sid})")
            return True
        except Exception as exc:
            logger.error(f"Failed to send invoice SMS to {to_phone}: {exc}")
            return False
    else:
        logger.info(f"[Simulation] Invoice SMS to {to_phone}: {message_body}")
        return True


# Crisp fallback SVG data-URIs representing Before/After photos when actual uploads are not present
DEFAULT_BEFORE_PHOTO = (
    "https://images.unsplash.com/photo-1581092160607-ee22621dd758?auto=format&fit=crop&w=600&q=80"
)
DEFAULT_AFTER_PHOTO = (
    "https://images.unsplash.com/photo-1621905251189-08b45d6a269e?auto=format&fit=crop&w=600&q=80"
)


class InvoicingService:
    """
    Automated Post-Job Invoicing, Before/After Photo Inspection Receipt,
    and Text-to-Pay Processing Engine.
    """

    _send_sms = staticmethod(send_invoice_sms)

    def generate_job_invoice(
        self,
        lead_action: LeadAction,
        tenant: Tenant,
        after_photo_data: Optional[Dict[str, Any]] = None,
    ) -> JobInvoice:
        """
        Builds or updates an itemized JobInvoice for a LeadAction:
        1. Computes gross contract price from signed_contract or proposal_data.
        2. Credits any upfront deposit paid by the homeowner.
        3. Formats itemized line items including membership discount credits.
        4. Calculates remaining balance due.
        5. Associates Before (diagnostic scan) and After (completed repair) inspection photos.
        """
        signed_contract = lead_action.signed_contract or {}
        proposal_data = lead_action.proposal_data or {}
        diagnostic_data = lead_action.diagnostic_data or {}
        metadata = lead_action.metadata_payload or {}

        # 1. Resolve Customer Information
        customer_name = (
            signed_contract.get("customer_name")
            or metadata.get("customer_name")
            or metadata.get("caller_name")
            or "Valued Customer"
        )
        customer_phone = (
            signed_contract.get("customer_phone")
            or metadata.get("customer_phone")
            or metadata.get("caller_phone")
            or lead_action.lead_external_id
            or ""
        )
        service_address = (
            metadata.get("service_address")
            or metadata.get("address")
            or (f"{tenant.settings.get('city', 'Metro Area')}, TX" if tenant.settings.get("city") else "On-Site Customer Location")
        )

        # 2. Financials & Line Items
        selected_tier = signed_contract.get("selected_tier", "Standard Replacement")
        tier_title = signed_contract.get("tier_title", f"{selected_tier} - Certified Equipment Installation")

        # Determine gross contract total and deposit credited
        membership_enrollment = lead_action.membership_enrollment or {}
        if signed_contract:
            contract_total = float(signed_contract.get("price_total", signed_contract.get("final_price", 0.0)))
            deposit_credited = float(signed_contract.get("deposit_paid", signed_contract.get("deposit_required", 0.0)))
            membership_discount = float(signed_contract.get("membership_discount", 0.0))
            if not membership_discount and membership_enrollment:
                membership_discount = float(membership_enrollment.get("discount_amount", 0.0))
            original_price = float(signed_contract.get("original_price", contract_total + membership_discount))
        elif proposal_data and proposal_data.get("options"):
            first_opt = proposal_data["options"][0]
            contract_total = float(first_opt.get("price_estimate", 1250.0))
            deposit_credited = float(proposal_data.get("deposit_required", 0.0))
            membership_discount = 0.0
            if membership_enrollment:
                membership_discount = float(membership_enrollment.get("discount_amount", 0.0))
            original_price = contract_total
            selected_tier = first_opt.get("tier_name", "Standard Service")
            tier_title = first_opt.get("title", selected_tier)
        else:
            # Fallback benchmark for routine emergency repair without formal proposal
            contract_total = 450.0
            deposit_credited = 0.0
            membership_discount = 0.0
            original_price = 450.0
            selected_tier = "Emergency Service"
            tier_title = "Emergency Diagnostic & System Restoration"

        line_items: List[InvoiceLineItem] = []

        # Line item for primary service/equipment
        equipment_label = diagnostic_data.get("equipment_type", "Mechanical System")
        if diagnostic_data.get("brand_manufacturer"):
            equipment_label = f"{diagnostic_data['brand_manufacturer']} {equipment_label}"

        line_items.append(
            InvoiceLineItem(
                description=f"{tier_title} ({equipment_label})",
                amount=original_price if membership_discount > 0 else contract_total,
            )
        )

        # If VIP Membership discount was applied, display as credit
        if membership_discount > 0:
            plan_name = (
                signed_contract.get("membership_plan_name")
                or membership_enrollment.get("plan_name")
                or "VIP Membership Club"
            )
            line_items.append(
                InvoiceLineItem(
                    description=f"{plan_name} Instant Savings Credit",
                    amount=-round(membership_discount, 2),
                )
            )

        # If deposit was credited, show explicit deduction
        if deposit_credited > 0:
            line_items.append(
                InvoiceLineItem(
                    description="Upfront Scheduling Deposit Credited (Paid at Authorization)",
                    amount=-round(deposit_credited, 2),
                )
            )

        balance_due = max(0.0, round(contract_total - deposit_credited, 2))

        # 3. Before & After Photos
        before_photo_url = (
            metadata.get("before_photo_url")
            or metadata.get("intake_photo", {}).get("url")
            or diagnostic_data.get("image_url")
            or DEFAULT_BEFORE_PHOTO
        )

        after_photo_url = None
        technician_notes = None
        if after_photo_data:
            after_photo_url = after_photo_data.get("after_photo_url") or after_photo_data.get("url")
            technician_notes = after_photo_data.get("technician_notes")
        if not after_photo_url:
            after_photo_url = metadata.get("after_photo_url") or DEFAULT_AFTER_PHOTO

        # 4. Generate Unique Invoice Number
        invoice_number = f"INV-{datetime.datetime.utcnow().year}-{str(lead_action.id)[:8].upper()}"

        # Preserve existing payment status if invoice was already paid
        existing_invoice = lead_action.invoice_data or {}
        payment_status = existing_invoice.get("payment_status", "PENDING")
        paid_at = existing_invoice.get("paid_at")
        transaction_id = existing_invoice.get("transaction_id")
        payment_method = existing_invoice.get("payment_method")

        invoice = JobInvoice(
            invoice_number=invoice_number,
            action_id=str(lead_action.id),
            tenant_name=tenant.name,
            tenant_slug=tenant.slug,
            contractor_name=tenant.name,
            license_number=tenant.settings.get("license_number"),
            trade=tenant.settings.get("trade"),
            customer_name=customer_name,
            customer_phone=customer_phone,
            service_address=service_address,
            selected_tier=selected_tier,
            line_items=line_items,
            contract_total=contract_total,
            deposit_credited=deposit_credited,
            balance_due=balance_due,
            payment_status=payment_status,
            before_photo_url=before_photo_url,
            after_photo_url=after_photo_url,
            paid_at=paid_at,
            transaction_id=transaction_id,
            payment_method=payment_method,
            technician_notes=technician_notes,
            created_at=existing_invoice.get("created_at", datetime.datetime.utcnow().isoformat()),
        )

        lead_action.invoice_data = invoice.model_dump()
        flag_modified(lead_action, "invoice_data")
        return invoice

    async def process_invoice_payment(
        self,
        action_id: uuid.UUID,
        db: AsyncSession,
        payment_intent_id: Optional[str] = None,
        payment_method: str = "card",
        customer_name: Optional[str] = None,
    ) -> JobInvoice:
        """
        Settles invoice balance:
        1. Updates payment_status to 'PAID' and assigns transaction_id.
        2. Sets lead_action action_type = 'INVOICE_PAID' and dispatch_status = 'COMPLETED'.
        3. Dispatches customer SMS payment confirmation.
        4. Immediately triggers trigger_post_job_review_request() to launch 5-star Google review sequence.
        """
        # Fetch LeadAction and Tenant
        query = select(LeadAction).where(LeadAction.id == action_id)
        lead_action = (await db.execute(query)).scalar_one_or_none()
        if not lead_action:
            raise ValueError(f"Lead action '{action_id}' not found")

        tenant_query = select(Tenant).where(Tenant.id == lead_action.tenant_id)
        tenant = (await db.execute(tenant_query)).scalar_one_or_none()
        if not tenant:
            raise ValueError(f"Tenant for lead action '{action_id}' not found")

        # Ensure invoice exists
        if not lead_action.invoice_data:
            self.generate_job_invoice(lead_action=lead_action, tenant=tenant)

        invoice_dict = dict(lead_action.invoice_data)
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        tx_id = payment_intent_id or f"pi_sim_{uuid.uuid4().hex[:14]}"
        settled_balance = invoice_dict.get("balance_due", 0.0)

        invoice_dict["payment_status"] = "PAID"
        invoice_dict["paid_at"] = now_iso
        invoice_dict["transaction_id"] = tx_id
        invoice_dict["payment_method"] = payment_method
        if customer_name:
            invoice_dict["customer_name"] = customer_name

        lead_action.invoice_data = invoice_dict
        flag_modified(lead_action, "invoice_data")

        lead_action.action_type = "INVOICE_PAID"
        lead_action.dispatch_status = "COMPLETED"
        flag_modified(lead_action, "action_type")
        flag_modified(lead_action, "dispatch_status")

        await db.commit()
        await db.refresh(lead_action)

        # Send customer payment receipt SMS
        customer_phone = invoice_dict.get("customer_phone")
        if customer_phone:
            from_phone = tenant.settings.get("twilio_phone_number") or settings.TWILIO_FROM_NUMBER
            receipt_sms = (
                f"🧾 PAID RECEIPT: Payment of ${settled_balance:,.2f} received in full for {tenant.name}. "
                f"Reference #{invoice_dict.get('invoice_number')}. Thank you for choosing our team!"
            )
            await self._send_sms(
                to_phone=customer_phone,
                message_body=receipt_sms,
                from_number=from_phone,
            )

        # Trigger post-job 5-star Google review sequence immediately
        try:
            await trigger_post_job_review_request(
                lead_action=lead_action,
                tenant=tenant,
                db=db,
            )
        except Exception as exc:
            logger.warning(f"Could not automatically trigger review request post-invoice: {exc}")

        return JobInvoice.model_validate(lead_action.invoice_data)


invoicing_service = InvoicingService()
generate_job_invoice = invoicing_service.generate_job_invoice
process_invoice_payment = invoicing_service.process_invoice_payment
