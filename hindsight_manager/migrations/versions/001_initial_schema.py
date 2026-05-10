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


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm SCHEMA public")
    op.execute("CREATE EXTENSION IF NOT EXISTS vchord CASCADE")
    op.execute("CREATE EXTENSION IF NOT EXISTS vchord_bm25 CASCADE")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_tokenizer CASCADE")
    op.execute(
        "SELECT tokenizer_catalog.create_tokenizer('llmlingua2', $$ model = \"llmlingua2\" $$)"
    )
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")

    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("username", sa.String(255), unique=True, nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=True),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column(
            "auth_provider",
            sa.Enum("LOCAL", "CAS", name="auth_provider", schema=SCHEMA, create_type=True),
            nullable=False,
        ),
        sa.Column("created_at", sa.String(), server_default="now()"),
        schema=SCHEMA,
    )

    op.create_table(
        "tenants",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("schema_name", sa.String(255), unique=True, nullable=False),
        sa.Column("config", sa.JSON(), nullable=True),
        sa.Column(
            "status",
            sa.Enum("ACTIVE", "DELETING", name="tenant_status", schema=SCHEMA, create_type=True),
            nullable=False,
            server_default="ACTIVE",
        ),
        sa.Column("created_at", sa.String(), server_default="now()"),
        schema=SCHEMA,
    )

    op.create_table(
        "tenant_members",
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey(f"{SCHEMA}.users.id"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey(f"{SCHEMA}.tenants.id"), nullable=False),
        sa.Column(
            "role",
            sa.Enum("OWNER", "MEMBER", name="member_role", schema=SCHEMA, create_type=True),
            nullable=False,
            server_default="MEMBER",
        ),
        sa.Column("created_at", sa.String(), server_default="now()"),
        sa.PrimaryKeyConstraint("user_id", "tenant_id"),
        schema=SCHEMA,
    )

    op.create_table(
        "api_keys",
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
    op.drop_table("api_keys", schema=SCHEMA)
    op.drop_table("tenant_members", schema=SCHEMA)
    op.drop_table("tenants", schema=SCHEMA)
    op.drop_table("users", schema=SCHEMA)
    op.execute(f"DROP SCHEMA IF EXISTS {SCHEMA}")
