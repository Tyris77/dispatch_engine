from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.models.tenant import Tenant
from app.schemas.weather import (
    WeatherAlert,
    WeatherBroadcastRequest,
    WeatherBroadcastResponse,
)
from app.services.weather_dispatch import weather_dispatch_service

router = APIRouter(tags=["Severe Weather Radar"])


@router.get(
    "/weather/alerts",
    response_model=List[WeatherAlert],
    summary="Get Active Severe Weather Alerts",
    description="Returns active meteorological hazard warnings, watches, and advisories for contractor territories.",
)
async def get_weather_alerts(
    tenant_slug: Optional[str] = Query(None, description="Optional tenant slug to localize alerts"),
    db: AsyncSession = Depends(get_db),
) -> List[WeatherAlert]:
    tenant = None
    if tenant_slug:
        query = select(Tenant).where(Tenant.slug == tenant_slug, Tenant.is_active == True)
        tenant = (await db.execute(query)).scalar_one_or_none()

    if not tenant:
        query = select(Tenant).where(Tenant.is_active == True).order_by(Tenant.created_at.asc())
        tenant = (await db.execute(query)).scalars().first()

    return weather_dispatch_service.get_active_weather_alerts(tenant)


@router.post(
    "/weather/broadcast",
    response_model=WeatherBroadcastResponse,
    status_code=status.HTTP_200_OK,
    summary="Broadcast Proactive Weather Alert SMS",
    description="Dispatches emergency preparedness SMS alerts to past customers with 1-tap priority emergency dispatch links.",
)
async def broadcast_weather_alert(
    request: WeatherBroadcastRequest,
    tenant_slug: Optional[str] = Query(None, description="Contractor tenant slug"),
    db: AsyncSession = Depends(get_db),
) -> WeatherBroadcastResponse:
    tenant = None
    if tenant_slug:
        query = select(Tenant).where(Tenant.slug == tenant_slug, Tenant.is_active == True)
        tenant = (await db.execute(query)).scalar_one_or_none()

    if not tenant:
        query = select(Tenant).where(Tenant.is_active == True).order_by(Tenant.created_at.asc())
        tenant = (await db.execute(query)).scalars().first()

    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active tenant found to dispatch broadcast",
        )

    response = await weather_dispatch_service.dispatch_proactive_weather_alert(
        tenant=tenant,
        alert_id=request.alert_id,
        custom_note=request.custom_note,
        trade_category=request.trade_category,
        db=db,
    )
    return response
