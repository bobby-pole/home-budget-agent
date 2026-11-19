"""add_document_ingest_fields_to_import_jobs

Revision ID: m9a4d61c3f25
Revises: k8f2c53b0d14
Create Date: 2026-11-19 17:12:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "m9a4d61c3f25"
down_revision: Union[str, Sequence[str], None] = "k8f2c53b0d14"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Allow nullable connection_id on import_jobs and add document_ingest tracking fields."""
    op.drop_index("uq_import_jobs_active_connection_type", table_name="import_jobs")

    with op.batch_alter_table("import_jobs", schema=None) as batch_op:
        batch_op.alter_column(
            "connection_id",
            existing_type=sa.Integer(),
            nullable=True,
        )
        batch_op.add_column(sa.Column("transaction_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("receipt_scan_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("import_batch_id", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("source_filename", sa.String(), nullable=True))
        batch_op.create_foreign_key(
            "fk_import_jobs_transaction",
            "transaction",
            ["transaction_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch_op.create_foreign_key(
            "fk_import_jobs_receipt_scan",
            "receiptscan",
            ["receipt_scan_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch_op.create_index(
            "ix_import_jobs_transaction_id", ["transaction_id"], unique=False
        )
        batch_op.create_index(
            "ix_import_jobs_receipt_scan_id", ["receipt_scan_id"], unique=False
        )
        batch_op.create_index(
            "ix_import_jobs_import_batch_id", ["import_batch_id"], unique=False
        )
        batch_op.create_index(
            "ix_import_jobs_batch_status",
            ["import_batch_id", "status"],
            unique=False,
        )

    op.create_index(
        "uq_import_jobs_active_connection_type",
        "import_jobs",
        ["connection_id", "job_type"],
        unique=True,
        sqlite_where=sa.text("status IN ('pending', 'running') AND connection_id IS NOT NULL"),
        postgresql_where=sa.text("status IN ('pending', 'running') AND connection_id IS NOT NULL"),
    )
    op.create_index(
        "uq_import_jobs_active_scan_type",
        "import_jobs",
        ["receipt_scan_id", "job_type"],
        unique=True,
        sqlite_where=sa.text("status IN ('pending', 'running') AND receipt_scan_id IS NOT NULL"),
        postgresql_where=sa.text("status IN ('pending', 'running') AND receipt_scan_id IS NOT NULL"),
    )


def downgrade() -> None:
    """Revert document_ingest columns and restore non-null connection_id on import_jobs."""
    op.drop_index("uq_import_jobs_active_scan_type", table_name="import_jobs")
    op.drop_index("uq_import_jobs_active_connection_type", table_name="import_jobs")

    op.execute(sa.text("DELETE FROM import_jobs WHERE connection_id IS NULL"))

    with op.batch_alter_table("import_jobs", schema=None) as batch_op:
        batch_op.drop_index("ix_import_jobs_batch_status")
        batch_op.drop_index("ix_import_jobs_import_batch_id")
        batch_op.drop_index("ix_import_jobs_receipt_scan_id")
        batch_op.drop_index("ix_import_jobs_transaction_id")
        batch_op.drop_constraint("fk_import_jobs_receipt_scan", type_="foreignkey")
        batch_op.drop_constraint("fk_import_jobs_transaction", type_="foreignkey")
        batch_op.drop_column("source_filename")
        batch_op.drop_column("import_batch_id")
        batch_op.drop_column("receipt_scan_id")
        batch_op.drop_column("transaction_id")
        batch_op.alter_column(
            "connection_id",
            existing_type=sa.Integer(),
            nullable=False,
        )

    op.create_index(
        "uq_import_jobs_active_connection_type",
        "import_jobs",
        ["connection_id", "job_type"],
        unique=True,
        sqlite_where=sa.text("status IN ('pending', 'running')"),
        postgresql_where=sa.text("status IN ('pending', 'running')"),
    )
