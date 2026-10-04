from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.models.tenant import Tenant
from app.schemas.copilot import CopilotQueryRequest, CopilotQueryResponse
from app.services.copilot import copilot_service

router = APIRouter(tags=["AI Operations Copilot"])


@router.post(
    "/api/v1/copilot/query",
    response_model=CopilotQueryResponse,
    summary="AI Operations Copilot Query",
    description="Processes dispatcher questions against real-time operational telemetry using Gemini 2.5 Flash.",
)
async def query_copilot(
    request: CopilotQueryRequest,
    db: AsyncSession = Depends(get_db),
) -> CopilotQueryResponse:
    tenant = None
    if request.tenant_slug:
        stmt = select(Tenant).where(Tenant.slug == request.tenant_slug)
        tenant = (await db.execute(stmt)).scalar_one_or_none()

    if not tenant:
        # Fallback to the first active tenant
        stmt = select(Tenant).where(Tenant.is_active == True).limit(1)
        tenant = (await db.execute(stmt)).scalar_one_or_none()

    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active contractor tenant found for copilot session",
        )

    return await copilot_service.execute_copilot_query(
        query=request.query_text,
        tenant=tenant,
        db=db,
    )
