"""multi-tenant schema

Revision ID: b5613ca7c88a
Revises: 7e0d4ea8462b
Create Date: 2026-04-03 00:01:45.833918

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


# revision identifiers, used by Alembic.
revision: str = 'b5613ca7c88a'
down_revision: Union[str, Sequence[str], None] = '7e0d4ea8462b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    conn = op.get_bind()
    
    # First, ensure there's a budget for each user
    users_without_budget = conn.execute(text("""
        SELECT u.id 
        FROM user u
        LEFT JOIN budgetmember bm ON bm.user_id = u.id
        WHERE bm.id IS NULL
    """)).fetchall()
    
    for (user_id,) in users_without_budget:
        # Create budget for user
        conn.execute(text("""
            INSERT INTO budget (name, owner_id, created_at)
            VALUES (:name, :owner_id, datetime('now'))
        """), {"name": "Domowy", "owner_id": user_id})
        
        budget_id = conn.execute(text("SELECT last_insert_rowid()")).scalar()
        
        # Add user as owner of budget
        conn.execute(text("""
            INSERT INTO budgetmember (budget_id, user_id, role)
            VALUES (:budget_id, :user_id, 'owner')
        """), {"budget_id": budget_id, "user_id": user_id})
    
    # Add budget_id column to category if it doesn't exist (it might be in initial schema)
    try:
        with op.batch_alter_table('category', schema=None) as batch_op:
            batch_op.add_column(sa.Column('budget_id', sa.Integer(), nullable=True))
    except Exception:
        # Column already exists, that's fine
        pass
    
    # Migrate categories: set budget_id based on owner_id
    # First find budget_id for each user based on budgetmember table
    conn.execute(text("""
        UPDATE category 
        SET budget_id = (
            SELECT bm.budget_id 
            FROM budgetmember bm 
            WHERE bm.user_id = category.owner_id
            LIMIT 1
        )
        WHERE owner_id IS NOT NULL AND budget_id IS NULL
    """))
    
    # Add budget_id column to tag if it doesn't exist (it might be in initial schema)
    try:
        with op.batch_alter_table('tag', schema=None) as batch_op:
            batch_op.add_column(sa.Column('budget_id', sa.Integer(), nullable=True))
    except Exception:
        # Column already exists, that's fine
        pass
    
    # Migrate tags: set budget_id based on owner_id
    conn.execute(text("""
        UPDATE tag 
        SET budget_id = (
            SELECT bm.budget_id 
            FROM budgetmember bm 
            WHERE bm.user_id = tag.owner_id
            LIMIT 1
        )
        WHERE owner_id IS NOT NULL AND budget_id IS NULL
    """))
    
    # Migrate monthly_budget: set budget_id based on user_id
    conn.execute(text("""
        UPDATE monthly_budget 
        SET budget_id = (
            SELECT bm.budget_id 
            FROM budgetmember bm 
            WHERE bm.user_id = monthly_budget.user_id
            LIMIT 1
        )
        WHERE user_id IS NOT NULL AND budget_id IS NULL
    """))
    
    # Now apply schema changes
    op.execute("DROP TABLE IF EXISTS _alembic_tmp_category")
    with op.batch_alter_table('category', schema=None) as batch_op:
        # Column already added in initial schema, just add foreign key
        batch_op.create_foreign_key('fk_category_budget_id', 'budget', ['budget_id'], ['id'])
        batch_op.drop_column('owner_id')

    op.execute("DROP TABLE IF EXISTS _alembic_tmp_monthly_budget")
    with op.batch_alter_table('monthly_budget', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_monthly_budget_user_id'))
        batch_op.drop_column('user_id')

    op.execute("DROP TABLE IF EXISTS _alembic_tmp_tag")
    with op.batch_alter_table('tag', schema=None) as batch_op:
        # Column already added in initial schema, just add foreign key
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
