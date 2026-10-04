import os
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.models.tenant import Tenant
from app.schemas.tech_mentor import (
    DiagnosticTroubleshootGuide,
    DiagnosticTroubleshootRequest,
)
from app.services.tech_mentor import tech_mentor_service

router = APIRouter(tags=["Field Tech AI Diagnostic Mentor & Fault Code Copilot"])

TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "templates")
templates = Jinja2Templates(directory=TEMPLATES_DIR)


@router.get(
    "/tech-mentor/{tenant_slug}",
    response_class=HTMLResponse,
    summary="Field Tech AI Diagnostic Mentor Mobile Console",
    description="Mobile-first troubleshooting tool for apprentice and journeyman technicians with voice dictation and multimeter test pinouts.",
)
async def get_tech_mentor_portal(
    tenant_slug: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Response:
    stmt = select(Tenant).where(Tenant.slug == tenant_slug)
    tenant = (await db.execute(stmt)).scalar_one_or_none()
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant '{tenant_slug}' not found",
        )

    return templates.TemplateResponse(
        request=request,
        name="tech_mentor.html",
        context={
            "tenant": tenant,
        },
    )


@router.post(
    "/api/v1/tech-mentor/troubleshoot",
    response_model=DiagnosticTroubleshootGuide,
    summary="Troubleshoot Equipment Fault Code / Symptoms",
    description="Generates root-cause analysis, step-by-step diagnostic test procedures, and expected multimeter readings using Gemini 2.5 Flash and trade catalogs.",
)
async def troubleshoot_equipment_fault_api(
    payload: DiagnosticTroubleshootRequest,
) -> DiagnosticTroubleshootGuide:
    return await tech_mentor_service.troubleshoot_equipment_fault(payload)
