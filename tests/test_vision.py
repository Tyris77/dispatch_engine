import io
import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lead_action import LeadAction
from app.models.tenant import Tenant
from app.schemas.vision import DiagnosticSubmissionResponse, EquipmentDiagnosticReport
from app.services.vision import (
    analyze_diagnostic_image,
    fallback_equipment_diagnostic,
    vision_service,
)


def test_equipment_diagnostic_schema_validation():
    """Verify that EquipmentDiagnosticReport validates required and optional fields correctly."""
    report = EquipmentDiagnosticReport(
        equipment_type="HVAC Condenser",
        brand_manufacturer="Carrier",
        model_number="24VNA936A003",
        serial_number="3822E19842",
        detected_materials=["Copper", "Aluminum"],
        damage_assessment="Leaking evaporator coil and low refrigerant.",
        recommended_parts_tools=["410A Refrigerant", "Nitrogen Leak Detector"],
        confidence_score=0.95,
    )
    assert report.equipment_type == "HVAC Condenser"
    assert report.brand_manufacturer == "Carrier"
    assert len(report.detected_materials) == 2
    assert report.confidence_score == 0.95

    # Test serialization and deserialization
    json_data = report.model_dump_json()
    rehydrated = EquipmentDiagnosticReport.model_validate_json(json_data)
    assert rehydrated.model_number == "24VNA936A003"
    assert rehydrated.confidence_score == 0.95


@pytest.mark.asyncio
async def test_analyze_diagnostic_image_gemini_success():
    """Verify analyze_diagnostic_image correctly parses Gemini multimodal structured outputs."""
    mock_json = """
    {
        "equipment_type": "Gas Water Heater",
        "brand_manufacturer": "Bradford White",
        "model_number": "RG250T6N",
        "serial_number": "BW2024-8841",
        "detected_materials": ["Copper", "Brass", "Galvanized Steel"],
        "damage_assessment": "Pinhole leak on hot outlet nipple with heavy calcium crust.",
        "recommended_parts_tools": ["3/4 Dielectric Nipple", "Pipe Thread Paste", "Pipe Wrench"],
        "confidence_score": 0.97
    }
    """
    mock_response = MagicMock()
    mock_response.text = mock_json

    mock_client = MagicMock()
    mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

    fake_image_bytes = b"\xff\xd8\xff\xe0\x00\x10JFIF"  # Fake JPEG header

    with patch("app.services.vision.settings.GEMINI_API_KEY", "test-vision-api-key"):
        with patch("app.services.vision.genai.Client", return_value=mock_client):
            report = await analyze_diagnostic_image(
                image_bytes=fake_image_bytes,
                mime_type="image/jpeg",
                trade_context={"trade": "plumbing"},
            )

    assert isinstance(report, EquipmentDiagnosticReport)
    assert report.equipment_type == "Gas Water Heater"
    assert report.brand_manufacturer == "Bradford White"
    assert report.model_number == "RG250T6N"
    assert report.confidence_score == 0.97
    assert "Dielectric Nipple" in report.recommended_parts_tools[0]


@pytest.mark.asyncio
async def test_analyze_diagnostic_image_fallback():
    """Verify that when Gemini API is unconfigured or fails, fallback provides a rich report."""
    fake_image_bytes = b"sample_bytes_content"

    # Test with plumbing context
    plumbing_report = await analyze_diagnostic_image(
        image_bytes=fake_image_bytes,
        mime_type="image/jpeg",
        trade_context={"trade": "emergency plumbing"},
    )
    assert plumbing_report.equipment_type == "Gas Water Heater"
    assert plumbing_report.brand_manufacturer == "Rheem"
    assert len(plumbing_report.recommended_parts_tools) > 0

    # Test with electrical context
    electrical_report = fallback_equipment_diagnostic(
        fake_image_bytes,
        trade_context={"trade": "commercial electrical"},
    )
    assert electrical_report.equipment_type == "Main Electrical Panel"
    assert electrical_report.brand_manufacturer == "Square D"
    assert any("Romex Wire" in mat for mat in electrical_report.detected_materials)

    # Test with roofing context
    roofing_report = fallback_equipment_diagnostic(
        fake_image_bytes,
        trade_context={"trade": "roofing restoration"},
    )
    assert roofing_report.equipment_type == "Architectural Shingle Roofing"
    assert roofing_report.brand_manufacturer == "GAF"


@pytest.mark.asyncio
async def test_get_intake_page_success(
    client: AsyncClient,
    db_session: AsyncSession,
    sample_tenant: dict,
):
    """Verify GET /intake/{action_id} renders the mobile camera capture screen."""
    tenant: Tenant = sample_tenant["tenant"]

    # Create a test LeadAction
    action = LeadAction(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        lead_external_id="+15554443322",
        action_type="DISPATCH_HVAC_EMERGENCY",
        dispatch_status="QUEUED",
        crm_sync_status="PENDING",
        metadata_payload={"channel": "voice"},
    )
    db_session.add(action)
    await db_session.commit()

    response = await client.get(f"/intake/{action.id}")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert tenant.name in response.text
    assert "Capture Equipment or Data Plate" in response.text


@pytest.mark.asyncio
async def test_get_intake_page_not_found(client: AsyncClient):
    """Verify GET /intake/{action_id} returns 404 for non-existent IDs."""
    fake_id = uuid.uuid4()
    response = await client.get(f"/intake/{fake_id}")
    assert response.status_code == 404
    assert f"Lead action '{fake_id}' not found" in response.text


@pytest.mark.asyncio
async def test_post_intake_photo_upload_and_dispatch(
    client: AsyncClient,
    db_session: AsyncSession,
    sample_tenant: dict,
):
    """Verify POST /intake/{action_id} processes uploaded image, updates lead, and redirects."""
    tenant: Tenant = sample_tenant["tenant"]
    tenant.settings = {
        **tenant.settings,
        "alert_phone_number": "+15557778899",
        "trade": "hvac",
    }
    await db_session.commit()

    action = LeadAction(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        lead_external_id="+15554443322",
        action_type="DISPATCH_EMERGENCY",
        dispatch_status="COMPLETED",
        crm_sync_status="PENDING",
        metadata_payload={},
    )
    db_session.add(action)
    await db_session.commit()

    # Create a mock image file
    fake_image_content = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00H\x00H\x00\x00"
    files = {
        "photo": ("condenser_plate.jpg", fake_image_content, "image/jpeg"),
    }
    data = {
        "notes": "Unit is humming loudly with no fan movement.",
    }

    with patch("app.api.v1.intake.send_diagnostic_sms_alert", new_callable=AsyncMock) as mock_sms:
        mock_sms.return_value = True

        response = await client.post(
            f"/intake/{action.id}",
            files=files,
            data=data,
            follow_redirects=False,
        )

    # Asserts 303 See Other redirect
    assert response.status_code == 303
    assert response.headers["location"] == f"/intake/{action.id}?success=true"

    # Verify database was updated
    await db_session.refresh(action)
    assert action.diagnostic_data is not None
    assert "equipment_type" in action.diagnostic_data
    assert "damage_assessment" in action.diagnostic_data
    assert len(action.diagnostic_data["recommended_parts_tools"]) > 0
    assert action.metadata_payload.get("intake_notes") == "Unit is humming loudly with no fan movement."

    # Verify SMS alert was triggered
    mock_sms.assert_awaited_once()
    call_args = mock_sms.call_args[1]
    assert call_args["to_phone"] == "+15557778899"
    assert "📸 DIAGNOSTIC UPDATE" in call_args["message_body"]


@pytest.mark.asyncio
async def test_post_intake_photo_json_mode(
    client: AsyncClient,
    db_session: AsyncSession,
    sample_tenant: dict,
):
    """Verify POST /intake/{action_id} returns structured JSON when Accept header specifies application/json."""
    tenant: Tenant = sample_tenant["tenant"]

    action = LeadAction(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        lead_external_id="+15559991122",
        action_type="DISPATCH_PLUMBING",
        dispatch_status="COMPLETED",
        crm_sync_status="PENDING",
        metadata_payload={},
    )
    db_session.add(action)
    await db_session.commit()

    fake_image_content = b"\xff\xd8\xff\xe0\x00\x10JFIFfakeimagedata"
    files = {
        "photo": ("water_heater.jpg", fake_image_content, "image/jpeg"),
    }

    response = await client.post(
        f"/intake/{action.id}",
        files=files,
        headers={"Accept": "application/json"},
    )

    assert response.status_code == 200
    res_json = response.json()
    assert res_json["success"] is True
    assert res_json["action_id"] == str(action.id)
    assert "report" in res_json
    assert res_json["report"]["equipment_type"] != ""
