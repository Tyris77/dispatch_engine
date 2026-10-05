import os
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import get_db
from app.models.tenant import Tenant
from app.schemas.speed_to_lead import (
    SpeedToLeadMetrics,
    SpeedToLeadPayload,
    SpeedToLeadResponse,
)
from app.services.speed_to_lead import speed_to_lead_service

router = APIRouter(tags=["Autonomous Speed-to-Lead Ingestion Engine"])

TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "templates")
templates = Jinja2Templates(directory=TEMPLATES_DIR)


@router.post(
    "/leads/ingest/google-lsa",
    response_model=SpeedToLeadResponse,
    summary="Ingest Google Local Services Ads (LSA) Paid Lead",
    description="Sub-5s ingestion webhook for Google Guaranteed leads. Triggers instant SMS and prioritizes tech.",
)
@router.post(
    "/api/v1/leads/ingest/google-lsa",
    response_model=SpeedToLeadResponse,
    include_in_schema=False,
)
async def ingest_google_lsa_lead(
    payload: SpeedToLeadPayload,
    db: AsyncSession = Depends(get_db),
) -> SpeedToLeadResponse:
    payload.platform = "google_lsa"
    return await speed_to_lead_service.ingest_lead(payload=payload, db=db)


@router.post(
    "/leads/ingest/angi",
    response_model=SpeedToLeadResponse,
    summary="Ingest Angi Leads / HomeAdvisor Paid Lead",
    description="Sub-5s ingestion webhook for Angi leads with automated 2-way homeowner qualification.",
)
@router.post(
    "/api/v1/leads/ingest/angi",
    response_model=SpeedToLeadResponse,
    include_in_schema=False,
)
async def ingest_angi_lead(
    payload: SpeedToLeadPayload,
    db: AsyncSession = Depends(get_db),
) -> SpeedToLeadResponse:
    payload.platform = "angi"
    return await speed_to_lead_service.ingest_lead(payload=payload, db=db)


@router.post(
    "/leads/ingest/thumbtack",
    response_model=SpeedToLeadResponse,
    summary="Ingest Thumbtack Pro Paid Lead",
    description="Sub-5s ingestion webhook for Thumbtack leads.",
)
@router.post(
    "/api/v1/leads/ingest/thumbtack",
    response_model=SpeedToLeadResponse,
    include_in_schema=False,
)
async def ingest_thumbtack_lead(
    payload: SpeedToLeadPayload,
    db: AsyncSession = Depends(get_db),
) -> SpeedToLeadResponse:
    payload.platform = "thumbtack"
    return await speed_to_lead_service.ingest_lead(payload=payload, db=db)


@router.post(
    "/leads/ingest/generic",
    response_model=SpeedToLeadResponse,
    summary="Ingest Generic Ad Channel Webhook",
    description="Universal paid advertising ingestion webhook for high-intent emergency jobs.",
)
@router.post(
    "/api/v1/leads/ingest/generic",
    response_model=SpeedToLeadResponse,
    include_in_schema=False,
)
async def ingest_generic_lead(
    payload: SpeedToLeadPayload,
    db: AsyncSession = Depends(get_db),
) -> SpeedToLeadResponse:
    return await speed_to_lead_service.ingest_lead(payload=payload, db=db)


@router.get(
    "/speed-to-lead/{tenant_slug}",
    response_class=HTMLResponse,
    summary="Speed-to-Lead Telemetry Dashboard",
    description="Live sub-5 second lead response telemetry dashboard with ad attribution, speed gauge, and simulator.",
)
async def get_speed_to_lead_dashboard(
    tenant_slug: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    format: Optional[str] = Query(None),
) -> Response:
    tenant = (await db.execute(select(Tenant).where(Tenant.slug == tenant_slug))).scalar_one_or_none()
    tenant_name = tenant.name if tenant else tenant_slug.replace("-", " ").title()

    metrics = await speed_to_lead_service.get_metrics(tenant_slug=tenant_slug, db=db)

    accept_header = request.headers.get("accept", "").lower()
    if format == "json" or "application/json" in accept_header:
        return JSONResponse(content=metrics.model_dump())

    return templates.TemplateResponse(
        request=request,
        name="speed_to_lead.html",
        context={
            "tenant_slug": tenant_slug,
            "tenant_name": tenant_name,
            "metrics": metrics,
        },
    )


@router.get(
    "/api/v1/speed-to-lead/{tenant_slug}/metrics",
    response_model=SpeedToLeadMetrics,
    summary="Get Speed-to-Lead Metrics JSON",
    description="Returns JSON metrics for response latencies and platform attribution.",
)
async def get_speed_to_lead_metrics_json(
    tenant_slug: str,
    db: AsyncSession = Depends(get_db),
) -> SpeedToLeadMetrics:
    return await speed_to_lead_service.get_metrics(tenant_slug=tenant_slug, db=db)
