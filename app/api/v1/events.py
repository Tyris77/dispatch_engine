import math
import uuid
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import get_current_tenant, get_db
from app.models.lead_action import LeadAction
from app.models.tenant import Tenant
from app.models.webhook_event import WebhookEvent
from app.schemas.lead import (
    LeadActionCreate,
    LeadActionRead,
    LeadDispatchPlan,
    LeadQualificationOutput,
)
from app.schemas.map import MapDataResponse, MapLeadFeature
from app.services.dispatch import dispatch_service
from app.services.qualification import qualification_service

router = APIRouter()


METRO_COORDINATES = {
    "dallas": [32.7767, -96.7970],
    "dfw": [32.7767, -96.7970],
    "austin": [30.2672, -97.7431],
    "houston": [29.7604, -95.3698],
    "phoenix": [33.4484, -112.0740],
    "denver": [39.7392, -104.9903],
    "atlanta": [33.7490, -84.3880],
}


@router.get(
    "/map-data",
    response_model=MapDataResponse,
    summary="Get fleet and territory dispatch map data",
    description="Returns geolocated recent leads, marker types (emergency/routine/completed), and deep-links for Leaflet.",
)
async def get_dispatch_map_data(
    tenant_slug: Optional[str] = Query(None, description="Filter by tenant slug"),
    limit: int = Query(50, ge=1, le=200, description="Max pins to return"),
    db: AsyncSession = Depends(get_db),
) -> MapDataResponse:
    # 1. Build Query
    query = (
        select(LeadAction, Tenant)
        .join(Tenant, LeadAction.tenant_id == Tenant.id)
        .order_by(LeadAction.created_at.desc())
        .limit(limit)
    )
    if tenant_slug:
        query = query.where(Tenant.slug == tenant_slug)

    rows = (await db.execute(query)).all()

    # 2. Determine Map Center
    default_center = [32.7767, -96.7970]
    if tenant_slug and rows:
        tenant_settings = rows[0][1].settings or {}
        city_key = str(tenant_settings.get("city", "")).lower()
        if city_key in METRO_COORDINATES:
            default_center = METRO_COORDINATES[city_key]

    features: List[MapLeadFeature] = []
    for lead, tenant in rows:
        meta = lead.metadata_payload or {}
        diag = lead.diagnostic_data or {}
        signed = lead.signed_contract or {}

        # Marker classification
        if signed or meta.get("status") in ["COMPLETED", "SIGNED"]:
            marker_type = "completed"
            status_label = "🟢 Signed & Scheduled"
        elif (lead.action_type and "EMERGENCY" in lead.action_type.upper()) or (lead.qualification_score is not None and lead.qualification_score >= 0.75):
            marker_type = "emergency"
            status_label = "🔴 Emergency Dispatch Active"
        else:
            marker_type = "routine"
            status_label = "🟡 Routine / Diagnostics"

        # Coordinates: use explicit if present, else deterministic pseudo-geocoding around center
        seed = lead.id.int
        angle = (seed % 360) * (math.pi / 180.0)
        radius = 0.015 + ((seed % 100) / 100.0) * 0.065  # approx 1.5km to 8km dispersion
        lat = meta.get("lat") or round(default_center[0] + radius * math.cos(angle), 5)
        lng = meta.get("lng") or round(default_center[1] + radius * math.sin(angle), 5)

        caller_name = meta.get("caller_name") or meta.get("customer_name")
        caller_phone = meta.get("caller_phone") or "Caller (Pending)"
        caller_display = f"{caller_name} ({caller_phone})" if caller_name else caller_phone

        features.append(
            MapLeadFeature(
                id=str(lead.id),
                action_id=str(lead.id),
                tenant_name=tenant.name,
                tenant_slug=tenant.slug,
                caller=caller_display,
                lat=lat,
                lng=lng,
                urgency="EMERGENCY" if marker_type == "emergency" else "ROUTINE",
                status="COMPLETED" if marker_type == "completed" else "ACTIVE",
                status_label=status_label,
                equipment_type=diag.get("equipment_type"),
                equipment_brand=diag.get("brand_manufacturer"),
                damage=diag.get("damage_assessment"),
                marker_type=marker_type,
                tracking_url=f"/track/{lead.id}",
                intake_url=f"/intake/{lead.id}",
                proposal_url=f"/proposal/{lead.id}",
                created_at=lead.created_at.strftime("%Y-%m-%d %H:%M UTC") if lead.created_at else "",
            )
        )

    return MapDataResponse(
        center=default_center,
        zoom=11,
        total_active=len(features),
        features=features,
    )


@router.get(
    "/actions",
    response_model=List[LeadActionRead],
    summary="List tenant lead actions",
    description="Retrieve lead dispatch actions, qualification scores, and CRM sync status.",
)
async def list_lead_actions(
    limit: int = 50,
    offset: int = 0,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> List[LeadActionRead]:
    query = (
        select(LeadAction)
        .where(LeadAction.tenant_id == tenant.id)
        .order_by(LeadAction.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    result = await db.execute(query)
    return list(result.scalars().all())


@router.get(
    "/actions/{action_id}",
    response_model=LeadActionRead,
    summary="Get lead action details",
)
async def get_lead_action(
    action_id: uuid.UUID,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> LeadActionRead:
    query = select(LeadAction).where(
        LeadAction.id == action_id,
        LeadAction.tenant_id == tenant.id,
    )
    result = await db.execute(query)
    action = result.scalar_one_or_none()
    if not action:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lead action not found",
        )
    return action


@router.post(
    "/dispatch",
    response_model=LeadActionRead,
    status_code=status.HTTP_201_CREATED,
    summary="Trigger immediate lead qualification and dispatch",
    description="Manually evaluate a lead payload and execute prioritized tenant routing.",
)
async def manual_dispatch_lead(
    payload: Dict[str, Any],
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> LeadActionRead:
    # 1. Create simulated event container
    event = WebhookEvent(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        source="api_manual_dispatch",
        event_type="lead.manual_trigger",
        status="PROCESSED",
        payload=payload,
    )
    db.add(event)
    await db.flush()

    # 2. Qualify Lead
    qualification = await qualification_service.qualify_lead(
        tenant_settings=tenant.settings,
        lead_payload=payload,
    )

    # 3. Create Dispatch Plan
    plan = dispatch_service.create_dispatch_plan(
        tenant=tenant,
        qualification=qualification,
        lead_payload=payload,
    )

    # 4. Execute Dispatch
    action = await dispatch_service.execute_dispatch(
        db=db,
        tenant=tenant,
        event=event,
        qualification=qualification,
        plan=plan,
    )
    await db.refresh(action)
    return action
