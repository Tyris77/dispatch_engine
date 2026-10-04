import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lead_action import LeadAction
from app.models.tenant import Tenant
from app.schemas.pay_app import (
    AIAContractProgressPayment,
    PayAppGenerateRequest,
    ScheduleOfValuesItem,
)
from app.services.pay_app import pay_app_service


def test_pay_app_schemas():
    """Verify validation of Schedule of Values and AIA G702 Progress Billing schemas."""
    item = ScheduleOfValuesItem(
        item_number="15-050",
        description="Mechanical / Core Equipment & Rough-In",
        scheduled_value=35000.0,
        work_completed_previous=10000.0,
        work_completed_this_period=15000.0,
        materials_stored=1000.0,
        total_completed_stored=26000.0,
        percent_complete=74.3,
        balance_to_finish=9000.0,
        retainage_rate_pct=10.0,
        retainage_amount=2600.0,
    )
    assert item.item_number == "15-050"
    assert item.total_completed_stored == 26000.0
    assert item.retainage_amount == 2600.0

    pay_app = AIAContractProgressPayment(
        application_number=1,
        period_to="October 04, 2026",
        project_name="Commercial Chiller Retrofit - 100 Main St",
        contractor_name="Apex Mechanical Inc",
        architect_name="Gensler Design & Engineering",
        original_contract_sum=100000.0,
        net_change_orders=0.0,
        contract_sum_to_date=100000.0,
        total_completed_stored=65000.0,
        total_retainage=6500.0,
        less_previous_certificates=0.0,
        current_payment_due=58500.0,
        balance_to_finish_plus_retainage=41500.0,
        line_items=[item],
    )
    assert pay_app.application_number == 1
    assert pay_app.current_payment_due == 58500.0
    assert pay_app.balance_to_finish_plus_retainage == 41500.0

    req = PayAppGenerateRequest(progress_pct=80.0, retainage_pct=10.0, application_number=2)
    assert req.progress_pct == 80.0


@pytest.mark.asyncio
async def test_generate_aia_payment_application_service(db_session: AsyncSession):
    """Test AIA G702 & G703 formulas, retainage escrow withholding, and balance to finish."""
    tenant = Tenant(
        id=uuid.uuid4(),
        name="Vanguard Commercial Mechanical",
        slug=f"vanguard-comm-{uuid.uuid4().hex[:6]}",
        api_key_hash="hash",
        webhook_secret="secret",
    )
    db_session.add(tenant)

    lead = LeadAction(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        action_type="COMMERCIAL_CONTRACT",
        lead_external_id="COMM-9012",
        qualification_summary="Plaza Tower - 50-Ton VRF Rooftop Replacement",
        metadata_payload={
            "contract_sum": 100000.00,
            "address": "400 Capitol Mall, Sacramento, CA",
        },
    )
    db_session.add(lead)
    await db_session.commit()

    # Generate at 60% progress, 10% retainage, App #1
    pay_app = pay_app_service.generate_aia_payment_application(
        lead_action=lead,
        tenant=tenant,
        progress_pct=60.0,
        retainage_pct=10.0,
        application_number=1,
    )

    assert pay_app.original_contract_sum == 100000.00
    assert pay_app.contract_sum_to_date == 100000.00
    assert len(pay_app.line_items) == 6
    # Sum of scheduled values equals contract sum
    sched_sum = sum(item.scheduled_value for item in pay_app.line_items)
    assert round(sched_sum, 2) == 100000.00

    # Retainage should equal 10% of total completed and stored
    expected_ret = round(pay_app.total_completed_stored * 0.10, 2)
    assert pay_app.total_retainage == expected_ret

    # Net draw due = total completed stored - total retainage - less previous
    expected_due = round(pay_app.total_completed_stored - pay_app.total_retainage - pay_app.less_previous_certificates, 2)
    assert pay_app.current_payment_due == expected_due

    # Balance to finish plus retainage
    expected_bal = round(pay_app.contract_sum_to_date - (pay_app.total_completed_stored - pay_app.total_retainage), 2)
    assert pay_app.balance_to_finish_plus_retainage == expected_bal

    # Test persistence with get_or_create_pay_app
    lead.pay_app_data = pay_app.model_dump()
    await db_session.commit()

    stored_app = await pay_app_service.get_or_create_pay_app(lead, tenant, db_session)
    assert stored_app.current_payment_due == pay_app.current_payment_due
    assert stored_app.contract_sum_to_date == 100000.00


@pytest.mark.asyncio
async def test_pay_app_views_and_endpoints(client: AsyncClient, db_session: AsyncSession):
    """Test HTML commercial view, JSON content negotiation, and recalculation endpoint."""
    tenant = Tenant(
        id=uuid.uuid4(),
        name="Metro Mechanical Contractors",
        slug=f"metro-mech-{uuid.uuid4().hex[:6]}",
        api_key_hash="hash",
        webhook_secret="secret",
    )
    db_session.add(tenant)

    lead = LeadAction(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        action_type="COMMERCIAL_CONTRACT",
        lead_external_id="COMM-8811",
        qualification_summary="Mercantile Center - Hydronic Piping Overhaul",
        metadata_payload={"contract_sum": 75000.00, "address": "120 Broadway, New York, NY"},
    )
    db_session.add(lead)
    await db_session.commit()

    # 1. GET HTML View
    resp_html = await client.get(f"/pay-app/{lead.id}")
    assert resp_html.status_code == 200
    assert "AIA Document G702" in resp_html.text
    assert "AIA Document G703" in resp_html.text
    assert "Contractor's Application for Payment" in resp_html.text

    # 2. GET JSON View via format=json
    resp_json = await client.get(f"/pay-app/{lead.id}?format=json")
    assert resp_json.status_code == 200
    data = resp_json.json()
    assert data["contract_sum_to_date"] == 75000.00
    assert len(data["line_items"]) == 6

    # 3. GET JSON View via API endpoint
    resp_api = await client.get(f"/api/v1/pay-app/{lead.id}")
    assert resp_api.status_code == 200
    assert resp_api.json()["contract_sum_to_date"] == 75000.00

    # 4. POST Recalculate / Generate endpoint
    recalc_payload = {
        "progress_pct": 85.0,
        "retainage_pct": 5.0,
        "application_number": 2,
        "architect_name": "Perkins Eastman Architects",
    }
    resp_post = await client.post(
        f"/pay-app/{lead.id}/generate",
        json=recalc_payload,
    )
    assert resp_post.status_code == 200
    updated_data = resp_post.json()
    assert updated_data["application_number"] == 2
    assert updated_data["architect_name"] == "Perkins Eastman Architects"

    # 5. 404 for unknown lead
    random_id = uuid.uuid4()
    resp_404 = await client.get(f"/pay-app/{random_id}")
    assert resp_404.status_code == 404
