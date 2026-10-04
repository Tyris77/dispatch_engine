import os
from typing import List, Optional
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, Response, UploadFile, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.models.tenant import Tenant
from app.schemas.tools import ToolAuditReport, ToolAuditResponse, TruckToolRegistry
from app.services.tools import audit_truck_tools, tools_service

router = APIRouter(tags=["Van Tool & Equipment Asset Scanner"])

TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "templates")
templates = Jinja2Templates(directory=TEMPLATES_DIR)


@router.get(
    "/tools/{tenant_slug}",
    response_class=HTMLResponse,
    summary="Van Tool & Asset Scanner Portal View",
    description="Renders fleet truck inventory, missing tool alerts, and mobile photo audit dropzone.",
)
async def get_tools_portal_view(
    tenant_slug: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    format: Optional[str] = Query(None),
) -> Response:
    stmt = select(Tenant).where(Tenant.slug == tenant_slug)
    tenant = (await db.execute(stmt)).scalar_one_or_none()
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Contractor tenant '{tenant_slug}' not found",
        )

    trucks = tools_service.get_truck_registry(tenant)
    audits = tools_service.get_audit_history(tenant)
    await db.commit()

    accept_header = request.headers.get("accept", "").lower()
    if "application/json" in accept_header or format == "json":
        return JSONResponse(
            content={
                "tenant_name": tenant.name,
                "tenant_slug": tenant.slug,
                "trucks": [t.model_dump() for t in trucks],
                "audits": [a.model_dump() for a in audits],
            }
        )

    return templates.TemplateResponse(
        request=request,
        name="tool_tracker.html",
        context={
            "tenant": tenant,
            "trucks": trucks,
            "audits": audits,
            "message": request.query_params.get("msg"),
        },
    )


@router.post(
    "/tools/{tenant_slug}/audit",
    summary="Execute Multimodal Tool Audit for Service Van",
    description="Inspects uploaded tool rack/shelving photo against truck mandatory tool inventory.",
)
async def post_truck_tool_audit(
    tenant_slug: str,
    request: Request,
    tool_photo: UploadFile = File(...),
    truck_id: str = Form("VAN-01"),
    db: AsyncSession = Depends(get_db),
) -> Response:
    stmt = select(Tenant).where(Tenant.slug == tenant_slug)
    tenant = (await db.execute(stmt)).scalar_one_or_none()
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Contractor tenant '{tenant_slug}' not found",
        )

    file_bytes = await tool_photo.read()
    if not file_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded tool image is empty",
        )

    trucks = tools_service.get_truck_registry(tenant, truck_id=truck_id)
    target_truck = trucks[0] if trucks else None
    required_tools = target_truck.required_tools if target_truck else None

    mime = tool_photo.content_type or "image/jpeg"
    report = await audit_truck_tools(
        image_bytes=file_bytes,
        required_tools=required_tools,
        truck_id=truck_id,
        mime_type=mime,
    )

    tools_service.record_audit(tenant, report)
    await db.commit()
    await db.refresh(tenant)

    accept_header = request.headers.get("accept", "").lower()
    if "application/json" in accept_header or request.query_params.get("format") == "json":
        return JSONResponse(
            content=ToolAuditResponse(
                status="SUCCESS",
                report=report,
                message=f"Van audit complete: {report.status}. Score: {report.audit_score}%.",
            ).model_dump()
        )

    msg = f"Audit+Completed:+{report.truck_id}+{report.status}+(Score:+{report.audit_score}%)"
    return RedirectResponse(
        url=f"/tools/{tenant.slug}?msg={msg}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post(
    "/api/v1/tools/audit",
    response_model=ToolAuditResponse,
    summary="REST API: Audit Truck Tools via Photo",
    description="Upload photo via API and receive structured ToolAuditReport.",
)
async def api_audit_tools(
    tool_photo: UploadFile = File(...),
    truck_id: str = Form("VAN-01"),
    tenant_slug: str = Form(...),
    db: AsyncSession = Depends(get_db),
) -> ToolAuditResponse:
    stmt = select(Tenant).where(Tenant.slug == tenant_slug)
    tenant = (await db.execute(stmt)).scalar_one_or_none()
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Contractor tenant '{tenant_slug}' not found",
        )

    file_bytes = await tool_photo.read()
    if not file_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded tool image is empty",
        )

    trucks = tools_service.get_truck_registry(tenant, truck_id=truck_id)
    target_truck = trucks[0] if trucks else None
    required_tools = target_truck.required_tools if target_truck else None

    mime = tool_photo.content_type or "image/jpeg"
    report = await audit_truck_tools(
        image_bytes=file_bytes,
        required_tools=required_tools,
        truck_id=truck_id,
        mime_type=mime,
    )

    tools_service.record_audit(tenant, report)
    await db.commit()

    return ToolAuditResponse(
        status="SUCCESS",
        report=report,
        message=f"Van tool audit complete for {truck_id}: {report.status}.",
    )


@router.get(
    "/api/v1/tools/{tenant_slug}",
    response_model=List[TruckToolRegistry],
    summary="REST API: Get Fleet Tool Registry",
    description="Returns list of service vans and their mandatory tool inventories.",
)
async def api_get_tool_registry(
    tenant_slug: str,
    db: AsyncSession = Depends(get_db),
) -> List[TruckToolRegistry]:
    stmt = select(Tenant).where(Tenant.slug == tenant_slug)
    tenant = (await db.execute(stmt)).scalar_one_or_none()
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Contractor tenant '{tenant_slug}' not found",
        )

    return tools_service.get_truck_registry(tenant)
