"""add_inbox_lifecycle_and_connection_prefs

Revision ID: k8f2c53b0d14
Revises: j7e1b42a9c03
Create Date: 2026-11-19 12:52:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "k8f2c53b0d14"
down_revision: Union[str, Sequence[str], None] = "j7e1b42a9c03"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add review_status lifecycle fields on transaction and sync prefs on external_receipt_connection."""
    with op.batch_alter_table("transaction", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("review_status", sa.String(), nullable=False, server_default="approved")
        )
        batch_op.add_column(
            sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(
            sa.Column("rejection_reason", sa.String(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("import_batch_id", sa.String(), nullable=True)
        )
        batch_op.create_index("ix_transaction_review_status", ["review_status"], unique=False)
        batch_op.create_index("ix_transaction_import_batch_id", ["import_batch_id"], unique=False)

    # Backfill active unverified ReceiptScans to review_status='pending'
    op.execute(
        sa.text(
            """
            UPDATE "transaction"
            SET review_status = 'pending'
            WHERE id IN (
                SELECT transaction_id
                FROM receiptscan
                WHERE transaction_id IS NOT NULL
                  AND LOWER(status) NOT IN ('done')
            )
            """
        )
    )

    with op.batch_alter_table("external_receipt_connection", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("default_account_id", sa.Integer(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("auto_merge_policy", sa.String(), nullable=False, server_default="auto")
        )
        batch_op.add_column(
            sa.Column(
                "auto_approve_clean",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("1"),
            )
        )
        batch_op.add_column(
            sa.Column("sync_from_date", sa.Date(), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_connection_default_account",
            "account",
            ["default_account_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index(
            "ix_external_receipt_connection_default_account_id",
            ["default_account_id"],
            unique=False,
        )


def downgrade() -> None:
    """Remove review_status lifecycle fields and connection sync prefs."""
    with op.batch_alter_table("external_receipt_connection", schema=None) as batch_op:
        batch_op.drop_index("ix_external_receipt_connection_default_account_id")
        batch_op.drop_constraint("fk_connection_default_account", type_="foreignkey")
        batch_op.drop_column("sync_from_date")
        batch_op.drop_column("auto_approve_clean")
        batch_op.drop_column("auto_merge_policy")
        batch_op.drop_column("default_account_id")

    with op.batch_alter_table("transaction", schema=None) as batch_op:
        batch_op.drop_index("ix_transaction_import_batch_id")
        batch_op.drop_index("ix_transaction_review_status")
        batch_op.drop_column("import_batch_id")
        batch_op.drop_column("rejection_reason")
        batch_op.drop_column("rejected_at")
        batch_op.drop_column("review_status")
