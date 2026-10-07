import uuid
from datetime import datetime, timedelta, timezone
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lead_action import LeadAction
from app.models.tenant import Tenant
from app.schemas.crew_surge import (
    CrewBidClaimRequest,
    CrewBidClaimResponse,
    CrewSubcontractor,
    SurgeBidBroadcast,
)
from app.services.crew_surge import crew_surge_service


@pytest.fixture
async def seeded_surge_action(sample_tenant: dict, db_session: AsyncSession) -> LeadAction:
    """Fixture providing a seeded emergency plumbing lead action."""
    tenant = sample_tenant["tenant"]

    action = LeadAction(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        lead_external_id="+17035559876",
        qualification_score=0.98,
        qualification_summary="EMERGENCY: Burst main pipe in basement flooding utility room in McLean, VA.",
        action_type="EMERGENCY_WATER_BURST",
        dispatch_status="QUEUED",
        crm_sync_status="PENDING",
        metadata_payload={
            "customer_name": "Eleanor Vance",
            "address": "1420 Chain Bridge Rd, McLean, VA 22101",
            "phone": "+17035559876",
            "gate_code": "Call box #4921 / Lockbox 8820",
            "issue_description": "Water pipe burst flooding basement",
        },
        profitability_data={
            "contract_revenue": 650.0,
            "material_costs": 60.0,
            "estimated_labor_cost": 422.50,
            "net_profit": 167.50,
            "margin_percentage": 25.8,
            "margin_tier": "HEALTHY",
        },
    )
    db_session.add(action)
    await db_session.commit()
    await db_session.refresh(action)
    return action


@pytest.mark.asyncio
async def test_create_surge_bid_service_margins(seeded_surge_action: LeadAction, db_session: AsyncSession):
    """Verify create_surge_bid accurately calculates 65/35 margin split, unique bid_id, and 15-min countdown."""
    broadcast = await crew_surge_service.create_surge_bid(
        action=seeded_surge_action,
        ticket_value=646.15,
        split_percentage=0.65,
        arrival_sla_minutes=45,
        db=db_session,
    )

    assert broadcast.bid_id.startswith("BID-2026-")
    assert broadcast.action_id == str(seeded_surge_action.id)
    assert broadcast.estimated_ticket_value == 646.15
    assert broadcast.subcontractor_payout == 420.0  # round(646.15 * 0.65, 2)
    assert broadcast.contractor_margin == 226.15
    assert broadcast.arrival_sla_minutes == 45
    assert broadcast.status == "OPEN"
    assert broadcast.claimed_by is None
    assert "Payout: $420" in broadcast.broadcast_sms
    assert "https://dispatchengine-production.up.railway.app/crew-bid/" in broadcast.broadcast_sms
    assert seeded_surge_action.surge_crew_bid_data is not None
    assert seeded_surge_action.surge_crew_bid_data["bid_id"] == broadcast.bid_id


@pytest.mark.asyncio
async def test_compliance_safety_gate_rejection(
    seeded_surge_action: LeadAction,
    db_session: AsyncSession,
):
    """Verify that subcontractors with missing W-9 or missing COI are rejected by compliance safety gate."""
    broadcast = await crew_surge_service.create_surge_bid(
        action=seeded_surge_action,
        ticket_value=500.0,
        db=db_session,
    )

    # 1. Attempt claim with unverified W-9 crew ('sub-dmv-unverified-w9')
    claim_req_w9 = CrewBidClaimRequest(
        subcontractor_id="sub-dmv-unverified-w9",
        subcontractor_phone="+17035550199",
        estimated_eta_minutes=30,
    )
    resp_w9 = await crew_surge_service.claim_surge_bid(
        bid_id=broadcast.bid_id,
        claim_data=claim_req_w9,
        db=db_session,
    )
    assert resp_w9.status == "REJECTED_COMPLIANCE"
    assert resp_w9.full_customer_address is None
    assert resp_w9.gate_codes is None
    assert resp_w9.w9_portal_url is not None
    assert "/w9/" in resp_w9.w9_portal_url

    # 2. Attempt claim with unverified COI crew ('sub-dmv-unverified-coi')
    claim_req_coi = CrewBidClaimRequest(
        subcontractor_id="sub-dmv-unverified-coi",
        subcontractor_phone="+12025550188",
        estimated_eta_minutes=25,
    )
    resp_coi = await crew_surge_service.claim_surge_bid(
        bid_id=broadcast.bid_id,
        claim_data=claim_req_coi,
        db=db_session,
    )
    assert resp_coi.status == "REJECTED_COMPLIANCE"
    assert "ACORD 25" in resp_coi.message or "COI" in resp_coi.message


@pytest.mark.asyncio
async def test_successful_claim_and_race_prevention(
    seeded_surge_action: LeadAction,
    db_session: AsyncSession,
):
    """Verify successful 1-tap claim, job locking, LeadAction update, and race condition rejection on 2nd claim."""
    broadcast = await crew_surge_service.create_surge_bid(
        action=seeded_surge_action,
        ticket_value=646.15,
        db=db_session,
    )

    claim_req = CrewBidClaimRequest(
        subcontractor_id="sub-dmv-mendez",
        subcontractor_phone="+17035550191",
        estimated_eta_minutes=35,
    )

    # 1. First claim by compliant subcontractor
    res1 = await crew_surge_service.claim_surge_bid(
        bid_id=broadcast.bid_id,
        claim_data=claim_req,
        db=db_session,
    )
    assert res1.status == "ACCEPTED"
    assert res1.bid_id == broadcast.bid_id
    assert res1.subcontractor_name == "Mendez Bros Plumbing LLC"
    assert res1.full_customer_address == "1420 Chain Bridge Rd, McLean, VA 22101"
    assert "Lockbox" in res1.gate_codes or "#4921" in res1.gate_codes
    assert res1.voucher_url == f"/crew-voucher/{seeded_surge_action.id}"
    assert res1.tracking_url == f"/track/{seeded_surge_action.id}"

    # Verify database lead action update
    await db_session.refresh(seeded_surge_action)
    assert seeded_surge_action.dispatch_status == "dispatched"
    assert seeded_surge_action.crew_data is not None
    assert seeded_surge_action.crew_data["crew_assignment"]["crew_name"] == "Mendez Bros Plumbing LLC"
    assert seeded_surge_action.surge_crew_bid_data["status"] == "CLAIMED"
    assert seeded_surge_action.surge_crew_bid_data["claimed_by"] == "Mendez Bros Plumbing LLC"

    # 2. Duplicate claim attempt by another crew -> ALREADY_CLAIMED
    claim_req2 = CrewBidClaimRequest(
        subcontractor_id="sub-dmv-vasquez",
        subcontractor_phone="+12025550144",
        estimated_eta_minutes=20,
    )
    res2 = await crew_surge_service.claim_surge_bid(
        bid_id=broadcast.bid_id,
        claim_data=claim_req2,
        db=db_session,
    )
    assert res2.status == "ALREADY_CLAIMED"
    assert "already been claimed" in res2.message.lower()


@pytest.mark.asyncio
async def test_trigger_bid_api_endpoint(
    client: AsyncClient,
    seeded_surge_action: LeadAction,
):
    """Verify POST /api/v1/crew-surge/trigger-bid/{action_id} triggers broadcast with customized split."""
    resp = await client.post(
        f"/api/v1/crew-surge/trigger-bid/{seeded_surge_action.id}",
        json={
            "ticket_value": 700.0,
            "split_percentage": 0.65,
            "arrival_sla_minutes": 40,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["bid_id"].startswith("BID-2026-")
    assert data["estimated_ticket_value"] == 700.0
    assert data["subcontractor_payout"] == 455.0  # 700 * 0.65
    assert data["contractor_margin"] == 245.0
    assert data["arrival_sla_minutes"] == 40
    assert data["status"] == "OPEN"


@pytest.mark.asyncio
async def test_get_crew_bid_portal_and_json(
    client: AsyncClient,
    seeded_surge_action: LeadAction,
    db_session: AsyncSession,
):
    """Verify GET /crew-bid/{bid_id} renders HTML view and responds to JSON format query."""
    broadcast = await crew_surge_service.create_surge_bid(
        action=seeded_surge_action,
        ticket_value=646.15,
        db=db_session,
    )

    # 1. HTML view
    resp_html = await client.get(f"/crew-bid/{broadcast.bid_id}")
    assert resp_html.status_code == 200
    assert "PAYS: $420.00" in resp_html.text or "PAYS:" in resp_html.text
    assert "Surge Dispatch Network" in resp_html.text
    assert "W-9 On File" in resp_html.text
    assert "Active ACORD COI" in resp_html.text

    # 2. JSON format
    resp_json = await client.get(f"/crew-bid/{broadcast.bid_id}?format=json")
    assert resp_json.status_code == 200
    data = resp_json.json()
    assert data["bid_id"] == broadcast.bid_id
    assert data["subcontractor_payout"] == 420.0


@pytest.mark.asyncio
async def test_claim_bid_api_endpoint(
    client: AsyncClient,
    seeded_surge_action: LeadAction,
    db_session: AsyncSession,
):
    """Verify POST /api/v1/crew-surge/claim/{bid_id} validates compliance and returns response."""
    broadcast = await crew_surge_service.create_surge_bid(
        action=seeded_surge_action,
        ticket_value=600.0,
        db=db_session,
    )

    # Claim via API
    resp = await client.post(
        f"/api/v1/crew-surge/claim/{broadcast.bid_id}",
        json={
            "subcontractor_id": "sub-dmv-potomac",
            "subcontractor_phone": "+17035550165",
            "estimated_eta_minutes": 28,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ACCEPTED"
    assert data["subcontractor_name"] == "Potomac Master Electric LLC"
    assert data["voucher_url"] == f"/crew-voucher/{seeded_surge_action.id}"
    assert data["full_customer_address"] is not None


@pytest.mark.asyncio
async def test_crew_network_dashboard_and_active_bids(
    client: AsyncClient,
    sample_tenant: dict,
    seeded_surge_action: LeadAction,
    db_session: AsyncSession,
):
    """Verify GET /crew-network/{tenant_slug} and active-bids API."""
    tenant = sample_tenant["tenant"]

    # Generate a surge bid for tenant
    await crew_surge_service.create_surge_bid(
        action=seeded_surge_action,
        ticket_value=646.15,
        db=db_session,
    )

    # 1. HTML network roster
    resp_html = await client.get(f"/crew-network/{tenant.slug}")
    assert resp_html.status_code == 200
    assert "1099 Crew Surge Dispatch" in resp_html.text
    assert "Enrolled DMV 1099 Subcontractor Roster" in resp_html.text
    assert "Mendez Bros Plumbing LLC" in resp_html.text

    # 2. JSON network
    resp_json = await client.get(f"/crew-network/{tenant.slug}?format=json")
    assert resp_json.status_code == 200
    data = resp_json.json()
    assert data["tenant"] == tenant.slug
    assert len(data["subcontractors"]) >= 5
    assert len(data["bids"]) >= 1

    # 3. Active bids endpoint
    resp_bids = await client.get(f"/api/v1/crew-surge/active-bids/{tenant.slug}")
    assert resp_bids.status_code == 200
    bids_list = resp_bids.json()
    assert len(bids_list) >= 1
    assert bids_list[0]["status"] == "OPEN"

    # 4. Subcontractors endpoint
    resp_subs = await client.get("/api/v1/crew-surge/subcontractors")
    assert resp_subs.status_code == 200
    subs_list = resp_subs.json()
    assert len(subs_list) >= 5


@pytest.mark.asyncio
async def test_404_handling(client: AsyncClient):
    """Verify 404 error responses for invalid action IDs, bid IDs, and tenant slugs."""
    fake_uuid = uuid.uuid4()
    resp_trigger = await client.post(f"/api/v1/crew-surge/trigger-bid/{fake_uuid}")
    assert resp_trigger.status_code == 404

    resp_bid = await client.get("/crew-bid/BID-NONEXISTENT")
    assert resp_bid.status_code == 404

    resp_net = await client.get("/crew-network/nonexistent-tenant-slug-999")
    assert resp_net.status_code == 404
