"""add_original_date_to_receiptscan

Revision ID: 071b11883c3f
Revises: 4bf7c2229c2e
Create Date: 2026-11-09 19:57:45.451156

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '071b11883c3f'
down_revision: Union[str, Sequence[str], None] = '4bf7c2229c2e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('receiptscan', schema=None) as batch_op:
        batch_op.add_column(sa.Column('original_date', sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('receiptscan', schema=None) as batch_op:
        batch_op.drop_column('original_date')
