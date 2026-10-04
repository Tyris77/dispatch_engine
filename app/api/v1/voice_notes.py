import os
import uuid
from typing import Optional
from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_db
from app.models.lead_action import LeadAction
from app.schemas.voice_notes import (
    DictatedWorkOrderSummary,
    VoiceNotesSubmissionRequest,
    VoiceNotesSubmissionResponse,
)
from app.services.voice_notes import voice_notes_service

router = APIRouter(tags=["Hands-Free Voice-to-Job Notes"])


@router.post(
    "/track/{action_id}/voice-notes",
    summary="Submit Dictated Technician Voice Notes",
    description="Parses spoken technician voice dictation into an itemized work order summary, updates lead_action.voice_notes_data, and enriches customer invoice.",
)
async def submit_technician_voice_notes(
    action_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    notes_text: Optional[str] = Form(None),
    trade_category: Optional[str] = Form(None),
) -> Response:
    stmt = (
        select(LeadAction)
        .options(selectinload(LeadAction.tenant))
        .where(LeadAction.id == action_id)
    )
    action = (await db.execute(stmt)).scalar_one_or_none()
    if not action:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Dispatch lead '{action_id}' not found",
        )

    # Support JSON payload or Form data
    dictation_text = notes_text
    trade = trade_category or action.category or "General"

    accept_header = request.headers.get("accept", "").lower()
    content_type = request.headers.get("content-type", "").lower()

    if "application/json" in content_type:
        try:
            body = await request.json()
            dictation_text = body.get("transcript_or_text") or body.get("notes_text") or dictation_text
            trade = body.get("trade_category") or trade
        except Exception:
            pass

    if not dictation_text or not dictation_text.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Dictation notes text is required",
        )

    summary = await voice_notes_service.process_dictation(
        raw_text_or_audio=dictation_text,
        trade_context={"trade_category": trade},
    )

    # Attach to lead action and sync into invoice
    voice_notes_service.attach_notes_to_lead(action, summary)
    await db.commit()
    await db.refresh(action)

    invoice_updated = bool(action.invoice_data and action.invoice_data.get("work_order_summary"))

    if "application/json" in accept_header or request.query_params.get("format") == "json":
        return JSONResponse(
            content=VoiceNotesSubmissionResponse(
                action_id=str(action.id),
                status="SUCCESS",
                summary=summary,
                invoice_updated=invoice_updated,
            ).model_dump()
        )

    return RedirectResponse(
        url=f"/track/{action.id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.get(
    "/api/v1/voice-notes/{action_id}",
    response_model=DictatedWorkOrderSummary,
    summary="Get Structured Work Order Voice Summary",
    description="Returns the parsed DictatedWorkOrderSummary JSON for the specified dispatch lead action.",
)
async def get_voice_notes_summary(
    action_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> DictatedWorkOrderSummary:
    stmt = select(LeadAction).where(LeadAction.id == action_id)
    action = (await db.execute(stmt)).scalar_one_or_none()
    if not action:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Dispatch lead '{action_id}' not found",
        )

    if not action.voice_notes_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No voice notes recorded for this dispatch lead",
        )

    return DictatedWorkOrderSummary.model_validate(action.voice_notes_data)
