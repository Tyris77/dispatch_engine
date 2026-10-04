import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lead_action import LeadAction
from app.models.tenant import Tenant
from app.schemas.lien_notice import LienNoticeDocument, LienNoticeResponse
from app.services.lien_notice import lien_notice_service


@pytest.fixture
async def lien_test_lead(sample_tenant: dict, db_session: AsyncSession) -> dict:
    """Fixture providing a tenant and an overdue LeadAction ready for statutory notice."""
    tenant = sample_tenant["tenant"]
    tenant.name = "Dominion Mechanical Contractors LLC"
    db_session.add(tenant)

    action = LeadAction(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        lead_external_id="+15559998877",
        qualification_score=0.91,
        qualification_summary="Emergency chiller coil overhaul and chemical flush.",
        action_type="DISPATCH_EMERGENCY_DISPATCH_QUEUE",
        dispatch_status="INVOICED",
        crm_sync_status="SYNCED",
        metadata_payload={
            "customer_name": "Montgomery Commercial Properties LLC",
            "address": "7400 Wisconsin Ave, Bethesda, MD 20814",
            "property_address": "7400 Wisconsin Ave, Bethesda, MD 20814",
        },
        invoice_data={
            "contract_total": 4850.0,
            "balance_due": 4850.0,
            "due_date": "2026-08-15",
            "status": "OVERDUE",
        },
    )

    db_session.add(action)
    await db_session.commit()
    await db_session.refresh(action)
    return {"tenant": tenant, "action": action}


def test_detect_jurisdiction():
    """Verify jurisdiction detection resolves MD, VA, DC, and standard default."""
    assert lien_notice_service.detect_jurisdiction("4800 Hampden Ln, Bethesda, MD 20814") == "MD"
    assert lien_notice_service.detect_jurisdiction("Rockville, Maryland") == "MD"
    assert lien_notice_service.detect_jurisdiction("1900 Reston Pkwy, Reston, VA 20191") == "VA"
    assert lien_notice_service.detect_jurisdiction("Fairfax, Virginia") == "VA"
    assert lien_notice_service.detect_jurisdiction("1600 Pennsylvania Ave NW, Washington, DC 20500") == "DC"
    assert lien_notice_service.detect_jurisdiction("District of Columbia") == "DC"
    assert lien_notice_service.detect_jurisdiction("100 Main St, Seattle, WA 98101") == "US_STANDARD"


def test_generate_statutory_lien_notice_md(lien_test_lead: dict):
    """Verify Maryland lien notice cites Md. Real Prop. § 9-104 with 120-day computation."""
    tenant = lien_test_lead["tenant"]
    action = lien_test_lead["action"]

    doc = lien_notice_service.generate_statutory_lien_notice(action, tenant)

    assert isinstance(doc, LienNoticeDocument)
    assert doc.jurisdiction == "MD"
    assert "§ 9-104" in doc.statutory_citation
    assert doc.notice_type == "NOTICE_OF_INTENT_TO_LIEN"
    assert doc.overdue_balance == 4850.0
    assert doc.customer_name == "Montgomery Commercial Properties LLC"
    assert "7400 Wisconsin Ave" in doc.property_address
    assert doc.notice_number.startswith("NTO-2026-")
    assert doc.certified_mail_tracking.startswith("7021 0350")
    assert "4,850.00" in doc.statutory_warning_text
    assert action.lien_notice_data is not None


def test_generate_statutory_lien_notice_va(sample_tenant: dict):
    """Verify Virginia preliminary notice cites Va. Code Ann. § 43-4."""
    tenant = sample_tenant["tenant"]
    action = LeadAction(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        lead_external_id="+15552229900",
        metadata_payload={
            "customer_name": "Tysons Corner Galleria",
            "address": "1800 Chain Bridge Rd, McLean, VA 22102",
        },
        invoice_data={"balance_due": 3200.0},
    )

    doc = lien_notice_service.generate_statutory_lien_notice(action, tenant)
    assert doc.jurisdiction == "VA"
    assert "§ 43-4" in doc.statutory_citation
    assert doc.notice_type == "PRELIMINARY_NOTICE_TO_OWNER"
    assert doc.overdue_balance == 3200.0


def test_generate_statutory_lien_notice_dc(sample_tenant: dict):
    """Verify District of Columbia notice cites D.C. Official Code § 40-303."""
    tenant = sample_tenant["tenant"]
    action = LeadAction(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        lead_external_id="+15553338811",
        metadata_payload={
            "customer_name": "Dupont Circle Holdings",
            "address": "1200 Connecticut Ave NW, Washington, DC 20036",
        },
        invoice_data={"balance_due": 5400.0},
    )

    doc = lien_notice_service.generate_statutory_lien_notice(action, tenant)
    assert doc.jurisdiction == "DC"
    assert "§ 40-303" in doc.statutory_citation
    assert doc.notice_type == "NOTICE_OF_INTENT_TO_LIEN"
    assert doc.overdue_balance == 5400.0


@pytest.mark.asyncio
async def test_get_lien_notice_view_html(
    lien_test_lead: dict,
    client: AsyncClient,
):
    """GET /lien-notice/{action_id} renders formal printable legal notice HTML."""
    action = lien_test_lead["action"]
    resp = await client.get(f"/lien-notice/{action.id}")
    assert resp.status_code == 200
    html = resp.text
    assert "STATUTORY NOTICE TO OWNER" in html or "NOTICE OF INTENT TO LIEN" in html
    assert "USPS CERTIFIED MAIL" in html
    assert "7400 Wisconsin Ave" in html
    assert "4,850.00" in html
    assert "Proof of Statutory Service" in html or "Affidavit" in html
    assert "Print Statutory Notice" in html or "Print" in html


@pytest.mark.asyncio
async def test_get_lien_notice_view_json(
    lien_test_lead: dict,
    client: AsyncClient,
):
    """GET /lien-notice/{action_id}?format=json returns serialized LienNoticeDocument."""
    action = lien_test_lead["action"]
    resp = await client.get(f"/lien-notice/{action.id}?format=json")
    assert resp.status_code == 200
    data = resp.json()
    assert data["customer_name"] == "Montgomery Commercial Properties LLC"
    assert data["overdue_balance"] == 4850.0
    assert "§ 9-104" in data["statutory_citation"]


@pytest.mark.asyncio
async def test_get_lien_notice_not_found(client: AsyncClient):
    """GET /lien-notice/{unknown_uuid} returns 404."""
    resp = await client.get(f"/lien-notice/{uuid.uuid4()}")
    assert resp.status_code == 404
    assert "not found" in resp.text.lower()


@pytest.mark.asyncio
async def test_post_generate_lien_notice_redirect(
    lien_test_lead: dict,
    client: AsyncClient,
):
    """POST /lien-notice/{action_id}/generate triggers generation and redirects to view."""
    action = lien_test_lead["action"]
    resp = await client.post(
        f"/lien-notice/{action.id}/generate",
        data={"notice_type": "NOTICE_OF_INTENT_TO_LIEN"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == f"/lien-notice/{action.id}"


@pytest.mark.asyncio
async def test_post_generate_lien_notice_json(
    lien_test_lead: dict,
    client: AsyncClient,
):
    """POST /lien-notice/{action_id}/generate?format=json returns LienNoticeResponse."""
    action = lien_test_lead["action"]
    resp = await client.post(
        f"/lien-notice/{action.id}/generate?format=json",
        data={"notice_type": "NOTICE_OF_INTENT_TO_LIEN"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "SUCCESS"
    assert "notice" in data
    assert data["notice"]["overdue_balance"] == 4850.0


@pytest.mark.asyncio
async def test_api_get_lien_notice(
    lien_test_lead: dict,
    client: AsyncClient,
):
    """GET /api/v1/lien-notice/{action_id} returns LienNoticeDocument via REST."""
    action = lien_test_lead["action"]
    resp = await client.get(f"/api/v1/lien-notice/{action.id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["jurisdiction"] == "MD"
    assert data["overdue_balance"] == 4850.0
    assert data["notice_number"].startswith("NTO-2026-")
