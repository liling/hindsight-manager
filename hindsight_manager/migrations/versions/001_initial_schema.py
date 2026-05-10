"""initial schema

Revision ID: 001
Revises:
Create Date: 2026-05-10
"""
import sqlalchemy as sa
from alembic import op

revision = "001"
down_revision = None
branch_labels = None
depends_on = None

SCHEMA = "manager"


def upgrade() -> None:
    # 创建扩展
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm SCHEMA public")
    op.execute("CREATE EXTENSION IF NOT EXISTS vchord CASCADE")
    op.execute("CREATE EXTENSION IF NOT EXISTS vchord_bm25 CASCADE")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_tokenizer CASCADE")
    op.execute(
        "SELECT tokenizer_catalog.create_tokenizer('llmlingua2', $$ model = \"llmlingua2\" $$)"
    )
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")

    # 创建 users 表
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("username", sa.String(255), unique=True, nullable=False),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("password_hash", sa.String(255), nullable=True),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("auth_provider", sa.Enum("LOCAL", "CAS", name="auth_provider", schema=SCHEMA, create_type=True), nullable=False),
        sa.Column("created_at", sa.String(), server_default="now()"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default="now()"),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        schema=SCHEMA,
    )
    op.create_index("ix_users_username", "users", ["username"], unique=True, schema=SCHEMA)
    op.create_index("ix_users_email", "users", ["email"], unique=True, schema=SCHEMA)

    # 创建 tenants 表
    op.create_table(
        "tenants",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("schema_name", sa.String(255), unique=True, nullable=False),
        sa.Column("config", sa.JSON(), nullable=True),
        sa.Column("status", sa.Enum("ACTIVE", "DELETING", name="tenant_status", schema=SCHEMA, create_type=True), nullable=False, server_default="ACTIVE"),
        sa.Column("created_at", sa.String(), server_default="now()"),
        schema=SCHEMA,
    )

    # 创建 tenant_members 表
    op.create_table(
        "tenant_members",
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey(f"{SCHEMA}.tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.Enum("OWNER", "MEMBER", name="member_role", schema=SCHEMA, create_type=True), nullable=False, server_default="MEMBER"),
        sa.Column("created_at", sa.String(), server_default="now()"),
        sa.PrimaryKeyConstraint("user_id", "tenant_id"),
        schema=SCHEMA,
    )
    op.create_index("ix_tenant_members_user_id", "tenant_members", ["user_id"], schema=SCHEMA)
    op.create_index("ix_tenant_members_tenant_id", "tenant_members", ["tenant_id"], schema=SCHEMA)

    # 创建 api_keys 表
    op.create_table(
        "api_keys",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey(f"{SCHEMA}.tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("key_hash", sa.String(64), unique=True, nullable=False),
        sa.Column("key_prefix", sa.String(16), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("created_at", sa.String(), server_default="now()"),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_system", sa.Boolean(), server_default="false", nullable=False),
        schema=SCHEMA,
    )
    op.create_index("ix_api_keys_tenant_id", "api_keys", ["tenant_id"], schema=SCHEMA)

    # 创建 email_verification_codes 表
    op.create_table(
        "email_verification_codes",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("code", sa.String(6), nullable=False),
        sa.Column("purpose", sa.Enum("RESET_PASSWORD", "VERIFY_EMAIL", name="code_purpose", schema=SCHEMA, create_type=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default="now()"),
        schema=SCHEMA,
    )
    op.create_index("ix_email_verification_codes_user_id", "email_verification_codes", ["user_id"], schema=SCHEMA)
    op.create_index("ix_email_verification_codes_expires_at", "email_verification_codes", ["expires_at"], schema=SCHEMA)

    # 创建 login_history 表
    op.create_table(
        "login_history",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.String(500), nullable=True),
        sa.Column("login_time", sa.DateTime(timezone=True), server_default="now()"),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("failure_reason", sa.String(255), nullable=True),
        schema=SCHEMA,
    )
    op.create_index("ix_login_history_user_id", "login_history", ["user_id"], schema=SCHEMA)
    op.create_index("ix_login_history_created_at", "login_history", ["login_time"], schema=SCHEMA)


def downgrade() -> None:
    op.drop_table("login_history", schema=SCHEMA)
    op.drop_table("email_verification_codes", schema=SCHEMA)
    op.drop_table("api_keys", schema=SCHEMA)
    op.drop_table("tenant_members", schema=SCHEMA)
    op.drop_table("tenants", schema=SCHEMA)
    op.drop_table("users", schema=SCHEMA)

    sa.Enum(name="code_purpose", schema=SCHEMA).drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="member_role", schema=SCHEMA).drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="tenant_status", schema=SCHEMA).drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="auth_provider", schema=SCHEMA).drop(op.get_bind(), checkfirst=True)

    op.execute(f"DROP SCHEMA IF EXISTS {SCHEMA}")
