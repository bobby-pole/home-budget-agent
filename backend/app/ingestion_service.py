"""Shared canonical ingestion and commit service (#259).

Provides provider-agnostic persistence paths for both dual adapter families:
- ``ingest_receipt_result`` / ``apply_receipt_result_to_existing_scan`` for ``ReceiptAdapterResult``
- ``ingest_transaction_batch`` for ``TransactionBatchAdapterResult``

Adding a new ``ReceiptSourceAdapter`` or ``TransactionSourceAdapter`` requires zero
provider-specific transaction commit code.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Callable, Optional, Sequence
import uuid

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, desc, select

from app.adapters.contracts import (
    ReceiptAdapterResult,
    TransactionAdapterResult,
    TransactionBatchAdapterResult,
)
from app.category_service import get_budget_categories
from app.inbox_service import (
    promote_transaction_to_approved,
    suggest_account_for_budget,
)
from app.models import (
    AutoMergePolicy,
    BankCsvPreviewResponse,
    BankCsvPreviewRow,
    Category,
    ReceiptScan,
    ReconciliationLink,
    ReconciliationMatchKind,
    ReconciliationStatus,
    ReviewStatus,
    ScanStatus,
    SourceRecord,
    Transaction,
    TransactionLine,
    TransactionStatus,
    ensure_tz_aware,
)
from app.money import quantize_money, quantize_quantity, quantize_unit_price
from app.reconciliation_service import (
    apply_auto_merge_for_transaction,
    discover_reconciliation_candidates,
)
from app.provenance_service import (
    build_source_record,
    find_existing_source_record,
    has_legacy_scan_duplicate,
    update_scan_source_metadata,
)


@dataclass(frozen=True)
class ReceiptIngestionOutcome:
    """Result of committing a ``ReceiptAdapterResult`` into the database."""

    imported: bool
    skipped: bool
    transaction_id: Optional[int] = None
    receipt_scan_id: Optional[int] = None
    source_record_id: Optional[int] = None
    auto_approved: bool = False
    auto_merged: bool = False
    pending_inbox: bool = False


def _has_pending_duplicate_for_tx(session: Session, *, budget_id: int, transaction_id: int) -> bool:
    pending_dup = session.exec(
        select(ReconciliationLink.id).where(
            ReconciliationLink.budget_id == budget_id,
            col(ReconciliationLink.match_kind) == ReconciliationMatchKind.RECEIPT_DUPLICATE.value,
            col(ReconciliationLink.status) == ReconciliationStatus.PENDING.value,
            (
                (col(ReconciliationLink.bank_transaction_id) == transaction_id)
                | (col(ReconciliationLink.target_transaction_id) == transaction_id)
            ),
        )
    ).first()
    return pending_dup is not None


def _persist_receipt_lines(
    session: Session,
    *,
    transaction_id: int,
    items: Sequence[dict[str, Any]],
    cat_name_to_id: dict[str, int],
) -> None:
    """Persist normalized receipt items into ``TransactionLine`` rows using Decimal arithmetic."""
    for item_raw in items:
        cat_name = str(item_raw.get("category") or "").strip().lower()
        cat_id = cat_name_to_id.get(cat_name) if cat_name else None
        orig = item_raw.get("original_price")
        fin = item_raw.get("final_price")
        raw_disc = quantize_money(item_raw.get("discount_total", Decimal("0.00")))
        discount_val = -abs(raw_disc) if raw_disc != Decimal("0.00") else Decimal("0.00")
        session.add(
            TransactionLine(
                name=str(item_raw.get("name") or "Unknown item"),
                price=quantize_unit_price(item_raw.get("price", Decimal("0.00"))),
                quantity=quantize_quantity(item_raw.get("quantity", Decimal("1"))),
                category_id=cat_id,
                category_source=item_raw.get("category_source"),
                transaction_id=transaction_id,
                original_price=quantize_unit_price(orig) if orig is not None else None,
                discount_total=discount_val,
                final_price=quantize_unit_price(fin) if fin is not None else None,
                is_adjustment=bool(item_raw.get("is_adjustment", False)),
            )
        )


def _categorize_receipt_dict_best_effort(
    session: Session,
    *,
    receipt_dict: dict[str, Any],
    budget_id: int,
    user_id: int,
    categorize: bool,
) -> tuple[dict[str, Any], dict[str, int]]:
    """Load budget categories and run cache-first AI categorization if requested."""
    db_categories = get_budget_categories(session, budget_id)
    cat_dicts = [{"id": c.id, "name": c.name} for c in db_categories if c.id is not None]
    cat_name_to_id = {c.name.lower(): c.id for c in db_categories if c.id is not None}

    if categorize and cat_dicts and receipt_dict.get("items"):
        try:
            from app.services import AIService

            categorized = AIService._categorize_parsed_items(receipt_dict, cat_dicts, user_id)
            if categorized:
                return categorized, cat_name_to_id
        except Exception:
            pass

    return receipt_dict, cat_name_to_id


def _parse_receipt_date_utc(
    date_str: str,
    *,
    purchase_timestamp: Optional[str] = None,
) -> datetime:
    if isinstance(purchase_timestamp, str) and purchase_timestamp.strip():
        try:
            dt = datetime.fromisoformat(purchase_timestamp.strip().replace("Z", "+00:00"))
            if dt.tzinfo is None:
                return dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except ValueError:
            pass
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return datetime.now(timezone.utc)


def ingest_receipt_result(
    session: Session,
    result: ReceiptAdapterResult,
    *,
    budget_id: int,
    user_id: int,
    note: Optional[str] = None,
    categorize: bool = True,
    commit: bool = True,
    account_id: Optional[int] = None,
    auto_merge_policy: str = AutoMergePolicy.AUTO.value,
    auto_approve_clean: bool = True,
    import_batch_id: Optional[str] = None,
) -> ReceiptIngestionOutcome:
    """Commit any ``ReceiptAdapterResult`` idempotently via a single shared persistence path."""
    prov = result.provenance
    existing_source = find_existing_source_record(
        session,
        budget_id=budget_id,
        provider=prov.provider,
        external_id=prov.external_id,
        canonical_hash=prov.canonical_hash,
    )
    if existing_source is not None:
        return ReceiptIngestionOutcome(
            imported=False,
            skipped=True,
            transaction_id=existing_source.transaction_id,
            receipt_scan_id=existing_source.receipt_scan_id,
            source_record_id=existing_source.id,
        )

    if prov.canonical_hash:
        legacy_scan = has_legacy_scan_duplicate(
            session,
            budget_id=budget_id,
            content_hash=prov.canonical_hash,
        )
        if legacy_scan is not None:
            return ReceiptIngestionOutcome(
                imported=False,
                skipped=True,
                transaction_id=legacy_scan.transaction_id,
                receipt_scan_id=legacy_scan.id,
            )

    canonical = result.receipt
    receipt_dict, cat_name_to_id = _categorize_receipt_dict_best_effort(
        session,
        receipt_dict=canonical.to_dict(),
        budget_id=budget_id,
        user_id=user_id,
        categorize=categorize,
    )

    raw_purchase_ts = canonical.get("purchase_timestamp")
    tx_date = _parse_receipt_date_utc(
        canonical.date,
        purchase_timestamp=raw_purchase_ts if isinstance(raw_purchase_ts, str) else None,
    )
    items = receipt_dict.get("items") or []
    if not items and result.validation_status == "failed":
        scan_status = ScanStatus.FAILED.value
        needs_review = True
    elif result.validation_status != "verified":
        scan_status = ScanStatus.NEEDS_REVIEW.value
        needs_review = True
    else:
        scan_status = ScanStatus.CATEGORIZATION_OK.value
        needs_review = False

    resolved_note = note
    if resolved_note is None and prov.external_id:
        resolved_note = f"{prov.provider} #{prov.external_id}"

    try:
        with session.begin_nested():
            tx = Transaction(
                merchant_name=canonical.merchant_name,
                total_amount=canonical.total_amount,
                currency=canonical.currency,
                date=tx_date,
                is_manual=False,
                type="expense",
                account_id=account_id,
                uploaded_by=user_id,
                budget_id=budget_id,
                import_hash=prov.canonical_hash,
                note=resolved_note,
                review_status=ReviewStatus.PENDING,
                import_batch_id=import_batch_id,
            )
            session.add(tx)
            session.flush()
            assert tx.id is not None

            scan = ReceiptScan(
                transaction_id=tx.id,
                image_path=None,
                status=scan_status,
                processed_via=result.processed_via or prov.adapter_version,
                content_hash=prov.canonical_hash,
                raw_ocr_text=result.raw_ocr_text,
                reconstructed_lines=result.reconstructed_lines,
                needs_review=needs_review,
                validation_message=result.validation_message,
            )
            session.add(scan)
            session.flush()

            _persist_receipt_lines(
                session,
                transaction_id=tx.id,
                items=items,
                cat_name_to_id=cat_name_to_id,
            )

            sr = build_source_record(
                budget_id=budget_id,
                transaction_id=tx.id,
                receipt_scan_id=scan.id,
                connection_id=prov.connection_id,
                source_type=prov.source_type,
                provider=prov.provider,
                external_id=prov.external_id,
                canonical_hash=prov.canonical_hash,
                adapter_version=prov.adapter_version,
                acquired_at=prov.acquired_at,
                quality=result.quality,
                raw_payload_policy=prov.raw_payload_policy,
            )
            session.add(sr)
            session.flush()
    except IntegrityError:
        raced = find_existing_source_record(
            session,
            budget_id=budget_id,
            provider=prov.provider,
            external_id=prov.external_id,
            canonical_hash=prov.canonical_hash,
        )
        if raced is not None:
            return ReceiptIngestionOutcome(
                imported=False,
                skipped=True,
                transaction_id=raced.transaction_id,
                receipt_scan_id=raced.receipt_scan_id,
                source_record_id=raced.id,
            )
        raise

    assert tx.id is not None
    discover_reconciliation_candidates(session, budget_id=budget_id, commit=False)

    auto_merged = False
    auto_approved = False
    pending_inbox = False

    if auto_merge_policy == AutoMergePolicy.AUTO.value:
        merged_link = apply_auto_merge_for_transaction(
            session,
            budget_id=budget_id,
            transaction_id=tx.id,
            user_id=user_id,
            commit=False,
        )
        if merged_link is not None:
            auto_merged = True

    session.refresh(tx)
    if tx.date is not None:
        tx.date = ensure_tz_aware(tx.date) or tx.date
    if tx.reconciled_into_id is not None:
        scan.status = ScanStatus.DONE
        scan.needs_review = False
        session.add(scan)
    else:
        has_pending_dup = _has_pending_duplicate_for_tx(session, budget_id=budget_id, transaction_id=tx.id)
        is_clean = (
            result.validation_status == "verified"
            and bool(items)
            and tx.account_id is not None
            and not has_pending_dup
            and auto_approve_clean
        )
        if is_clean:
            promote_transaction_to_approved(
                session,
                transaction=tx,
                scan=scan,
                finalize_scan=True,
                commit=False,
            )
            auto_approved = True
        else:
            pending_inbox = True
            if has_pending_dup:
                scan.status = ScanStatus.NEEDS_REVIEW
                scan.needs_review = True
                if not scan.validation_message:
                    scan.validation_message = "DUPLICATE_REVIEW_REQUIRED"
            session.add(scan)

    if commit:
        session.commit()
    else:
        session.flush()

    return ReceiptIngestionOutcome(
        imported=True,
        skipped=False,
        transaction_id=tx.id,
        receipt_scan_id=scan.id,
        source_record_id=sr.id,
        auto_approved=auto_approved,
        auto_merged=auto_merged,
        pending_inbox=pending_inbox,
    )


def apply_receipt_result_to_existing_scan(
    session: Session,
    *,
    scan: ReceiptScan,
    transaction: Transaction,
    result: ReceiptAdapterResult,
    db_categories: Sequence[Category],
    is_demo_uploader: bool = False,
    auto_merge_policy: str = AutoMergePolicy.AUTO.value,
    auto_approve_clean: bool = True,
) -> ScanStatus:
    """Apply a ``ReceiptAdapterResult`` to an existing background-processed scan/transaction."""
    receipt = result.receipt
    receipt_dict = receipt.to_dict()
    items = receipt_dict.get("items") or []

    scan.status = ScanStatus.PARSING_OK
    scan.processed_via = result.processed_via or result.provenance.adapter_version
    scan.raw_ocr_text = result.raw_ocr_text
    scan.reconstructed_lines = result.reconstructed_lines

    transaction.merchant_name = receipt.merchant_name
    transaction.total_amount = receipt.total_amount
    transaction.currency = receipt.currency

    assert scan.id is not None

    if not items and result.validation_status == "failed":
        scan.status = ScanStatus.FAILED
        scan.needs_review = True
        scan.validation_message = result.validation_message or "RECEIPT_EMPTY"
        transaction.review_status = ReviewStatus.PENDING
        update_scan_source_metadata(session, receipt_scan_id=scan.id, quality=Decimal("0.0000"))
        session.add(scan)
        session.add(transaction)
        session.commit()
        return ScanStatus.FAILED

    requires_review = result.validation_status != "verified"
    if requires_review:
        scan.status = ScanStatus.NEEDS_REVIEW
        scan.needs_review = True
        scan.validation_message = result.validation_message
    else:
        scan.status = ScanStatus.CATEGORIZATION_OK
        scan.needs_review = False
        scan.validation_message = None

    if receipt.date:
        try:
            parsed_dt = datetime.strptime(receipt.date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            now_utc = datetime.now(timezone.utc)
            if is_demo_uploader and (parsed_dt.year != now_utc.year or parsed_dt.month != now_utc.month):
                transaction.date = now_utc
                scan.original_date = receipt.date
            else:
                transaction.date = parsed_dt
        except (ValueError, TypeError):
            pass

    cat_name_to_id = {c.name.lower(): c.id for c in db_categories if c.id is not None}
    assert transaction.id is not None
    _persist_receipt_lines(
        session,
        transaction_id=transaction.id,
        items=items,
        cat_name_to_id=cat_name_to_id,
    )

    update_scan_source_metadata(
        session,
        receipt_scan_id=scan.id,
        quality=result.quality,
    )
    session.add(transaction)
    session.add(scan)
    session.flush()

    if transaction.budget_id is not None:
        discover_reconciliation_candidates(session, budget_id=transaction.budget_id, commit=False)
        if auto_merge_policy == AutoMergePolicy.AUTO.value and transaction.uploaded_by is not None:
            apply_auto_merge_for_transaction(
                session,
                budget_id=transaction.budget_id,
                transaction_id=transaction.id,
                user_id=transaction.uploaded_by,
                commit=False,
            )
            session.refresh(transaction)
        if transaction.date is not None:
            transaction.date = ensure_tz_aware(transaction.date) or transaction.date

        if transaction.reconciled_into_id is not None:
            scan.status = ScanStatus.DONE
            scan.needs_review = False
            session.add(scan)
        else:
            has_pending_dup = _has_pending_duplicate_for_tx(
                session, budget_id=transaction.budget_id, transaction_id=transaction.id
            )
            is_clean = (
                result.validation_status == "verified"
                and bool(items)
                and transaction.account_id is not None
                and not has_pending_dup
                and auto_approve_clean
            )
            if is_clean:
                promote_transaction_to_approved(
                    session,
                    transaction=transaction,
                    scan=scan,
                    finalize_scan=True,
                    commit=False,
                )
            else:
                transaction.review_status = ReviewStatus.PENDING
                if has_pending_dup:
                    scan.status = ScanStatus.NEEDS_REVIEW
                    scan.needs_review = True
                    if not scan.validation_message:
                        scan.validation_message = "DUPLICATE_REVIEW_REQUIRED"
                session.add(transaction)
                session.add(scan)

    session.commit()
    return scan.status


def _detect_tx_type_default(item: TransactionAdapterResult) -> str:
    if item.transaction.tx_type_hint:
        return item.transaction.tx_type_hint
    return "expense" if item.transaction.amount < Decimal("0") else "income"


def _classify_batch_duplicates(
    session: Session,
    batch: TransactionBatchAdapterResult,
    *,
    budget_id: int,
) -> tuple[list[tuple[TransactionAdapterResult, bool]], int]:
    """Classify each batch item against existing hashes and external IDs without mutating DB."""
    if not batch.items:
        return [], 0

    hashes_to_check = [
        item.provenance.canonical_hash
        for item in batch.items
        if item.provenance.canonical_hash
    ]
    ext_pairs_to_check = {
        (item.provenance.provider, item.provenance.external_id)
        for item in batch.items
        if item.provenance.external_id
    }

    existing_legacy_hashes: set[str] = set()
    existing_source_hashes: set[str] = set()
    existing_external_keys: set[tuple[str, str]] = set()
    if hashes_to_check:
        existing_legacy_hashes = {
            h
            for h in session.exec(
                select(Transaction.import_hash).where(
                    Transaction.budget_id == budget_id,
                    col(Transaction.import_hash).in_(hashes_to_check),
                )
            ).all()
            if h
        }
        existing_source_hashes = {
            h
            for h in session.exec(
                select(SourceRecord.canonical_hash).where(
                    SourceRecord.budget_id == budget_id,
                    col(SourceRecord.canonical_hash).in_(hashes_to_check),
                )
            ).all()
            if h
        }
    if ext_pairs_to_check:
        ext_ids = [ext_id for _, ext_id in ext_pairs_to_check]
        ext_rows = session.exec(
            select(SourceRecord.provider, SourceRecord.external_id).where(
                SourceRecord.budget_id == budget_id,
                col(SourceRecord.external_id).in_(ext_ids),
            )
        ).all()
        existing_external_keys = {
            (provider, ext_id)
            for provider, ext_id in ext_rows
            if ext_id is not None and (provider, ext_id) in ext_pairs_to_check
        }

    seen_hashes = existing_legacy_hashes | existing_source_hashes
    seen_external_keys = set(existing_external_keys)
    classified: list[tuple[TransactionAdapterResult, bool]] = []
    skipped_count = 0

    for item in batch.items:
        row_hash = item.provenance.canonical_hash
        ext_id = item.provenance.external_id
        ext_key = (item.provenance.provider, ext_id) if ext_id else None
        is_dup = bool(
            (row_hash and row_hash in seen_hashes)
            or (ext_key and ext_key in seen_external_keys)
        )
        if is_dup:
            skipped_count += 1
        else:
            if row_hash:
                seen_hashes.add(row_hash)
            if ext_key:
                seen_external_keys.add(ext_key)
        classified.append((item, is_dup))

    return classified, skipped_count


def preview_transaction_batch(
    session: Session,
    batch: TransactionBatchAdapterResult,
    *,
    budget_id: int,
    filename: str = "",
    tx_type_classifier: Optional[Callable[[TransactionAdapterResult], str]] = None,
) -> BankCsvPreviewResponse:
    """Dry-run preview of a parsed CSV/PDF statement before committing transactions."""
    classified, dup_count = _classify_batch_duplicates(session, batch, budget_id=budget_id)
    suggested_acc = suggest_account_for_budget(session, budget_id=budget_id)

    rows: list[BankCsvPreviewRow] = []
    for item, is_dup in classified:
        tx_data = item.transaction
        t_type = (
            tx_type_classifier(item)
            if tx_type_classifier is not None
            else _detect_tx_type_default(item)
        )
        rows.append(
            BankCsvPreviewRow(
                date=tx_data.booked_at,
                merchant_name=tx_data.counterparty or tx_data.title or "Bank Transaction",
                title=tx_data.title or "",
                amount=quantize_money(tx_data.abs_amount),
                currency=tx_data.currency,
                detected_type=t_type,
                is_duplicate=is_dup,
            )
        )

    total_rows = len(classified)
    new_count = total_rows - dup_count
    return BankCsvPreviewResponse(
        filename=filename,
        total_rows=total_rows,
        new_count=new_count,
        duplicate_count=dup_count,
        suggested_account_id=suggested_acc,
        warnings=list(batch.warnings or []),
        rows=rows,
    )


def ingest_transaction_batch(
    session: Session,
    batch: TransactionBatchAdapterResult,
    *,
    budget_id: int,
    user_id: int,
    filename: str = "",
    enable_ai_categorization: bool = False,
    tx_type_classifier: Optional[Callable[[TransactionAdapterResult], str]] = None,
    account_id: Optional[int] = None,
    auto_merge_policy: str = AutoMergePolicy.MANUAL.value,
    auto_approve_clean: bool = True,
    require_account: bool = False,
    import_batch_id: Optional[str] = None,
) -> dict[str, Any]:
    """Persist any ``TransactionBatchAdapterResult`` with staging, idempotent dedup, and reconciliation."""
    if not batch.items:
        return {"created": 0, "skipped": 0, "failed": 0, "summary": "No transactions found in file."}

    classified, skipped_count = _classify_batch_duplicates(session, batch, budget_id=budget_id)
    final_items = [item for item, is_dup in classified if not is_dup]

    if not final_items:
        discover_reconciliation_candidates(session, budget_id=budget_id, commit=True)
        return {
            "created": 0,
            "skipped": skipped_count,
            "failed": 0,
            "approved_count": 0,
            "pending_count": 0,
            "auto_merged_count": 0,
            "summary": f"All {len(batch.items)} transactions already imported.",
        }

    batch_uid = import_batch_id or uuid.uuid4().hex[:16]
    db_categories = get_budget_categories(session, budget_id)
    cat_dicts = [{"id": c.id, "name": c.name} for c in db_categories]
    cat_name_to_id = {c.name.lower(): c.id for c in db_categories}
    id_to_cat_name = {c.id: c.name for c in db_categories}

    ai_mapping: dict[str, str] = {}
    if enable_ai_categorization:
        from app.services import AIService

        unique_descriptions = list(
            {
                f"{item.transaction.counterparty} {item.transaction.title}".strip()
                for item in final_items
            }
        )
        history_stmt = (
            select(Transaction.merchant_name, Transaction.category_id)
            .where(Transaction.budget_id == budget_id, col(Transaction.category_id).is_not(None))
            .order_by(desc(Transaction.date))
            .limit(500)
        )
        history = session.exec(history_stmt).all()
        local_mapping = {
            h[0].lower(): id_to_cat_name.get(h[1])
            for h in history
            if h[0] and h[1] in id_to_cat_name
        }

        descriptions_to_query: list[str] = []
        for desc_text in unique_descriptions:
            cached_cat = local_mapping.get(desc_text.lower())
            if cached_cat:
                ai_mapping[desc_text] = cached_cat
            else:
                descriptions_to_query.append(desc_text)

        if descriptions_to_query:
            for i in range(0, len(descriptions_to_query), 50):
                chunk = descriptions_to_query[i : i + 50]
                ai_mapping.update(AIService.categorize_descriptions(chunk, categories=cat_dicts))

    created_txs: list[Transaction] = []
    for item in final_items:
        tx_data = item.transaction
        prov = item.provenance
        desc_key = f"{tx_data.counterparty} {tx_data.title}".strip()

        if enable_ai_categorization:
            cat_name = ai_mapping.get(desc_key, tx_data.category_hint or "Other")
            cat_id = cat_name_to_id.get(cat_name.lower())
        elif tx_data.category_hint:
            cat_id = cat_name_to_id.get(tx_data.category_hint.lower())
        else:
            cat_id = None

        t_type = (
            tx_type_classifier(item)
            if tx_type_classifier is not None
            else _detect_tx_type_default(item)
        )
        t_date = tx_data.booked_at
        t_amount = quantize_money(tx_data.abs_amount)

        try:
            with session.begin_nested():
                target_tx = Transaction(
                    merchant_name=tx_data.counterparty or tx_data.title or "Bank Transaction",
                    total_amount=t_amount,
                    currency=tx_data.currency,
                    date=t_date,
                    is_manual=False,
                    type=t_type,
                    status=TransactionStatus.CLEARED,
                    account_id=account_id,
                    uploaded_by=user_id,
                    budget_id=budget_id,
                    category_id=cat_id,
                    note=tx_data.title,
                    import_hash=prov.canonical_hash,
                    review_status=ReviewStatus.PENDING,
                    import_batch_id=batch_uid,
                )
                session.add(target_tx)
                session.flush()

                if target_tx.id is not None:
                    session.add(
                        build_source_record(
                            budget_id=budget_id,
                            transaction_id=target_tx.id,
                            connection_id=prov.connection_id,
                            source_type=prov.source_type,
                            provider=prov.provider,
                            external_id=prov.external_id,
                            canonical_hash=prov.canonical_hash,
                            adapter_version=prov.adapter_version,
                            acquired_at=prov.acquired_at,
                            quality=item.quality,
                            raw_payload_policy=prov.raw_payload_policy,
                        )
                    )
                    session.flush()
        except IntegrityError:
            raced = find_existing_source_record(
                session,
                budget_id=budget_id,
                provider=prov.provider,
                external_id=prov.external_id,
                canonical_hash=prov.canonical_hash,
            )
            if raced is not None:
                skipped_count += 1
                continue
            raise

        created_txs.append(target_tx)

    session.flush()
    discover_reconciliation_candidates(session, budget_id=budget_id, commit=False)

    auto_merged_count = 0
    approved_count = 0
    pending_count = 0

    if auto_merge_policy == AutoMergePolicy.AUTO.value:
        for tx in created_txs:
            if tx.id is None:
                continue
            merged_link = apply_auto_merge_for_transaction(
                session,
                budget_id=budget_id,
                transaction_id=tx.id,
                user_id=user_id,
                include_bank_exact=True,
                commit=False,
            )
            if merged_link is not None:
                auto_merged_count += 1

    for tx in created_txs:
        session.refresh(tx)
        if tx.date is not None:
            tx.date = ensure_tz_aware(tx.date) or tx.date
        if tx.reconciled_into_id is not None:
            continue
        is_clean = (
            tx.total_amount > Decimal("0.00")
            and (tx.account_id is not None or not require_account)
            and auto_approve_clean
        )
        if is_clean:
            tx.review_status = ReviewStatus.APPROVED
            session.add(tx)
            approved_count += 1
        else:
            pending_count += 1

    session.flush()
    if account_id is not None and approved_count > 0:
        from app.models import recalculate_account_balance

        recalculate_account_balance(session.connection(), account_id)

    session.commit()
    discover_reconciliation_candidates(session, budget_id=budget_id, commit=True)
    return {
        "created": len(created_txs),
        "skipped": skipped_count,
        "failed": 0,
        "approved_count": approved_count,
        "pending_count": pending_count,
        "auto_merged_count": auto_merged_count,
        "import_batch_id": batch_uid,
        "summary": {
            "code": "CSV_IMPORT_COMPLETE",
            "imported": len(created_txs),
            "skipped": skipped_count,
            "approved": approved_count,
            "pending": pending_count,
            "auto_merged": auto_merged_count,
            "filename": filename,
        },
    }
