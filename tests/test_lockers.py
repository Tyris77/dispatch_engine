import uuid
from datetime import datetime, timezone
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lead_action import LeadAction
from app.models.tenant import Tenant
from app.schemas.lockers import (
    LockerBranchQueryRequest,
    LockerDistributorBranch,
    LockerReservationItem,
    LockerReservationVoucher,
    LockerReserveRequest,
)
from app.services.lockers import haversine_distance, locker_service


@pytest.fixture
async def seeded_locker_action(sample_tenant: dict, db_session: AsyncSession) -> LeadAction:
    """Fixture providing a seeded emergency HVAC service lead action."""
    tenant = sample_tenant["tenant"]

    action = LeadAction(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        lead_external_id="+15553334455",
        qualification_score=0.96,
        qualification_summary="No heat in sub-freezing weather; blower motor humming and dual capacitor swollen.",
        action_type="EMERGENCY_NO_HEAT_DISPATCH",
        dispatch_status="QUEUED",
        crm_sync_status="PENDING",
        metadata_payload={
            "sender_name": "Gregory House",
            "address": "7915 Airpark Rd, Gaithersburg, MD 20879",
            "phone": "+15553334455",
            "assigned_technician": "Dave Miller (Truck #4)",
        },
        diagnostic_data={
            "equipment_type": "Carrier 80% Gas Furnace",
            "recommended_parts_tools": [
                "Universal Round Dual Run Capacitor 45/5 MFD",
                "2-Pole 30-Amp Contactor 24V",
            ],
        },
        profitability_data={
            "contract_revenue": 1250.0,
            "material_costs": 45.0,
            "estimated_labor_cost": 275.0,
            "net_profit": 930.0,
            "margin_percentage": 74.4,
            "margin_tier": "EXCELLENT",
        },
    )
    db_session.add(action)
    await db_session.commit()
    await db_session.refresh(action)
    return action


def test_haversine_distance_and_nearest_branch():
    """Verify haversine distance calculation and nearest branch resolution."""
    # Distance between Alexandria VA (38.814, -77.135) and Gaithersburg MD (39.167, -77.165)
    dist = haversine_distance(38.814, -77.135, 39.167, -77.165)
    assert 20.0 < dist < 30.0

    # Gaithersburg address should match RE Michel Gaithersburg
    branch = locker_service.find_nearest_locker_branch(
        customer_address="7915 Airpark Rd, Gaithersburg, MD 20879"
    )
    assert branch.branch_id == "remichel-gaithersburg"
    assert branch.state == "MD"

    # Alexandria address should match Ferguson Alexandria
    branch_va = locker_service.find_nearest_locker_branch(
        customer_address="5700 Edsall Rd, Alexandria, VA 22304"
    )
    assert branch_va.branch_id == "ferguson-alexandria"
    assert branch_va.state == "VA"


def test_locker_reservation_pin_and_expiration(seeded_locker_action: LeadAction):
    """Verify locker reservation assigns box, generates 4-digit PIN, and sets 4-hour expiration."""
    req = LockerReserveRequest(
        technician_name="Dave Miller",
        technician_phone="+12025550199",
    )
    voucher = locker_service.reserve_after_hours_locker(
        action=seeded_locker_action,
        request_data=req,
    )

    assert voucher.reservation_id.startswith("LCK-2026-")
    assert voucher.locker_box_number.startswith("Box #")

    # 4-digit PIN verification
    assert len(voucher.secure_pickup_pin) == 4
    assert voucher.secure_pickup_pin.isdigit()

    # 4-hour expiration window check
    exp_dt = datetime.fromisoformat(voucher.expires_at.replace("Z", "+00:00"))
    now_dt = datetime.now(timezone.utc)
    diff_hours = (exp_dt - now_dt).total_seconds() / 3600.0
    assert 3.8 < diff_hours <= 4.1

    # Pricing & Locker Fee verification
    assert voucher.emergency_locker_fee == 35.00
    assert voucher.material_subtotal > 0
    assert voucher.total_cost == voucher.material_subtotal + voucher.emergency_locker_fee

    # Navigation URL verification
    assert "google.com/maps/dir" in voucher.navigation_url

    # Check profitability sync
    assert seeded_locker_action.profitability_data is not None
    assert seeded_locker_action.profitability_data["material_costs"] >= voucher.total_cost


@pytest.mark.asyncio
async def test_post_reserve_locker_api(
    client: AsyncClient,
    seeded_locker_action: LeadAction,
    db_session: AsyncSession,
):
    """Verify POST /api/v1/lockers/reserve/{action_id} provisions after-hours locker."""
    url = f"/api/v1/lockers/reserve/{seeded_locker_action.id}"
    payload = {
        "preferred_region": "MD",
        "technician_name": "Marcus Vance",
        "technician_phone": "+12025559988",
    }
    response = await client.post(url, json=payload)
    assert response.status_code == 200

    data = response.json()
    assert data["action_id"] == str(seeded_locker_action.id)
    assert len(data["secure_pickup_pin"]) == 4
    assert data["locker_box_number"].startswith("Box #")
    assert data["status"] == "CONFIRMED"
    assert len(data["items"]) >= 1

    # Verify persisted in database
    await db_session.refresh(seeded_locker_action)
    assert seeded_locker_action.locker_reservation_data is not None
    assert seeded_locker_action.locker_reservation_data["secure_pickup_pin"] == data["secure_pickup_pin"]


@pytest.mark.asyncio
async def test_get_locker_voucher_html_view(
    client: AsyncClient,
    seeded_locker_action: LeadAction,
):
    """Verify GET /lockers/{action_id} renders mobile-optimized voucher HTML."""
    url = f"/lockers/{seeded_locker_action.id}"
    response = await client.get(url)
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]

    html = response.text
    assert "After-Hours Emergency Pickup Voucher" in html
    assert "ASSIGNED LOCKER BAY" in html
    assert "SECURE PICKUP PIN" in html
    assert "Perimeter Gate Code" in html
    assert "Get Turn-by-Turn Directions" in html


@pytest.mark.asyncio
async def test_get_locker_voucher_json_api(
    client: AsyncClient,
    seeded_locker_action: LeadAction,
):
    """Verify GET /api/v1/lockers/{action_id}/json returns structured JSON payload."""
    url = f"/api/v1/lockers/{seeded_locker_action.id}/json"
    response = await client.get(url)
    assert response.status_code == 200

    data = response.json()
    assert "secure_pickup_pin" in data
    assert "locker_box_number" in data
    assert "distributor" in data
    assert "emergency_gate_code" in data["distributor"]


@pytest.mark.asyncio
async def test_check_branches_query_api(client: AsyncClient):
    """Verify POST /api/v1/lockers/check-branches computes distance to nearby facilities."""
    url = "/api/v1/lockers/check-branches"
    payload = {
        "zip_code": "22304",
        "customer_address": "5700 Edsall Rd, Alexandria, VA 22304",
    }
    response = await client.post(url, json=payload)
    assert response.status_code == 200

    data = response.json()
    assert data["total_branches_found"] == 6
    assert data["nearest_branch"]["branch"]["branch_id"] == "ferguson-alexandria"
    assert data["nearest_branch"]["distance_miles"] < 2.0


@pytest.mark.asyncio
async def test_get_lockers_vault_html_view(
    client: AsyncClient,
    sample_tenant: dict,
    seeded_locker_action: LeadAction,
):
    """Verify GET /lockers-vault/{tenant_slug} renders multi-truck lockers vault."""
    tenant = sample_tenant["tenant"]
    url = f"/lockers-vault/{tenant.slug}"
    response = await client.get(url)
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]

    html = response.text
    assert "Emergency Locker Fleet Vault" in html
    assert "After-Hours Staged Materials" in html
    assert "Connected Regional Distributor Hubs" in html


@pytest.mark.asyncio
async def test_lockers_unknown_ids_return_404(client: AsyncClient):
    """Verify 404 responses for invalid/nonexistent action ID and tenant slug."""
    fake_id = uuid.uuid4()
    resp1 = await client.get(f"/lockers/{fake_id}")
    assert resp1.status_code == 404

    resp2 = await client.get(f"/api/v1/lockers/{fake_id}/json")
    assert resp2.status_code == 404

    resp3 = await client.post(f"/api/v1/lockers/reserve/{fake_id}", json={})
    assert resp3.status_code == 404

    resp4 = await client.get("/lockers-vault/completely-non-existent-tenant-slug")
    assert resp4.status_code == 404
