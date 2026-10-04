import io
import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lead_action import LeadAction
from app.models.tenant import Tenant
from app.schemas.storyboard import (
    DailyProgressMilestone,
    JobStoryboardData,
    StoryboardVisionAssessment,
)
from app.services.storyboard import storyboard_service

# Valid 1x1 RGBA PNG
TINY_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"
    b"\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


def test_storyboard_schemas():
    """Validate storyboard data models and constraints."""
    milestone = DailyProgressMilestone(
        day_number=1,
        date="2026-10-04",
        photo_urls=["/storyboard/photo1.jpg"],
        summary="Tear off completed, synthetic underlayment secured.",
        completion_percentage=35,
        weather_tight_verified=True,
        customer_notes="No leaks observed.",
    )
    assert milestone.day_number == 1
    assert milestone.completion_percentage == 35
    assert milestone.weather_tight_verified is True

    board = JobStoryboardData(
        action_id=str(uuid.uuid4()),
        project_title="Architectural Shingle Roof Replacement",
        total_days_estimated=3,
        current_completion_pct=35,
        is_weather_tight=True,
        milestones=[milestone],
    )
    assert board.total_days_estimated == 3
    assert len(board.milestones) == 1
    assert board.is_weather_tight is True

    assessment = StoryboardVisionAssessment(
        progress_percentage=40,
        weather_tight=True,
        summary="Work progressing smoothly.",
    )
    assert assessment.progress_percentage == 40


def test_storyboard_fallback_assessment():
    """Verify fallback heuristics when Gemini API is simulated."""
    # Percentage extraction in notes
    assess1 = storyboard_service._fallback_assessment(
        notes="Valleys dry. 55% completed today.",
        prev_pct=20,
        day_number=2,
        total_days=3,
    )
    assert assess1.progress_percentage == 55
    assert assess1.weather_tight is True

    # Weather-tight negative keyword detection
    assess2 = storyboard_service._fallback_assessment(
        notes="Tear-off done but open roof overnight due to wind.",
        prev_pct=30,
        day_number=1,
        total_days=3,
    )
    assert assess2.weather_tight is False


@pytest.mark.asyncio
async def test_add_daily_milestone_service(db_session: AsyncSession):
    """Test milestone addition, image storage, and status progression."""
    tenant = Tenant(
        id=uuid.uuid4(),
        name="Apex Roofing Specialists",
        slug=f"apex-roofing-{uuid.uuid4().hex[:6]}",
        api_key_hash="hash",
        webhook_secret="secret",
        settings={"base_url": "http://testserver"},
    )
    db_session.add(tenant)

    lead = LeadAction(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        action_type="DISPATCH_SCHEDULED",
        lead_external_id="+15559876543",
        qualification_summary="Full 35-Square Asphalt Shingle Replacement",
        metadata_payload={
            "phone": "+15559876543",
            "address": "1234 Highland Ave, Atlanta, GA",
            "estimated_days": 3,
        },
    )
    db_session.add(lead)
    await db_session.commit()

    # Day 1 milestone upload
    board_day1 = await storyboard_service.add_daily_milestone(
        action_id=lead.id,
        image_bytes_list=[TINY_PNG, TINY_PNG],
        notes="Day 1 tear-off finished, ice and water shield installed. 35% complete.",
        db=db_session,
    )
    assert len(board_day1.milestones) == 1
    assert board_day1.current_completion_pct == 35
    assert board_day1.is_weather_tight is True
    assert len(board_day1.milestones[0].photo_urls) == 2

    # Verify DB persistence
    await db_session.refresh(lead)
    assert lead.storyboard_data is not None
    assert lead.storyboard_data["current_completion_pct"] == 35


@pytest.mark.asyncio
async def test_storyboard_views_and_endpoints(client: AsyncClient, db_session: AsyncSession):
    """Test GET view (HTML & JSON), photo endpoint, and POST milestone upload."""
    tenant = Tenant(
        id=uuid.uuid4(),
        name="Summit Ridge Exteriors",
        slug=f"summit-ridge-{uuid.uuid4().hex[:6]}",
        api_key_hash="hash",
        webhook_secret="secret",
    )
    db_session.add(tenant)

    lead = LeadAction(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        action_type="JOB_IN_PROGRESS",
        lead_external_id="+15552223344",
        qualification_summary="Two-Story Siding & Fascia Wrap",
        metadata_payload={"estimated_days": 4, "phone": "+15552223344"},
    )
    db_session.add(lead)
    await db_session.commit()

    # 1. GET HTML view
    resp_html = await client.get(f"/storyboard/{lead.id}")
    assert resp_html.status_code == 200
    assert "Jobsite Progress Storyboard" in resp_html.text
    assert "Two-Story Siding" in resp_html.text

    # 2. GET JSON view via format=json
    resp_json = await client.get(f"/storyboard/{lead.id}?format=json")
    assert resp_json.status_code == 200
    data = resp_json.json()
    assert data["action_id"] == str(lead.id)
    assert data["total_days_estimated"] == 4

    # 3. GET JSON via API endpoint
    resp_api = await client.get(f"/api/v1/storyboard/{lead.id}")
    assert resp_api.status_code == 200
    assert resp_api.json()["action_id"] == str(lead.id)

    # 4. POST milestone upload with multipart form
    files = [
        ("photos", ("day1_site.png", io.BytesIO(TINY_PNG), "image/png")),
    ]
    resp_upload = await client.post(
        f"/storyboard/{lead.id}/milestone",
        files=files,
        data={"notes": "All siding stripped and housewrap installed. Weather-tight verified."},
        headers={"Accept": "application/json"},
    )
    assert resp_upload.status_code == 200
    upload_data = resp_upload.json()
    assert len(upload_data["milestones"]) == 1
    photo_url = upload_data["milestones"][0]["photo_urls"][0]
    assert photo_url.startswith(f"/storyboard/{lead.id}/photo/")

    # 5. GET stored photo
    resp_photo = await client.get(photo_url)
    assert resp_photo.status_code == 200
    assert resp_photo.headers["content-type"] in ("image/png", "image/jpeg")

    # 6. 404 for unknown job
    random_id = uuid.uuid4()
    resp_404 = await client.get(f"/storyboard/{random_id}")
    assert resp_404.status_code == 404
