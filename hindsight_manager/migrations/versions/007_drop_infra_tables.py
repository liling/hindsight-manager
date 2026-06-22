"""drop infra tables (Phase 5)

Revision ID: 007
Revises: 006
Create Date: 2026-06-22

WARNING: Only run after Plan B is stable for 1-2 weeks and data has been verified
in xinyi.* schemas. This drops manager.users/audit_logs/login_history/email_verifications
and the tenant_members FK constraint.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "007"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        DO $$ BEGIN
            ALTER TABLE manager.tenant_members DROP CONSTRAINT IF EXISTS tenant_members_user_id_fkey;
        EXCEPTION WHEN OTHERS THEN null;
        END $$;
    """)
    op.drop_table("email_verifications", schema="manager")
    op.drop_table("login_history", schema="manager")
    op.drop_table("audit_logs", schema="manager")
    op.drop_table("users", schema="manager")
    op.execute("DROP TYPE IF EXISTS manager.auth_provider")
    op.execute("DROP TYPE IF EXISTS manager.user_role")


def downgrade() -> None:
    pass