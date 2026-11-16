"""add_encrypted_oauth_attempt

Revision ID: h5c9f31d8a12
Revises: g4b8e21c9d05
Create Date: 2026-11-16 17:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "h5c9f31d8a12"
down_revision: Union[str, Sequence[str], None] = "g4b8e21c9d05"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Persist encrypted pending PKCE OAuth attempts on external_receipt_connection."""
    with op.batch_alter_table("external_receipt_connection", schema=None) as batch_op:
        batch_op.add_column(sa.Column("encrypted_oauth_attempt", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("oauth_attempt_key_id", sa.String(), nullable=True))
        batch_op.add_column(
            sa.Column("oauth_attempt_expires_at", sa.DateTime(timezone=True), nullable=True)
        )


def downgrade() -> None:
    """Remove encrypted pending PKCE OAuth attempt columns."""
    with op.batch_alter_table("external_receipt_connection", schema=None) as batch_op:
        batch_op.drop_column("oauth_attempt_expires_at")
        batch_op.drop_column("oauth_attempt_key_id")
        batch_op.drop_column("encrypted_oauth_attempt")
