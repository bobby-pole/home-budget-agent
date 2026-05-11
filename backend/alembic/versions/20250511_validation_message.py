"""add validation_message to receiptscan

Revision ID: 20250511_validation_message
Revises: 20250420_system_categories_per_budget
Create Date: 2026-05-11

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "20250511_validation_message"
down_revision: Union[str, Sequence[str], None] = "20250420_system_categories_per_budget"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("receiptscan", sa.Column("validation_message", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("receiptscan", "validation_message")
