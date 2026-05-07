"""Add is_system and encrypted_key to api_keys

Revision ID: 002
Revises: 001
Create Date: 2026-05-07
"""
import sqlalchemy as sa
from alembic import op

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None

SCHEMA = "manager"


def upgrade() -> None:
    op.add_column(
        "api_keys",
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default="false"),
        schema=SCHEMA,
    )
    op.add_column(
        "api_keys",
        sa.Column("encrypted_key", sa.Text(), nullable=True),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_column("api_keys", "encrypted_key", schema=SCHEMA)
    op.drop_column("api_keys", "is_system", schema=SCHEMA)
