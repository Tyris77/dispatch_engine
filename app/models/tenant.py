from typing import Any, Dict, List, Optional
from sqlalchemy import Boolean, JSON, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Tenant(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Tenant entity for multi-tenant isolation and credential management."""
    __tablename__ = "tenants"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    api_key_hash: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    webhook_secret: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True, nullable=False)
    settings: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    # Relationships
    webhook_events: Mapped[List["WebhookEvent"]] = relationship(
        "WebhookEvent",
        back_populates="tenant",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    lead_actions: Mapped[List["LeadAction"]] = relationship(
        "LeadAction",
        back_populates="tenant",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<Tenant id={self.id} slug={self.slug} active={self.is_active}>"
