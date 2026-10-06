import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lead_action import LeadAction
from app.models.tenant import Tenant
from app.schemas.sms_bridge import (
    SmsBridgeResponse,
    SmsDispatchAction,
    TechnicianSmsPayload,
)
from app.services.sms_bridge import sms_bridge_service


def test_sms_bridge_schemas():
    """Verify validation and serialization of SMS Bridge schemas."""
    payload = TechnicianSmsPayload(
        From="+15558889999",
        Body="1",
        To="+15551112222",
    )
    assert payload.From == "+15558889999"
    assert payload.Body == "1"

    action = SmsDispatchAction(
        action_id=str(uuid.uuid4()),
        technician_name="Carlos Gomez",
        technician_phone="+15558889999",
        dispatch_text="Emergency burst pipe",
        status="PENDING",
        homeowner_phone="+12025550194",
        tracking_url="https://dispatchengine-production.up.railway.app/track/123",
        dispatched_at="2026-10-06 12:00:00 UTC",
    )
    assert action.technician_name == "Carlos Gomez"
    assert action.status == "PENDING"


def test_dispatch_technician_sms_format():
    """Verify dispatch SMS matches 'Reply 1 to ACCEPT or 2 to PASS' specification."""
    action_id = str(uuid.uuid4())
    dispatch = sms_bridge_service.dispatch_technician_sms(
        action_id=action_id,
        tenant_name="Apex Plumbing",
        technician_name="Carlos Gomez",
        technician_phone="+15558889999",
        address="1420 K St NW, DC",
        issue="Burst pipe",
        ticket_est="$1,200",
    )

    assert dispatch.action_id == action_id
    assert "Reply 1 to ACCEPT or 2 to PASS" in dispatch.dispatch_text
    assert "1420 K St NW, DC" in dispatch.dispatch_text
    assert "$1,200" in dispatch.dispatch_text
    assert dispatch.status == "PENDING"


@pytest.mark.asyncio
async def test_handle_technician_reply_accept_updates_db(db_session: AsyncSession):
    """Verify technician replying '1' sets dispatch_status to accepted and triggers homeowner tracking SMS."""
    # Seed tenant and LeadAction
    tenant = Tenant(
        id=uuid.uuid4(),
        name="Apex SMS Tenant",
        slug=f"sms-tenant-{uuid.uuid4().hex[:6]}",
        api_key_hash="hash",
        webhook_secret="secret",
        settings={},
    )
    db_session.add(tenant)
    await db_session.commit()

    action = LeadAction(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        action_type="DISPATCH_EMERGENCY",
        dispatch_status="QUEUED",
        crm_sync_status="PENDING",
        metadata_payload={},
        tracking_data={"status": "DISPATCHED"},
    )
    db_session.add(action)
    await db_session.commit()

    action_id_str = str(action.id)

    # Dispatch to tech
    sms_bridge_service.dispatch_technician_sms(
        action_id=action_id_str,
        technician_name="Carlos Gomez",
        technician_phone="+15558889999",
        homeowner_phone="+12025550194",
    )

    # Tech replies '1'
    res = await sms_bridge_service.handle_technician_reply(
        from_phone="+15558889999",
        body="1",
        db=db_session,
    )

    assert res.reply_interpreted == "ACCEPT"
    assert res.dispatch_status == "accepted"
    assert res.homeowner_notified is True
    assert res.backup_notified is False
    assert "<Response><Message>" in res.twiml_response

    # Verify DB persistence
    query = select(LeadAction).where(LeadAction.id == action.id)
    updated_action = (await db_session.execute(query)).scalar_one_or_none()
    assert updated_action is not None
    assert updated_action.dispatch_status == "accepted"
    assert updated_action.tracking_data["status"] == "ACCEPTED"
    assert updated_action.tracking_data["accepted_by"] == "Carlos Gomez"
    assert f"/track/{action_id_str}" in updated_action.tracking_data["homeowner_sms"]


@pytest.mark.asyncio
async def test_handle_technician_reply_pass_cascades_to_backup(db_session: AsyncSession):
    """Verify technician replying '2' escalates to Backup Technician #2."""
    action_id = str(uuid.uuid4())

    sms_bridge_service.dispatch_technician_sms(
        action_id=action_id,
        technician_name="Carlos Gomez",
        technician_phone="+15558889999",
        backup_technician_name="Dave Vance",
        backup_technician_phone="+15557778888",
    )

    # Tech replies '2' (pass)
    res = await sms_bridge_service.handle_technician_reply(
        from_phone="+15558889999",
        body="2",
        db=db_session,
    )

    assert res.reply_interpreted == "PASS"
    assert res.dispatch_status == "escalated"
    assert res.homeowner_notified is False
    assert res.backup_notified is True
    assert "Dave Vance" in res.response_message


@pytest.mark.asyncio
async def test_api_simulate_dispatch(client: AsyncClient):
    """Test POST /api/v1/sms/simulate-dispatch endpoint."""
    payload = {
        "tenant_name": "Apex Plumbing",
        "technician_name": "Carlos Gomez",
        "technician_phone": "+15558889999",
        "address": "1420 K St NW, Washington, DC",
        "issue": "Burst pipe flood",
        "ticket_est": "$1,200",
    }
    response = await client.post("/api/v1/sms/simulate-dispatch", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["technician_name"] == "Carlos Gomez"
    assert "Reply 1 to ACCEPT or 2 to PASS" in data["dispatch_text"]
    assert data["status"] == "PENDING"


@pytest.mark.asyncio
async def test_api_technician_reply_webhook_json_and_form(client: AsyncClient):
    """Test POST /api/v1/sms/technician-reply handling JSON and Twilio form encoded formats."""
    # 1. Test JSON format
    json_payload = {
        "From": "+15558889999",
        "Body": "1",
    }
    resp_json = await client.post("/api/v1/sms/technician-reply", json=json_payload)
    assert resp_json.status_code == 200
    data = resp_json.json()
    assert data["reply_interpreted"] == "ACCEPT"
    assert data["homeowner_notified"] is True

    # 2. Test Twilio form urlencoded format
    form_payload = {
        "From": "+15558889999",
        "Body": "2",
    }
    resp_form = await client.post(
        "/api/v1/sms/technician-reply",
        data=form_payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp_form.status_code == 200
    assert "application/xml" in resp_form.headers["content-type"]
    assert "<Response><Message>" in resp_form.text


@pytest.mark.asyncio
async def test_api_sms_status(client: AsyncClient):
    """Test GET /api/v1/sms/status telemetry endpoint."""
    response = await client.get("/api/v1/sms/status")
    assert response.status_code == 200
    data = response.json()
    assert "active_dispatches" in data
    assert "recent_history" in data
