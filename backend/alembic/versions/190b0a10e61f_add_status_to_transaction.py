"""add status to transaction

Revision ID: 190b0a10e61f
Revises: 9f9168e7c584
Create Date: 2026-09-05 09:27:15.925555

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '190b0a10e61f'
down_revision: Union[str, Sequence[str], None] = '9f9168e7c584'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('transaction', schema=None) as batch_op:
        batch_op.add_column(sa.Column('status', sa.String(), server_default='uncleared', nullable=False))
        batch_op.create_index(batch_op.f('ix_transaction_status'), ['status'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('transaction', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_transaction_status'))
        batch_op.drop_column('status')
