"""add is_adjustment to transactionline

Revision ID: 20260529_transactionline_is_adjustment
Revises: 20250511_discount_fields_transactionline
Create Date: 2026-05-29

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260529_transactionline_is_adjustment"
down_revision: Union[str, Sequence[str], None] = "20250511_discount_fields_transactionline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "transactionline",
        sa.Column("is_adjustment", sa.Boolean(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("transactionline", "is_adjustment")
