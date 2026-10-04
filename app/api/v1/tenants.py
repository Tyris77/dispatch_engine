import uuid
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import get_current_tenant, get_db, verify_master_admin
from app.core.security import generate_api_key, generate_webhook_secret
from app.models.tenant import Tenant
from app.schemas.tenant import (
    TenantCreate,
    TenantCreatedResponse,
    TenantRead,
    TenantUpdate,
)

router = APIRouter()


@router.post(
    "",
    response_model=TenantCreatedResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Provision new tenant",
    description="Create a new isolated tenant. Generates a secure API key and webhook HMAC secret.",
)
async def create_tenant(
    tenant_in: TenantCreate,
    db: AsyncSession = Depends(get_db),
    _admin: bool = Depends(verify_master_admin),
) -> TenantCreatedResponse:
    # Check if slug exists
    query = select(Tenant).where(Tenant.slug == tenant_in.slug)
    existing = (await db.execute(query)).scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Tenant with slug '{tenant_in.slug}' already exists",
        )

    raw_api_key, api_key_hash = generate_api_key()
    webhook_secret = generate_webhook_secret()

    tenant = Tenant(
        id=uuid.uuid4(),
        name=tenant_in.name,
        slug=tenant_in.slug,
        api_key_hash=api_key_hash,
        webhook_secret=webhook_secret,
        settings=tenant_in.settings,
        is_active=True,
    )
    db.add(tenant)
    await db.flush()
    await db.refresh(tenant)

    return TenantCreatedResponse(
        id=tenant.id,
        name=tenant.name,
        slug=tenant.slug,
        settings=tenant.settings,
        is_active=tenant.is_active,
        created_at=tenant.created_at,
        updated_at=tenant.updated_at,
        api_key=raw_api_key,
        webhook_secret=webhook_secret,
    )


@router.get(
    "",
    response_model=List[TenantRead],
    summary="List all tenants (Admin)",
)
async def list_tenants(
    db: AsyncSession = Depends(get_db),
    _admin: bool = Depends(verify_master_admin),
) -> List[TenantRead]:
    query = select(Tenant).order_by(Tenant.created_at.desc())
    result = await db.execute(query)
    return list(result.scalars().all())


@router.get(
    "/me",
    response_model=TenantRead,
    summary="Get current tenant info",
)
async def get_current_tenant_info(
    current_tenant: Tenant = Depends(get_current_tenant),
) -> TenantRead:
    return current_tenant


@router.get(
    "/{slug}",
    response_model=TenantRead,
    summary="Get tenant by slug",
)
async def get_tenant_by_slug_route(
    slug: str,
    db: AsyncSession = Depends(get_db),
    _admin: bool = Depends(verify_master_admin),
) -> TenantRead:
    query = select(Tenant).where(Tenant.slug == slug)
    result = await db.execute(query)
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return tenant


@router.patch(
    "/{slug}",
    response_model=TenantRead,
    summary="Update tenant details & routing settings",
)
async def update_tenant(
    slug: str,
    tenant_update: TenantUpdate,
    db: AsyncSession = Depends(get_db),
    _admin: bool = Depends(verify_master_admin),
) -> TenantRead:
    query = select(Tenant).where(Tenant.slug == slug)
    result = await db.execute(query)
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    if tenant_update.name is not None:
        tenant.name = tenant_update.name
    if tenant_update.is_active is not None:
        tenant.is_active = tenant_update.is_active
    if tenant_update.settings is not None:
        tenant.settings = tenant_update.settings

    await db.flush()
    await db.refresh(tenant)
    return tenant
