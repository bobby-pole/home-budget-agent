"""add discount fields to transactionline

Revision ID: 20250511_discount_fields_transactionline
Revises: 20250511_scan_status_enum
Create Date: 2026-05-11

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20250511_discount_fields_transactionline"
down_revision: Union[str, Sequence[str], None] = "20250511_scan_status_enum"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("transactionline", sa.Column("original_price", sa.Float(), nullable=True))
    op.add_column("transactionline", sa.Column("discount_total", sa.Float(), nullable=False, server_default="0.0"))
    op.add_column("transactionline", sa.Column("final_price", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("transactionline", "final_price")
    op.drop_column("transactionline", "discount_total")
    op.drop_column("transactionline", "original_price")
