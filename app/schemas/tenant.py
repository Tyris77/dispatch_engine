import uuid
from datetime import datetime
from typing import Any, Dict, Optional
from pydantic import BaseModel, ConfigDict, Field


class TenantBase(BaseModel):
    name: str = Field(..., min_length=2, max_length=255, description="Tenant organization name")
    slug: str = Field(..., min_length=2, max_length=64, pattern=r"^[a-z0-9_-]+$", description="URL-friendly identifier")
    settings: Dict[str, Any] = Field(default_factory=dict, description="Custom routing and tenant configuration")


class TenantCreate(TenantBase):
    """Payload to provision a new tenant."""
    pass


class TenantUpdate(BaseModel):
    """Payload to update an existing tenant."""
    name: Optional[str] = Field(None, min_length=2, max_length=255)
    is_active: Optional[bool] = None
    settings: Optional[Dict[str, Any]] = None


class TenantRead(TenantBase):
    """Public tenant representation (sensitive hashes excluded)."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    is_active: bool
    created_at: datetime
    updated_at: datetime


class TenantCreatedResponse(TenantRead):
    """Returned once upon tenant creation with the raw API key and webhook secret."""
    api_key: str = Field(..., description="Raw API key (store securely, shown once)")
    webhook_secret: str = Field(..., description="Secret used to sign and verify incoming webhooks")
