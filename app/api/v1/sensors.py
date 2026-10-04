import os
import uuid
from typing import Optional
from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, Response, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.models.tenant import Tenant
from app.schemas.sensors import (
    ConnectedSensorDevice,
    SensorAlertPayload,
    SensorAlertResponse,
)
from app.services.sensors import sensors_service

router = APIRouter(tags=["Smart IoT Sensor Ingestion & Emergency Dispatch"])

TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "templates")
templates = Jinja2Templates(directory=TEMPLATES_DIR)


@router.get(
    "/sensors/{tenant_slug}",
    response_class=HTMLResponse,
    summary="Smart Property IoT Sensor Console",
    description="Live telemetry monitor showing smart water shutoffs, freeze sensors, and simulation controls.",
)
async def get_sensor_monitor_view(
    tenant_slug: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    message: Optional[str] = Query(None, description="Optional status message"),
    format: Optional[str] = Query(None, description="Response format override ('json')"),
) -> Response:
    # 1. Fetch Tenant
    stmt = select(Tenant).where(Tenant.slug == tenant_slug)
    tenant = (await db.execute(stmt)).scalar_one_or_none()
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant '{tenant_slug}' not found",
        )

    # 2. Fetch Connected Fleet
    devices = sensors_service.get_connected_fleet_telemetry(tenant)
    on_call_tech = sensors_service._resolve_on_call_technician(tenant)

    if format == "json" or "application/json" in request.headers.get("accept", ""):
        return JSONResponse(
            content={
                "tenant_slug": tenant.slug,
                "tenant_name": tenant.name,
                "on_call_technician": on_call_tech,
                "connected_devices": [dev.model_dump() for dev in devices],
            }
        )

    return templates.TemplateResponse(
        request=request,
        name="sensor_monitor.html",
        context={
            "tenant": tenant,
            "devices": devices,
            "on_call_tech": on_call_tech,
            "message": message,
        },
    )


@router.post(
    "/api/v1/sensors/alert",
    response_model=SensorAlertResponse,
    summary="Ingest IoT Smart Sensor Alert",
    description="Standardized webhook ingestion for smart shutoff valves, flow burst meters, and freeze alarms.",
)
async def post_sensor_alert_endpoint(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Response:
    content_type = request.headers.get("content-type", "")

    # Parse JSON or Form payload
    if "application/json" in content_type:
        raw_data = await request.json()
        payload = SensorAlertPayload.model_validate(raw_data)
        is_json_request = True
    else:
        form = await request.form()
        payload = SensorAlertPayload(
            sensor_id=str(form.get("sensor_id", "FL-MOEN-9912A")),
            sensor_type=str(form.get("sensor_type", "FLOW_BURST_ALARM")),
            property_address=str(form.get("property_address", "1401 S Joyce St, Arlington, VA")),
            customer_name=str(form.get("customer_name", "Elena Rostova")),
            customer_phone=str(form.get("customer_phone", "+17035550182")),
            reading_value=str(form.get("reading_value", "8.4 GPM Pipe Burst")),
            severity=str(form.get("severity", "CRITICAL_EMERGENCY")),
            tenant_slug=str(form.get("tenant_slug", "")) or None,
        )
        is_json_request = False

    # Resolve Tenant
    tenant: Optional[Tenant] = None
    if payload.tenant_slug:
        stmt = select(Tenant).where(Tenant.slug == payload.tenant_slug)
        tenant = (await db.execute(stmt)).scalar_one_or_none()
    elif payload.tenant_id:
        try:
            tid = uuid.UUID(payload.tenant_id)
            stmt = select(Tenant).where(Tenant.id == tid)
            tenant = (await db.execute(stmt)).scalar_one_or_none()
        except (ValueError, TypeError):
            pass

    if not tenant:
        stmt = select(Tenant).where(Tenant.is_active == True)
        tenant = (await db.execute(stmt)).scalars().first()

    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active tenant found for sensor alert ingestion",
        )

    alert_response = await sensors_service.process_iot_sensor_alert(
        payload=payload,
        tenant=tenant,
        db=db,
    )

    if is_json_request or "application/json" in request.headers.get("accept", ""):
        return JSONResponse(content=alert_response.model_dump())

    return RedirectResponse(
        url=f"/sensors/{tenant.slug}?message=Emergency+{payload.sensor_type}+Alert+Dispatched+to+{alert_response.tech_alerted}",
        status_code=status.HTTP_303_SEE_OTHER,
    )
