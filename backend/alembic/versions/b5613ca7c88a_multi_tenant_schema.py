"""multi-tenant schema

Revision ID: b5613ca7c88a
Revises: 7e0d4ea8462b
Create Date: 2026-04-03 00:01:45.833918

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b5613ca7c88a'
down_revision: Union[str, Sequence[str], None] = '7e0d4ea8462b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('category', schema=None) as batch_op:
        batch_op.add_column(sa.Column('budget_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key('fk_category_budget_id', 'budget', ['budget_id'], ['id'])
        batch_op.drop_column('owner_id')

    with op.batch_alter_table('monthly_budget', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_monthly_budget_user_id'))
        batch_op.drop_column('user_id')

    with op.batch_alter_table('tag', schema=None) as batch_op:
        batch_op.add_column(sa.Column('budget_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key('fk_tag_budget_id', 'budget', ['budget_id'], ['id'])
        batch_op.drop_column('owner_id')


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('tag', schema=None) as batch_op:
        batch_op.add_column(sa.Column('owner_id', sa.INTEGER(), nullable=True))
        batch_op.drop_constraint('fk_tag_budget_id', type_='foreignkey')
        batch_op.create_foreign_key('fk_tag_owner_id', 'user', ['owner_id'], ['id'])
        batch_op.drop_column('budget_id')

    with op.batch_alter_table('monthly_budget', schema=None) as batch_op:
        batch_op.add_column(sa.Column('user_id', sa.INTEGER(), nullable=True))
        batch_op.create_foreign_key('fk_monthly_budget_user_id', 'user', ['user_id'], ['id'])
        batch_op.create_index(batch_op.f('ix_monthly_budget_user_id'), ['user_id'], unique=False)

    with op.batch_alter_table('category', schema=None) as batch_op:
        batch_op.add_column(sa.Column('owner_id', sa.INTEGER(), nullable=True))
        batch_op.drop_constraint('fk_category_budget_id', type_='foreignkey')
        batch_op.create_foreign_key('fk_category_owner_id', 'user', ['owner_id'], ['id'])
        batch_op.drop_column('budget_id')
