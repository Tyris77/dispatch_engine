from typing import Any, Dict, List, Optional
from sqlalchemy import JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base, TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin


class WebhookEvent(Base, UUIDPrimaryKeyMixin, TimestampMixin, TenantScopedMixin):
    """Raw and processed incoming webhook events partitioned by tenant."""
    __tablename__ = "webhook_events"

    source: Mapped[str] = mapped_column(String(64), nullable=False, default="generic")
    event_type: Mapped[str] = mapped_column(String(128), nullable=False, default="lead.received")
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(255), index=True, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="PENDING", index=True, nullable=False)
    payload: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)
    headers: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relationships
    tenant: Mapped["Tenant"] = relationship(
        "Tenant",
        back_populates="webhook_events",
    )
    lead_actions: Mapped[List["LeadAction"]] = relationship(
        "LeadAction",
        back_populates="webhook_event",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<WebhookEvent id={self.id} tenant_id={self.tenant_id} status={self.status}>"
