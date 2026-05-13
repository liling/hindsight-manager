"""fix created_at column type from string to timestamp

Revision ID: 002
Revises: 001
Create Date: 2026-05-13
"""
import sqlalchemy as sa
from alembic import op

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None

SCHEMA = "manager"
TABLES = ["users", "tenants", "tenant_members", "api_keys"]


def upgrade() -> None:
    for table in TABLES:
        op.execute(
            f"UPDATE {SCHEMA}.{table} SET created_at = NOW() WHERE created_at = 'now()'"
        )
        op.execute(
            f"ALTER TABLE {SCHEMA}.{table} ALTER COLUMN created_at DROP DEFAULT"
        )
        op.execute(
            f"ALTER TABLE {SCHEMA}.{table} ALTER COLUMN created_at TYPE timestamp with time zone "
            f"USING created_at::timestamp with time zone"
        )
        op.execute(
            f"ALTER TABLE {SCHEMA}.{table} ALTER COLUMN created_at SET DEFAULT now()"
        )


def downgrade() -> None:
    for table in TABLES:
        op.execute(
            f'ALTER TABLE {SCHEMA}.{table} ALTER COLUMN created_at TYPE text'
        )
        op.execute(
            f"ALTER TABLE {SCHEMA}.{table} ALTER COLUMN created_at SET DEFAULT 'now()'"
        )
