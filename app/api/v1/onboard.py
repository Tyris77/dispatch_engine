import os
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import get_db
from app.models.tenant import Tenant
from app.schemas.onboard import OnboardRequest, OnboardResponse
from app.services.onboarding import onboarding_service

router = APIRouter(tags=["Self-Serve Instant Contractor Onboarding & Activation Engine"])

TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "templates")
templates = Jinja2Templates(directory=TEMPLATES_DIR)


@router.get(
    "/onboard",
    response_class=HTMLResponse,
    summary="Interactive Contractor Self-Serve Onboarding Flow",
    description="3-step interactive setup wizard provisioning dedicated AI lines and embeddable widgets in <60 seconds.",
)
async def get_onboard_page(
    request: Request,
) -> Response:
    return templates.TemplateResponse(
        request=request,
        name="onboard.html",
        context={},
    )


@router.post(
    "/onboard/provision",
    response_model=OnboardResponse,
    summary="Automated Contractor Tenant Provisioning",
    description="Validates contractor credentials, provisions forwarding line, sets up multi-tier escalation, and generates widget script in <150ms.",
)
@router.post(
    "/api/v1/onboard/provision",
    response_model=OnboardResponse,
    include_in_schema=False,
)
async def provision_contractor_endpoint(
    payload: OnboardRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> OnboardResponse:
    base_url = str(request.base_url).rstrip("/")
    return await onboarding_service.provision_contractor(
        payload=payload,
        db=db,
        base_url=base_url,
    )


@router.get(
    "/onboard/success/{tenant_slug}",
    response_class=HTMLResponse,
    summary="Contractor Activation Success Screen",
    description="Renders dedicated carrier star codes, widget script snippets, and quick launches into console.",
)
async def get_onboard_success_page(
    tenant_slug: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    format: Optional[str] = Query(None),
) -> Response:
    tenant = (await db.execute(select(Tenant).where(Tenant.slug == tenant_slug))).scalar_one_or_none()
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Contractor tenant '{tenant_slug}' not found",
        )

    base_url = str(request.base_url).rstrip("/")
    app_domain = base_url if base_url else "https://dispatchengine-production.up.railway.app"
    forwarding_num = (tenant.settings or {}).get("assigned_twilio_number") or "+1 (202) 555-0199"

    resp_data = OnboardResponse(
        tenant_slug=tenant.slug,
        tenant_id=str(tenant.id),
        forwarding_phone_number=forwarding_num,
        widget_script_tag=f'<script src="{app_domain}/api/v1/widget/{tenant.slug}.js"></script>',
        portal_url=f"{app_domain}/portal/{tenant.slug}",
        dashboard_url=f"{app_domain}/dashboard?tenant_slug={tenant.slug}",
        status="ACTIVE",
        carrier_forwarding_instructions=onboarding_service.generate_carrier_instructions(forwarding_num),
    )

    accept_header = request.headers.get("accept", "").lower()
    if format == "json" or "application/json" in accept_header:
        return JSONResponse(content=resp_data.model_dump())

    return templates.TemplateResponse(
        request=request,
        name="onboard.html",
        context={
            "initial_data": resp_data.model_dump(),
            "tenant": tenant,
        },
    )
