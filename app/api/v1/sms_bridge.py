import uuid
from typing import Optional
from fastapi import APIRouter, Depends, Form, Request, Response, status
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.schemas.sms_bridge import (
    SmsBridgeResponse,
    SmsDispatchAction,
    TechnicianSmsPayload,
)
from app.services.sms_bridge import sms_bridge_service

router = APIRouter(prefix="/sms", tags=["Two-Way SMS Technician Dispatch Bridge"])


class SimulateDispatchRequest(BaseModel):
    action_id: Optional[str] = None
    tenant_name: str = "Apex Plumbing"
    technician_name: str = "Carlos Gomez"
    technician_phone: str = "+15558889999"
    backup_technician_name: str = "Dave Vance"
    backup_technician_phone: str = "+15557778888"
    homeowner_phone: str = "+12025550194"
    address: str = "1420 K St NW, Washington, DC"
    issue: str = "Burst pipe"
    ticket_est: str = "$1,200"


@router.post(
    "/simulate-dispatch",
    response_model=SmsDispatchAction,
    summary="Simulate Outbound Technician Dispatch SMS",
    description="Dispatches priority 'Reply 1 to Accept' SMS to on-call technician.",
)
async def simulate_dispatch_endpoint(
    req: SimulateDispatchRequest,
) -> SmsDispatchAction:
    action_id = req.action_id or str(uuid.uuid4())
    return sms_bridge_service.dispatch_technician_sms(
        action_id=action_id,
        tenant_name=req.tenant_name,
        technician_name=req.technician_name,
        technician_phone=req.technician_phone,
        backup_technician_name=req.backup_technician_name,
        backup_technician_phone=req.backup_technician_phone,
        homeowner_phone=req.homeowner_phone,
        address=req.address,
        issue=req.issue,
        ticket_est=req.ticket_est,
    )


@router.post(
    "/technician-reply",
    summary="Twilio Inbound Technician SMS Webhook",
    description="Processes inbound reply ('1' to accept, '2' to pass). Supports JSON or Twilio urlencoded form data.",
)
async def handle_technician_sms_reply(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Response:
    content_type = request.headers.get("content-type", "")

    from_phone = ""
    body = ""

    if "application/json" in content_type:
        try:
            json_body = await request.json()
            from_phone = json_body.get("From") or json_body.get("from") or ""
            body = json_body.get("Body") or json_body.get("body") or ""
        except Exception:
            pass
    else:
        # Twilio standard form-encoded POST
        try:
            form_data = await request.form()
            from_phone = form_data.get("From") or ""
            body = form_data.get("Body") or ""
        except Exception:
            pass

    if not from_phone or not body:
        # Fallback to query params
        from_phone = from_phone or request.query_params.get("From", "+15558889999")
        body = body or request.query_params.get("Body", "1")

    res: SmsBridgeResponse = await sms_bridge_service.handle_technician_reply(
        from_phone=from_phone,
        body=body,
        db=db,
    )

    # Return XML TwiML if request is likely Twilio, otherwise JSON
    if "application/json" in content_type:
        return JSONResponse(content=res.model_dump())

    return Response(
        content=res.twiml_response or "<Response></Response>",
        media_type="application/xml; charset=utf-8",
    )


@router.get(
    "/status",
    summary="Get SMS Bridge Telemetry & Active Dispatches",
    description="Returns live status of all active two-way technician SMS alerts and audit history.",
)
async def get_sms_bridge_status():
    return {
        "active_dispatches": list(sms_bridge_service.dispatches.values()),
        "recent_history": sms_bridge_service.history[-20:],
    }
