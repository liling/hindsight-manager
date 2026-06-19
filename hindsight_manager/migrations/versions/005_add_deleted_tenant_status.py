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
    # PG 12+ allows ALTER TYPE ... ADD VALUE IF NOT EXISTS inside a
    # transaction block (which Alembic wraps). If this fails on older PG,
    # switch to: op.execute("COMMIT"); op.execute("ALTER TYPE ...")
    op.execute(
        f"ALTER TYPE {SCHEMA}.tenant_status ADD VALUE IF NOT EXISTS 'deleted'"
    )


def downgrade() -> None:
    # PG 不支持从 enum 直接移除值；downgrade 需重建类型，留作 not implemented。
    raise NotImplementedError(
        "Removing enum values requires type rebuild; see PG docs."
    )
