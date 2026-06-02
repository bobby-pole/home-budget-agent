"""Add default_budget_id to User

Revision ID: e7b4ff5f33ce
Revises: 5f33e5ac5df4
Create Date: 2026-05-31 11:12:58.180767

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e7b4ff5f33ce'
down_revision: Union[str, Sequence[str], None] = '5f33e5ac5df4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.add_column(sa.Column('default_budget_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key('fk_user_default_budget_id_budget', 'budget', ['default_budget_id'], ['id'], ondelete='SET NULL')
    # ### end Alembic commands ###


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.drop_constraint('fk_user_default_budget_id_budget', type_='foreignkey')
        batch_op.drop_column('default_budget_id')
    # ### end Alembic commands ###
