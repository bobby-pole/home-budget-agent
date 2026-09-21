"""add_external_receipt_connection

Revision ID: 4bf7c2229c2e
Revises: 48c0326d4cbc
Create Date: 2026-09-21 11:55:25.465401

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4bf7c2229c2e'
down_revision: Union[str, Sequence[str], None] = '48c0326d4cbc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'external_receipt_connection',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('budget_id', sa.Integer(), nullable=False),
        sa.Column('owner_user_id', sa.Integer(), nullable=False),
        sa.Column('provider', sa.String(), nullable=False),
        sa.Column('account_identifier', sa.String(), nullable=True),
        sa.Column('consented_scopes', sa.String(), nullable=True),
        sa.Column('status', sa.String(), nullable=False, server_default='active'),
        sa.Column('last_error_code', sa.String(), nullable=True),
        sa.Column('consented_at', sa.DateTime(), nullable=False),
        sa.Column('encrypted_refresh_token', sa.String(), nullable=True),
        sa.Column('encryption_key_id', sa.String(), nullable=True),
        sa.Column('last_success_at', sa.DateTime(), nullable=True),
        sa.Column('next_sync_at', sa.DateTime(), nullable=True),
        sa.Column('sync_requested_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['budget_id'], ['budget.id']),
        sa.ForeignKeyConstraint(['owner_user_id'], ['user.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('budget_id', 'provider', name='uq_connection_budget_provider'),
    )
    with op.batch_alter_table('external_receipt_connection', schema=None) as batch_op:
        batch_op.create_index('ix_connection_budget_status', ['budget_id', 'status'], unique=False)
        batch_op.create_index(batch_op.f('ix_external_receipt_connection_budget_id'), ['budget_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_external_receipt_connection_owner_user_id'), ['owner_user_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_external_receipt_connection_provider'), ['provider'], unique=False)
        batch_op.create_index(batch_op.f('ix_external_receipt_connection_status'), ['status'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('external_receipt_connection', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_external_receipt_connection_status'))
        batch_op.drop_index(batch_op.f('ix_external_receipt_connection_provider'))
        batch_op.drop_index(batch_op.f('ix_external_receipt_connection_owner_user_id'))
        batch_op.drop_index(batch_op.f('ix_external_receipt_connection_budget_id'))
        batch_op.drop_index('ix_connection_budget_status')

    op.drop_table('external_receipt_connection')
