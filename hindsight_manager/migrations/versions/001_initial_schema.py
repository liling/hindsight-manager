"""initial schema

Revision ID: 001
Revises:
Create Date: 2026-05-06
"""
import sqlalchemy as sa
from alembic import op

revision = "001"
down_revision = None
branch_labels = None
depends_on = None

SCHEMA = "manager"


def _s(table: str) -> str:
    return f"{SCHEMA}.{table}"


def upgrade() -> None:
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")

    op.create_table(
        _s("users"),
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("username", sa.String(255), unique=True, nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=True),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column(
            "auth_provider",
            sa.Enum("local", "cas", name="auth_provider", create_type=True),
            nullable=False,
        ),
        sa.Column("created_at", sa.String(), server_default="now()"),
        schema=SCHEMA,
    )

    op.create_table(
        _s("tenants"),
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("schema_name", sa.String(255), unique=True, nullable=False),
        sa.Column("config", sa.JSON(), nullable=True),
        sa.Column(
            "status",
            sa.Enum("active", "deleting", name="tenant_status", create_type=True),
            nullable=False,
            server_default="active",
        ),
        sa.Column("created_at", sa.String(), server_default="now()"),
        schema=SCHEMA,
    )

    op.create_table(
        _s("tenant_members"),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey(f"{SCHEMA}.users.id"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey(f"{SCHEMA}.tenants.id"), nullable=False),
        sa.Column(
            "role",
            sa.Enum("owner", "member", name="member_role", create_type=True),
            nullable=False,
            server_default="member",
        ),
        sa.Column("created_at", sa.String(), server_default="now()"),
        sa.PrimaryKeyConstraint("user_id", "tenant_id"),
        schema=SCHEMA,
    )

    op.create_table(
        _s("api_keys"),
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey(f"{SCHEMA}.tenants.id"), nullable=False),
        sa.Column("key_hash", sa.String(64), unique=True, nullable=False),
        sa.Column("key_prefix", sa.String(16), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("created_at", sa.String(), server_default="now()"),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_table(_s("api_keys"), schema=SCHEMA)
    op.drop_table(_s("tenant_members"), schema=SCHEMA)
    op.drop_table(_s("tenants"), schema=SCHEMA)
    op.drop_table(_s("users"), schema=SCHEMA)
    op.execute(f"DROP SCHEMA IF EXISTS {SCHEMA}")
