import uuid
from typing import Any, Dict, Optional
from sqlalchemy import Float, ForeignKey, JSON, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base, TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin


class LeadAction(Base, UUIDPrimaryKeyMixin, TimestampMixin, TenantScopedMixin):
    """Lead qualification decision, routing execution, and CRM synchronization logs."""
    __tablename__ = "lead_actions"

    webhook_event_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("webhook_events.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    lead_external_id: Mapped[Optional[str]] = mapped_column(String(255), index=True, nullable=True)
    qualification_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    qualification_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    action_type: Mapped[str] = mapped_column(
        String(64),
        default="DISPATCH_ROUTED",
        nullable=False,
    )
    dispatch_status: Mapped[str] = mapped_column(
        String(32),
        default="QUEUED",
        index=True,
        nullable=False,
    )
    crm_sync_status: Mapped[str] = mapped_column(
        String(32),
        default="PENDING",
        index=True,
        nullable=False,
    )
    metadata_payload: Mapped[Dict[str, Any]] = mapped_column(
        JSON,
        default=dict,
        nullable=False,
    )
    diagnostic_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSON,
        nullable=True,
        default=None,
    )
    proposal_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSON,
        nullable=True,
        default=None,
    )
    signed_contract: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSON,
        nullable=True,
        default=None,
    )
    review_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSON,
        nullable=True,
        default=None,
    )
    tracking_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSON,
        nullable=True,
        default=None,
    )
    membership_enrollment: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSON,
        nullable=True,
        default=None,
    )
    invoice_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSON,
        nullable=True,
        default=None,
    )
    material_po: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSON,
        nullable=True,
        default=None,
    )
    profitability_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSON,
        nullable=True,
        default=None,
    )
    reactivation_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSON,
        nullable=True,
        default=None,
    )
    insurance_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSON,
        nullable=True,
        default=None,
    )
    crew_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSON,
        nullable=True,
        default=None,
    )
    safety_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSON,
        nullable=True,
        default=None,
    )
    lien_waiver_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSON,
        nullable=True,
        default=None,
    )
    voice_notes_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSON,
        nullable=True,
        default=None,
    )
    lien_notice_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSON,
        nullable=True,
        default=None,
    )
    warranty_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSON,
        nullable=True,
        default=None,
    )
    financing_selection: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSON,
        nullable=True,
        default=None,
    )
    trip_mileage: Mapped[Optional[float]] = mapped_column(
        Float,
        nullable=True,
        default=None,
    )
    referral_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSON,
        nullable=True,
        default=None,
    )
    route_stop_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSON,
        nullable=True,
        default=None,
    )
    surge_pricing_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSON,
        nullable=True,
        default=None,
    )
    rebate_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSON,
        nullable=True,
        default=None,
    )
    commercial_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSON,
        nullable=True,
        default=None,
    )
    sensor_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSON,
        nullable=True,
        default=None,
    )
    mitigation_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSON,
        nullable=True,
        default=None,
    )
    backfill_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSON,
        nullable=True,
        default=None,
    )
    arbitrage_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSON,
        nullable=True,
        default=None,
    )
    storyboard_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSON,
        nullable=True,
        default=None,
    )
    pay_app_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSON,
        nullable=True,
        default=None,
    )
    partner_exchange_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSON,
        nullable=True,
        default=None,
    )
    speed_to_lead_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSON,
        nullable=True,
        default=None,
    )
    claim_supplement_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSON,
        nullable=True,
        default=None,
    )
    locker_reservation_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSON,
        nullable=True,
        default=None,
    )



    # Relationships
    tenant: Mapped["Tenant"] = relationship(
        "Tenant",
        back_populates="lead_actions",
    )
    webhook_event: Mapped[Optional["WebhookEvent"]] = relationship(
        "WebhookEvent",
        back_populates="lead_actions",
    )

    def __repr__(self) -> str:
        return f"<LeadAction id={self.id} tenant_id={self.tenant_id} action={self.action_type}>"

    @property
    def category(self) -> Optional[str]:
        if self.metadata_payload:
            return (
                self.metadata_payload.get("category")
                or self.metadata_payload.get("trade_type")
                or self.metadata_payload.get("trade")
            )
        return None

    @property
    def contact_id(self) -> Optional[str]:
        return self.lead_external_id

    @property
    def transcription(self) -> Optional[str]:
        return self.qualification_summary

    @property
    def extracted_address(self) -> Optional[str]:
        if self.metadata_payload:
            return (
                self.metadata_payload.get("address")
                or self.metadata_payload.get("extracted_address")
            )
        return None
