"""Hybrid Import Inbox lifecycle, exception approval, and provenance-preserving rejection (#163)."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Optional, Sequence

from sqlalchemy import and_, extract, or_
from sqlalchemy.orm import selectinload
from sqlmodel import Session, col, desc, func, select

from app.models import (
    Account,
    Budget,
    BudgetAlert,
    BudgetMember,
    Category,
    EnvelopeAllocation,
    InboxBulkActionResponse,
    ReceiptScan,
    ReceiptScanRead,
    ReconciliationLink,
    ReconciliationMatchKind,
    ReconciliationStatus,
    ReviewStatus,
    ScanStatus,
    SourceRecord,
    SourceRecordRead,
    TagRead,
    Transaction,
    TransactionLine,
    TransactionLineRead,
    TransactionRead,
    ensure_tz_aware,
    recalculate_account_balance,
)
from app.money import format_money, quantize_money
from app.reconciliation_service import (
    discover_reconciliation_candidates,
    unlink_reconciliation_link,
)

INBOX_SCAN_STATUSES: tuple[str, ...] = (
    ScanStatus.CATEGORIZATION_OK.value,
    ScanStatus.NEEDS_REVIEW.value,
    ScanStatus.FAILED.value,
    "needs_review",
    "error",
    "categorization_ok",
)

UNVERIFIED_SCAN_BLOCKERS: tuple[str, ...] = (
    ScanStatus.NEEDS_REVIEW.value,
    ScanStatus.FAILED.value,
    "needs_review",
    "error",
)


class InboxNotFoundError(Exception):
    """Raised when an inbox transaction or target account cannot be found in budget scope."""


class InboxValidationError(Exception):
    """Raised when an inbox action violates account, role, or validation invariants."""


def _enum_str(val: Any) -> str:
    return val.value if isinstance(val, Enum) else str(val)


def suggest_account_for_budget(
    session: Session,
    *,
    budget_id: int,
    connection_default_account_id: Optional[int] = None,
) -> Optional[int]:
    """Suggest the best default active account for imports and Inbox approvals.

    Order of precedence:
    1. Explicit connection default account (when active and belonging to ``budget_id``)
    2. Most recently used active on-budget checking/cash account in ``budget_id``
    3. First active on-budget checking/cash account
    4. First active on-budget account
    5. First active account in ``budget_id``
    """
    if connection_default_account_id is not None:
        conn_acc = session.get(Account, connection_default_account_id)
        if conn_acc and conn_acc.budget_id == budget_id and conn_acc.is_active:
            return conn_acc.id

    recent_account_id = session.exec(
        select(Transaction.account_id)
        .join(Account, col(Transaction.account_id) == col(Account.id))
        .where(
            Transaction.budget_id == budget_id,
            col(Transaction.account_id).is_not(None),
            col(Transaction.reconciled_into_id).is_(None),
            col(Transaction.review_status) == ReviewStatus.APPROVED.value,
            col(Account.is_active).is_(True),
            col(Account.is_on_budget).is_(True),
            col(Account.type).in_(("checking", "cash")),
        )
        .order_by(desc(Transaction.date), desc(Transaction.id))
    ).first()
    if recent_account_id is not None:
        return int(recent_account_id)

    on_budget_checking = session.exec(
        select(Account.id)
        .where(
            Account.budget_id == budget_id,
            col(Account.is_active).is_(True),
            col(Account.is_on_budget).is_(True),
            col(Account.type).in_(("checking", "cash")),
        )
        .order_by(col(Account.id))
    ).first()
    if on_budget_checking is not None:
        return int(on_budget_checking)

    on_budget_any = session.exec(
        select(Account.id)
        .where(
            Account.budget_id == budget_id,
            col(Account.is_active).is_(True),
            col(Account.is_on_budget).is_(True),
        )
        .order_by(col(Account.id))
    ).first()
    if on_budget_any is not None:
        return int(on_budget_any)

    any_active = session.exec(
        select(Account.id)
        .where(
            Account.budget_id == budget_id,
            col(Account.is_active).is_(True),
        )
        .order_by(col(Account.id))
    ).first()
    return int(any_active) if any_active is not None else None


def get_budget_first_month_date(session: Session, *, budget_id: int) -> date:
    """Return the first day of the month in which ``budget_id`` was created."""
    budget = session.get(Budget, budget_id)
    ref_dt = budget.created_at if budget and budget.created_at else datetime.now(timezone.utc)
    return date(ref_dt.year, ref_dt.month, 1)


def check_envelope_balance_and_alert(session: Session, transaction: Transaction) -> None:
    """Create household zeroed-envelope alerts when an approved expense exhausts an envelope."""
    if transaction.type != "expense" or not transaction.budget_id:
        return
    if _enum_str(transaction.review_status) != ReviewStatus.APPROVED.value:
        return
    if transaction.reconciled_into_id is not None:
        return

    category_amounts: dict[int, Decimal] = {}
    lines = session.exec(
        select(TransactionLine).where(TransactionLine.transaction_id == transaction.id)
    ).all()

    if lines:
        for line in lines:
            if line.category_id is not None:
                line_total = quantize_money(Decimal(str(line.price)) * Decimal(str(line.quantity)))
                category_amounts[line.category_id] = (
                    category_amounts.get(line.category_id, Decimal("0.00")) + line_total
                )
    elif transaction.category_id is not None:
        category_amounts[transaction.category_id] = quantize_money(transaction.total_amount)

    if not category_amounts:
        return

    raw_date = getattr(transaction, "date", None)
    if isinstance(raw_date, str):
        try:
            date_obj = datetime.fromisoformat(str(raw_date).replace("Z", "+00:00"))
        except ValueError:
            date_obj = datetime.now(timezone.utc)
    elif isinstance(raw_date, datetime):
        date_obj = raw_date
    else:
        date_obj = datetime.now(timezone.utc)

    year = date_obj.year
    month = date_obj.month

    for cat_id, amt in category_amounts.items():
        planned = session.exec(
            select(col(EnvelopeAllocation.amount)).where(
                EnvelopeAllocation.budget_id == transaction.budget_id,
                EnvelopeAllocation.category_id == cat_id,
                EnvelopeAllocation.year == year,
                EnvelopeAllocation.month == month,
            )
        ).first()
        planned_dec = quantize_money(planned) if planned is not None else Decimal("0.00")

        spent_no_lines = session.scalar(
            select(func.sum(Transaction.total_amount)).where(
                Transaction.budget_id == transaction.budget_id,
                Transaction.type == "expense",
                col(Transaction.reconciled_into_id).is_(None),
                col(Transaction.review_status) == ReviewStatus.APPROVED.value,
                extract("year", col(Transaction.date)) == year,
                extract("month", col(Transaction.date)) == month,
                col(Transaction.category_id) == cat_id,
                ~col(Transaction.id).in_(
                    select(TransactionLine.transaction_id).where(
                        col(TransactionLine.transaction_id).is_not(None)
                    )
                ),
            )
        ) or Decimal("0.00")

        spent_with_lines = session.scalar(
            select(func.sum(TransactionLine.price * TransactionLine.quantity))
            .join(Transaction, col(Transaction.id) == col(TransactionLine.transaction_id))
            .where(
                Transaction.budget_id == transaction.budget_id,
                Transaction.type == "expense",
                col(Transaction.reconciled_into_id).is_(None),
                col(Transaction.review_status) == ReviewStatus.APPROVED.value,
                extract("year", col(Transaction.date)) == year,
                extract("month", col(Transaction.date)) == month,
                col(TransactionLine.category_id) == cat_id,
            )
        ) or Decimal("0.00")

        spent_dec = quantize_money(spent_no_lines) + quantize_money(spent_with_lines)
        remaining = planned_dec - spent_dec
        delta_dec = quantize_money(amt)
        remaining_before = remaining + delta_dec

        if remaining_before > Decimal("0.00") and remaining <= Decimal("0.00"):
            category = session.get(Category, cat_id)
            cat_name = category.name if category else "Nieznana"
            other_members = session.exec(
                select(BudgetMember.user_id).where(
                    BudgetMember.budget_id == transaction.budget_id,
                    BudgetMember.user_id != transaction.uploaded_by,
                )
            ).all()
            for member_id in other_members:
                if member_id is None:
                    continue
                alert_msg = json.dumps(
                    {
                        "type": "zeroed_envelope",
                        "remaining": format_money(remaining),
                    }
                )
                session.add(
                    BudgetAlert(
                        budget_id=transaction.budget_id,
                        user_id=member_id,
                        category_name=cat_name,
                        message=alert_msg,
                    )
                )


def _recalculate_tx_accounts(session: Session, tx: Transaction) -> None:
    conn = session.connection()
    if tx.account_id is not None:
        recalculate_account_balance(conn, tx.account_id)
    if tx.transfer_id is not None:
        recalculate_account_balance(conn, tx.transfer_id)


def promote_transaction_to_approved(
    session: Session,
    *,
    transaction: Transaction,
    scan: Optional[ReceiptScan] = None,
    finalize_scan: bool = True,
    commit: bool = False,
) -> None:
    """Promote a staged transaction to APPROVED, update account balance, and run envelope alerts."""
    if transaction.date is not None:
        transaction.date = ensure_tz_aware(transaction.date) or transaction.date
    transaction.review_status = ReviewStatus.APPROVED
    transaction.rejected_at = None
    transaction.rejection_reason = None
    session.add(transaction)

    if finalize_scan and transaction.id is not None:
        target_scan = scan or session.exec(
            select(ReceiptScan).where(ReceiptScan.transaction_id == transaction.id)
        ).first()
        if target_scan is not None:
            target_scan.status = ScanStatus.DONE
            target_scan.needs_review = False
            target_scan.validation_message = None
            session.add(target_scan)

    session.flush()
    _recalculate_tx_accounts(session, transaction)
    check_envelope_balance_and_alert(session, transaction)

    if commit:
        session.commit()


_IN_PROGRESS_SCAN_STATUSES: tuple[str, ...] = (
    ScanStatus.QUEUED.value,
    ScanStatus.RUNNING.value,
    ScanStatus.OCR_OK.value,
    ScanStatus.PARSING_OK.value,
    "processing",
)

_TOTAL_ERROR_PREFIXES: tuple[str, ...] = (
    "RECEIPT_SUM_MISMATCH",
    "RECEIPT_EMPTY",
    "RECEIPT_ZERO_PRICE_ITEM",
    "RECEIPT_FUTURE_DATE",
    "VALIDATION_FAILED",
)

_RECEIPT_TOLERANCE = Decimal("0.01")


def _compute_lines_total_decimal(lines: Sequence[TransactionLine]) -> Decimal:
    """Compute the exact sum of transaction lines using Decimal arithmetic."""
    total = Decimal("0.00")
    for line in lines:
        qty = Decimal(str(line.quantity if line.quantity is not None else "1"))
        disc = Decimal(str(line.discount_total if line.discount_total is not None else "0.00"))
        if (
            not line.is_adjustment
            and line.original_price is not None
            and disc < Decimal("0.00")
        ):
            line_sum = Decimal(str(line.original_price)) * qty + disc
        else:
            line_sum = Decimal(str(line.price)) * qty
        total += line_sum
    return quantize_money(total)


def compute_canonical_total_valid(tx: Transaction) -> Optional[bool]:
    """Return canonical receipt total validation state using Decimal precision.

    Returns:
      - ``True`` only when a receipt scan finished validation without math errors,
        has at least one line, and ``|sum(lines) - total_amount| <= 0.01``.
      - ``False`` when receipt validation failed or line sum mismatches ``total_amount``.
      - ``None`` for non-receipt records or in-progress scans.
    """
    scan = tx.receipt_scan
    if scan is None:
        return None

    status_val = _enum_str(scan.status)
    if status_val in _IN_PROGRESS_SCAN_STATUSES:
        return None

    if status_val in (ScanStatus.FAILED.value, "error"):
        return False

    is_finalized = status_val in (ScanStatus.DONE.value, "done")
    msg = (scan.validation_message or "").strip()
    if not is_finalized and msg and msg.startswith(_TOTAL_ERROR_PREFIXES):
        return False

    lines = tx.lines or []
    if not lines:
        return False

    lines_sum = _compute_lines_total_decimal(lines)
    tx_total = quantize_money(tx.total_amount if tx.total_amount is not None else Decimal("0.00"))
    return abs(lines_sum - tx_total) <= _RECEIPT_TOLERANCE


def compute_review_reasons(
    tx: Transaction,
    *,
    canonical_total_valid: Optional[bool],
    has_pending_duplicate: bool = False,
) -> list[str]:
    """Build deterministic deduplicated review reason codes explaining why an item needs attention."""
    reasons: list[str] = []

    def _add(code: str) -> None:
        cleaned = code.strip()
        if cleaned and cleaned not in reasons:
            reasons.append(cleaned)

    scan = tx.receipt_scan
    scan_status = _enum_str(scan.status) if scan is not None else ""
    in_progress = bool(scan is not None and scan_status in _IN_PROGRESS_SCAN_STATUSES)
    is_finalized_scan = bool(scan is not None and scan_status in (ScanStatus.DONE.value, "done"))

    if scan is not None and not in_progress:
        val_msg = (scan.validation_message or "").strip()
        if scan_status in (ScanStatus.FAILED.value, "error"):
            if val_msg:
                _add(val_msg)
            elif scan.error_message and scan.error_message.strip():
                _add(scan.error_message.strip())
            else:
                _add("VALIDATION_FAILED")
        elif val_msg and not is_finalized_scan:
            _add(val_msg)

    if canonical_total_valid is False and not any(
        r.startswith(_TOTAL_ERROR_PREFIXES) for r in reasons
    ):
        lines = tx.lines or []
        if not lines:
            _add("RECEIPT_EMPTY")
        else:
            lines_sum = _compute_lines_total_decimal(lines)
            tx_total = quantize_money(tx.total_amount if tx.total_amount is not None else Decimal("0.00"))
            delta = abs(lines_sum - tx_total)
            _add(f"RECEIPT_SUM_MISMATCH:{delta:.2f}")

    if has_pending_duplicate:
        _add("DUPLICATE_REVIEW_REQUIRED")

    if (
        tx.account_id is None
        and _enum_str(tx.review_status) == ReviewStatus.PENDING.value
        and not in_progress
    ):
        _add("MISSING_ACCOUNT")

    if not reasons and not in_progress:
        needs_attention = (
            _enum_str(tx.review_status) == ReviewStatus.PENDING.value
            or (scan is not None and bool(scan.needs_review) and not is_finalized_scan)
        )
        if needs_attention:
            _add("NEEDS_REVIEW")

    return reasons


def _fetch_pending_duplicate_tx_ids(
    session: Session,
    *,
    budget_id: Optional[int],
    transaction_ids: Sequence[int],
) -> set[int]:
    if budget_id is None or not transaction_ids:
        return set()
    id_set = list(set(transaction_ids))
    links = session.exec(
        select(
            ReconciliationLink.bank_transaction_id,
            ReconciliationLink.target_transaction_id,
        ).where(
            ReconciliationLink.budget_id == budget_id,
            col(ReconciliationLink.match_kind) == ReconciliationMatchKind.RECEIPT_DUPLICATE.value,
            col(ReconciliationLink.status) == ReconciliationStatus.PENDING.value,
            (
                col(ReconciliationLink.bank_transaction_id).in_(id_set)
                | col(ReconciliationLink.target_transaction_id).in_(id_set)
            ),
        )
    ).all()
    matched: set[int] = set()
    wanted = set(id_set)
    for bank_id, target_id in links:
        if bank_id in wanted:
            matched.add(bank_id)
        if target_id in wanted:
            matched.add(target_id)
    return matched


def serialize_transaction_read(
    tx: Transaction,
    *,
    suggested_account_id: Optional[int] = None,
    has_pending_duplicate: Optional[bool] = None,
    session: Optional[Session] = None,
) -> TransactionRead:
    """Serialize a ``Transaction`` ORM instance into ``TransactionRead`` with provenance signals."""
    if has_pending_duplicate is None:
        if session is not None and tx.id is not None and tx.budget_id is not None:
            has_dup = tx.id in _fetch_pending_duplicate_tx_ids(
                session,
                budget_id=tx.budget_id,
                transaction_ids=[tx.id],
            )
        else:
            has_dup = False
    else:
        has_dup = has_pending_duplicate

    canonical_total_valid = compute_canonical_total_valid(tx)
    review_reasons = compute_review_reasons(
        tx,
        canonical_total_valid=canonical_total_valid,
        has_pending_duplicate=has_dup,
    )

    lines = [
        TransactionLineRead.model_validate(line)
        for line in (tx.lines or [])
    ]
    tags = [TagRead.model_validate(tag) for tag in (tx.tags or [])]
    scan_read = ReceiptScanRead.model_validate(tx.receipt_scan) if tx.receipt_scan is not None else None
    source_records = [
        SourceRecordRead.model_validate(sr)
        for sr in (tx.source_records or [])
    ]
    tx_data = TransactionRead.model_validate(
        tx,
        update={
            "lines": lines,
            "tags": tags,
            "receipt_scan": scan_read,
            "source_records": source_records,
            "suggested_account_id": tx.account_id if tx.account_id is not None else suggested_account_id,
            "review_reasons": review_reasons,
            "canonical_total_valid": canonical_total_valid,
        },
    )
    return tx_data


def serialize_transactions_read(
    session: Session,
    transactions: Sequence[Transaction],
    *,
    budget_id: int,
    include_suggested_account: bool = True,
) -> list[TransactionRead]:
    """Batch-serialize transactions into ``TransactionRead`` without N+1 duplicate lookups."""
    if not transactions:
        return []
    suggested_account_id = (
        suggest_account_for_budget(session, budget_id=budget_id)
        if include_suggested_account
        else None
    )
    tx_ids = [tx.id for tx in transactions if tx.id is not None]
    pending_dup_ids = _fetch_pending_duplicate_tx_ids(
        session,
        budget_id=budget_id,
        transaction_ids=tx_ids,
    )
    return [
        serialize_transaction_read(
            tx,
            suggested_account_id=suggested_account_id,
            has_pending_duplicate=(tx.id in pending_dup_ids if tx.id is not None else False),
        )
        for tx in transactions
    ]


def _has_exception_scan(tx: Transaction) -> bool:
    scan = tx.receipt_scan
    if scan is None:
        return False
    status_val = _enum_str(scan.status)
    return status_val in INBOX_SCAN_STATUSES


def list_inbox_items(
    session: Session,
    *,
    budget_id: int,
    tab: str = "exceptions",
    source_type: Optional[str] = None,
    needs_review: Optional[bool] = None,
) -> list[TransactionRead]:
    """Return Inbox transactions scoped to ``budget_id`` filtered by hybrid tab and source provenance."""
    stmt = (
        select(Transaction)
        .options(
            selectinload(Transaction.lines),  # type: ignore[arg-type]
            selectinload(Transaction.tags),  # type: ignore[arg-type]
            selectinload(Transaction.receipt_scan),  # type: ignore[arg-type]
            selectinload(Transaction.source_records),  # type: ignore[arg-type]
        )
        .outerjoin(ReceiptScan, col(ReceiptScan.transaction_id) == col(Transaction.id))
        .where(
            Transaction.budget_id == budget_id,
            col(Transaction.reconciled_into_id).is_(None),
        )
    )

    normalized_tab = (tab or "exceptions").strip().lower()
    if normalized_tab == "rejected":
        stmt = stmt.where(col(Transaction.review_status) == ReviewStatus.REJECTED.value)
    elif normalized_tab == "all":
        stmt = stmt.where(
            or_(
                col(Transaction.review_status) == ReviewStatus.PENDING.value,
                col(Transaction.review_status) == ReviewStatus.REJECTED.value,
                col(ReceiptScan.status).in_(INBOX_SCAN_STATUSES),
            )
        )
    else:
        stmt = stmt.where(
            col(Transaction.review_status) != ReviewStatus.REJECTED.value,
            or_(
                col(Transaction.review_status) == ReviewStatus.PENDING.value,
                col(ReceiptScan.status).in_(INBOX_SCAN_STATUSES),
            ),
        )

    if needs_review is not None:
        if needs_review:
            stmt = stmt.where(
                or_(
                    col(ReceiptScan.needs_review).is_(True),
                    and_(
                        col(ReceiptScan.id).is_(None),
                        col(Transaction.review_status) == ReviewStatus.PENDING.value,
                    ),
                )
            )
        else:
            stmt = stmt.where(col(ReceiptScan.needs_review).is_(False))

    if source_type and source_type != "all":
        norm_source = source_type.strip().lower()
        matching_tx_ids = select(SourceRecord.transaction_id).where(
            SourceRecord.budget_id == budget_id,
            col(SourceRecord.transaction_id).is_not(None),
            col(SourceRecord.source_type) == norm_source,
        )
        stmt = stmt.where(col(Transaction.id).in_(matching_tx_ids))

    stmt = stmt.order_by(desc(Transaction.date), desc(Transaction.id))
    rows = list(session.exec(stmt).unique().all())
    return serialize_transactions_read(session, rows, budget_id=budget_id)


def _validate_target_account(session: Session, *, budget_id: int, account_id: int) -> Account:
    acc = session.get(Account, account_id)
    if acc is None or acc.budget_id != budget_id:
        raise InboxValidationError("Target account not found in the active budget")
    if not acc.is_active:
        raise InboxValidationError("Target account is archived or inactive")
    return acc


def approve_inbox_items(
    session: Session,
    *,
    budget_id: int,
    transaction_ids: Sequence[int],
    account_id: int,
    user_id: int,
) -> InboxBulkActionResponse:
    """Bulk-approve eligible Inbox items assigning ``account_id`` while protecting critical scan blockers."""
    del user_id  # Reserved for audit extensions; route enforces owner/editor/member budget scope.
    _validate_target_account(session, budget_id=budget_id, account_id=account_id)

    if not transaction_ids:
        return InboxBulkActionResponse(
            approved_count=0,
            skipped_ids=[],
            errors=[],
        )

    txs = list(
        session.exec(
            select(Transaction).where(
                Transaction.budget_id == budget_id,
                col(Transaction.id).in_(list(set(transaction_ids))),
            )
        ).all()
    )
    tx_by_id = {tx.id: tx for tx in txs if tx.id is not None}

    updated_ids: list[int] = []
    skipped_ids: list[int] = []
    errors: list[dict[str, Any]] = []

    for tx_id in transaction_ids:
        tx = tx_by_id.get(tx_id)
        if tx is None or tx.reconciled_into_id is not None:
            skipped_ids.append(tx_id)
            errors.append({"transaction_id": tx_id, "code": "NOT_FOUND_OR_MERGED"})
            continue

        scan = session.exec(
            select(ReceiptScan).where(ReceiptScan.transaction_id == tx_id)
        ).first()
        if scan is not None and _enum_str(scan.status) in (
            ScanStatus.FAILED.value,
            "error",
        ):
            # Failed OCR scans cannot be blindly bulk-approved; user must edit/verify manually.
            skipped_ids.append(tx_id)
            errors.append({"transaction_id": tx_id, "code": "FAILED_SCAN"})
            continue

        tx.account_id = account_id
        promote_transaction_to_approved(
            session,
            transaction=tx,
            scan=scan,
            finalize_scan=True,
            commit=False,
        )
        updated_ids.append(tx_id)

    session.flush()
    if updated_ids:
        discover_reconciliation_candidates(session, budget_id=budget_id, commit=False)
    session.commit()

    return InboxBulkActionResponse(
        approved_count=len(updated_ids),
        skipped_ids=skipped_ids,
        errors=errors,
    )


def reject_transaction_preserving_provenance(
    session: Session,
    *,
    budget_id: int,
    transaction_id: int,
    user_id: int,
    reason: Optional[str] = None,
    commit: bool = True,
) -> TransactionRead:
    """Soft-reject/delete an imported transaction while retaining SourceRecord tombstones."""
    tx = session.get(Transaction, transaction_id)
    if tx is None or tx.budget_id != budget_id:
        raise InboxNotFoundError("Transaction not found in active budget")

    # Unlink any accepted reconciliation links touching this transaction so counterparts remain intact.
    accepted_links = list(
        session.exec(
            select(ReconciliationLink).where(
                ReconciliationLink.budget_id == budget_id,
                col(ReconciliationLink.status) == ReconciliationStatus.ACCEPTED.value,
                (
                    (col(ReconciliationLink.bank_transaction_id) == transaction_id)
                    | (col(ReconciliationLink.target_transaction_id) == transaction_id)
                ),
            )
        ).all()
    )
    for link in accepted_links:
        if link.id is not None:
            unlink_reconciliation_link(
                session,
                budget_id=budget_id,
                link_id=link.id,
                user_id=user_id,
            )

    # Remove stale pending reconciliation proposals referencing this transaction.
    pending_links = list(
        session.exec(
            select(ReconciliationLink).where(
                ReconciliationLink.budget_id == budget_id,
                col(ReconciliationLink.status) == ReconciliationStatus.PENDING.value,
                (
                    (col(ReconciliationLink.bank_transaction_id) == transaction_id)
                    | (col(ReconciliationLink.target_transaction_id) == transaction_id)
                ),
            )
        ).all()
    )
    for pending in pending_links:
        session.delete(pending)

    session.refresh(tx)
    if tx.date is not None:
        tx.date = ensure_tz_aware(tx.date) or tx.date
    tx.review_status = ReviewStatus.REJECTED
    tx.rejected_at = datetime.now(timezone.utc)
    tx.rejection_reason = (reason or "deleted_by_user").strip() or "deleted_by_user"
    session.add(tx)
    session.flush()
    _recalculate_tx_accounts(session, tx)

    if commit:
        session.commit()
    else:
        session.flush()

    session.refresh(tx)
    suggested_acc = suggest_account_for_budget(session, budget_id=budget_id)
    return serialize_transaction_read(tx, suggested_account_id=suggested_acc, session=session)


def restore_inbox_item(
    session: Session,
    *,
    budget_id: int,
    transaction_id: int,
    account_id: Optional[int] = None,
    commit: bool = True,
) -> TransactionRead:
    """Restore a rejected transaction back into Inbox pending review (or approved when clean)."""
    tx = session.get(Transaction, transaction_id)
    if tx is None or tx.budget_id != budget_id:
        raise InboxNotFoundError("Transaction not found in active budget")
    if _enum_str(tx.review_status) != ReviewStatus.REJECTED.value:
        raise InboxValidationError("Only rejected transactions can be restored")

    if account_id is not None:
        _validate_target_account(session, budget_id=budget_id, account_id=account_id)
        tx.account_id = account_id

    if tx.date is not None:
        tx.date = ensure_tz_aware(tx.date) or tx.date
    tx.rejected_at = None
    tx.rejection_reason = None
    tx.review_status = ReviewStatus.PENDING
    session.add(tx)
    session.flush()

    discover_reconciliation_candidates(session, budget_id=budget_id, commit=False)

    if commit:
        session.commit()
    else:
        session.flush()

    session.refresh(tx)
    suggested_acc = suggest_account_for_budget(session, budget_id=budget_id)
    return serialize_transaction_read(tx, suggested_account_id=suggested_acc, session=session)
