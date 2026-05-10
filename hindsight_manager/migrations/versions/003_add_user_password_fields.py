"""Add user password fields

Revision ID: 003
Revises: 002
Create Date: 2026-05-10
"""
import sqlalchemy as sa
from alembic import op

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None

SCHEMA = "manager"


def upgrade() -> None:
    # 添加新字段到 users 表
    op.add_column("users", sa.Column("email", sa.String(255), nullable=True), schema=SCHEMA)
    op.add_column("users", sa.Column("updated_at", sa.DateTime(timezone=True), server_default="now()"), schema=SCHEMA)
    op.add_column("users", sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True), schema=SCHEMA)
    op.add_column("users", sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False), schema=SCHEMA)

    # 创建唯一索引
    op.create_index("ix_users_email", "users", ["email"], unique=True, schema=SCHEMA)

    # 创建邮箱验证码表
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

    # 创建登录历史表
    op.create_table(
        "login_history",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.String(500), nullable=True),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("failed_reason", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default="now()"),
        schema=SCHEMA,
    )

    op.create_index("ix_login_history_user_id", "login_history", ["user_id"], schema=SCHEMA)
    op.create_index("ix_login_history_created_at", "login_history", ["created_at"], schema=SCHEMA)


def downgrade() -> None:
    op.drop_table("login_history", schema=SCHEMA)
    op.drop_table("email_verification_codes", schema=SCHEMA)
    op.drop_index("ix_users_email", table_name="users", schema=SCHEMA)
    op.drop_column("users", "is_active", schema=SCHEMA)
    op.drop_column("users", "last_login_at", schema=SCHEMA)
    op.drop_column("users", "updated_at", schema=SCHEMA)
    op.drop_column("users", "email", schema=SCHEMA)
