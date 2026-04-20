"""System categories per budget

Revision ID: 20250420_system_categories_per_budget
Revises: 20240411_import_hash
Create Date: 2026-04-20 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20250420_system_categories_per_budget'
down_revision: Union[str, Sequence[str], None] = '20240411_import_hash'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 1. Dodajemy constraint unique per budget dla nazw kategorii
    # 2. Naprawiamy strukturalny problem z nullable budget_id dla kategorii systemowych
    
    # Sprawdź czy tabela ma już constraint
    connection = op.get_bind()
    
    # Sprawdź czy jest już jakiś unique constraint na (name, budget_id)
    result = connection.execute(sa.text("""
        SELECT sql FROM sqlite_master 
        WHERE type='table' AND name='category'
    """)).fetchone()
    
    if result and 'uq_category_name_budget' not in result[0]:
        # Wyczyść ewentualne pozostałości po poprzednich próbach
        op.execute("DROP TABLE IF EXISTS category_new")
        
        # Utwórz nową tabelę z constraint
        op.execute("""
            CREATE TABLE category_new (
                id INTEGER NOT NULL,
                name VARCHAR NOT NULL,
                icon VARCHAR,
                color VARCHAR,
                is_system BOOLEAN NOT NULL,
                parent_id INTEGER,
                order_index INTEGER NOT NULL,
                budget_id INTEGER,
                PRIMARY KEY (id),
                FOREIGN KEY(parent_id) REFERENCES category (id),
                FOREIGN KEY(budget_id) REFERENCES budget (id),
                CONSTRAINT uq_category_name_budget UNIQUE (name, budget_id)
            )
        """)
        
        # Skopiuj istniejące dane, jawnie wymieniając kolumny dla bezpieczeństwa
        op.execute("""
            INSERT INTO category_new (id, name, icon, color, is_system, parent_id, order_index, budget_id)
            SELECT id, name, icon, color, is_system, parent_id, order_index, budget_id 
            FROM category
        """)
        
        # Usuń starą tabelę i zmień nazwę nowej
        op.drop_table('category')
        op.rename_table('category_new', 'category')
    
    # Utwórz indeksy jeśli nie istnieją
    op.create_index(op.f('ix_category_budget_id'), 'category', ['budget_id'], unique=False, if_not_exists=True)


def downgrade() -> None:
    """Downgrade schema."""
    # Przywróć poprzedni stan bez unique constraint per budget
    op.drop_constraint('uq_category_name_budget', 'category', type_='unique')
    op.drop_index(op.f('ix_category_budget_id'), table_name='category')
    
    # Przywróć stare indeksy jeśli były
    # (Nie ma potrzeby zmiany struktury tabeli wstecz)
    pass