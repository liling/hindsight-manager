"""add audit_outbox

Revision ID: 006
Revises: 005
Create Date: 2026-06-22

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("DO $$ BEGIN CREATE TYPE manager.outbox_status AS ENUM ('pending', 'delivered', 'failed'); EXCEPTION WHEN duplicate_object THEN null; END $$;")
    op.create_table(
        "audit_outbox",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("client_id", sa.String(64), nullable=False, server_default="hm-prod"),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("resource_type", sa.String(50), nullable=False),
        sa.Column("resource_id", sa.String(255), nullable=False),
        sa.Column("detail", sa.dialects.postgresql.JSONB, nullable=True),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("idempotency_key", sa.String(64), nullable=True, unique=True),
        sa.Column("status",
                  sa.dialects.postgresql.ENUM("pending", "delivered", "failed",
                                              name="outbox_status", schema="manager", create_type=False),
                  nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        schema="manager",
    )
    op.create_index("ix_audit_outbox_user_id", "audit_outbox", ["user_id"], schema="manager")
    op.create_index("ix_audit_outbox_status", "audit_outbox", ["status"], schema="manager")


def downgrade() -> None:
    op.drop_table("audit_outbox", schema="manager")
    op.execute("DROP TYPE IF EXISTS manager.outbox_status")