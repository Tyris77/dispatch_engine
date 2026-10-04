import os
import uuid
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.models.lead_action import LeadAction
from app.models.tenant import Tenant
from app.schemas.mitigation import MitigationDryingReport
from app.services.mitigation import mitigation_service

router = APIRouter(tags=["IICRC S500 Water Mitigation & Psychrometric Drying Log Engine"])

TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "templates")
templates = Jinja2Templates(directory=TEMPLATES_DIR)


@router.get(
    "/mitigation/{action_id}",
    response_class=HTMLResponse,
    summary="IICRC S500 Water Mitigation Drying Report",
    description="Printable insurance adjuster drying packet with psychrometric GPP curves, moisture grids, and certification.",
)
async def get_mitigation_report_view(
    action_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    format: Optional[str] = Query(None, description="Response format override ('json')"),
) -> Response:
    try:
        action_uuid = uuid.UUID(action_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Invalid action ID format: '{action_id}'",
        )

    stmt = select(LeadAction).where(LeadAction.id == action_uuid)
    lead_action = (await db.execute(stmt)).scalar_one_or_none()
    if not lead_action:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"LeadAction '{action_id}' not found",
        )

    # Fetch Tenant
    tenant_stmt = select(Tenant).where(Tenant.id == lead_action.tenant_id)
    tenant = (await db.execute(tenant_stmt)).scalar_one_or_none()
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant associated with action not found",
        )

    report = await mitigation_service.get_mitigation_report(action_id=action_uuid, db=db)

    if format == "json" or "application/json" in request.headers.get("accept", ""):
        return JSONResponse(content=report.model_dump())

    return templates.TemplateResponse(
        request=request,
        name="mitigation_log.html",
        context={
            "report": report,
            "tenant": tenant,
            "lead_action": lead_action,
        },
    )


@router.post(
    "/mitigation/{action_id}/log",
    summary="Record Daily Moisture Meter Log",
    description="Ingests daily psychrometric atmospheric readings and structural moisture content.",
)
async def post_mitigation_daily_log(
    action_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Response:
    try:
        action_uuid = uuid.UUID(action_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Invalid action ID format: '{action_id}'",
        )

    stmt = select(LeadAction).where(LeadAction.id == action_uuid)
    lead_action = (await db.execute(stmt)).scalar_one_or_none()
    if not lead_action:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"LeadAction '{action_id}' not found",
        )

    content_type = request.headers.get("content-type", "")
    is_json = "application/json" in content_type

    if is_json:
        log_data = await request.json()
    else:
        form = await request.form()
        day_num = int(form.get("day_number", 1))
        temp_f = float(form.get("temp_fahrenheit", 72.0))
        rh_pct = float(form.get("relative_humidity_pct", 35.0))
        dehumids = int(form.get("dehumidifiers_running", 2))
        air_movers = int(form.get("air_movers_running", 4))

        reading_drywall = float(form.get("reading_drywall", 10.5))
        reading_subfloor = float(form.get("reading_subfloor", 11.8))

        log_data = {
            "day_number": day_num,
            "temp_fahrenheit": temp_f,
            "relative_humidity_pct": rh_pct,
            "dehumidifiers_running": dehumids,
            "air_movers_running": air_movers,
            "readings": [
                {
                    "room_name": "Basement Containment",
                    "material_type": "Drywall",
                    "moisture_percentage": reading_drywall,
                    "dry_standard": 12.0,
                },
                {
                    "room_name": "Basement Containment",
                    "material_type": "Subfloor",
                    "moisture_percentage": reading_subfloor,
                    "dry_standard": 12.0,
                },
            ],
        }

    updated_report = await mitigation_service.record_daily_moisture_log(
        action_id=action_uuid,
        log_data=log_data,
        db=db,
    )

    if is_json or "application/json" in request.headers.get("accept", ""):
        return JSONResponse(content=updated_report.model_dump())

    return RedirectResponse(
        url=f"/mitigation/{action_id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )
