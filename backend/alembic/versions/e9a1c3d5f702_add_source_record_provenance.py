"""add_source_record_provenance

Revision ID: e9a1c3d5f702
Revises: d4f8a92c1e01
Create Date: 2026-11-14 20:00:00.000000

"""
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional, Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e9a1c3d5f702"
down_revision: Union[str, Sequence[str], None] = "d4f8a92c1e01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _clean_opt_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def _parse_dt(value: Any, fallback: datetime) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        cleaned = value.strip()
        if cleaned:
            try:
                parsed = datetime.fromisoformat(cleaned.replace("Z", "+00:00"))
                return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)
            except ValueError:
                pass
    return fallback


def upgrade() -> None:
    """Create source_record table with partial unique indexes, add processed_via, and backfill."""
    with op.batch_alter_table("receiptscan", schema=None) as batch_op:
        batch_op.add_column(sa.Column("processed_via", sa.String(), nullable=True))

    op.create_table(
        "source_record",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("budget_id", sa.Integer(), nullable=False),
        sa.Column("transaction_id", sa.Integer(), nullable=True),
        sa.Column("receipt_scan_id", sa.Integer(), nullable=True),
        sa.Column("connection_id", sa.Integer(), nullable=True),
        sa.Column("source_type", sa.String(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("external_id", sa.String(), nullable=True),
        sa.Column("canonical_hash", sa.String(), nullable=True),
        sa.Column("adapter_version", sa.String(), nullable=False),
        sa.Column("acquired_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("quality", sa.Numeric(precision=5, scale=4), nullable=True),
        sa.Column("raw_payload_policy", sa.String(), nullable=False, server_default="none"),
        sa.ForeignKeyConstraint(["budget_id"], ["budget.id"]),
        sa.ForeignKeyConstraint(["connection_id"], ["external_receipt_connection.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["receipt_scan_id"], ["receiptscan.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["transaction_id"], ["transaction.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    with op.batch_alter_table("source_record", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_source_record_budget_id"), ["budget_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_source_record_connection_id"), ["connection_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_source_record_provider"), ["provider"], unique=False)
        batch_op.create_index(batch_op.f("ix_source_record_receipt_scan_id"), ["receipt_scan_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_source_record_source_type"), ["source_type"], unique=False)
        batch_op.create_index(batch_op.f("ix_source_record_transaction_id"), ["transaction_id"], unique=False)

    op.create_index(
        "uq_source_record_budget_provider_external_id",
        "source_record",
        ["budget_id", "provider", "external_id"],
        unique=True,
        sqlite_where=sa.text("external_id IS NOT NULL"),
        postgresql_where=sa.text("external_id IS NOT NULL"),
    )
    op.create_index(
        "uq_source_record_budget_canonical_hash",
        "source_record",
        ["budget_id", "canonical_hash"],
        unique=True,
        sqlite_where=sa.text("canonical_hash IS NOT NULL"),
        postgresql_where=sa.text("canonical_hash IS NOT NULL"),
    )

    _backfill_legacy_source_records()


def _backfill_legacy_source_records() -> None:
    conn = op.get_bind()
    tx_rows = conn.execute(
        sa.text(
            'SELECT id, budget_id, is_manual, import_hash, note, date '
            'FROM "transaction" WHERE budget_id IS NOT NULL ORDER BY id ASC'
        )
    ).mappings().all()

    if not tx_rows:
        return

    scan_rows = conn.execute(
        sa.text(
            "SELECT id, transaction_id, content_hash, keep_image, image_path, created_at "
            "FROM receiptscan ORDER BY id ASC"
        )
    ).mappings().all()

    scans_by_tx: dict[int, dict[str, Any]] = {}
    for srow in scan_rows:
        tx_id = srow["transaction_id"]
        if tx_id is not None and tx_id not in scans_by_tx:
            scans_by_tx[tx_id] = dict(srow)

    source_table = sa.table(
        "source_record",
        sa.column("budget_id", sa.Integer()),
        sa.column("transaction_id", sa.Integer()),
        sa.column("receipt_scan_id", sa.Integer()),
        sa.column("connection_id", sa.Integer()),
        sa.column("source_type", sa.String()),
        sa.column("provider", sa.String()),
        sa.column("external_id", sa.String()),
        sa.column("canonical_hash", sa.String()),
        sa.column("adapter_version", sa.String()),
        sa.column("acquired_at", sa.DateTime(timezone=True)),
        sa.column("quality", sa.Numeric(precision=5, scale=4)),
        sa.column("raw_payload_policy", sa.String()),
    )

    now_utc = datetime.now(timezone.utc)
    seen_external: set[tuple[int, str, str]] = set()
    seen_hashes: set[tuple[int, str]] = set()
    inserts: list[dict[str, Any]] = []

    for trow in tx_rows:
        tx_id = int(trow["id"])
        budget_id = int(trow["budget_id"])
        import_hash = _clean_opt_str(trow["import_hash"])
        note = _clean_opt_str(trow["note"]) or ""
        scan = scans_by_tx.get(tx_id)

        receipt_scan_id: Optional[int] = None
        external_id: Optional[str] = None
        canonical_hash: Optional[str] = None

        if scan is not None:
            receipt_scan_id = int(scan["id"])
            scan_hash = _clean_opt_str(scan["content_hash"])
            acquired_at = scan["created_at"] or trow["date"] or now_utc
            keep_image = bool(scan["keep_image"])
            has_image = bool(_clean_opt_str(scan["image_path"]))

            if note.startswith("Lidl Plus #"):
                source_type = "MERCHANT_API"
                provider = "lidl_plus"
                external_id = _clean_opt_str(note[len("Lidl Plus #"):])
                canonical_hash = scan_hash or import_hash
                adapter_version = "lidl_plus_v3"
                quality = Decimal("1.0000")
                raw_payload_policy = "canonical_only"
            elif scan_hash and scan_hash.startswith("sample_"):
                source_type = "OCR_PHOTO"
                provider = "demo_sample"
                canonical_hash = scan_hash
                adapter_version = "demo_sample_v1"
                quality = Decimal("1.0000")
                raw_payload_policy = (
                    "retained_image"
                    if keep_image
                    else ("ephemeral_image" if has_image else "canonical_only")
                )
            else:
                source_type = "OCR_PHOTO"
                provider = "legacy_scan"
                canonical_hash = scan_hash
                adapter_version = "legacy_backfill"
                quality = Decimal("0.8500")
                raw_payload_policy = (
                    "retained_image"
                    if keep_image
                    else ("ephemeral_image" if has_image else "canonical_only")
                )
        elif import_hash:
            source_type = "BANK_CSV"
            provider = "legacy_bank_import"
            canonical_hash = import_hash
            adapter_version = "legacy_backfill"
            quality = Decimal("0.9500")
            raw_payload_policy = "none"
            acquired_at = trow["date"] or now_utc
        else:
            source_type = "MANUAL"
            provider = "legacy_manual"
            adapter_version = "legacy_backfill"
            quality = Decimal("1.0000")
            raw_payload_policy = "none"
            acquired_at = trow["date"] or now_utc

        if external_id is not None:
            ext_key = (budget_id, provider, external_id)
            if ext_key in seen_external:
                external_id = None
            else:
                seen_external.add(ext_key)

        if canonical_hash is not None:
            hash_key = (budget_id, canonical_hash)
            if hash_key in seen_hashes:
                canonical_hash = None
            else:
                seen_hashes.add(hash_key)

        inserts.append(
            {
                "budget_id": budget_id,
                "transaction_id": tx_id,
                "receipt_scan_id": receipt_scan_id,
                "connection_id": None,
                "source_type": source_type,
                "provider": provider,
                "external_id": external_id,
                "canonical_hash": canonical_hash,
                "adapter_version": adapter_version,
                "acquired_at": _parse_dt(acquired_at, now_utc),
                "quality": quality,
                "raw_payload_policy": raw_payload_policy,
            }
        )

    if inserts:
        op.bulk_insert(source_table, inserts)


def downgrade() -> None:
    """Drop source_record table/indexes and processed_via column."""
    op.drop_index("uq_source_record_budget_canonical_hash", table_name="source_record")
    op.drop_index("uq_source_record_budget_provider_external_id", table_name="source_record")

    with op.batch_alter_table("source_record", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_source_record_transaction_id"))
        batch_op.drop_index(batch_op.f("ix_source_record_source_type"))
        batch_op.drop_index(batch_op.f("ix_source_record_receipt_scan_id"))
        batch_op.drop_index(batch_op.f("ix_source_record_provider"))
        batch_op.drop_index(batch_op.f("ix_source_record_connection_id"))
        batch_op.drop_index(batch_op.f("ix_source_record_budget_id"))

    op.drop_table("source_record")

    with op.batch_alter_table("receiptscan", schema=None) as batch_op:
        batch_op.drop_column("processed_via")
