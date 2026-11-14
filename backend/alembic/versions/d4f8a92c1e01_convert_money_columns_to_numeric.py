"""convert_money_columns_to_numeric

Revision ID: d4f8a92c1e01
Revises: 3b1c8f42d1e0
Create Date: 2026-11-14 16:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d4f8a92c1e01"
down_revision: Union[str, Sequence[str], None] = "3b1c8f42d1e0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Convert monetary and quantity columns from FLOAT to exact NUMERIC."""
    with op.batch_alter_table("account", schema=None) as batch_op:
        batch_op.alter_column(
            "initial_balance",
            existing_type=sa.Float(),
            type_=sa.Numeric(precision=12, scale=2),
            existing_nullable=False,
        )
        batch_op.alter_column(
            "current_balance",
            existing_type=sa.Float(),
            type_=sa.Numeric(precision=12, scale=2),
            existing_nullable=False,
        )

    with op.batch_alter_table("transaction", schema=None) as batch_op:
        batch_op.alter_column(
            "total_amount",
            existing_type=sa.Float(),
            type_=sa.Numeric(precision=12, scale=2),
            existing_nullable=False,
        )

    with op.batch_alter_table("transactionline", schema=None) as batch_op:
        batch_op.alter_column(
            "price",
            existing_type=sa.Float(),
            type_=sa.Numeric(precision=12, scale=4),
            existing_nullable=False,
        )
        batch_op.alter_column(
            "quantity",
            existing_type=sa.Float(),
            type_=sa.Numeric(precision=12, scale=4),
            existing_nullable=False,
        )
        batch_op.alter_column(
            "original_price",
            existing_type=sa.Float(),
            type_=sa.Numeric(precision=12, scale=4),
            existing_nullable=True,
        )
        batch_op.alter_column(
            "discount_total",
            existing_type=sa.Float(),
            type_=sa.Numeric(precision=12, scale=2),
            existing_nullable=False,
            existing_server_default="0.0",
            server_default="0.00",
        )
        batch_op.alter_column(
            "final_price",
            existing_type=sa.Float(),
            type_=sa.Numeric(precision=12, scale=4),
            existing_nullable=True,
        )

    with op.batch_alter_table("envelope_allocation", schema=None) as batch_op:
        batch_op.alter_column(
            "amount",
            existing_type=sa.Float(),
            type_=sa.Numeric(precision=12, scale=2),
            existing_nullable=False,
        )

    # Quantize legacy float rows to remove binary IEEE-754 drift (e.g. 10.990000000000002).
    op.execute(sa.text("UPDATE account SET initial_balance = ROUND(initial_balance, 2), current_balance = ROUND(current_balance, 2)"))
    op.execute(sa.text('UPDATE "transaction" SET total_amount = ROUND(total_amount, 2)'))
    op.execute(
        sa.text(
            "UPDATE transactionline SET "
            "price = ROUND(price, 4), "
            "quantity = ROUND(quantity, 4), "
            "original_price = CASE WHEN original_price IS NOT NULL THEN ROUND(original_price, 4) ELSE NULL END, "
            "discount_total = ROUND(discount_total, 2), "
            "final_price = CASE WHEN final_price IS NOT NULL THEN ROUND(final_price, 4) ELSE NULL END"
        )
    )
    op.execute(sa.text("UPDATE envelope_allocation SET amount = ROUND(amount, 2)"))


def downgrade() -> None:
    """Revert monetary and quantity columns from NUMERIC back to FLOAT."""
    with op.batch_alter_table("envelope_allocation", schema=None) as batch_op:
        batch_op.alter_column(
            "amount",
            existing_type=sa.Numeric(precision=12, scale=2),
            type_=sa.Float(),
            existing_nullable=False,
        )

    with op.batch_alter_table("transactionline", schema=None) as batch_op:
        batch_op.alter_column(
            "final_price",
            existing_type=sa.Numeric(precision=12, scale=4),
            type_=sa.Float(),
            existing_nullable=True,
        )
        batch_op.alter_column(
            "discount_total",
            existing_type=sa.Numeric(precision=12, scale=2),
            type_=sa.Float(),
            existing_nullable=False,
            existing_server_default="0.00",
            server_default="0.0",
        )
        batch_op.alter_column(
            "original_price",
            existing_type=sa.Numeric(precision=12, scale=4),
            type_=sa.Float(),
            existing_nullable=True,
        )
        batch_op.alter_column(
            "quantity",
            existing_type=sa.Numeric(precision=12, scale=4),
            type_=sa.Float(),
            existing_nullable=False,
        )
        batch_op.alter_column(
            "price",
            existing_type=sa.Numeric(precision=12, scale=4),
            type_=sa.Float(),
            existing_nullable=False,
        )

    with op.batch_alter_table("transaction", schema=None) as batch_op:
        batch_op.alter_column(
            "total_amount",
            existing_type=sa.Numeric(precision=12, scale=2),
            type_=sa.Float(),
            existing_nullable=False,
        )

    with op.batch_alter_table("account", schema=None) as batch_op:
        batch_op.alter_column(
            "current_balance",
            existing_type=sa.Numeric(precision=12, scale=2),
            type_=sa.Float(),
            existing_nullable=False,
        )
        batch_op.alter_column(
            "initial_balance",
            existing_type=sa.Numeric(precision=12, scale=2),
            type_=sa.Float(),
            existing_nullable=False,
        )
