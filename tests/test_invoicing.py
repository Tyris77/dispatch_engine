import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lead_action import LeadAction
from app.models.tenant import Tenant
from app.schemas.invoice import (
    InvoiceCompleteSubmission,
    InvoiceLineItem,
    InvoicePaymentSubmission,
    JobInvoice,
)
from app.services.invoicing import generate_job_invoice, process_invoice_payment


def test_invoice_schemas():
    """Verify that InvoiceLineItem, JobInvoice, and submission schemas validate correctly."""
    item = InvoiceLineItem(description="Primary AC Compressor Replacement", amount=1850.0)
    assert item.description == "Primary AC Compressor Replacement"
    assert item.amount == 1850.0

    credit = InvoiceLineItem(description="Upfront Deposit Credited", amount=-500.0)
    assert credit.amount == -500.0

    invoice = JobInvoice(
        invoice_number="INV-2026-0042",
        line_items=[item, credit],
        contract_total=1850.0,
        deposit_credited=500.0,
        balance_due=1350.0,
        payment_status="PENDING",
        before_photo_url="https://storage.googleapis.com/test-bucket/before.jpg",
        after_photo_url="https://storage.googleapis.com/test-bucket/after.jpg",
        contractor_name="Apex HVAC Pros",
        customer_name="John Homeowner",
        customer_phone="+15551234567",
    )
    assert invoice.invoice_number == "INV-2026-0042"
    assert invoice.contract_total == 1850.0
    assert invoice.deposit_credited == 500.0
    assert invoice.balance_due == 1350.0
    assert invoice.payment_status == "PENDING"
    assert len(invoice.line_items) == 2

    complete_sub = InvoiceCompleteSubmission(
        technician_notes="Dual capacitor replaced and tested; cooling restored to 68F.",
        after_photo_url="https://storage.googleapis.com/test-bucket/completed_unit.jpg",
    )
    assert complete_sub.technician_notes.startswith("Dual capacitor")
    assert complete_sub.after_photo_url is not None

    pay_sub = InvoicePaymentSubmission(
        payment_intent_id="pi_test_1234567890",
        payment_method="card",
        tip_amount=25.0,
    )
    assert pay_sub.payment_intent_id == "pi_test_1234567890"
    assert pay_sub.payment_method == "card"
    assert pay_sub.tip_amount == 25.0


def test_generate_job_invoice_with_contract_and_deposit():
    """Verify generate_job_invoice properly credits deposit and computes remaining balance."""
    tenant = Tenant(
        id=uuid.uuid4(),
        name="Apex Comfort Heating & Air",
        slug="apex-comfort",
        api_key_hash="hash",
        webhook_secret="whsec_test",
        is_active=True,
        settings={"license_number": "HVAC-LIC-84920", "trade": "HVAC"},
    )

    lead_action = LeadAction(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        lead_external_id="+15559876543",
        action_type="EMERGENCY_DISPATCH",
        qualification_score=0.9,
        signed_contract={
            "selected_tier": "Standard Replacement",
            "tier_title": "16-SEER2 High Efficiency Inverter Heat Pump",
            "price_total": 4800.0,
            "deposit_paid": 1200.0,
            "customer_name": "Sarah Connor",
            "customer_phone": "+15559876543",
        },
        diagnostic_data={
            "equipment_type": "HVAC Heat Pump",
            "brand_manufacturer": "Carrier",
            "image_url": "https://storage.googleapis.com/test/carrier_before.jpg",
        },
    )

    invoice = generate_job_invoice(lead_action=lead_action, tenant=tenant)

    assert invoice.invoice_number.startswith("INV-")
    assert invoice.contract_total == 4800.0
    assert invoice.deposit_credited == 1200.0
    assert invoice.balance_due == 3600.0
    assert invoice.payment_status == "PENDING"
    assert invoice.before_photo_url == "https://storage.googleapis.com/test/carrier_before.jpg"
    assert invoice.customer_name == "Sarah Connor"
    assert invoice.contractor_name == "Apex Comfort Heating & Air"
    assert invoice.license_number == "HVAC-LIC-84920"

    # Line items check: Primary scope + deposit credit
    assert len(invoice.line_items) == 2
    desc_list = [i.description for i in invoice.line_items]
    assert any("16-SEER2" in d for d in desc_list)
    assert any("Deposit" in d for d in desc_list)


def test_generate_job_invoice_with_membership_discount():
    """Verify generate_job_invoice accounts for VIP membership discount line item."""
    tenant = Tenant(
        id=uuid.uuid4(),
        name="Precision Flow Plumbing",
        slug="precision-plumbing",
        api_key_hash="hash",
        webhook_secret="whsec_test",
        is_active=True,
        settings={"license_number": "PLUMB-9912"},
    )

    lead_action = LeadAction(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        lead_external_id="+15554443333",
        action_type="BOOKING_NOTIFICATION",
        qualification_score=0.85,
        signed_contract={
            "selected_tier": "Repair / Patch",
            "tier_title": "Main Water Line Replacement",
            "price_total": 2125.0,
            "deposit_paid": 500.0,
            "customer_name": "Mark Watney",
            "customer_phone": "+15554443333",
        },
        membership_enrollment={
            "plan_name": "VIP Plumbing Shield",
            "discount_pct": 15,
            "discount_amount": 375.0,
            "status": "ACTIVE",
        },
    )

    invoice = generate_job_invoice(lead_action=lead_action, tenant=tenant)

    assert invoice.contract_total == 2125.0
    assert invoice.deposit_credited == 500.0
    assert invoice.balance_due == 1625.0
    # Membership line item should be listed
    descriptions = [item.description for item in invoice.line_items]
    assert any("VIP Plumbing Shield" in d for d in descriptions)


@pytest.mark.asyncio
async def test_process_invoice_payment_settlement(db_session: AsyncSession, sample_tenant: dict):
    """Verify process_invoice_payment sets PAID status and triggers Google review sequence."""
    tenant = sample_tenant["tenant"]

    lead_action = LeadAction(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        lead_external_id="+15557778888",
        action_type="EMERGENCY_DISPATCH",
        qualification_score=0.95,
        signed_contract={
            "selected_tier": "Premium System",
            "tier_title": "Daikin VRV Life System",
            "price_total": 6500.0,
            "deposit_paid": 1500.0,
            "customer_name": "Alice Resident",
            "customer_phone": "+15557778888",
        },
    )
    db_session.add(lead_action)
    await db_session.commit()
    await db_session.refresh(lead_action)

    # First generate the invoice
    inv = generate_job_invoice(lead_action=lead_action, tenant=tenant)
    lead_action.invoice_data = inv.model_dump()
    await db_session.commit()

    # Process payment
    updated_inv = await process_invoice_payment(
        action_id=lead_action.id,
        db=db_session,
        payment_intent_id="pi_mock_success_7788",
    )

    assert updated_inv.payment_status == "PAID"
    assert updated_inv.transaction_id == "pi_mock_success_7788"
    assert updated_inv.paid_at is not None
    assert updated_inv.balance_due == 5000.0

    # LeadAction should now have review_data initialized from reputation booster
    await db_session.refresh(lead_action)
    assert lead_action.invoice_data["payment_status"] == "PAID"
    assert lead_action.review_data is not None
    assert lead_action.review_data.get("status") == "PROMPTED"


@pytest.mark.asyncio
async def test_api_invoice_get_and_json(client: AsyncClient, db_session: AsyncSession, sample_tenant: dict):
    """Verify GET /invoice/{action_id} serves both rich HTML mobile view and structured JSON."""
    tenant = sample_tenant["tenant"]

    lead_action = LeadAction(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        lead_external_id="+15551112222",
        action_type="SMS_FOLLOWUP",
        qualification_score=0.88,
        signed_contract={
            "selected_tier": "Standard Replacement",
            "tier_title": "Rheem 50-Gal Hybrid Water Heater",
            "price_total": 2900.0,
            "deposit_paid": 500.0,
            "customer_name": "David Copperfield",
            "customer_phone": "+15551112222",
        },
        diagnostic_data={
            "equipment_type": "Water Heater",
            "brand_manufacturer": "Rheem",
            "image_url": "https://storage.googleapis.com/test/rheem_before.jpg",
        },
    )
    db_session.add(lead_action)
    await db_session.commit()

    # 1. Nonexistent lead -> 404
    resp_404 = await client.get(f"/invoice/{uuid.uuid4()}")
    assert resp_404.status_code == 404

    # 2. HTML View
    resp_html = await client.get(f"/invoice/{lead_action.id}")
    assert resp_html.status_code == 200
    assert "text/html" in resp_html.headers.get("content-type", "")
    assert "Rheem 50-Gal Hybrid Water Heater" in resp_html.text
    assert "David Copperfield" in resp_html.text
    assert "Balance Due" in resp_html.text
    assert "Pay with Card / Apple Pay" in resp_html.text
    assert "Before &amp; After Photo Inspection" in resp_html.text

    # 3. JSON format query parameter
    resp_json = await client.get(f"/invoice/{lead_action.id}?format=json")
    assert resp_json.status_code == 200
    data = resp_json.json()
    assert data["contract_total"] == 2900.0
    assert data["deposit_credited"] == 500.0
    assert data["balance_due"] == 2400.0
    assert data["payment_status"] == "PENDING"
    assert data["before_photo_url"] == "https://storage.googleapis.com/test/rheem_before.jpg"


@pytest.mark.asyncio
async def test_api_invoice_complete_technician_flow(client: AsyncClient, db_session: AsyncSession, sample_tenant: dict):
    """Verify POST /invoice/{action_id}/complete uploads after photo, marks COMPLETED, and texts pay link."""
    tenant = sample_tenant["tenant"]

    lead_action = LeadAction(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        lead_external_id="+15553334444",
        action_type="EMERGENCY_DISPATCH",
        qualification_score=0.9,
        dispatch_status="IN_PROGRESS",
        signed_contract={
            "selected_tier": "Repair / Patch",
            "tier_title": "Dual Capacitor & Hard Start Kit",
            "price_total": 450.0,
            "deposit_paid": 100.0,
            "customer_name": "Tony Stark",
            "customer_phone": "+15553334444",
        },
    )
    db_session.add(lead_action)
    await db_session.commit()

    payload = {
        "technician_notes": "Unit running whisper-quiet. Subcooling within factory spec.",
        "after_photo_url": "https://storage.googleapis.com/test/stark_after.jpg",
    }

    resp = await client.post(f"/invoice/{lead_action.id}/complete", json=payload)
    assert resp.status_code == 200
    res_data = resp.json()
    assert res_data["status"] == "COMPLETED"
    assert res_data["pay_link"].startswith(f"http://testserver/invoice/{lead_action.id}")

    # Verify DB update
    await db_session.refresh(lead_action)
    assert lead_action.dispatch_status == "COMPLETED"
    assert lead_action.invoice_data["after_photo_url"] == "https://storage.googleapis.com/test/stark_after.jpg"
    assert lead_action.invoice_data["balance_due"] == 350.0


@pytest.mark.asyncio
async def test_api_invoice_settlement_flow(client: AsyncClient, db_session: AsyncSession, sample_tenant: dict):
    """Verify POST /invoice/{action_id}/settle processes card payment, marks PAID, and triggers reviews."""
    tenant = sample_tenant["tenant"]

    lead_action = LeadAction(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        lead_external_id="+15556667777",
        action_type="EMERGENCY_DISPATCH",
        qualification_score=0.92,
        dispatch_status="COMPLETED",
        signed_contract={
            "selected_tier": "Standard Replacement",
            "tier_title": "Square D 200A Electrical Panel",
            "price_total": 3500.0,
            "deposit_paid": 500.0,
            "customer_name": "Bruce Wayne",
            "customer_phone": "+15556667777",
        },
    )
    db_session.add(lead_action)
    await db_session.commit()

    settle_payload = {
        "payment_intent_id": "pi_live_wayne_ent_999",
        "payment_method": "apple_pay",
        "tip_amount": 50.0,
    }

    resp = await client.post(f"/invoice/{lead_action.id}/settle", json=settle_payload)
    assert resp.status_code == 200
    res_data = resp.json()
    assert res_data["payment_status"] == "PAID"
    assert res_data["invoice"]["transaction_id"] == "pi_live_wayne_ent_999"
    assert res_data["review_prompt_sent"] is True

    # Re-fetch invoice HTML view to confirm PAID state
    get_html = await client.get(f"/invoice/{lead_action.id}")
    assert get_html.status_code == 200
    assert "Paid in Full" in get_html.text
    assert "RECEIPT CONFIRMED" in get_html.text
    assert "pi_live_wayne_ent_999" in get_html.text


@pytest.mark.asyncio
async def test_dashboard_and_portal_invoice_metrics(client: AsyncClient, db_session: AsyncSession, sample_tenant: dict):
    """Verify that operator dashboard and client portal compute and display settled invoice revenue."""
    tenant = sample_tenant["tenant"]

    # Seed 1 paid invoice and 1 pending invoice for this tenant
    paid_lead = LeadAction(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        lead_external_id="+15550001111",
        action_type="EMERGENCY_DISPATCH",
        qualification_score=0.9,
        invoice_data={
            "invoice_number": "INV-PAID-01",
            "contract_total": 4200.0,
            "deposit_credited": 1000.0,
            "balance_due": 3200.0,
            "payment_status": "PAID",
        },
    )
    pending_lead = LeadAction(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        lead_external_id="+15550002222",
        action_type="EMERGENCY_DISPATCH",
        qualification_score=0.85,
        invoice_data={
            "invoice_number": "INV-PEND-02",
            "contract_total": 1500.0,
            "deposit_credited": 300.0,
            "balance_due": 1200.0,
            "payment_status": "PENDING",
        },
    )
    db_session.add_all([paid_lead, pending_lead])
    await db_session.commit()

    # 1. Operator Dashboard filtered to this tenant
    dash_resp = await client.get(f"/dashboard?tenant_slug={tenant.slug}")
    assert dash_resp.status_code == 200
    assert "Revenue Collected" in dash_resp.text
    assert "$4,200.00" in dash_resp.text
    assert "PAID ($4,200)" in dash_resp.text
    assert "Invoice Due" in dash_resp.text

    # 2. Client Portal (authenticated via query param)
    portal_resp = await client.get(f"/portal/{tenant.slug}?api_key={sample_tenant['raw_api_key']}")
    assert portal_resp.status_code == 200
    assert "Revenue &amp; Invoices" in portal_resp.text or "Revenue & Invoices" in portal_resp.text
    assert "$4,200.00" in portal_resp.text
    assert "1 Invoices Settled" in portal_resp.text
    assert "PAID ($4,200)" in portal_resp.text
