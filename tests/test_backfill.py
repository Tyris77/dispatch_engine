import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lead_action import LeadAction
from app.models.tenant import Tenant
from app.schemas.backfill import BackfillBroadcastResult, BackfillCandidate
from app.services.backfill import backfill_service


def _tenant(name="Backfill Pros") -> Tenant:
    return Tenant(
        id=uuid.uuid4(),
        name=name,
        slug=f"bf-{uuid.uuid4().hex[:6]}",
        api_key_hash="hash",
        webhook_secret="secret",
        is_active=True,
        settings={},
    )


def _lead(tenant: Tenant, name: str, address: str, **extra) -> LeadAction:
    return LeadAction(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        lead_external_id=f"LD-{uuid.uuid4().hex[:6]}",
        qualification_score=0.8,
        qualification_summary="Pending HVAC estimate request",
        action_type="DISPATCH_ROUTED",
        dispatch_status="QUEUED",
        crm_sync_status="PENDING",
        metadata_payload={
            "customer_name": name,
            "phone": "+17035550111",
            "address": address,
            **extra,
        },
    )


def test_backfill_schemas():
    cand = BackfillCandidate(
        action_id="a1",
        customer_name="Jane",
        phone="+17035550100",
        address="1 Main St, Arlington, VA",
        corridor="Arlington / Alexandria Corridor",
        service_needed="Tune-up",
    )
    assert cand.discount_amount == 50.0
    res = BackfillBroadcastResult(
        canceled_action_id="c1",
        original_slot_time="Today 2 PM",
        candidates_contacted=2,
        claimed_by_name=None,
        status="BROADCAST_SENT",
    )
    assert res.claimed_by_name is None
    assert res.status == "BROADCAST_SENT"


def test_extract_corridor():
    assert backfill_service.extract_corridor("1401 S Joyce St, Arlington, VA") == "Arlington / Alexandria Corridor"
    assert backfill_service.extract_corridor("7315 Wisconsin Ave, Bethesda, MD") == "Bethesda / Rockville Corridor"
    assert backfill_service.extract_corridor(None) == "Northern Virginia Metro Corridor"


@pytest.mark.asyncio
async def test_process_slot_cancellation_broadcasts(db_session: AsyncSession):
    tenant = _tenant()
    db_session.add(tenant)
    canceled = _lead(tenant, "Cancel Carl", "1401 S Joyce St, Arlington, VA", scheduled_slot="Today 3:00 PM")
    near = _lead(tenant, "Near Nina", "2800 Clarendon Blvd, Arlington, VA")
    db_session.add_all([canceled, near])
    await db_session.commit()

    result = await backfill_service.process_slot_cancellation(canceled.id, tenant, db_session)
    assert result.status == "BROADCAST_SENT"
    assert result.original_slot_time == "Today 3:00 PM"
    assert result.candidates_contacted >= 2
    assert "$50" in result.broadcast_message
    assert any(c.customer_name == "Near Nina" for c in result.candidates)

    await db_session.refresh(canceled)
    assert canceled.backfill_data["status"] == "BROADCAST_SENT"


@pytest.mark.asyncio
async def test_process_slot_cancellation_not_found(db_session: AsyncSession):
    tenant = _tenant()
    db_session.add(tenant)
    await db_session.commit()
    with pytest.raises(ValueError):
        await backfill_service.process_slot_cancellation(uuid.uuid4(), tenant, db_session)


@pytest.mark.asyncio
async def test_claim_backfill_slot_confirms_candidate(db_session: AsyncSession):
    tenant = _tenant()
    db_session.add(tenant)
    canceled = _lead(tenant, "Cancel Carl", "1401 S Joyce St, Arlington, VA")
    cand = _lead(tenant, "Claim Clara", "1200 S Hayes St, Arlington, VA")
    db_session.add_all([canceled, cand])
    await db_session.commit()

    await backfill_service.process_slot_cancellation(canceled.id, tenant, db_session)
    result = await backfill_service.claim_backfill_slot(cand.id, "Today 2:00 PM", tenant, db_session)

    assert result.status == "SLOT_BACKFILLED"
    assert result.claimed_by_name == "Claim Clara"
    await db_session.refresh(cand)
    assert cand.dispatch_status == "CONFIRMED"
    assert cand.metadata_payload["discount_applied"] == 50.0
    await db_session.refresh(canceled)
    assert canceled.backfill_data["status"] == "SLOT_BACKFILLED"


@pytest.mark.asyncio
async def test_backfill_trigger_endpoint(client: AsyncClient, sample_tenant: dict, db_session: AsyncSession):
    tenant = sample_tenant["tenant"]
    lead = _lead(tenant, "Endpoint Eve", "1401 S Joyce St, Arlington, VA")
    db_session.add(lead)
    await db_session.commit()

    res = await client.post(f"/api/v1/backfill/trigger/{lead.id}")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "BROADCAST_SENT"
    assert data["canceled_action_id"] == str(lead.id)


@pytest.mark.asyncio
async def test_backfill_trigger_endpoint_not_found(client: AsyncClient):
    res = await client.post(f"/api/v1/backfill/trigger/{uuid.uuid4()}")
    assert res.status_code == 404
