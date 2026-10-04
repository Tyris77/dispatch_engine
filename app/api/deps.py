from typing import Optional
from fastapi import Depends, Header, HTTPException, Security, status
from fastapi.security import APIKeyHeader
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import settings
from app.core.security import hash_api_key, verify_api_key
from app.db.session import get_db
from app.models.tenant import Tenant

# Security Schemes
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
admin_key_header = APIKeyHeader(name="X-Admin-API-Key", auto_error=False)


async def get_current_tenant(
    api_key: Optional[str] = Security(api_key_header),
    db: AsyncSession = Depends(get_db),
) -> Tenant:
    """Authenticate and isolate current tenant by X-API-Key header."""
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-API-Key header",
        )

    # Compute hash of the provided API key
    key_hash = hash_api_key(api_key)
    query = select(Tenant).where(Tenant.api_key_hash == key_hash, Tenant.is_active == True)
    result = await db.execute(query)
    tenant = result.scalar_one_or_none()

    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or inactive API key",
        )

    return tenant


async def get_tenant_by_slug(
    tenant_slug: str,
    db: AsyncSession = Depends(get_db),
) -> Tenant:
    """Resolve an active tenant by URL slug."""
    query = select(Tenant).where(Tenant.slug == tenant_slug, Tenant.is_active == True)
    result = await db.execute(query)
    tenant = result.scalar_one_or_none()

    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant '{tenant_slug}' not found or inactive",
        )

    return tenant


async def verify_master_admin(
    admin_key: Optional[str] = Security(admin_key_header),
) -> bool:
    """Verify Master Admin privileges for cross-tenant operations."""
    if not admin_key or admin_key != settings.MASTER_ADMIN_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or missing X-Admin-API-Key header",
        )
    return True
