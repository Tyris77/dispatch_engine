import datetime
from datetime import timezone
import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lead_action import LeadAction
from app.models.tenant import Tenant
from app.services.reactivation import reactivation_service


@pytest.mark.asyncio
async def test_48_hour_unsigned_proposal_reviver(db_session: AsyncSession, sample_tenant: dict):
    tenant: Tenant = sample_tenant["tenant"]

    # 1. Create a lead with a Good-Better-Best proposal generated >48 hours ago
    past_time = datetime.datetime.now(timezone.utc) - datetime.timedelta(hours=52)
    action = LeadAction(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        lead_external_id="+12025550144",
        qualification_score=0.92,
        qualification_summary="Emergency roof patch and structural shingle repair needed.",
        action_type="EMERGENCY_DISPATCH",
        dispatch_status="COMPLETED",
        crm_sync_status="SYNCED",
        metadata_payload={
            "customer_name": "John",
            "city": "Bethesda",
            "phone": "+12025550144",
        },
        proposal_data={
            "equipment_summary": "Architectural Shingle Roofing System",
            "options": [
                {
                    "tier_name": "Repair / Patch",
                    "title": "Emergency Flashing & Ridge Cap Patch",
                    "price_estimate": 1450.0,
                    "scope_bullets": ["Replace damaged flashing", "Seal ridge cap"],
                    "warranty_info": "1-Year Workmanship",
                }
            ],
            "deposit_required": 500.0,
        },
        signed_contract=None,  # Unsigned
        created_at=past_time,
        updated_at=past_time,
    )
    db_session.add(action)
    await db_session.commit()
    await db_session.refresh(action)

    # 2. Run Autonomous Reactivation Sweep
    result = await reactivation_service.scan_and_reactivate_dead_leads(
        db=db_session,
        tenant_id=tenant.id,
        force_all=False,
        base_url="http://testserver",
    )

    assert result.scanned_leads_count >= 1
    assert result.reactivated_count >= 1
    assert result.total_reactivated_pipeline_value >= 1450.0

    offer = result.offers_dispatched[0]
    assert offer.action_id == str(action.id)
    assert offer.customer_name == "John"
    assert offer.customer_phone == "+12025550144"
    assert offer.discount_incentive == 250.0
    assert "Bethesda" in offer.message_body
    assert "$250 credit" in offer.message_body
    assert f"/proposal/{action.id}" in offer.message_body

    # Verify action in DB now has reactivation_data saved
    await db_session.refresh(action)
    assert action.reactivation_data is not None
    assert action.reactivation_data["status"] == "SENT"
    assert action.reactivation_data["campaign_type"] == "UNSIGNED_PROPOSAL_48H"


@pytest.mark.asyncio
async def test_seasonal_equipment_age_reviver(db_session: AsyncSession, sample_tenant: dict):
    tenant: Tenant = sample_tenant["tenant"]

    # Create a lead with 12-year-old Carrier equipment diagnostic report
    past_time = datetime.datetime.now(timezone.utc) - datetime.timedelta(days=200)
    action = LeadAction(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        lead_external_id="+12025550188",
        qualification_score=0.88,
        qualification_summary="Diagnostic scan of outdoor heat pump compressor.",
        action_type="DISPATCH_ROUTED",
        dispatch_status="COMPLETED",
        crm_sync_status="SYNCED",
        metadata_payload={
            "customer_name": "Sarah",
            "city": "Arlington",
            "phone": "+12025550188",
        },
        diagnostic_data={
            "equipment_type": "Outdoor Heat Pump",
            "make": "Carrier",
            "brand_manufacturer": "Carrier",
            "estimated_age_years": 12,
            "damage_assessment": "Coil corrosion and aged contactor relay.",
        },
        proposal_data=None,
        signed_contract=None,
        created_at=past_time,
        updated_at=past_time,
    )
    db_session.add(action)
    await db_session.commit()
    await db_session.refresh(action)

    # Run sweep
    result = await reactivation_service.scan_and_reactivate_dead_leads(
        db=db_session,
        tenant_id=tenant.id,
        force_all=True,
        base_url="http://testserver",
    )

    matching_offers = [o for o in result.offers_dispatched if o.action_id == str(action.id)]
    assert len(matching_offers) == 1
    offer = matching_offers[0]
    assert offer.campaign_type == "SEASONAL_EQUIPMENT_AGE"
    assert "Carrier" in offer.message_body
    assert "12+ years old" in offer.message_body or "10+ years old" in offer.message_body
    assert "$250 off" in offer.message_body
    assert offer.discount_incentive == 250.0


@pytest.mark.asyncio
async def test_trigger_single_lead_reactivation_api(client: AsyncClient, db_session: AsyncSession, sample_tenant: dict):
    tenant: Tenant = sample_tenant["tenant"]

    action = LeadAction(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        lead_external_id="+12025550199",
        qualification_score=0.90,
        qualification_summary="Roof inspection quotation pending.",
        action_type="DISPATCH_ROUTED",
        dispatch_status="COMPLETED",
        crm_sync_status="SYNCED",
        metadata_payload={
            "customer_name": "Michael",
            "city": "Washington DC",
        },
        proposal_data={
            "options": [{"price_estimate": 2200.0}],
        },
    )
    db_session.add(action)
    await db_session.commit()

    # Trigger single lead reactivation via API
    resp = await client.post(
        f"/api/v1/reactivation/trigger/{action.id}",
        params={"campaign_type": "UNSIGNED_PROPOSAL_48H", "custom_credit": 300.0},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["action_id"] == str(action.id)
    assert data["discount_incentive"] == 300.0
    assert data["status"] == "SENT"
    assert "Michael" in data["message_body"]
    assert "$300 credit" in data["message_body"]


@pytest.mark.asyncio
async def test_batch_scan_reactivation_api(client: AsyncClient, db_session: AsyncSession, sample_tenant: dict):
    tenant: Tenant = sample_tenant["tenant"]

    # Batch scan endpoint
    resp = await client.post(
        "/api/v1/reactivation/batch-scan",
        params={"tenant_id": str(tenant.id), "force_all": True},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "scanned_leads_count" in data
    assert "reactivated_count" in data
    assert "total_reactivated_pipeline_value" in data


@pytest.mark.asyncio
async def test_dashboard_and_portal_reactivation_telemetry(client: AsyncClient, db_session: AsyncSession, sample_tenant: dict):
    tenant: Tenant = sample_tenant["tenant"]

    # Seed an action with reactivation_data
    action = LeadAction(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        lead_external_id="+12025550222",
        qualification_score=0.91,
        qualification_summary="Roof valley leak and shingle replacement.",
        action_type="DISPATCH_ROUTED",
        dispatch_status="COMPLETED",
        crm_sync_status="SYNCED",
        metadata_payload={"customer_name": "David", "city": "Bethesda"},
        proposal_data={"options": [{"price_estimate": 1850.0}]},
        reactivation_data={
            "status": "SENT",
            "campaign_type": "UNSIGNED_PROPOSAL_48H",
            "potential_recovered_revenue": 1850.0,
            "discount_incentive": 250.0,
            "customer_phone": "+12025550222",
            "message_body": "Hi David, Carlos from Apex Roofing...",
        },
    )
    db_session.add(action)
    await db_session.commit()

    # 1. Check Dashboard
    dash_resp = await client.get("/dashboard")
    assert dash_resp.status_code == 200
    assert "Reactivated Pipeline" in dash_resp.text
    assert "Permit Radar" in dash_resp.text
    assert "REVIVED ($250 OFF)" in dash_resp.text

    # 2. Check Client Portal
    portal_resp = await client.get(
        f"/portal/{tenant.slug}",
        headers={"X-API-Key": sample_tenant["raw_api_key"]},
    )
    assert portal_resp.status_code == 200
    assert "Reactivated Pipeline" in portal_resp.text
    assert "Permit Radar" in portal_resp.text
    assert "REVIVED ($250 OFF)" in portal_resp.text

