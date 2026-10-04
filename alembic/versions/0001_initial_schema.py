"""initial_schema

Revision ID: 0001_initial_schema
Revises: 
Create Date: 2026-09-30 19:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Tenants table
    op.create_table(
        "tenants",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("api_key_hash", sa.String(length=255), nullable=False),
        sa.Column("webhook_secret", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("settings", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(op.f("ix_tenants_slug"), "tenants", ["slug"], unique=True)
    op.create_index(op.f("ix_tenants_api_key_hash"), "tenants", ["api_key_hash"], unique=False)
    op.create_index(op.f("ix_tenants_is_active"), "tenants", ["is_active"], unique=False)

    # 2. Webhook Events table
    op.create_table(
        "webhook_events",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("headers", sa.JSON(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
    )
    op.create_index(op.f("ix_webhook_events_tenant_id"), "webhook_events", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_webhook_events_idempotency_key"), "webhook_events", ["idempotency_key"], unique=False)
    op.create_index(op.f("ix_webhook_events_status"), "webhook_events", ["status"], unique=False)

    # 3. Lead Actions table
    op.create_table(
        "lead_actions",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("webhook_event_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("lead_external_id", sa.String(length=255), nullable=True),
        sa.Column("qualification_score", sa.Float(), nullable=True),
        sa.Column("qualification_summary", sa.Text(), nullable=True),
        sa.Column("action_type", sa.String(length=64), nullable=False),
        sa.Column("dispatch_status", sa.String(length=32), nullable=False),
        sa.Column("crm_sync_status", sa.String(length=32), nullable=False),
        sa.Column("metadata_payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["webhook_event_id"], ["webhook_events.id"], ondelete="SET NULL"),
    )
    op.create_index(op.f("ix_lead_actions_tenant_id"), "lead_actions", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_lead_actions_webhook_event_id"), "lead_actions", ["webhook_event_id"], unique=False)
    op.create_index(op.f("ix_lead_actions_lead_external_id"), "lead_actions", ["lead_external_id"], unique=False)
    op.create_index(op.f("ix_lead_actions_dispatch_status"), "lead_actions", ["dispatch_status"], unique=False)
    op.create_index(op.f("ix_lead_actions_crm_sync_status"), "lead_actions", ["crm_sync_status"], unique=False)


def downgrade() -> None:
    op.drop_table("lead_actions")
    op.drop_table("webhook_events")
    op.drop_table("tenants")
