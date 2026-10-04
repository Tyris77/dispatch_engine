import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lead_action import LeadAction
from app.models.tenant import Tenant
from app.schemas.mileage import FleetMileageReport, MileageTripRecord
from app.services.mileage import mileage_service


@pytest.fixture
async def mileage_test_data(sample_tenant: dict, db_session: AsyncSession) -> dict:
    """Fixture providing tenant with multiple LeadAction records containing trip mileage."""
    tenant = sample_tenant["tenant"]
    tenant.name = "Apex Precision Fleet Services LLC"
    tenant.settings = {
        "shop_address": "4000 Commercial Center Dr, Austin, TX 78744",
        "on_call_roster": [
            {"name": "Marcus Vance", "phone": "+15551112233", "trade": "HVAC"},
            {"name": "Dave Miller", "phone": "+15552223344", "trade": "Plumbing"},
        ],
    }
    db_session.add(tenant)

    # Action 1: Emergency dispatch with explicit trip mileage
    action1 = LeadAction(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        lead_external_id="+15553334444",
        qualification_score=0.95,
        qualification_summary="Emergency burst commercial water riser flooding mechanical room.",
        action_type="EMERGENCY_DISPATCH",
        dispatch_status="COMPLETED",
        crm_sync_status="SYNCED",
        metadata_payload={
            "customer_name": "Travis County Center",
            "address": "700 Lavaca St, Austin, TX 78701",
            "assigned_technician": "Dave Miller",
            "trade_type": "Plumbing",
        },
        trip_mileage=24.5,
    )

    # Action 2: Estimate inspection
    action2 = LeadAction(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        lead_external_id="+15554445555",
        qualification_score=0.88,
        qualification_summary="Comprehensive commercial HVAC system replacement estimate inspection.",
        action_type="DISPATCH_ROUTED",
        dispatch_status="CONFIRMED",
        crm_sync_status="SYNCED",
        metadata_payload={
            "customer_name": "Austin Tech Ridge Office",
            "address": "11200 Metric Blvd, Austin, TX 78758",
            "assigned_technician": "Marcus Vance",
            "trade_type": "HVAC",
        },
        proposal_data={"tier": "Best", "price": 12500.0},
        trip_mileage=36.0,
    )

    # Action 3: Parts will-call pickup run
    action3 = LeadAction(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        lead_external_id="+15555556666",
        qualification_score=0.82,
        qualification_summary="Will-call supply warehouse parts pickup for 15-ton compressor capacitor.",
        action_type="DISPATCH_ROUTED",
        dispatch_status="COMPLETED",
        crm_sync_status="SYNCED",
        metadata_payload={
            "customer_name": "Johnstone Supply Warehouse",
            "address": "2100 E St Elmo Rd, Austin, TX 78744",
            "assigned_technician": "Marcus Vance",
            "trade_type": "HVAC",
        },
        material_po={"po_number": "PO-2026-9921", "amount": 420.0},
        trip_mileage=12.8,
    )

    db_session.add_all([action1, action2, action3])
    await db_session.commit()
    await db_session.refresh(action1)
    await db_session.refresh(action2)
    await db_session.refresh(action3)

    return {"tenant": tenant, "actions": [action1, action2, action3]}


def test_mileage_schemas():
    """Verify validation and serialization of MileageTripRecord and FleetMileageReport."""
    trip = MileageTripRecord(
        trip_id="TRIP-2026-0001",
        date="2026-03-12",
        driver_name="Marcus Vance",
        origin_address="4000 Commercial Center Dr, Austin, TX",
        destination_address="742 Evergreen Terrace, Austin, TX",
        business_purpose="Emergency Dispatch",
        miles_driven=28.4,
        irs_rate=0.67,
        deductible_dollars=19.03,
    )
    assert trip.trip_id == "TRIP-2026-0001"
    assert trip.miles_driven == 28.4
    assert trip.deductible_dollars == 19.03
    assert trip.irs_rate == 0.67

    report = FleetMileageReport(
        tenant_slug="apex-fleet",
        tenant_name="Apex Precision Fleet",
        tax_year=2026,
        total_trips=1,
        total_business_miles=28.4,
        total_tax_deduction_dollars=19.03,
        irs_rate=0.67,
        trips=[trip],
    )
    assert report.total_trips == 1
    assert report.total_business_miles == 28.4
    assert report.total_tax_deduction_dollars == 19.03


@pytest.mark.asyncio
async def test_mileage_service_report_generation(
    mileage_test_data: dict,
    db_session: AsyncSession,
):
    """Verify mileage service aggregates actions, computes mileage deductions, and formats CSV."""
    tenant = mileage_test_data["tenant"]

    report = await mileage_service.generate_fleet_mileage_report(
        tenant=tenant,
        tax_year=2026,
        db=db_session,
    )

    assert report.tenant_slug == tenant.slug
    assert report.tenant_name == tenant.name
    assert report.tax_year == 2026
    assert report.total_trips == 3
    # Expected miles: 24.5 + 36.0 + 12.8 = 73.3
    assert report.total_business_miles == 73.3
    # Expected deduction: round(73.3 * 0.67, 2) = round(49.111, 2) = 49.11
    assert report.total_tax_deduction_dollars == round(sum(t.deductible_dollars for t in report.trips), 2)
    assert report.irs_rate == 0.67

    # Verify business purposes categorized correctly
    purposes = [t.business_purpose for t in report.trips]
    assert "Emergency Dispatch" in purposes
    assert "Estimate Inspection" in purposes
    assert "Will-Call Parts Pickup" in purposes

    # Verify CSV generation
    csv_text = mileage_service.generate_mileage_csv(report)
    assert "# IRS FLEET MILEAGE TAX LEDGER" in csv_text
    assert tenant.name in csv_text
    assert "Trip ID,Date,Driver / Technician" in csv_text
    assert "73.3" in csv_text
    assert "Dave Miller" in csv_text
    assert "Marcus Vance" in csv_text


@pytest.mark.asyncio
async def test_mileage_service_baseline_fallback(
    sample_tenant: dict,
    db_session: AsyncSession,
):
    """Verify mileage service produces a realistic baseline log for new tenants without historical leads."""
    tenant = sample_tenant["tenant"]

    report = await mileage_service.generate_fleet_mileage_report(
        tenant=tenant,
        tax_year=2026,
        db=db_session,
    )
    assert report.total_trips >= 3
    assert report.total_business_miles > 0.0
    assert report.total_tax_deduction_dollars > 0.0


@pytest.mark.asyncio
async def test_mileage_ledger_html_view(
    client: AsyncClient,
    mileage_test_data: dict,
):
    """Verify GET /fleet/mileage/{tenant_slug} renders printable HTML ledger with filters and stats."""
    tenant = mileage_test_data["tenant"]

    resp = await client.get(f"/fleet/mileage/{tenant.slug}")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    html = resp.text

    assert tenant.name in html
    assert "IRS Publication 463 Standard Mileage Compliance" in html
    assert "Total Business Miles" in html
    assert "Federal Tax Deduction" in html
    assert "73.3" in html
    assert "$0.67" in html
    assert "Export IRS CPA CSV" in html
    assert "Print / PDF Ledger" in html
    assert "Dave Miller" in html
    assert "Marcus Vance" in html


@pytest.mark.asyncio
async def test_mileage_export_csv_download(
    client: AsyncClient,
    mileage_test_data: dict,
):
    """Verify GET /api/v1/mileage/{tenant_slug}/export.csv downloads valid CPA tax CSV."""
    tenant = mileage_test_data["tenant"]

    resp = await client.get(f"/api/v1/mileage/{tenant.slug}/export.csv")
    assert resp.status_code == 200
    assert "text/csv" in resp.headers["content-type"]
    assert f'attachment; filename="IRS_Fleet_Mileage_{tenant.slug}_2026.csv"' in resp.headers["content-disposition"]

    csv_body = resp.text
    assert "# IRS FLEET MILEAGE TAX LEDGER" in csv_body
    assert "Origin Address,Destination Address,IRS Qualifying Purpose" in csv_body
    assert "73.3" in csv_body


@pytest.mark.asyncio
async def test_mileage_rest_json_endpoints(
    client: AsyncClient,
    mileage_test_data: dict,
):
    """Verify REST JSON responses for fleet mileage."""
    tenant = mileage_test_data["tenant"]

    # Endpoint 1: Query param format=json on ledger route
    resp1 = await client.get(f"/fleet/mileage/{tenant.slug}?format=json")
    assert resp1.status_code == 200
    data1 = resp1.json()
    assert data1["tenant_slug"] == tenant.slug
    assert data1["total_trips"] == 3
    assert data1["total_business_miles"] == 73.3

    # Endpoint 2: Direct REST route
    resp2 = await client.get(f"/api/v1/mileage/{tenant.slug}")
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["tenant_slug"] == tenant.slug
    assert data2["total_tax_deduction_dollars"] > 0.0

    # 404 test
    resp_404 = await client.get("/api/v1/mileage/non-existent-tenant-slug")
    assert resp_404.status_code == 404
