"""add user role and audit logs

Revision ID: 003
Revises: 002
Create Date: 2026-05-13
"""
import sqlalchemy as sa
from alembic import op

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None

SCHEMA = "manager"


def upgrade() -> None:
    # 添加 user_role 枚举类型
    user_role = sa.Enum("ADMIN", "USER", name="user_role", schema=SCHEMA, create_type=True)
    user_role.create(op.get_bind(), checkfirst=True)

    # 添加 users.role 列
    op.add_column(
        "users",
        sa.Column("role", user_role, nullable=False, server_default="USER"),
        schema=SCHEMA,
    )

    # 数据迁移：将 username='admin' 的用户设为 ADMIN
    op.execute(f"UPDATE {SCHEMA}.users SET role = 'ADMIN' WHERE username = 'admin'")

    # 创建 audit_logs 表
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey(f"{SCHEMA}.users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("resource_type", sa.String(50), nullable=False),
        sa.Column("resource_id", sa.String(255), nullable=False),
        sa.Column("detail", sa.JSON(), nullable=True),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        schema=SCHEMA,
    )
    op.create_index("ix_audit_logs_user_id", "audit_logs", ["user_id"], schema=SCHEMA)
    op.create_index("ix_audit_logs_action", "audit_logs", ["action"], schema=SCHEMA)
    op.create_index("ix_audit_logs_created_at", "audit_logs", ["created_at"], schema=SCHEMA)
    op.create_index("ix_audit_logs_resource_type_id", "audit_logs", ["resource_type", "resource_id"], schema=SCHEMA)


def downgrade() -> None:
    op.drop_table("audit_logs", schema=SCHEMA)
    op.drop_column("users", "role", schema=SCHEMA)
    sa.Enum(name="user_role", schema=SCHEMA).drop(op.get_bind(), checkfirst=True)
