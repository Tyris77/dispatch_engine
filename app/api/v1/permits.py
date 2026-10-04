import os
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.models.tenant import Tenant
from app.schemas.permit import MunicipalPermit, SubcontractorBidRequest, SubcontractorBidResponse
from app.services.permit_radar import permit_radar_service

router = APIRouter(tags=["Municipal Permit Radar"])

# Locate templates directory
TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "templates")
templates = Jinja2Templates(directory=TEMPLATES_DIR)


@router.get(
    "/permits/{tenant_slug}",
    response_class=HTMLResponse,
    summary="Municipal Permit B2B Opportunity Radar Portal",
    description="Renders territory permit radar feed (DC, Arlington, Alexandria) with project intelligence and 1-click AI bid generator.",
)
async def municipal_permit_radar_view(
    tenant_slug: str,
    request: Request,
    jurisdiction: Optional[str] = Query(None, description="Filter by municipality (e.g. 'Washington DC', 'Arlington County', 'City of Alexandria')"),
    trade: Optional[str] = Query(None, description="Filter by trade (e.g. 'HVAC', 'Plumbing', 'Roofing', 'Electrical')"),
    min_valuation: Optional[float] = Query(None, description="Minimum declared permit valuation"),
    db: AsyncSession = Depends(get_db),
) -> Response:
    # 1. Resolve Tenant
    query = select(Tenant).where(Tenant.slug == tenant_slug, Tenant.is_active == True)
    tenant = (await db.execute(query)).scalar_one_or_none()
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Active contractor tenant '{tenant_slug}' not found.",
        )

    # 2. Fetch Filtered Permits
    permits = permit_radar_service.get_territory_permits(
        jurisdiction=jurisdiction,
        trade=trade,
        min_valuation=min_valuation,
    )

    total_valuation = sum(p.estimated_valuation for p in permits)

    return templates.TemplateResponse(
        request=request,
        name="permit_radar.html",
        context={
            "tenant": tenant,
            "permits": permits,
            "selected_jurisdiction": jurisdiction or "All",
            "selected_trade": trade or "All",
            "min_valuation": min_valuation or 0.0,
            "total_permits_count": len(permits),
            "total_pipeline_valuation": total_valuation,
            "base_url": str(request.base_url).rstrip("/"),
        },
    )


@router.get(
    "/api/v1/permits/{tenant_slug}",
    response_model=List[MunicipalPermit],
    summary="Fetch Municipal Permit Feed (JSON)",
    description="Returns filtered list of active municipal permits across Washington DC, Arlington County, and Alexandria.",
)
async def get_permit_feed_json(
    tenant_slug: str,
    jurisdiction: Optional[str] = Query(None),
    trade: Optional[str] = Query(None),
    min_valuation: Optional[float] = Query(None),
    db: AsyncSession = Depends(get_db),
) -> List[MunicipalPermit]:
    query = select(Tenant).where(Tenant.slug == tenant_slug, Tenant.is_active == True)
    tenant = (await db.execute(query)).scalar_one_or_none()
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Active contractor tenant '{tenant_slug}' not found.",
        )

    return permit_radar_service.get_territory_permits(
        jurisdiction=jurisdiction,
        trade=trade,
        min_valuation=min_valuation,
    )


@router.post(
    "/api/v1/permits/generate-bid",
    response_model=SubcontractorBidResponse,
    summary="1-Click AI Subcontractor Bid Generator",
    description="Gemini drafts a tailored subcontractor bid letter directly to the General Contractor citing their specific permit scope.",
)
async def generate_bid_for_permit(
    payload: SubcontractorBidRequest,
    db: AsyncSession = Depends(get_db),
) -> SubcontractorBidResponse:
    query = select(Tenant).where(Tenant.slug == payload.tenant_slug, Tenant.is_active == True)
    tenant = (await db.execute(query)).scalar_one_or_none()
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Active contractor tenant '{payload.tenant_slug}' not found.",
        )

    permit = permit_radar_service.get_permit_by_id(payload.permit_id)
    if not permit:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Municipal Permit '{payload.permit_id}' not found.",
        )

    response = await permit_radar_service.generate_subcontractor_bid(
        permit=permit,
        tenant=tenant,
        custom_scope_notes=payload.custom_scope_notes,
    )
    return response
