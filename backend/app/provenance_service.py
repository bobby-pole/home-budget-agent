"""Source provenance tracking and idempotent ingestion helpers (Issue #193)."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, delete, select

from app.models import RawPayloadPolicy, ReceiptScan, SourceRecord, SourceType
from app.money import quantize_score

DEFAULT_QUALITY_BY_SOURCE: dict[SourceType, str] = {
    SourceType.MERCHANT_API: "1.00",
    SourceType.E_RECEIPT: "1.00",
    SourceType.BANK_CSV: "0.95",
    SourceType.OCR_PHOTO: "0.85",
    SourceType.MANUAL: "1.00",
}


def normalize_external_id(value: Optional[str]) -> Optional[str]:
    """Normalize an external source identifier; treat blank strings as None."""
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned if cleaned else None


def normalize_hash(value: Optional[str]) -> Optional[str]:
    """Normalize a canonical hash string; treat blank strings as None."""
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned if cleaned else None


def compute_canonical_hash(payload: bytes | str | dict[str, Any]) -> str:
    """Compute a deterministic SHA-256 hex digest for raw bytes, text, or canonical dict."""
    if isinstance(payload, bytes):
        raw_bytes = payload
    elif isinstance(payload, str):
        raw_bytes = payload.encode("utf-8")
    else:
        serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        raw_bytes = serialized.encode("utf-8")
    return hashlib.sha256(raw_bytes).hexdigest()


def extract_eparagon_external_id(file_bytes: bytes) -> Optional[str]:
    """Extract an explicit e-Paragon document ID when present; never fabricate one."""
    import base64

    try:
        raw_data = json.loads(file_bytes.decode("utf-8"))
    except Exception:
        return None

    data: Any = raw_data
    if isinstance(raw_data, dict) and isinstance(raw_data.get("data"), str):
        parts = raw_data["data"].split(".")
        if len(parts) >= 2:
            try:
                seg = parts[1]
                rem = len(seg) % 4
                if rem:
                    seg += "=" * (4 - rem)
                data = json.loads(base64.urlsafe_b64decode(seg).decode("utf-8"))
            except Exception:
                data = raw_data

    if not isinstance(data, dict):
        return None

    doc = data.get("dokument") or data.get("document") or data
    if isinstance(doc, dict) and ("dokument" in doc or "document" in doc):
        doc = doc.get("dokument") or doc.get("document")
    if not isinstance(doc, dict):
        return None

    paragon_raw = doc.get("paragon")
    header_raw = doc.get("naglowek")
    podmiot_raw = doc.get("podmiot1")
    paragon = paragon_raw if isinstance(paragon_raw, dict) else {}
    header = header_raw if isinstance(header_raw, dict) else {}
    podmiot = podmiot_raw if isinstance(podmiot_raw, dict) else {}

    explicit_id = normalize_external_id(
        doc.get("documentId") or paragon.get("nrDok") or header.get("id")
    )
    if not explicit_id:
        return None
    nip = normalize_external_id(podmiot.get("NIP"))
    return f"{nip}:{explicit_id}" if nip else explicit_id


def find_existing_source_record(
    session: Session,
    *,
    budget_id: int,
    provider: Optional[str] = None,
    external_id: Optional[str] = None,
    canonical_hash: Optional[str] = None,
) -> Optional[SourceRecord]:
    """Look up an existing SourceRecord by durable (budget, provider, external_id) or (budget, canonical_hash)."""
    ext_clean = normalize_external_id(external_id)
    if ext_clean and provider:
        existing = session.exec(
            select(SourceRecord).where(
                col(SourceRecord.budget_id) == budget_id,
                col(SourceRecord.provider) == provider,
                col(SourceRecord.external_id) == ext_clean,
            )
        ).first()
        if existing is not None:
            return existing

    hash_clean = normalize_hash(canonical_hash)
    if hash_clean:
        existing = session.exec(
            select(SourceRecord).where(
                col(SourceRecord.budget_id) == budget_id,
                col(SourceRecord.canonical_hash) == hash_clean,
            )
        ).first()
        if existing is not None:
            return existing

    return None


def build_source_record(
    *,
    budget_id: int,
    transaction_id: Optional[int],
    receipt_scan_id: Optional[int] = None,
    connection_id: Optional[int] = None,
    source_type: SourceType,
    provider: str,
    external_id: Optional[str] = None,
    canonical_hash: Optional[str] = None,
    adapter_version: str = "1.0",
    acquired_at: Optional[datetime] = None,
    quality: Optional[Any] = None,
    raw_payload_policy: RawPayloadPolicy = RawPayloadPolicy.NONE,
) -> SourceRecord:
    """Construct a validated SourceRecord instance with quantized quality and aware timestamp."""
    score_input = quality if quality is not None else DEFAULT_QUALITY_BY_SOURCE[source_type]
    return SourceRecord(
        budget_id=budget_id,
        transaction_id=transaction_id,
        receipt_scan_id=receipt_scan_id,
        connection_id=connection_id,
        source_type=source_type,
        provider=provider.strip() or source_type.value.lower(),
        external_id=normalize_external_id(external_id),
        canonical_hash=normalize_hash(canonical_hash),
        adapter_version=adapter_version,
        acquired_at=acquired_at or datetime.now(timezone.utc),
        quality=quantize_score(score_input),
        raw_payload_policy=raw_payload_policy,
    )


def record_source_provenance(
    session: Session,
    *,
    budget_id: int,
    transaction_id: Optional[int],
    receipt_scan_id: Optional[int] = None,
    connection_id: Optional[int] = None,
    source_type: SourceType,
    provider: str,
    external_id: Optional[str] = None,
    canonical_hash: Optional[str] = None,
    adapter_version: str = "1.0",
    acquired_at: Optional[datetime] = None,
    quality: Optional[Any] = None,
    raw_payload_policy: RawPayloadPolicy = RawPayloadPolicy.NONE,
) -> tuple[SourceRecord, bool]:
    """Idempotently persist a SourceRecord inside a savepoint.

    Returns (record, created_new). Recovers cleanly from concurrent unique constraint races.
    """
    ext_clean = normalize_external_id(external_id)
    hash_clean = normalize_hash(canonical_hash)

    existing = find_existing_source_record(
        session,
        budget_id=budget_id,
        provider=provider,
        external_id=ext_clean,
        canonical_hash=hash_clean,
    )
    if existing is not None:
        return existing, False

    candidate = build_source_record(
        budget_id=budget_id,
        transaction_id=transaction_id,
        receipt_scan_id=receipt_scan_id,
        connection_id=connection_id,
        source_type=source_type,
        provider=provider,
        external_id=ext_clean,
        canonical_hash=hash_clean,
        adapter_version=adapter_version,
        acquired_at=acquired_at,
        quality=quality,
        raw_payload_policy=raw_payload_policy,
    )
    try:
        with session.begin_nested():
            session.add(candidate)
            session.flush()
        return candidate, True
    except IntegrityError:
        existing_after_race = find_existing_source_record(
            session,
            budget_id=budget_id,
            provider=provider,
            external_id=ext_clean,
            canonical_hash=hash_clean,
        )
        if existing_after_race is not None:
            return existing_after_race, False
        raise


def record_manual_source_provenance(
    session: Session,
    *,
    budget_id: int,
    transaction_id: int,
    provider: str = "manual",
    adapter_version: str = "manual_v1",
    acquired_at: Optional[datetime] = None,
) -> tuple[SourceRecord, bool]:
    """Persist a MANUAL SourceRecord provenance anchor for manual or system transactions."""
    return record_source_provenance(
        session,
        budget_id=budget_id,
        transaction_id=transaction_id,
        source_type=SourceType.MANUAL,
        provider=provider,
        external_id=None,
        canonical_hash=None,
        adapter_version=adapter_version,
        acquired_at=acquired_at,
        quality="1.00",
        raw_payload_policy=RawPayloadPolicy.NONE,
    )


def update_scan_source_metadata(
    session: Session,
    *,
    receipt_scan_id: int,
    quality: Optional[Any] = None,
    raw_payload_policy: Optional[RawPayloadPolicy] = None,
) -> None:
    """Update quality or retention policy on SourceRecord(s) linked to a ReceiptScan."""
    records = session.exec(
        select(SourceRecord).where(col(SourceRecord.receipt_scan_id) == receipt_scan_id)
    ).all()
    for record in records:
        if quality is not None:
            record.quality = quantize_score(quality)
        if raw_payload_policy is not None:
            record.raw_payload_policy = raw_payload_policy
        session.add(record)


def delete_source_records_for_transaction(session: Session, transaction_id: int) -> None:
    """Explicitly remove SourceRecord rows linked to a transaction (SQLite FK-off safe)."""
    session.exec(
        delete(SourceRecord).where(col(SourceRecord.transaction_id) == transaction_id)
    )


def has_legacy_scan_duplicate(
    session: Session, *, budget_id: int, content_hash: str
) -> Optional[ReceiptScan]:
    """Fallback duplicate check against ReceiptScan.content_hash for un-backfilled rows."""
    from app.models import Transaction

    return session.exec(
        select(ReceiptScan).where(
            col(ReceiptScan.content_hash) == content_hash,
            col(ReceiptScan.transaction_id).in_(
                select(Transaction.id).where(col(Transaction.budget_id) == budget_id)
            ),
        )
    ).first()
