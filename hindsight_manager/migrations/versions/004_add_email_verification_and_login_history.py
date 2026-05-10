"""add email verification and login history tables

Revision ID: 004_add_email_verification_and_login_history
Revises: 003_add_user_password_fields
Create Date: 2025-05-10 21:55:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '004_add_email_verification_and_login_history'
down_revision: Union[str, None] = '003_add_user_password_fields'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create email_verifications table
    op.create_table(
        'email_verifications',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('code', sa.String(length=10), nullable=False),
        sa.Column('purpose', sa.String(length=50), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('verified', sa.Boolean(), nullable=False),
        sa.Column('attempts', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        schema='manager'
    )
    op.create_index(op.f('ix_email_verifications_email'), 'email_verifications', ['email'], unique=False, schema='manager')

    # Create login_history table
    op.create_table(
        'login_history',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('ip_address', sa.String(length=45), nullable=True),
        sa.Column('user_agent', sa.String(length=500), nullable=True),
        sa.Column('login_time', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('success', sa.Boolean(), nullable=False),
        sa.Column('failure_reason', sa.String(length=255), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        schema='manager'
    )
    op.create_index(op.f('ix_login_history_user_id'), 'login_history', ['user_id'], unique=False, schema='manager')


def downgrade() -> None:
    op.drop_index(op.f('ix_login_history_user_id'), table_name='login_history', schema='manager')
    op.drop_table('login_history', schema='manager')
    op.drop_index(op.f('ix_email_verifications_email'), table_name='email_verifications', schema='manager')
    op.drop_table('email_verifications', schema='manager')
