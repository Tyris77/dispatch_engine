import os
from typing import Optional
from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, Response, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.schemas.agency import (
    AgencyOverview,
    AgencyProfile,
    AgencyTenantOnboardRequest,
    ManagedTenantSummary,
)
from app.services.agency import agency_service

router = APIRouter(tags=["Agency White-Label & Franchise Management Engine"])

TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "templates")
templates = Jinja2Templates(directory=TEMPLATES_DIR)


@router.get(
    "/agency",
    response_class=HTMLResponse,
    summary="Agency Executive & Franchise Management Console",
    description="Renders multi-tenant aggregate KPIs, managed contractor directory, white-label branding, and 1-click onboarding.",
)
async def get_agency_dashboard(
    request: Request,
    db: AsyncSession = Depends(get_db),
    format: Optional[str] = Query(None),
) -> Response:
    overview = await agency_service.get_agency_overview(db)

    accept_header = request.headers.get("accept", "").lower()
    if "application/json" in accept_header or format == "json":
        return JSONResponse(content=overview.model_dump())

    return templates.TemplateResponse(
        request=request,
        name="agency_dashboard.html",
        context={
            "overview": overview,
            "message": request.query_params.get("msg"),
        },
    )


@router.post(
    "/agency/onboard",
    summary="1-Click Contractor Onboarding via Web Console",
    description="Provisions a new contractor tenant instance with generated credentials and default trade rules.",
)
async def post_agency_onboard(
    request: Request,
    name: str = Form(...),
    slug: str = Form(...),
    trade_category: str = Form("HVAC"),
    contact_email: str = Form(...),
    monthly_retainer: float = Form(799.0),
    db: AsyncSession = Depends(get_db),
) -> Response:
    req = AgencyTenantOnboardRequest(
        name=name,
        slug=slug,
        trade_category=trade_category,
        contact_email=contact_email,
        monthly_retainer=monthly_retainer,
    )
    new_tenant = await agency_service.onboard_agency_tenant(db, req)

    accept_header = request.headers.get("accept", "").lower()
    if "application/json" in accept_header or request.query_params.get("format") == "json":
        return JSONResponse(
            status_code=status.HTTP_201_CREATED,
            content={
                "status": "SUCCESS",
                "tenant_id": str(new_tenant.id),
                "name": new_tenant.name,
                "slug": new_tenant.slug,
                "message": f"Contractor '{new_tenant.name}' provisioned successfully.",
            },
        )

    return RedirectResponse(
        url=f"/agency?msg=Contractor+{new_tenant.name}+Successfully+Provisioned",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post(
    "/agency/branding",
    summary="Update Agency White-Label Branding Settings",
    description="Updates agency name, brand color, custom domain, and support email.",
)
async def post_agency_branding(
    agency_name: str = Form(...),
    brand_color: str = Form(...),
    custom_domain: Optional[str] = Form(None),
    contact_email: str = Form(...),
) -> Response:
    agency_service.update_agency_profile({
        "agency_name": agency_name,
        "brand_color": brand_color,
        "custom_domain": custom_domain,
        "contact_email": contact_email,
    })
    return RedirectResponse(
        url="/agency?msg=Agency+White-Label+Branding+Updated",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.get(
    "/api/v1/agency/overview",
    response_model=AgencyOverview,
    summary="REST API: Get Multi-Tenant Agency Overview",
    description="Returns aggregate KPI roll-up, directory of managed contractor tenants, and agency branding profile.",
)
async def api_get_agency_overview(
    db: AsyncSession = Depends(get_db),
) -> AgencyOverview:
    return await agency_service.get_agency_overview(db)


@router.post(
    "/api/v1/agency/onboard",
    status_code=status.HTTP_201_CREATED,
    summary="REST API: Provision New Contractor Tenant",
    description="API endpoint to onboard and configure a new tenant under agency management.",
)
async def api_onboard_tenant(
    req: AgencyTenantOnboardRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    new_tenant = await agency_service.onboard_agency_tenant(db, req)
    return {
        "status": "SUCCESS",
        "tenant_id": str(new_tenant.id),
        "name": new_tenant.name,
        "slug": new_tenant.slug,
        "message": f"Contractor '{new_tenant.name}' successfully provisioned.",
    }


@router.post(
    "/api/v1/agency/profile",
    response_model=AgencyProfile,
    summary="REST API: Update Agency White-Label Profile",
    description="Updates agency branding, logo, and custom domain.",
)
async def api_update_agency_profile(
    profile_data: AgencyProfile,
) -> AgencyProfile:
    return agency_service.update_agency_profile(profile_data.model_dump())
