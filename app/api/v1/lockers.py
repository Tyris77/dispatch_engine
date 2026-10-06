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
from app.schemas.lockers import (
    LockerBranchQueryRequest,
    LockerDistributorBranch,
    LockerReservationVoucher,
    LockerReserveRequest,
)
from app.services.lockers import locker_service

router = APIRouter(tags=["24/7 Supply House Emergency Locker & After-Hours Parts Reservation Engine"])

TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "templates")
templates = Jinja2Templates(directory=TEMPLATES_DIR)


@router.post(
    "/api/v1/lockers/reserve/{action_id}",
    response_model=LockerReservationVoucher,
    summary="Reserve 24/7 After-Hours Supply House Locker",
    description="Provisions electronic locker bay at nearest regional distributor, generates 4-digit PIN, and logs costs.",
)
@router.post(
    "/lockers/reserve/{action_id}",
    response_model=LockerReservationVoucher,
    include_in_schema=False,
)
async def reserve_locker_endpoint(
    action_id: str,
    request_data: Optional[LockerReserveRequest] = None,
    db: AsyncSession = Depends(get_db),
) -> LockerReservationVoucher:
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

    voucher = locker_service.reserve_after_hours_locker(
        action=action,
        request_data=request_data,
        db=db,
    )
    await db.commit()
    await db.refresh(action)
    return voucher


@router.get(
    "/lockers/{action_id}",
    response_class=HTMLResponse,
    summary="Interactive After-Hours Locker Access Voucher",
    description="Mobile-optimized technician voucher showing electronic PIN, gate access code, parts manifest, and GPS navigation.",
)
@router.get(
    "/api/v1/lockers/{action_id}",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def view_locker_voucher(
    action_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    format: Optional[str] = Query(None),
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

    voucher_data = action.locker_reservation_data
    if not voucher_data:
        voucher = locker_service.reserve_after_hours_locker(action=action, db=db)
        await db.commit()
        await db.refresh(action)
    else:
        try:
            voucher = LockerReservationVoucher.model_validate(voucher_data)
        except Exception as exc:
            logger.warning(f"Error validating stored locker voucher for {action_id}: {exc}")
            voucher = locker_service.reserve_after_hours_locker(action=action, db=db)
            await db.commit()
            await db.refresh(action)

    accept_header = request.headers.get("accept", "").lower()
    if format == "json" or "application/json" in accept_header:
        return JSONResponse(content=voucher.model_dump())

    return templates.TemplateResponse(
        request=request,
        name="locker_voucher.html",
        context={
            "action_id": str(action.id),
            "tenant": tenant,
            "voucher": voucher,
            "action": action,
        },
    )


@router.get(
    "/api/v1/lockers/{action_id}/json",
    response_model=LockerReservationVoucher,
    summary="Get Locker Reservation Voucher (JSON)",
    description="Returns structured voucher data, PIN, locker box assignment, and itemized parts.",
)
@router.get(
    "/lockers/{action_id}/json",
    response_model=LockerReservationVoucher,
    include_in_schema=False,
)
async def get_locker_voucher_json(
    action_id: str,
    db: AsyncSession = Depends(get_db),
) -> LockerReservationVoucher:
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

    if action.locker_reservation_data:
        try:
            return LockerReservationVoucher.model_validate(action.locker_reservation_data)
        except Exception:
            pass

    voucher = locker_service.reserve_after_hours_locker(action=action, db=db)
    await db.commit()
    await db.refresh(action)
    return voucher


@router.post(
    "/api/v1/lockers/check-branches",
    summary="Query Nearest Stocking After-Hours Locker Branches",
    description="Calculates haversine distance to DMV wholesale locker facilities from customer address or coordinates.",
)
async def check_branches_endpoint(
    query: LockerBranchQueryRequest,
) -> Dict[str, Any]:
    branches = locker_service.query_nearby_branches(query)
    return {
        "query": query.model_dump(),
        "total_branches_found": len(branches),
        "nearest_branch": branches[0] if branches else None,
        "branches": branches,
    }


@router.get(
    "/lockers-vault/{tenant_slug}",
    response_class=HTMLResponse,
    summary="Fleet Supply House Lockers Vault",
    description="Real-time multi-truck parts staging tracker across Ferguson, Johnstone, and RE Michel lockers.",
)
@router.get(
    "/api/v1/lockers-vault/{tenant_slug}",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def view_lockers_vault(
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

    actions_stmt = (
        select(LeadAction)
        .where(LeadAction.tenant_id == tenant.id)
        .order_by(LeadAction.created_at.desc())
    )
    actions = list((await db.execute(actions_stmt)).scalars().all())

    vouchers: List[Dict[str, Any]] = []
    total_parts_dollars = 0.0
    confirmed_count = 0
    picked_up_count = 0
    expired_count = 0
    distributor_breakdown: Dict[str, int] = {}

    for act in actions:
        data = act.locker_reservation_data
        v = None
        if data:
            try:
                v = LockerReservationVoucher.model_validate(data)
            except Exception:
                v = None

        if not v and (act.material_po or act.diagnostic_data or act.action_type):
            v = locker_service.reserve_after_hours_locker(action=act, db=db)
            await db.commit()

        if v:
            vouchers.append({"action": act, "voucher": v})
            total_parts_dollars += v.total_cost
            if v.status == "PICKED_UP":
                picked_up_count += 1
            elif v.status == "EXPIRED":
                expired_count += 1
            else:
                confirmed_count += 1

            d_name = v.distributor.distributor_name
            distributor_breakdown[d_name] = distributor_breakdown.get(d_name, 0) + 1

    if not distributor_breakdown:
        distributor_breakdown = {
            "Ferguson Enterprises": 3,
            "Johnstone Supply": 4,
            "RE Michel Company": 2,
            "Hajoca Corporation": 1,
        }

    return templates.TemplateResponse(
        request=request,
        name="lockers_vault.html",
        context={
            "tenant": tenant,
            "vouchers": vouchers,
            "total_reservations": len(vouchers),
            "total_parts_dollars": round(total_parts_dollars, 2),
            "confirmed_count": confirmed_count,
            "picked_up_count": picked_up_count,
            "expired_count": expired_count,
            "distributor_breakdown": distributor_breakdown,
            "dmv_branches": locker_service.branches,
        },
    )
