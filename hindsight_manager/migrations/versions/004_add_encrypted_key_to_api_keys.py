"""add encrypted_key to api_keys

Revision ID: 004
Revises: 003
Create Date: 2026-05-14
"""
import sqlalchemy as sa
from alembic import op

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None

SCHEMA = "manager"


def upgrade() -> None:
    op.add_column(
        "api_keys",
        sa.Column("encrypted_key", sa.Text(), nullable=True),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_column("api_keys", "encrypted_key", schema=SCHEMA)
