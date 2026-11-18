"""add_connection_is_enabled

Revision ID: j7e1b42a9c03
Revises: h5c9f31d8a12
Create Date: 2026-11-18 11:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "j7e1b42a9c03"
down_revision: Union[str, Sequence[str], None] = "h5c9f31d8a12"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add per-connection is_enabled flag to external_receipt_connection."""
    with op.batch_alter_table("external_receipt_connection", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "is_enabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("1"),
            )
        )


def downgrade() -> None:
    """Remove per-connection is_enabled flag from external_receipt_connection."""
    with op.batch_alter_table("external_receipt_connection", schema=None) as batch_op:
        batch_op.drop_column("is_enabled")
