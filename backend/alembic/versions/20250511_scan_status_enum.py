"""Granular ScanStatus enum + error_message column on receiptscan

Revision ID: 20250511_scan_status_enum
Revises: 20250511_validation_message
Create Date: 2026-05-11

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20250511_scan_status_enum"
down_revision: Union[str, Sequence[str], None] = "20250511_validation_message"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add error_message column
    op.add_column("receiptscan", sa.Column("error_message", sa.String(), nullable=True))

    # 2. Add index on status (SQLite: create index if not already present)
    op.create_index("ix_receiptscan_status", "receiptscan", ["status"], unique=False)

    # 3. Migrate legacy status values to new enum strings
    op.execute("UPDATE receiptscan SET status = 'RUNNING'            WHERE status = 'processing'")
    op.execute("UPDATE receiptscan SET status = 'CATEGORIZATION_OK'  WHERE status = 'done'")
    op.execute("UPDATE receiptscan SET status = 'FAILED'             WHERE status = 'error'")
    op.execute("UPDATE receiptscan SET status = 'NEEDS_REVIEW'       WHERE status = 'needs_review'")


def downgrade() -> None:
    # Reverse status migration
    op.execute("UPDATE receiptscan SET status = 'processing'   WHERE status = 'RUNNING'")
    op.execute("UPDATE receiptscan SET status = 'processing'   WHERE status = 'QUEUED'")
    op.execute("UPDATE receiptscan SET status = 'processing'   WHERE status = 'OCR_OK'")
    op.execute("UPDATE receiptscan SET status = 'processing'   WHERE status = 'PARSING_OK'")
    op.execute("UPDATE receiptscan SET status = 'done'         WHERE status = 'CATEGORIZATION_OK'")
    op.execute("UPDATE receiptscan SET status = 'needs_review' WHERE status = 'NEEDS_REVIEW'")
    op.execute("UPDATE receiptscan SET status = 'error'        WHERE status = 'FAILED'")

    op.drop_index("ix_receiptscan_status", table_name="receiptscan")
    op.drop_column("receiptscan", "error_message")
