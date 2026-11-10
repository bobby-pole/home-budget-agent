"""add_scan_usage_log

Revision ID: 3b1c8f42d1e0
Revises: 071b11883c3f
Create Date: 2026-11-10 09:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3b1c8f42d1e0'
down_revision: Union[str, Sequence[str], None] = '071b11883c3f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'scan_usage_log',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('scan_type', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(op.f('ix_scan_usage_log_user_id'), 'scan_usage_log', ['user_id'], unique=False)
    op.create_index(op.f('ix_scan_usage_log_scan_type'), 'scan_usage_log', ['scan_type'], unique=False)
    op.create_index(op.f('ix_scan_usage_log_created_at'), 'scan_usage_log', ['created_at'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_scan_usage_log_created_at'), table_name='scan_usage_log')
    op.drop_index(op.f('ix_scan_usage_log_scan_type'), table_name='scan_usage_log')
    op.drop_index(op.f('ix_scan_usage_log_user_id'), table_name='scan_usage_log')
    op.drop_table('scan_usage_log')
