"""add_note_to_transaction

Revision ID: fee1dd034a04
Revises: 1c101542ee75
Create Date: 2026-03-28 23:05:58.055477

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'fee1dd034a04'
down_revision: Union[str, Sequence[str], None] = '1c101542ee75'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('transaction', schema=None) as batch_op:
        batch_op.add_column(sa.Column('note', sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('transaction', schema=None) as batch_op:
        batch_op.drop_column('note')
