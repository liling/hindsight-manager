"""rename infra tables (Phase 5 prep)

Revision ID: 007
Revises: 006
Create Date: 2026-06-22

DEPRECATED APPROACH: drop tables with CASCADE.

NEW APPROACH: RENAME to *_deprecated suffix so:
- DBA / vendor teams have 1-2 weeks to verify xinyi.* data before final drop
- Easy rollback via single RENAME
- No data loss in migration window

The actual DROP of deprecated tables is a separate Phase 6 migration (008),
which is only run manually after explicit confirmation.

Idempotent: uses IF EXISTS + catches errors.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "007"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop FK constraint on tenant_members.user_id (if it still exists)
    op.execute("""
        DO $$ BEGIN
            ALTER TABLE manager.tenant_members DROP CONSTRAINT IF EXISTS tenant_members_user_id_fkey;
        EXCEPTION WHEN OTHERS THEN null;
        END $$;
    """)

    # Rename tables instead of dropping. Each RENAME is idempotent via IF EXISTS.
    # _deprecated suffix leaves the data accessible for verification / rollback.
    for table in ["email_verifications", "login_history", "audit_logs", "users"]:
        op.execute(f"""
            DO $$ BEGIN
                IF EXISTS (
                    SELECT 1 FROM information_schema.tables
                    WHERE table_schema = 'manager' AND table_name = '{table}'
                ) THEN
                    ALTER TABLE manager.{table} RENAME TO {table}_deprecated;
                END IF;
            EXCEPTION WHEN OTHERS THEN null;
            END $$;
        """)


def downgrade() -> None:
    # Reverse: rename back to original names. Idempotent.
    for table in ["email_verifications", "login_history", "audit_logs", "users"]:
        op.execute(f"""
            DO $$ BEGIN
                IF EXISTS (
                    SELECT 1 FROM information_schema.tables
                    WHERE table_schema = 'manager' AND table_name = '{table}_deprecated'
                ) THEN
                    ALTER TABLE manager.{table}_deprecated RENAME TO {table};
                END IF;
            EXCEPTION WHEN OTHERS THEN null;
            END $$;
        """)