import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lead_action import LeadAction
from app.models.tenant import Tenant
from app.schemas.tax_vault import Annual1099Report, Subcontractor1099Record
from app.services.tax_vault import tax_vault_service


@pytest.fixture
async def tax_vault_test_data(sample_tenant: dict, db_session: AsyncSession) -> dict:
    """Fixture providing tenant with multiple LeadAction records containing crew labor settlements."""
    tenant = sample_tenant["tenant"]
    tenant.name = "Lone Star Commercial Roofing and Restoration"
    db_session.add(tenant)

    await db_session.commit()
    await db_session.refresh(tenant)


    # Lead 1: Crew Alpha - Roof tear-off and reshingle
    action1 = LeadAction(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        lead_external_id="+15551113333",
        qualification_score=0.94,
        qualification_summary="Commercial EPDM membrane roof tear-off and replacement.",
        action_type="EMERGENCY_DISPATCH",
        dispatch_status="COMPLETED",
        crm_sync_status="SYNCED",
        crew_data={
            "voucher_number": "VOUCH-2026-A101",
            "action_id": "dummy-1",
            "customer_name": "Austin Business Park",
            "job_address": "8800 Research Blvd, Austin, TX",
            "scope_summary": "Full tear-off and 60-mil EPDM installation",
            "status": "SETTLED",
            "settled_at": "2026-04-10T14:30:00Z",
            "created_at": "2026-04-10T14:30:00Z",
            "crew_assignment": {
                "crew_name": "Apex Rapid Shingle Crew Alpha",
                "foreman_name": "Mateo Hernandez",
                "foreman_phone": "+15554441111",
                "trade_specialty": "Roofing",
                "total_crew_payout": 4250.0,
            },
        },
    )

    # Lead 2: Crew Alpha - Second job
    action2 = LeadAction(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        lead_external_id="+15552224444",
        qualification_score=0.91,
        qualification_summary="Storm damage shingle replacement and flashing repair.",
        action_type="DISPATCH_ROUTED",
        dispatch_status="COMPLETED",
        crm_sync_status="SYNCED",
        crew_data={
            "voucher_number": "VOUCH-2026-A102",
            "action_id": "dummy-2",
            "customer_name": "Highland Plaza",
            "job_address": "600 E 4th St, Austin, TX",
            "scope_summary": "Emergency shingle tie-in",
            "status": "SETTLED",
            "settled_at": "2026-06-18T11:00:00Z",
            "created_at": "2026-06-18T11:00:00Z",
            "crew_assignment": {
                "crew_name": "Apex Rapid Shingle Crew Alpha",
                "foreman_name": "Mateo Hernandez",
                "foreman_phone": "+15554441111",
                "trade_specialty": "Roofing",
                "total_crew_payout": 2100.0,
            },
        },
    )

    # Lead 3: Crew Beta - Gutters & Flashing (Subcontractor below threshold)
    action3 = LeadAction(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        lead_external_id="+15553335555",
        qualification_score=0.85,
        qualification_summary="Seamless aluminum commercial gutter fabrication.",
        action_type="DISPATCH_ROUTED",
        dispatch_status="COMPLETED",
        crm_sync_status="SYNCED",
        crew_data={
            "voucher_number": "VOUCH-2026-B201",
            "action_id": "dummy-3",
            "customer_name": "Riverside Lofts",
            "job_address": "1200 S Congress Ave, Austin, TX",
            "scope_summary": "Gutter downspout fabrication",
            "status": "SETTLED",
            "settled_at": "2026-08-05T09:15:00Z",
            "created_at": "2026-08-05T09:15:00Z",
            "crew_assignment": {
                "crew_name": "Hill Country Seamless Gutters LLC",
                "foreman_name": "Clayton Brooks",
                "foreman_phone": "+15556662222",
                "trade_specialty": "Gutters",
                "total_crew_payout": 450.0,  # Below $600 threshold
            },
        },
    )

    db_session.add_all([action1, action2, action3])
    await db_session.commit()
    await db_session.refresh(action1)
    await db_session.refresh(action2)
    await db_session.refresh(action3)

    return {"tenant": tenant, "actions": [action1, action2, action3]}


def test_tax_vault_schemas():
    """Verify validation and serialization of Subcontractor1099Record and Annual1099Report."""
    rec = Subcontractor1099Record(
        crew_name="Apex Rapid Shingle Crew Alpha",
        foreman_name="Mateo Hernandez",
        phone="+15554441111",
        total_vouchers_count=2,
        box1_nonemployee_compensation=6350.0,
        w9_status="ON_FILE",
        ein_or_ssn_masked="XX-XXX4912",
        is_reportable=True,
    )
    assert rec.crew_name == "Apex Rapid Shingle Crew Alpha"
    assert rec.box1_nonemployee_compensation == 6350.0
    assert rec.is_reportable is True
    assert rec.w9_status == "ON_FILE"

    report = Annual1099Report(
        tenant_slug="lone-star-roofing",
        tenant_name="Lone Star Commercial Roofing",
        tax_year=2026,
        total_subcontractors=1,
        total_1099_payouts=6350.0,
        filing_threshold=600.0,
        records=[rec],
    )
    assert report.total_subcontractors == 1
    assert report.total_1099_payouts == 6350.0
    assert report.filing_threshold == 600.0


@pytest.mark.asyncio
async def test_tax_vault_report_generation(
    tax_vault_test_data: dict,
    db_session: AsyncSession,
):
    """Verify tax vault aggregates vouchers, identifies $600 threshold, and generates CSV."""
    tenant = tax_vault_test_data["tenant"]

    report = await tax_vault_service.generate_annual_1099_report(
        tenant=tenant,
        tax_year=2026,
        db=db_session,
    )

    assert report.tenant_slug == tenant.slug
    assert report.tax_year == 2026
    assert report.total_subcontractors == 2

    # Expected payouts: 4250 + 2100 = 6350 (Crew Alpha) + 450 (Crew Beta) = 6800.0
    assert report.total_1099_payouts == 6800.0

    # Crew Alpha check
    crew_alpha = next((r for r in report.records if r.crew_name == "Apex Rapid Shingle Crew Alpha"), None)
    assert crew_alpha is not None
    assert crew_alpha.box1_nonemployee_compensation == 6350.0
    assert crew_alpha.total_vouchers_count == 2
    assert crew_alpha.is_reportable is True
    assert crew_alpha.ein_or_ssn_masked.startswith("XX-XXX")

    # Crew Beta check (under threshold)
    crew_beta = next((r for r in report.records if r.crew_name == "Hill Country Seamless Gutters LLC"), None)
    assert crew_beta is not None
    assert crew_beta.box1_nonemployee_compensation == 450.0
    assert crew_beta.total_vouchers_count == 1
    assert crew_beta.is_reportable is False

    # CSV export test
    csv_text = tax_vault_service.export_1099_csv(report)
    assert "Tax Year,Payer Legal Name" in csv_text
    assert "Apex Rapid Shingle Crew Alpha" in csv_text
    assert "6350.00" in csv_text
    assert "YES" in csv_text
    assert "Hill Country Seamless Gutters LLC" in csv_text
    assert "450.00" in csv_text
    assert "NO" in csv_text


@pytest.mark.asyncio
async def test_tax_vault_html_view(
    client: AsyncClient,
    tax_vault_test_data: dict,
    db_session: AsyncSession,
):
    """Verify GET /tax-vault/{tenant_slug} renders printable IRS Form 1099-NEC ledger."""
    tenant = tax_vault_test_data["tenant"]

    resp = await client.get(f"/tax-vault/{tenant.slug}?tax_year=2026")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    html = resp.text

    assert tenant.name in html
    assert "1099-NEC Subcontractor Tax Vault" in html
    assert "Box 1 Nonemployee Comp" in html
    assert "Apex Rapid Shingle Crew Alpha" in html
    assert "6,350.00" in html
    assert "Export CPA CSV" in html
    assert "Print Ledger" in html


@pytest.mark.asyncio
async def test_tax_vault_export_csv_download(
    client: AsyncClient,
    tax_vault_test_data: dict,
    db_session: AsyncSession,
):
    """Verify GET /api/v1/tax-vault/{tenant_slug}/export.csv downloads formatted CPA tax CSV."""
    tenant = tax_vault_test_data["tenant"]

    resp = await client.get(f"/api/v1/tax-vault/{tenant.slug}/export.csv?tax_year=2026")
    assert resp.status_code == 200
    assert "text/csv" in resp.headers["content-type"]
    assert f'attachment; filename="IRS_1099_NEC_{tenant.slug}_2026.csv"' in resp.headers["content-disposition"]

    csv_body = resp.text
    assert "Tax Year,Payer Legal Name" in csv_body
    assert "Apex Rapid Shingle Crew Alpha" in csv_body
    assert "6350.00" in csv_body


@pytest.mark.asyncio
async def test_tax_vault_rest_json_endpoints(
    client: AsyncClient,
    tax_vault_test_data: dict,
    db_session: AsyncSession,
):

    """Verify REST JSON responses for 1099 tax vault."""
    tenant = tax_vault_test_data["tenant"]

    # Endpoint 1: format=json on ledger view
    resp1 = await client.get(f"/tax-vault/{tenant.slug}?format=json")
    assert resp1.status_code == 200
    data1 = resp1.json()
    assert data1["tenant_slug"] == tenant.slug
    assert data1["total_subcontractors"] == 2
    assert data1["total_1099_payouts"] == 6800.0

    # Endpoint 2: Direct REST route
    resp2 = await client.get(f"/api/v1/tax-vault/{tenant.slug}")
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["tenant_slug"] == tenant.slug
    assert len(data2["records"]) == 2

    # 404 test
    resp_404 = await client.get("/api/v1/tax-vault/non-existent-tenant-slug")
    assert resp_404.status_code == 404
