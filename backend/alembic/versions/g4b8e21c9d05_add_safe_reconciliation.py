"""add_safe_reconciliation

Revision ID: g4b8e21c9d05
Revises: f3a9d71b2e04
Create Date: 2026-11-14 22:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "g4b8e21c9d05"
down_revision: Union[str, Sequence[str], None] = "f3a9d71b2e04"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add Transaction.reconciled_into_id and reconciliation_link table."""
    with op.batch_alter_table("transaction", schema=None) as batch_op:
        batch_op.add_column(sa.Column("reconciled_into_id", sa.Integer(), nullable=True))
        batch_op.create_index("ix_transaction_reconciled_into_id", ["reconciled_into_id"], unique=False)
        batch_op.create_foreign_key(
            "fk_transaction_reconciled_into_id",
            "transaction",
            ["reconciled_into_id"],
            ["id"],
            ondelete="SET NULL",
        )

    op.create_table(
        "reconciliation_link",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("budget_id", sa.Integer(), nullable=False),
        sa.Column("bank_source_record_id", sa.Integer(), nullable=False),
        sa.Column("target_source_record_id", sa.Integer(), nullable=False),
        sa.Column("bank_transaction_id", sa.Integer(), nullable=False),
        sa.Column("target_transaction_id", sa.Integer(), nullable=False),
        sa.Column("match_kind", sa.String(), nullable=False, server_default="exact"),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("score", sa.Numeric(precision=5, scale=4), nullable=False),
        sa.Column("reasons", sa.JSON(), nullable=False),
        sa.Column("previous_receipt_status", sa.String(), nullable=True),
        sa.Column("decided_by_user_id", sa.Integer(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["budget_id"], ["budget.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["bank_source_record_id"], ["source_record.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["target_source_record_id"], ["source_record.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["bank_transaction_id"], ["transaction.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["target_transaction_id"], ["transaction.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["decided_by_user_id"], ["user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "budget_id",
            "bank_source_record_id",
            "target_source_record_id",
            name="uq_reconciliation_budget_source_pair",
        ),
    )

    with op.batch_alter_table("reconciliation_link", schema=None) as batch_op:
        batch_op.create_index("ix_reconciliation_link_budget_id", ["budget_id"], unique=False)
        batch_op.create_index("ix_reconciliation_link_bank_source_record_id", ["bank_source_record_id"], unique=False)
        batch_op.create_index("ix_reconciliation_link_target_source_record_id", ["target_source_record_id"], unique=False)
        batch_op.create_index("ix_reconciliation_link_bank_transaction_id", ["bank_transaction_id"], unique=False)
        batch_op.create_index("ix_reconciliation_link_target_transaction_id", ["target_transaction_id"], unique=False)
        batch_op.create_index("ix_reconciliation_link_status", ["status"], unique=False)
        batch_op.create_index(
            "ix_reconciliation_link_budget_status",
            ["budget_id", "status", "score"],
            unique=False,
        )

    op.create_index(
        "uq_reconciliation_active_bank_source",
        "reconciliation_link",
        ["bank_source_record_id"],
        unique=True,
        sqlite_where=sa.text("status = 'accepted'"),
        postgresql_where=sa.text("status = 'accepted'"),
    )
    op.create_index(
        "uq_reconciliation_active_target_purchase_exclusive",
        "reconciliation_link",
        ["target_source_record_id"],
        unique=True,
        sqlite_where=sa.text("status = 'accepted' AND match_kind = 'exact'"),
        postgresql_where=sa.text("status = 'accepted' AND match_kind = 'exact'"),
    )


def downgrade() -> None:
    """Drop reconciliation_link table and Transaction.reconciled_into_id."""
    op.drop_index("uq_reconciliation_active_target_purchase_exclusive", table_name="reconciliation_link")
    op.drop_index("uq_reconciliation_active_bank_source", table_name="reconciliation_link")

    with op.batch_alter_table("reconciliation_link", schema=None) as batch_op:
        batch_op.drop_index("ix_reconciliation_link_budget_status")
        batch_op.drop_index("ix_reconciliation_link_status")
        batch_op.drop_index("ix_reconciliation_link_target_transaction_id")
        batch_op.drop_index("ix_reconciliation_link_bank_transaction_id")
        batch_op.drop_index("ix_reconciliation_link_target_source_record_id")
        batch_op.drop_index("ix_reconciliation_link_bank_source_record_id")
        batch_op.drop_index("ix_reconciliation_link_budget_id")

    op.drop_table("reconciliation_link")

    with op.batch_alter_table("transaction", schema=None) as batch_op:
        batch_op.drop_constraint("fk_transaction_reconciled_into_id", type_="foreignkey")
        batch_op.drop_index("ix_transaction_reconciled_into_id")
        batch_op.drop_column("reconciled_into_id")
