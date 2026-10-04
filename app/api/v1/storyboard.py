import os
import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, Response, UploadFile, status
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.models.lead_action import LeadAction
from app.models.tenant import Tenant
from app.schemas.storyboard import JobStoryboardData
from app.services.storyboard import _mime_for, _sniff_ext, get_photo_path, storyboard_service

router = APIRouter(tags=["Multi-Day Jobsite Progress Storyboard"])

TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "templates")
templates = Jinja2Templates(directory=TEMPLATES_DIR)


@router.get(
    "/storyboard/{action_id}",
    response_class=HTMLResponse,
    summary="Customer-Facing Jobsite Progress Storyboard",
    description="Interactive multi-day visual timeline with photo carousel, completion progress bar, weather-tight badge, and foreman notes.",
)
async def get_storyboard_view(
    action_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    format: Optional[str] = Query(None),
) -> Response:
    lead = (await db.execute(select(LeadAction).where(LeadAction.id == action_id))).scalar_one_or_none()
    if not lead:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job record '{action_id}' not found",
        )

    board: JobStoryboardData = await storyboard_service.get_storyboard(action_id=action_id, db=db)
    if not board:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Storyboard for '{action_id}' could not be initialized",
        )

    accept_header = request.headers.get("accept", "").lower()
    if format == "json" or "application/json" in accept_header:
        return JSONResponse(content=board.model_dump())

    tenant = (await db.execute(select(Tenant).where(Tenant.id == lead.tenant_id))).scalar_one_or_none()

    return templates.TemplateResponse(
        request=request,
        name="storyboard.html",
        context={
            "board": board,
            "lead": lead,
            "tenant": tenant,
        },
    )


@router.post(
    "/storyboard/{action_id}/milestone",
    summary="Foreman Daily Photo & Progress Milestone Upload",
    description="Uploads daily jobsite photos and notes. Triggers Gemini Vision evaluation and homeowner SMS notification.",
)
async def upload_daily_milestone(
    action_id: uuid.UUID,
    request: Request,
    photos: List[UploadFile] = File(...),
    notes: str = Form(""),
    db: AsyncSession = Depends(get_db),
) -> Response:
    lead = (await db.execute(select(LeadAction).where(LeadAction.id == action_id))).scalar_one_or_none()
    if not lead:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job record '{action_id}' not found",
        )

    image_bytes_list: List[bytes] = []
    for photo in photos:
        content = await photo.read()
        if content:
            image_bytes_list.append(content)

    if not image_bytes_list:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one valid photo file must be uploaded",
        )

    try:
        updated_board: JobStoryboardData = await storyboard_service.add_daily_milestone(
            action_id=action_id,
            image_bytes_list=image_bytes_list,
            notes=notes,
            db=db,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )

    accept_header = request.headers.get("accept", "").lower()
    if "application/json" in accept_header or request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JSONResponse(content=updated_board.model_dump())

    return RedirectResponse(
        url=f"/storyboard/{action_id}?uploaded=1",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.get(
    "/storyboard/{action_id}/photo/{filename}",
    summary="Serve Stored Jobsite Milestone Photo",
    description="Securely streams milestone image from local upload vault.",
)
async def serve_storyboard_photo(
    action_id: uuid.UUID,
    filename: str,
) -> Response:
    path = get_photo_path(action_id=action_id, filename=filename)
    if not path or not os.path.isfile(path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Photo '{filename}' not found for job '{action_id}'",
        )

    ext = _sniff_ext(open(path, "rb").read(16))
    return FileResponse(path, media_type=_mime_for(ext))


@router.get(
    "/api/v1/storyboard/{action_id}",
    response_model=JobStoryboardData,
    summary="Get Storyboard JSON Payload",
    description="Direct API endpoint returning complete multi-day job progress timeline.",
)
async def get_storyboard_api(
    action_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> JobStoryboardData:
    board = await storyboard_service.get_storyboard(action_id=action_id, db=db)
    if not board:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job record '{action_id}' not found",
        )
    return board
