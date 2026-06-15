"""Merge multiple head revisions

Revision ID: 9f9168e7c584
Revises: 5d38caf49410, f775379c3748
Create Date: 2026-06-15 21:26:50.733151

"""
from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = '9f9168e7c584'
down_revision: Union[str, Sequence[str], None] = ('5d38caf49410', 'f775379c3748')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
