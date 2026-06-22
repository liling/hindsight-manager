"""drop infra tables (Phase 5)

Revision ID: 007
Revises: 006
Create Date: 2026-06-22

WARNING: Only run after Plan B is stable for 1-2 weeks and data has been verified
in xinyi.* schemas. This drops manager.users/audit_logs/login_history/email_verifications
and the tenant_members FK constraint.

All DDL uses IF EXISTS so the migration is idempotent and safe to run repeatedly
even if some tables were never created. DO block ensures the FK drop is also idempotent.
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
    op.execute("DROP TABLE IF EXISTS manager.email_verifications CASCADE")
    op.execute("DROP TABLE IF EXISTS manager.login_history CASCADE")
    op.execute("DROP TABLE IF EXISTS manager.audit_logs CASCADE")
    op.execute("DROP TABLE IF EXISTS manager.users CASCADE")
    op.execute("DROP TYPE IF EXISTS manager.auth_provider")
    op.execute("DROP TYPE IF EXISTS manager.user_role")


def downgrade() -> None:
    pass