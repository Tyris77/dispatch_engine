import os
import uuid
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_db
from app.core.logging import logger
from app.models.lead_action import LeadAction
from app.models.tenant import Tenant
from app.schemas.insurance_claim import (
    ClaimGenerateRequest,
    InsuranceClaimSupplementReport,
)
from app.services.insurance_claim import insurance_claim_service

router = APIRouter(tags=["Autonomous Insurance Claim Supplement Engine"])

TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "templates")
templates = Jinja2Templates(directory=TEMPLATES_DIR)


@router.post(
    "/api/v1/claims/generate-supplement/{action_id}",
    response_model=InsuranceClaimSupplementReport,
    summary="Autonomous Insurance Claim Supplement Generator",
    description="Synthesizes diagnostic, mitigation, and proposal records, detects missing carrier line items, and generates an Xactimate supplement report.",
)
@router.post(
    "/claims/generate-supplement/{action_id}",
    response_model=InsuranceClaimSupplementReport,
    include_in_schema=False,
)
async def generate_supplement_endpoint(
    action_id: str,
    request_data: Optional[ClaimGenerateRequest] = None,
    db: AsyncSession = Depends(get_db),
) -> InsuranceClaimSupplementReport:
    try:
        action_uuid = uuid.UUID(str(action_id))
    except (ValueError, AttributeError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Dispatch lead '{action_id}' not found",
        )

    stmt = (
        select(LeadAction)
        .options(selectinload(LeadAction.tenant))
        .where(LeadAction.id == action_uuid)
    )
    action = (await db.execute(stmt)).scalar_one_or_none()
    if not action:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Dispatch lead '{action_id}' not found",
        )

    tenant_name = action.tenant.name if action.tenant else "Apex Restoration & Mechanical Systems"
    report = insurance_claim_service.generate_claim_supplement(
        action=action,
        request_data=request_data,
        tenant_name=tenant_name,
    )
    await insurance_claim_service.save_supplement_to_action(action, report, db)
    return report


@router.get(
    "/claims/{action_id}",
    response_class=HTMLResponse,
    summary="Interactive Insurance Claim Supplement Dossier",
    description="Renders luxury print/PDF-ready insurance supplement report with Xactimate line items, IRC code citations, and formal Adjuster Demand Letter.",
)
@router.get(
    "/api/v1/claims/{action_id}",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def view_claim_supplement(
    action_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    carrier: Optional[str] = Query(None),
    claim_num: Optional[str] = Query(None),
    orig_amount: Optional[float] = Query(None),
) -> Response:
    try:
        action_uuid = uuid.UUID(str(action_id))
    except (ValueError, AttributeError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Dispatch lead '{action_id}' not found",
        )

    stmt = (
        select(LeadAction)
        .options(selectinload(LeadAction.tenant))
        .where(LeadAction.id == action_uuid)
    )
    action = (await db.execute(stmt)).scalar_one_or_none()
    if not action:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Dispatch lead '{action_id}' not found",
        )

    tenant = action.tenant
    tenant_name = tenant.name if tenant else "Apex Restoration & Mechanical Systems"

    # Re-generate if query overrides provided or if no supplement exists yet
    needs_recalc = bool(carrier or claim_num or orig_amount)
    if not action.claim_supplement_data or needs_recalc:
        req = ClaimGenerateRequest(
            insurance_carrier=carrier or "State Farm",
            claim_number=claim_num,
            original_adjuster_amount=orig_amount or 1450.0,
        )
        report = insurance_claim_service.generate_claim_supplement(
            action=action,
            request_data=req,
            tenant_name=tenant_name,
        )
        await insurance_claim_service.save_supplement_to_action(action, report, db)
    else:
        try:
            report = InsuranceClaimSupplementReport.model_validate(action.claim_supplement_data)
        except Exception as exc:
            logger.warning(f"Failed to parse stored claim supplement for {action_id}: {exc}")
            report = insurance_claim_service.generate_claim_supplement(
                action=action,
                tenant_name=tenant_name,
            )
            await insurance_claim_service.save_supplement_to_action(action, report, db)

    accept_header = request.headers.get("accept", "").lower()
    if "application/json" in accept_header or request.query_params.get("format") == "json":
        return JSONResponse(content=report.model_dump())

    return templates.TemplateResponse(
        request=request,
        name="claim_supplement.html",
        context={
            "action_id": str(action.id),
            "tenant": tenant,
            "report": report,
            "action": action,
        },
    )


@router.get(
    "/api/v1/claims/{action_id}/json",
    response_model=InsuranceClaimSupplementReport,
    summary="Fetch Insurance Claim Supplement (JSON)",
    description="Returns structured Xactimate line items, code justifications, and demand letter payload.",
)
@router.get(
    "/claims/{action_id}/json",
    response_model=InsuranceClaimSupplementReport,
    include_in_schema=False,
)
async def get_claim_supplement_json(
    action_id: str,
    db: AsyncSession = Depends(get_db),
) -> InsuranceClaimSupplementReport:
    try:
        action_uuid = uuid.UUID(str(action_id))
    except (ValueError, AttributeError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Dispatch lead '{action_id}' not found",
        )

    stmt = (
        select(LeadAction)
        .options(selectinload(LeadAction.tenant))
        .where(LeadAction.id == action_uuid)
    )
    action = (await db.execute(stmt)).scalar_one_or_none()
    if not action:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Dispatch lead '{action_id}' not found",
        )

    tenant_name = action.tenant.name if action.tenant else "Apex Restoration & Mechanical Systems"
    if action.claim_supplement_data:
        try:
            return InsuranceClaimSupplementReport.model_validate(action.claim_supplement_data)
        except Exception:
            pass

    report = insurance_claim_service.generate_claim_supplement(action=action, tenant_name=tenant_name)
    await insurance_claim_service.save_supplement_to_action(action, report, db)
    return report


@router.get(
    "/claims-vault/{tenant_slug}",
    response_class=HTMLResponse,
    summary="Multi-Job Insurance Recovery Vault",
    description="Tracks multi-job insurance supplements, total dollars recovered, pending adjuster approvals, and carrier metrics.",
)
@router.get(
    "/api/v1/claims-vault/{tenant_slug}",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def get_claims_vault(
    tenant_slug: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Response:
    tenant_stmt = select(Tenant).where(Tenant.slug == tenant_slug)
    tenant = (await db.execute(tenant_stmt)).scalar_one_or_none()
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant '{tenant_slug}' not found",
        )

    # Fetch all leads for this tenant
    actions_stmt = (
        select(LeadAction)
        .where(LeadAction.tenant_id == tenant.id)
        .order_by(LeadAction.created_at.desc())
    )
    actions = list((await db.execute(actions_stmt)).scalars().all())

    supplements: List[Dict[str, Any]] = []
    total_supplement_dollars = 0.0
    pending_approvals = 0
    approved_count = 0
    carrier_breakdown: Dict[str, float] = {}

    for act in actions:
        rep_data = act.claim_supplement_data
        rep = None
        if rep_data:
            try:
                rep = InsuranceClaimSupplementReport.model_validate(rep_data)
            except Exception:
                rep = None

        # Auto-synthesize on the fly if lead has emergency or mitigation data
        if not rep and (act.diagnostic_data or act.mitigation_data or act.action_type):
            rep = insurance_claim_service.generate_claim_supplement(
                action=act,
                tenant_name=tenant.name,
            )
            act.claim_supplement_data = rep.model_dump()
            await db.commit()

        if rep:
            supplements.append({"action": act, "report": rep})
            total_supplement_dollars += rep.supplement_amount
            if rep.status == "APPROVED":
                approved_count += 1
            else:
                pending_approvals += 1

            carrier = rep.insurance_carrier
            carrier_breakdown[carrier] = carrier_breakdown.get(carrier, 0.0) + rep.supplement_amount

    # Sample demo carriers if breakdown is empty to ensure rich UX
    if not carrier_breakdown:
        carrier_breakdown = {
            "State Farm": 3480.00,
            "Travelers": 2845.00,
            "Allstate": 1950.00,
            "USAA": 1420.00,
        }

    return templates.TemplateResponse(
        request=request,
        name="claims_vault.html",
        context={
            "tenant": tenant,
            "supplements": supplements,
            "total_supplement_dollars": round(total_supplement_dollars, 2),
            "pending_approvals": pending_approvals,
            "approved_count": approved_count,
            "carrier_breakdown": carrier_breakdown,
            "total_claims": len(supplements),
        },
    )
