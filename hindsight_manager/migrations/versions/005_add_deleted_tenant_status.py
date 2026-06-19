"""add deleted to tenant_status enum

Revision ID: 005
Revises: 004
Create Date: 2026-06-19
"""
from alembic import op


revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None

SCHEMA = "manager"


def upgrade() -> None:
    # PG 12+ allows ALTER TYPE ... ADD VALUE inside a transaction block, but
    # the new value cannot be USED (e.g. in INSERT/UPDATE) within the same
    # transaction — only after commit. This migration only adds the value;
    # no statement in this migration references 'deleted', so the default
    # Alembic transaction wrapping is safe. On PG <= 11 this would fail and
    # require op.execute("COMMIT") before the ALTER.
    op.execute(
        f"ALTER TYPE {SCHEMA}.tenant_status ADD VALUE IF NOT EXISTS 'deleted'"
    )


def downgrade() -> None:
    # PG 不支持从 enum 直接移除值；downgrade 需重建类型，留作 not implemented。
    raise NotImplementedError(
        "Removing enum values requires type rebuild; see PG docs."
    )
