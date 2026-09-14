"""add needs_review to receiptscan

Revision ID: 48c0326d4cbc
Revises: 190b0a10e61f
Create Date: 2026-09-14 23:27:34.914596

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '48c0326d4cbc'
down_revision: Union[str, Sequence[str], None] = '190b0a10e61f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('receiptscan', schema=None) as batch_op:
        batch_op.add_column(sa.Column('needs_review', sa.Boolean(), server_default=sa.text('0'), nullable=False))
        batch_op.create_index(batch_op.f('ix_receiptscan_needs_review'), ['needs_review'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('receiptscan', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_receiptscan_needs_review'))
        batch_op.drop_column('needs_review')
