"""add_import_jobs_queue

Revision ID: f3a9d71b2e04
Revises: e9a1c3d5f702
Create Date: 2026-11-14 21:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f3a9d71b2e04"
down_revision: Union[str, Sequence[str], None] = "e9a1c3d5f702"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create import_jobs and import_provider_limits tables for durable worker scheduling."""
    op.create_table(
        "import_jobs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("job_type", sa.String(), nullable=False, server_default="connection_sync"),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("connection_id", sa.Integer(), nullable=False),
        sa.Column("budget_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cursor", sa.String(), nullable=True),
        sa.Column("correlation_id", sa.String(), nullable=False),
        sa.Column("lease_owner", sa.String(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["connection_id"],
            ["external_receipt_connection.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["budget_id"], ["budget.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    with op.batch_alter_table("import_jobs", schema=None) as batch_op:
        batch_op.create_index("ix_import_jobs_job_type", ["job_type"], unique=False)
        batch_op.create_index("ix_import_jobs_provider", ["provider"], unique=False)
        batch_op.create_index("ix_import_jobs_connection_id", ["connection_id"], unique=False)
        batch_op.create_index("ix_import_jobs_budget_id", ["budget_id"], unique=False)
        batch_op.create_index("ix_import_jobs_status", ["status"], unique=False)
        batch_op.create_index("ix_import_jobs_next_retry_at", ["next_retry_at"], unique=False)
        batch_op.create_index("ix_import_jobs_correlation_id", ["correlation_id"], unique=False)
        batch_op.create_index("ix_import_jobs_lease_owner", ["lease_owner"], unique=False)
        batch_op.create_index("ix_import_jobs_lease_expires_at", ["lease_expires_at"], unique=False)
        batch_op.create_index(
            "ix_import_jobs_claimable",
            ["status", "next_retry_at", "lease_expires_at"],
            unique=False,
        )
        batch_op.create_index(
            "ix_import_jobs_connection_status",
            ["connection_id", "status"],
            unique=False,
        )
        batch_op.create_index(
            "ix_import_jobs_provider_status",
            ["provider", "status"],
            unique=False,
        )

    op.create_index(
        "uq_import_jobs_active_connection_type",
        "import_jobs",
        ["connection_id", "job_type"],
        unique=True,
        sqlite_where=sa.text("status IN ('pending', 'running')"),
        postgresql_where=sa.text("status IN ('pending', 'running')"),
    )

    op.create_table(
        "import_provider_limits",
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("cooldown_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_dispatched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("provider"),
    )


def downgrade() -> None:
    """Drop import_provider_limits and import_jobs tables."""
    op.drop_table("import_provider_limits")
    op.drop_index("uq_import_jobs_active_connection_type", table_name="import_jobs")

    with op.batch_alter_table("import_jobs", schema=None) as batch_op:
        batch_op.drop_index("ix_import_jobs_provider_status")
        batch_op.drop_index("ix_import_jobs_connection_status")
        batch_op.drop_index("ix_import_jobs_claimable")
        batch_op.drop_index("ix_import_jobs_lease_expires_at")
        batch_op.drop_index("ix_import_jobs_lease_owner")
        batch_op.drop_index("ix_import_jobs_correlation_id")
        batch_op.drop_index("ix_import_jobs_next_retry_at")
        batch_op.drop_index("ix_import_jobs_status")
        batch_op.drop_index("ix_import_jobs_budget_id")
        batch_op.drop_index("ix_import_jobs_connection_id")
        batch_op.drop_index("ix_import_jobs_provider")
        batch_op.drop_index("ix_import_jobs_job_type")

    op.drop_table("import_jobs")
