"""Safe, deterministic, reversible receipt-bank reconciliation service (#261)."""

from __future__ import annotations

import logging
import re
from bisect import bisect_left, bisect_right
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Optional, Sequence

from rapidfuzz import fuzz
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, delete, func, select

from app.models import (
    Account,
    BudgetMember,
    ReconciliationActionResponse,
    ReconciliationLink,
    ReconciliationLinkRead,
    ReconciliationListResponse,
    ReconciliationMatchKind,
    ReconciliationSignalRead,
    ReconciliationStatus,
    ReconciliationTransactionSummary,
    ReviewStatus,
    SourceRecord,
    SourceType,
    Transaction,
    TransactionLine,
    TransactionStatus,
    User,
    ensure_tz_aware,
    recalculate_account_balance,
)
from app.money import MONEY_QUANT, quantize_money, quantize_score
from app.provenance_service import record_manual_source_provenance

logger = logging.getLogger("reconciliation_service")

RECONCILIATION_WRITE_ROLES = {"owner", "editor"}

MIN_CANDIDATE_SCORE = Decimal("0.4500")
AUTO_MERGE_SCORE_THRESHOLD = Decimal("0.9000")
AMOUNT_TOLERANCE = Decimal("0.01")
DUPLICATE_DAY_WINDOW = 2

TARGET_SOURCE_TYPES: tuple[SourceType, ...] = (
    SourceType.OCR_PHOTO,
    SourceType.MERCHANT_API,
    SourceType.E_RECEIPT,
    SourceType.MANUAL,
)
RECEIPT_DUPLICATE_INCOMING_SOURCES: tuple[SourceType, ...] = (
    SourceType.MERCHANT_API,
    SourceType.E_RECEIPT,
    SourceType.OCR_PHOTO,
)
RECEIPT_DUPLICATE_TARGET_SOURCES: tuple[SourceType, ...] = (
    SourceType.MANUAL,
    SourceType.OCR_PHOTO,
    SourceType.E_RECEIPT,
    SourceType.MERCHANT_API,
)


def _enum_str(val: Any) -> str:
    return val.value if isinstance(val, Enum) else str(val)

_MERCHANT_NOISE_RE = re.compile(
    r"\b(sp\.?\s*z\s*o\.?\s*o\.?|s\.?\s*a\.?|sp\.?\s*j\.?|sp\.?\s*k\.?|polska|pl|"
    r"platnosc\s+karta|płatność\s+kartą|zakup\s+kartą|zakup\s+przy\s+użyciu\s+karty|"
    r"transakcja\s+blik|płatność\s+blik|platnosc\s+blik|terminal|pos|karta|card|visa|mastercard)\b",
    re.IGNORECASE,
)
_REFUND_KW_RE = re.compile(r"\b(zwrot|refund|korekta|reklamacj\w*|storno|return)\b", re.IGNORECASE)
_DIGITS_ID_RE = re.compile(r"#?\b\d{3,}\b")
_PUNCT_WS_RE = re.compile(r"[^\w\s]", re.UNICODE)
_MULTI_WS_RE = re.compile(r"\s+")


class ReconciliationNotFoundError(Exception):
    """Raised when a reconciliation candidate/link does not exist in the active budget."""


class ReconciliationConflictError(Exception):
    """Raised when linking/unlinking would violate source exclusivity or state rules."""


class ReconciliationPermissionError(Exception):
    """Raised when a budget viewer attempts to mutate reconciliation decisions."""


def require_reconciliation_write_access(session: Session, user: User, budget_id: int) -> None:
    """Ensure the authenticated user holds an owner/editor membership in ``budget_id``."""
    membership = session.exec(
        select(BudgetMember).where(
            BudgetMember.budget_id == budget_id,
            BudgetMember.user_id == user.id,
        )
    ).first()
    if not membership or membership.role not in RECONCILIATION_WRITE_ROLES:
        raise ReconciliationPermissionError("Only budget owners and editors can manage reconciliation")


def _normalize_merchant_text(raw: Optional[str]) -> str:
    if not raw:
        return ""
    cleaned = raw.lower()
    cleaned = _MERCHANT_NOISE_RE.sub(" ", cleaned)
    cleaned = _DIGITS_ID_RE.sub(" ", cleaned)
    cleaned = _PUNCT_WS_RE.sub(" ", cleaned)
    return _MULTI_WS_RE.sub(" ", cleaned).strip()


def _compute_merchant_similarity(bank_tx: Transaction, target_tx: Transaction) -> Decimal:
    target_norm = _normalize_merchant_text(target_tx.merchant_name)
    if not target_norm:
        return Decimal("0.0000")

    bank_candidates = [
        _normalize_merchant_text(bank_tx.merchant_name),
        _normalize_merchant_text(bank_tx.note),
        _normalize_merchant_text(f"{bank_tx.merchant_name or ''} {bank_tx.note or ''}"),
    ]
    best_ratio = Decimal("0.0000")
    for bank_norm in bank_candidates:
        if not bank_norm:
            continue
        token_score = Decimal(str(fuzz.token_set_ratio(target_norm, bank_norm)))
        partial_score = Decimal(str(fuzz.partial_ratio(target_norm, bank_norm)))
        combined = (token_score * Decimal("0.7")) + (partial_score * Decimal("0.3"))
        ratio = quantize_score(combined / Decimal("100"))
        if ratio > best_ratio:
            best_ratio = ratio
    return best_ratio


def _confidence_tier(score: Decimal) -> str:
    if score >= Decimal("0.8000"):
        return "high"
    if score >= Decimal("0.5500"):
        return "medium"
    return "low"


def _tx_utc_date(tx: Transaction) -> Optional[datetime]:
    return ensure_tz_aware(tx.date)


def _has_refund_hint(bank_tx: Transaction, target_tx: Transaction) -> bool:
    combined = f"{bank_tx.merchant_name or ''} {bank_tx.note or ''} {target_tx.note or ''}"
    return bool(_REFUND_KW_RE.search(combined))


def _evaluate_candidate_pair(
    *,
    bank_sr: SourceRecord,
    bank_tx: Transaction,
    target_sr: SourceRecord,
    target_tx: Transaction,
    target_all_sources: Sequence[SourceRecord],
    split_partner_bank_tx_ids: dict[tuple[int, int], list[int]],
    accepted_split_sum: Decimal,
    accepted_refund_sum: Decimal,
    target_has_exact_purchase: bool,
    target_has_split_purchase: bool,
    same_day_conflict_count: int,
) -> Optional[tuple[ReconciliationMatchKind, Decimal, dict[str, Any]]]:
    """Deterministically score a ``(bank_source_record, target_source_record)`` pair.

    Returns ``None`` when transactions are incompatible or score falls below threshold.
    """
    if bank_tx.id is None or target_tx.id is None or bank_tx.id == target_tx.id:
        return None
    if (bank_tx.currency or "").upper() != (target_tx.currency or "").upper():
        return None

    bank_dt = _tx_utc_date(bank_tx)
    target_dt = _tx_utc_date(target_tx)
    if bank_dt is None or target_dt is None:
        return None

    bank_abs = quantize_money(abs(bank_tx.total_amount))
    target_abs = quantize_money(abs(target_tx.total_amount))
    if bank_abs <= Decimal("0.00") or target_abs <= Decimal("0.00"):
        return None

    days_diff = (bank_dt.date() - target_dt.date()).days
    abs_days = abs(days_diff)
    merchant_sim = _compute_merchant_similarity(bank_tx, target_tx)
    target_has_bank_link = (
        target_has_exact_purchase
        or target_has_split_purchase
        or any(sr.source_type == SourceType.BANK_CSV for sr in target_all_sources)
    )

    signals: list[dict[str, Any]] = []
    match_kind: Optional[ReconciliationMatchKind] = None
    amount_weight = Decimal("0.0000")
    date_weight = Decimal("0.0000")
    merchant_weight = Decimal("0.0000")
    account_weight = Decimal("0.0000")
    source_weight = Decimal("0.0000")

    # 1. Determine match kind + amount + date compatibility
    if bank_tx.type == "income" and target_tx.type == "expense":
        # Candidate refund inflow settling after an expense purchase (even if purchase already matched)
        if not (0 <= days_diff <= 30):
            return None
        remaining_refundable = target_abs - accepted_refund_sum
        if remaining_refundable <= Decimal("0.00") or bank_abs > (remaining_refundable + AMOUNT_TOLERANCE):
            return None
        amount_diff = abs(bank_abs - target_abs)
        refund_hint = _has_refund_hint(bank_tx, target_tx)
        if amount_diff <= AMOUNT_TOLERANCE and (merchant_sim >= Decimal("0.5500") or refund_hint):
            match_kind = ReconciliationMatchKind.REFUND
            amount_weight = Decimal("0.4200")
            signals.append(
                {
                    "code": "refund_amount_exact",
                    "matched": True,
                    "weight": str(amount_weight),
                    "detail": {"bank_amount": str(bank_abs), "target_amount": str(target_abs)},
                }
            )
        elif bank_abs < target_abs and (merchant_sim >= Decimal("0.6000") or refund_hint):
            match_kind = ReconciliationMatchKind.REFUND
            amount_weight = Decimal("0.3000")
            signals.append(
                {
                    "code": "refund_amount_partial",
                    "matched": True,
                    "weight": str(amount_weight),
                    "detail": {"bank_amount": str(bank_abs), "target_amount": str(target_abs)},
                }
            )
        else:
            return None

        if abs_days <= 7:
            date_weight = Decimal("0.2200")
            date_code = "refund_date_recent"
        else:
            date_weight = Decimal("0.1400")
            date_code = "refund_date_window"
        signals.append(
            {
                "code": date_code,
                "matched": True,
                "weight": str(date_weight),
                "detail": {"days_diff": days_diff},
            }
        )
    elif bank_tx.type == target_tx.type:
        if target_has_exact_purchase:
            return None
        if not (-2 <= days_diff <= 5):
            return None
        amount_diff = abs(bank_abs - target_abs)
        if amount_diff <= AMOUNT_TOLERANCE:
            if target_has_bank_link:
                return None
            match_kind = ReconciliationMatchKind.EXACT
            if amount_diff == Decimal("0.00"):
                amount_weight = Decimal("0.4500")
                amount_code = "amount_exact"
            else:
                amount_weight = Decimal("0.4000")
                amount_code = "amount_exact_rounding"
            signals.append(
                {
                    "code": amount_code,
                    "matched": True,
                    "weight": str(amount_weight),
                    "detail": {"amount_diff": str(amount_diff)},
                }
            )
        elif bank_tx.type == "expense" and bank_abs < target_abs:
            if not target_has_split_purchase and target_has_bank_link:
                return None
            remaining_target = target_abs - accepted_split_sum
            if bank_abs > (remaining_target + AMOUNT_TOLERANCE):
                return None
            covers_remainder = accepted_split_sum > Decimal("0.00") and abs(bank_abs - remaining_target) <= AMOUNT_TOLERANCE
            partner_ids = split_partner_bank_tx_ids.get((target_tx.id, bank_tx.id), [])
            if not partner_ids and not covers_remainder and merchant_sim < Decimal("0.5500"):
                return None
            match_kind = ReconciliationMatchKind.SPLIT_PAYMENT
            if partner_ids or covers_remainder:
                amount_weight = Decimal("0.3600")
                amount_code = "split_payment_remainder" if covers_remainder else "split_payment_pair_sum"
            else:
                amount_weight = Decimal("0.2800")
                amount_code = "split_payment_partial"
            signals.append(
                {
                    "code": amount_code,
                    "matched": True,
                    "weight": str(amount_weight),
                    "detail": {
                        "bank_amount": str(bank_abs),
                        "target_amount": str(target_abs),
                        "remaining_amount": str(remaining_target),
                        "partner_bank_tx_ids": partner_ids,
                    },
                }
            )
        else:
            return None

        if abs_days == 0:
            date_weight = Decimal("0.2500")
            date_code = "date_same_day"
        elif abs_days == 1:
            date_weight = Decimal("0.2200")
            date_code = "date_within_1d"
        elif abs_days == 2:
            date_weight = Decimal("0.1700")
            date_code = "date_within_2d"
        else:
            date_weight = Decimal("0.1000")
            date_code = "date_settlement_lag"
        signals.append(
            {
                "code": date_code,
                "matched": True,
                "weight": str(date_weight),
                "detail": {"days_diff": days_diff},
            }
        )
    else:
        return None

    # 2. Merchant similarity signal
    if merchant_sim >= Decimal("0.8500"):
        merchant_weight = Decimal("0.2000")
        signals.append(
            {
                "code": "merchant_strong_match",
                "matched": True,
                "weight": str(merchant_weight),
                "detail": {"similarity": str(merchant_sim)},
            }
        )
    elif merchant_sim >= Decimal("0.5500"):
        merchant_weight = quantize_score(merchant_sim * Decimal("0.2000"))
        signals.append(
            {
                "code": "merchant_partial_match",
                "matched": True,
                "weight": str(merchant_weight),
                "detail": {"similarity": str(merchant_sim)},
            }
        )
    else:
        signals.append(
            {
                "code": "merchant_mismatch",
                "matched": False,
                "weight": "0.0000",
                "detail": {"similarity": str(merchant_sim)},
            }
        )

    # 3. Account match signal
    if bank_tx.account_id is not None and target_tx.account_id is not None:
        if bank_tx.account_id == target_tx.account_id:
            account_weight = Decimal("0.0500")
            signals.append(
                {
                    "code": "account_exact_match",
                    "matched": True,
                    "weight": str(account_weight),
                    "detail": {"account_id": bank_tx.account_id},
                }
            )
        else:
            signals.append(
                {
                    "code": "account_mismatch",
                    "matched": False,
                    "weight": "0.0000",
                    "detail": {
                        "bank_account_id": bank_tx.account_id,
                        "target_account_id": target_tx.account_id,
                    },
                }
            )
    else:
        account_weight = Decimal("0.0200")
        signals.append(
            {
                "code": "account_unassigned",
                "matched": False,
                "weight": str(account_weight),
                "detail": {"bank_account_id": bank_tx.account_id},
            }
        )

    # 4. Existing source provenance signal
    def _enum_str(val: Any) -> str:
        return val.value if isinstance(val, Enum) else str(val)

    if target_has_bank_link and match_kind == ReconciliationMatchKind.SPLIT_PAYMENT:
        source_weight = Decimal("0.0300")
        signals.append(
            {
                "code": "source_split_continuation",
                "matched": True,
                "weight": str(source_weight),
                "detail": {"existing_source_types": [_enum_str(sr.source_type) for sr in target_all_sources]},
            }
        )
    elif _enum_str(target_sr.source_type) in {
        SourceType.MERCHANT_API.value,
        SourceType.E_RECEIPT.value,
        SourceType.OCR_PHOTO.value,
    }:
        source_weight = Decimal("0.0500")
        signals.append(
            {
                "code": "source_receipt_unpaired",
                "matched": True,
                "weight": str(source_weight),
                "detail": {"source_type": _enum_str(target_sr.source_type), "provider": target_sr.provider},
            }
        )
    else:
        source_weight = Decimal("0.0250")
        signals.append(
            {
                "code": "source_manual_unpaired",
                "matched": True,
                "weight": str(source_weight),
                "detail": {"source_type": _enum_str(target_sr.source_type)},
            }
        )

    if same_day_conflict_count > 1:
        signals.append(
            {
                "code": "same_day_equal_amount_ambiguity",
                "matched": False,
                "weight": "0.0000",
                "detail": {"conflict_count": same_day_conflict_count},
            }
        )

    total_score = quantize_score(amount_weight + date_weight + merchant_weight + account_weight + source_weight)
    if total_score < MIN_CANDIDATE_SCORE:
        return None

    reasons: dict[str, Any] = {
        "confidence_tier": _confidence_tier(total_score),
        "signals": signals,
        "summary": {
            "days_diff": days_diff,
            "merchant_similarity": str(merchant_sim),
            "same_day_conflict_count": same_day_conflict_count,
        },
    }
    return match_kind, total_score, reasons


def _to_grosze(amount: Decimal) -> int:
    """Convert quantized money amount into integer grosze/cents for O(1) complement lookup."""
    return int((quantize_money(abs(amount)) * 100).to_integral_value())


def _find_split_partner_map(
    bank_pairs: list[tuple[SourceRecord, Transaction]],
    target_pairs: list[tuple[SourceRecord, Transaction]],
    *,
    excluded_target_sr_ids: Optional[set[int]] = None,
) -> dict[tuple[int, int], list[int]]:
    """Precompute ``(target_tx_id, bank_tx_id) -> [partner_bank_tx_ids]`` for split payments.

    Uses per-currency date-sorted buckets + binary search + integer-grosze complement
    indexing so fuzzy merchant similarity is evaluated only on amount-compatible pairs.
    """
    result: dict[tuple[int, int], list[int]] = {}
    banks_by_currency: dict[str, list[tuple[date, int, Transaction, int]]] = defaultdict(list)

    for _, tx in bank_pairs:
        if tx.id is None or tx.type != "expense":
            continue
        tx_dt = _tx_utc_date(tx)
        if tx_dt is None:
            continue
        cents = _to_grosze(tx.total_amount)
        if cents <= 0:
            continue
        banks_by_currency[(tx.currency or "").upper()].append((tx_dt.date(), tx.id, tx, cents))

    sorted_dates_by_currency: dict[str, list[date]] = {}
    for curr, rows in banks_by_currency.items():
        rows.sort(key=lambda item: (item[0], item[1]))
        sorted_dates_by_currency[curr] = [item[0] for item in rows]

    sim_cache: dict[tuple[int, int], Decimal] = {}

    def _cached_similarity(bank_tx: Transaction, target_tx: Transaction) -> Decimal:
        assert bank_tx.id is not None and target_tx.id is not None
        key = (bank_tx.id, target_tx.id)
        cached = sim_cache.get(key)
        if cached is None:
            cached = _compute_merchant_similarity(bank_tx, target_tx)
            sim_cache[key] = cached
        return cached

    for target_sr, target_tx in target_pairs:
        if target_tx.id is None or target_tx.type != "expense":
            continue
        if excluded_target_sr_ids and target_sr.id in excluded_target_sr_ids:
            continue
        target_dt = _tx_utc_date(target_tx)
        if target_dt is None:
            continue
        target_cents = _to_grosze(target_tx.total_amount)
        if target_cents <= 0:
            continue
        target_curr = (target_tx.currency or "").upper()
        bucket = banks_by_currency.get(target_curr)
        if not bucket:
            continue

        bucket_dates = sorted_dates_by_currency[target_curr]
        target_d = target_dt.date()
        lo = bisect_left(bucket_dates, target_d - timedelta(days=2))
        hi = bisect_right(bucket_dates, target_d + timedelta(days=5))
        if hi - lo < 2:
            continue

        window_entries: list[tuple[Transaction, int]] = []
        by_cents: dict[int, list[int]] = defaultdict(list)
        for k in range(lo, hi):
            _, _, b_tx, b_cents = bucket[k]
            if b_tx.id == target_tx.id or b_cents >= target_cents:
                continue
            local_idx = len(window_entries)
            window_entries.append((b_tx, b_cents))
            by_cents[b_cents].append(local_idx)

        if len(window_entries) < 2:
            continue

        for idx1, (b1, a1_cents) in enumerate(window_entries):
            assert b1.id is not None
            base_complement = target_cents - a1_cents
            seen_partner_indices: set[int] = set()
            for delta in (-1, 0, 1):
                for idx2 in by_cents.get(base_complement + delta, ()):
                    if idx2 <= idx1 or idx2 in seen_partner_indices:
                        continue
                    seen_partner_indices.add(idx2)
                    b2, _ = window_entries[idx2]
                    assert b2.id is not None
                    sim1 = _cached_similarity(b1, target_tx)
                    sim2 = _cached_similarity(b2, target_tx)
                    if max(sim1, sim2) >= Decimal("0.5500") or (
                        sim1 >= Decimal("0.3500") and sim2 >= Decimal("0.3500")
                    ):
                        result.setdefault((target_tx.id, b1.id), []).append(b2.id)
                        result.setdefault((target_tx.id, b2.id), []).append(b1.id)
    return result


def discover_reconciliation_candidates(
    session: Session,
    *,
    budget_id: int,
    commit: bool = True,
) -> int:
    """Compute/refresh pending reconciliation candidates for ``budget_id`` idempotently.

    Existing non-pending links (``accepted``, ``rejected``, ``unlinked``) are never
    overwritten or duplicated, ensuring statement re-imports preserve user decisions.
    """
    existing_links = list(
        session.exec(
            select(ReconciliationLink).where(
                ReconciliationLink.budget_id == budget_id,
                col(ReconciliationLink.match_kind) != ReconciliationMatchKind.RECEIPT_DUPLICATE.value,
            )
        ).all()
    )
    links_by_pair: dict[tuple[int, int], ReconciliationLink] = {
        (link.bank_source_record_id, link.target_source_record_id): link for link in existing_links
    }
    accepted_bank_sr_ids = {
        link.bank_source_record_id
        for link in existing_links
        if link.status == ReconciliationStatus.ACCEPTED
    }
    accepted_exact_target_sr_ids = {
        link.target_source_record_id
        for link in existing_links
        if link.status == ReconciliationStatus.ACCEPTED
        and link.match_kind == ReconciliationMatchKind.EXACT
    }
    accepted_split_bank_tx_ids: dict[int, list[int]] = {}
    accepted_refund_bank_tx_ids: dict[int, list[int]] = {}
    for link in existing_links:
        if link.status != ReconciliationStatus.ACCEPTED:
            continue
        if link.match_kind == ReconciliationMatchKind.SPLIT_PAYMENT:
            accepted_split_bank_tx_ids.setdefault(link.target_source_record_id, []).append(
                link.bank_transaction_id
            )
        elif link.match_kind == ReconciliationMatchKind.REFUND:
            accepted_refund_bank_tx_ids.setdefault(link.target_source_record_id, []).append(
                link.bank_transaction_id
            )

    accepted_split_sum_by_target_sr: dict[int, Decimal] = {}
    accepted_refund_sum_by_target_sr: dict[int, Decimal] = {}
    needed_accepted_bank_tx_ids = {
        tx_id
        for ids in (*accepted_split_bank_tx_ids.values(), *accepted_refund_bank_tx_ids.values())
        for tx_id in ids
    }
    if needed_accepted_bank_tx_ids:
        accepted_bank_txs = session.exec(
            select(Transaction).where(col(Transaction.id).in_(needed_accepted_bank_tx_ids))
        ).all()
        amt_by_tx_id = {
            t.id: quantize_money(abs(t.total_amount)) for t in accepted_bank_txs if t.id is not None
        }
        for sr_id, tx_ids in accepted_split_bank_tx_ids.items():
            accepted_split_sum_by_target_sr[sr_id] = sum(
                (amt_by_tx_id.get(tid, Decimal("0.00")) for tid in tx_ids),
                Decimal("0.00"),
            )
        for sr_id, tx_ids in accepted_refund_bank_tx_ids.items():
            accepted_refund_sum_by_target_sr[sr_id] = sum(
                (amt_by_tx_id.get(tid, Decimal("0.00")) for tid in tx_ids),
                Decimal("0.00"),
            )

    bank_rows = session.exec(
        select(SourceRecord, Transaction)
        .join(Transaction, col(SourceRecord.transaction_id) == col(Transaction.id))
        .where(
            SourceRecord.budget_id == budget_id,
            SourceRecord.source_type == SourceType.BANK_CSV,
            col(Transaction.reconciled_into_id).is_(None),
            col(Transaction.review_status) != ReviewStatus.REJECTED.value,
        )
    ).all()

    target_rows = session.exec(
        select(SourceRecord, Transaction)
        .join(Transaction, col(SourceRecord.transaction_id) == col(Transaction.id))
        .where(
            SourceRecord.budget_id == budget_id,
            col(SourceRecord.source_type).in_(TARGET_SOURCE_TYPES),
            col(Transaction.reconciled_into_id).is_(None),
            col(Transaction.review_status) != ReviewStatus.REJECTED.value,
        )
    ).all()

    all_budget_sources = list(
        session.exec(
            select(SourceRecord).where(
                SourceRecord.budget_id == budget_id,
                col(SourceRecord.transaction_id).is_not(None),
            )
        ).all()
    )
    sources_by_tx_id: dict[int, list[SourceRecord]] = {}
    for sr in all_budget_sources:
        if sr.transaction_id is not None:
            sources_by_tx_id.setdefault(sr.transaction_id, []).append(sr)

    active_bank_pairs = [(sr, tx) for sr, tx in bank_rows if sr.id not in accepted_bank_sr_ids]
    active_target_pairs = list(target_rows)

    # Count same-day equal-amount transactions on each side to surface ambiguity in reasons.
    bank_bucket_counts: dict[tuple[str, Any, Decimal, str], int] = {}
    for _, b_tx in active_bank_pairs:
        b_dt = _tx_utc_date(b_tx)
        if b_dt is None:
            continue
        key = (
            (b_tx.currency or "").upper(),
            b_dt.date(),
            quantize_money(abs(b_tx.total_amount)),
            b_tx.type,
        )
        bank_bucket_counts[key] = bank_bucket_counts.get(key, 0) + 1

    target_bucket_counts: dict[tuple[str, Any, Decimal, str], int] = {}
    for target_sr, t_tx in active_target_pairs:
        if target_sr.id in accepted_exact_target_sr_ids:
            continue
        t_dt = _tx_utc_date(t_tx)
        if t_dt is None:
            continue
        key = (
            (t_tx.currency or "").upper(),
            t_dt.date(),
            quantize_money(abs(t_tx.total_amount)),
            t_tx.type,
        )
        target_bucket_counts[key] = target_bucket_counts.get(key, 0) + 1

    split_partner_map = _find_split_partner_map(
        active_bank_pairs,
        active_target_pairs,
        excluded_target_sr_ids=accepted_exact_target_sr_ids,
    )

    upserted = 0
    now = datetime.now(timezone.utc)
    seen_active_pending_pairs: set[tuple[int, int]] = set()

    for bank_sr, bank_tx in active_bank_pairs:
        if bank_sr.id is None or bank_tx.id is None:
            continue
        b_dt = _tx_utc_date(bank_tx)
        if b_dt is None:
            continue
        b_bucket = (
            (bank_tx.currency or "").upper(),
            b_dt.date(),
            quantize_money(abs(bank_tx.total_amount)),
            bank_tx.type,
        )
        b_conflicts = bank_bucket_counts.get(b_bucket, 0)

        for target_sr, target_tx in active_target_pairs:
            if target_sr.id is None or target_tx.id is None:
                continue
            t_dt = _tx_utc_date(target_tx)
            if t_dt is None:
                continue
            t_bucket = (
                (target_tx.currency or "").upper(),
                t_dt.date(),
                quantize_money(abs(target_tx.total_amount)),
                target_tx.type,
            )
            conflict_count = max(b_conflicts, target_bucket_counts.get(t_bucket, 0))

            scored = _evaluate_candidate_pair(
                bank_sr=bank_sr,
                bank_tx=bank_tx,
                target_sr=target_sr,
                target_tx=target_tx,
                target_all_sources=sources_by_tx_id.get(target_tx.id, [target_sr]),
                split_partner_bank_tx_ids=split_partner_map,
                accepted_split_sum=accepted_split_sum_by_target_sr.get(target_sr.id, Decimal("0.00")),
                accepted_refund_sum=accepted_refund_sum_by_target_sr.get(target_sr.id, Decimal("0.00")),
                target_has_exact_purchase=target_sr.id in accepted_exact_target_sr_ids,
                target_has_split_purchase=target_sr.id in accepted_split_bank_tx_ids,
                same_day_conflict_count=conflict_count,
            )
            if scored is None:
                continue

            match_kind, score, reasons = scored
            pair_key = (bank_sr.id, target_sr.id)
            existing = links_by_pair.get(pair_key)

            if existing is not None:
                # Preserve non-pending user decisions untouched on re-import/refresh.
                if existing.status != ReconciliationStatus.PENDING:
                    continue
                seen_active_pending_pairs.add(pair_key)
                if (
                    existing.match_kind != match_kind
                    or quantize_score(existing.score) != score
                    or existing.reasons != reasons
                ):
                    existing.match_kind = match_kind
                    existing.score = score
                    existing.reasons = reasons
                    existing.updated_at = now
                    session.add(existing)
                continue

            seen_active_pending_pairs.add(pair_key)
            new_link = ReconciliationLink(
                budget_id=budget_id,
                bank_source_record_id=bank_sr.id,
                target_source_record_id=target_sr.id,
                bank_transaction_id=bank_tx.id,
                target_transaction_id=target_tx.id,
                match_kind=match_kind,
                status=ReconciliationStatus.PENDING,
                score=score,
                reasons=reasons,
                created_at=now,
                updated_at=now,
            )
            session.add(new_link)
            links_by_pair[pair_key] = new_link
            upserted += 1

    # Remove only stale PENDING links that are no longer valid candidates; never touch decided rows.
    for pair_key, existing in links_by_pair.items():
        if existing.status == ReconciliationStatus.PENDING and pair_key not in seen_active_pending_pairs:
            session.delete(existing)

    upserted += discover_receipt_duplicate_candidates(session, budget_id=budget_id, commit=False)

    if commit:
        session.commit()
    else:
        session.flush()
    return upserted


def _pick_duplicate_anchor_pair(
    pair_a: tuple[SourceRecord, Transaction],
    pair_b: tuple[SourceRecord, Transaction],
    *,
    accepted_bank_linked_tx_ids: set[int],
) -> tuple[tuple[SourceRecord, Transaction], tuple[SourceRecord, Transaction]]:
    """Return ``(incoming_to_absorb, surviving_anchor)`` deterministically.

    Manual / already-approved / bank-linked transactions survive as the anchor so the
    user's existing account, note, and bank reconciliation link remain intact while
    imported basket lines and provenance records fold into them.
    """
    def _anchor_rank(sr: SourceRecord, tx: Transaction) -> tuple[int, int, int, int]:
        tx_id = tx.id or 0
        is_bank_linked = 1 if tx_id in accepted_bank_linked_tx_ids else 0
        is_approved = 1 if _enum_str(tx.review_status) == ReviewStatus.APPROVED.value else 0
        is_manual = 1 if _enum_str(sr.source_type) == SourceType.MANUAL.value or tx.is_manual else 0
        return (is_bank_linked, is_approved, is_manual, -tx_id)

    rank_a = _anchor_rank(pair_a[0], pair_a[1])
    rank_b = _anchor_rank(pair_b[0], pair_b[1])
    if rank_a >= rank_b:
        return pair_b, pair_a
    return pair_a, pair_b


def _evaluate_receipt_duplicate_pair(
    *,
    incoming_sr: SourceRecord,
    incoming_tx: Transaction,
    anchor_sr: SourceRecord,
    anchor_tx: Transaction,
    same_day_conflict_count: int,
) -> Optional[tuple[Decimal, dict[str, Any]]]:
    """Deterministically score a cross-source duplicate receipt pair."""
    if incoming_tx.id is None or anchor_tx.id is None or incoming_tx.id == anchor_tx.id:
        return None
    if incoming_tx.type != anchor_tx.type:
        return None
    if (incoming_tx.currency or "").upper() != (anchor_tx.currency or "").upper():
        return None

    in_dt = _tx_utc_date(incoming_tx)
    an_dt = _tx_utc_date(anchor_tx)
    if in_dt is None or an_dt is None:
        return None

    in_abs = quantize_money(abs(incoming_tx.total_amount))
    an_abs = quantize_money(abs(anchor_tx.total_amount))
    if in_abs <= Decimal("0.00") or an_abs <= Decimal("0.00"):
        return None
    if abs(in_abs - an_abs) > AMOUNT_TOLERANCE:
        return None

    days_diff = (in_dt.date() - an_dt.date()).days
    abs_days = abs(days_diff)
    if abs_days > DUPLICATE_DAY_WINDOW:
        return None

    sim_ab = _compute_merchant_similarity(incoming_tx, anchor_tx)
    sim_ba = _compute_merchant_similarity(anchor_tx, incoming_tx)
    merchant_sim = max(sim_ab, sim_ba)

    in_norm = _normalize_merchant_text(incoming_tx.merchant_name)
    an_norm = _normalize_merchant_text(anchor_tx.merchant_name)
    if in_norm and an_norm and merchant_sim < Decimal("0.5000"):
        return None

    signals: list[dict[str, Any]] = []
    if in_abs == an_abs:
        amount_weight = Decimal("0.4500")
        signals.append(
            {
                "code": "exact_amount",
                "matched": True,
                "weight": str(amount_weight),
                "detail": {"amount": str(in_abs)},
            }
        )
    else:
        amount_weight = Decimal("0.4000")
        signals.append(
            {
                "code": "near_amount",
                "matched": True,
                "weight": str(amount_weight),
                "detail": {"incoming": str(in_abs), "anchor": str(an_abs)},
            }
        )

    if abs_days == 0:
        date_weight = Decimal("0.2500")
        signals.append(
            {"code": "same_day", "matched": True, "weight": str(date_weight), "detail": {"days_diff": 0}}
        )
    elif abs_days == 1:
        date_weight = Decimal("0.1800")
        signals.append(
            {"code": "date_adjacent", "matched": True, "weight": str(date_weight), "detail": {"days_diff": days_diff}}
        )
    else:
        date_weight = Decimal("0.1000")
        signals.append(
            {"code": "date_window_2d", "matched": True, "weight": str(date_weight), "detail": {"days_diff": days_diff}}
        )

    if in_norm and an_norm:
        merchant_weight = quantize_score(merchant_sim * Decimal("0.3000"))
        signals.append(
            {
                "code": "merchant_similarity",
                "matched": merchant_sim >= Decimal("0.6000"),
                "weight": str(merchant_weight),
                "detail": {"similarity": str(merchant_sim)},
            }
        )
    else:
        merchant_weight = Decimal("0.0000")
        signals.append(
            {
                "code": "merchant_missing",
                "matched": False,
                "weight": "0.0000",
                "detail": {"similarity": "0.0000"},
            }
        )

    if same_day_conflict_count > 1:
        signals.append(
            {
                "code": "same_day_equal_amount_ambiguity",
                "matched": False,
                "weight": "0.0000",
                "detail": {"conflict_count": same_day_conflict_count},
            }
        )

    total_score = quantize_score(amount_weight + date_weight + merchant_weight)
    if total_score < MIN_CANDIDATE_SCORE:
        return None

    reasons: dict[str, Any] = {
        "confidence_tier": _confidence_tier(total_score),
        "signals": signals,
        "summary": {
            "days_diff": days_diff,
            "merchant_similarity": str(merchant_sim),
            "same_day_conflict_count": same_day_conflict_count,
            "incoming_source": _enum_str(incoming_sr.source_type),
            "anchor_source": _enum_str(anchor_sr.source_type),
        },
    }
    return total_score, reasons


def discover_receipt_duplicate_candidates(
    session: Session,
    *,
    budget_id: int,
    commit: bool = True,
) -> int:
    """Detect cross-source duplicate candidates among non-bank transactions idempotently."""
    # Ensure active non-rejected manual entries have a MANUAL SourceRecord anchor.
    manual_txs = session.exec(
        select(Transaction).where(
            Transaction.budget_id == budget_id,
            col(Transaction.is_manual).is_(True),
            col(Transaction.type) != "transfer",
            col(Transaction.reconciled_into_id).is_(None),
            col(Transaction.review_status) != ReviewStatus.REJECTED.value,
        )
    ).all()
    if manual_txs:
        manual_ids = [t.id for t in manual_txs if t.id is not None]
        existing_manual_srs = set(
            session.exec(
                select(SourceRecord.transaction_id).where(
                    SourceRecord.budget_id == budget_id,
                    col(SourceRecord.transaction_id).in_(manual_ids),
                )
            ).all()
        )
        for mtx in manual_txs:
            if mtx.id is not None and mtx.id not in existing_manual_srs:
                record_manual_source_provenance(
                    session,
                    budget_id=budget_id,
                    transaction_id=mtx.id,
                    acquired_at=ensure_tz_aware(mtx.date),
                )
        session.flush()

    existing_dup_links = list(
        session.exec(
            select(ReconciliationLink).where(
                ReconciliationLink.budget_id == budget_id,
                col(ReconciliationLink.match_kind) == ReconciliationMatchKind.RECEIPT_DUPLICATE.value,
            )
        ).all()
    )
    dup_by_unordered_sr: dict[tuple[int, int], ReconciliationLink] = {
        (
            min(link.bank_source_record_id, link.target_source_record_id),
            max(link.bank_source_record_id, link.target_source_record_id),
        ): link
        for link in existing_dup_links
    }
    accepted_bank_linked_tx_ids = {
        int(tx_id)
        for tx_id in session.exec(
            select(ReconciliationLink.target_transaction_id).where(
                ReconciliationLink.budget_id == budget_id,
                col(ReconciliationLink.status) == ReconciliationStatus.ACCEPTED.value,
                col(ReconciliationLink.match_kind) != ReconciliationMatchKind.RECEIPT_DUPLICATE.value,
            )
        ).all()
        if tx_id is not None
    }

    rows = list(
        session.exec(
            select(SourceRecord, Transaction)
            .join(Transaction, col(SourceRecord.transaction_id) == col(Transaction.id))
            .where(
                SourceRecord.budget_id == budget_id,
                col(SourceRecord.source_type).in_(RECEIPT_DUPLICATE_TARGET_SOURCES),
                col(Transaction.type) != "transfer",
                col(Transaction.reconciled_into_id).is_(None),
                col(Transaction.review_status) != ReviewStatus.REJECTED.value,
            )
        ).all()
    )
    # Use the earliest primary SourceRecord per transaction to avoid duplicate candidate rows
    # when a surviving transaction already accumulated secondary SourceRecords.
    primary_pair_by_tx: dict[int, tuple[SourceRecord, Transaction]] = {}
    for sr, tx in rows:
        if tx.id is None or sr.id is None:
            continue
        existing_pair = primary_pair_by_tx.get(tx.id)
        if existing_pair is None or (sr.id < (existing_pair[0].id or 0)):
            primary_pair_by_tx[tx.id] = (sr, tx)

    pairs = sorted(primary_pair_by_tx.values(), key=lambda p: p[1].id or 0)
    bucket_counts: dict[tuple[str, Any, Decimal, str], int] = {}
    for _, tx in pairs:
        dt = _tx_utc_date(tx)
        if dt is None:
            continue
        key = (
            (tx.currency or "").upper(),
            dt.date(),
            quantize_money(abs(tx.total_amount)),
            tx.type,
        )
        bucket_counts[key] = bucket_counts.get(key, 0) + 1

    upserted = 0
    now = datetime.now(timezone.utc)
    seen_pending_pairs: set[tuple[int, int]] = set()
    incoming_sources_set = {s.value for s in RECEIPT_DUPLICATE_INCOMING_SOURCES}

    for i in range(len(pairs)):
        sr_a, tx_a = pairs[i]
        for j in range(i + 1, len(pairs)):
            sr_b, tx_b = pairs[j]
            if tx_a.id == tx_b.id or sr_a.id is None or sr_b.id is None:
                continue
            src_a = _enum_str(sr_a.source_type)
            src_b = _enum_str(sr_b.source_type)
            # At least one item must be an imported/scanned receipt, and items must come from
            # different source channels or different non-manual providers.
            if src_a not in incoming_sources_set and src_b not in incoming_sources_set:
                continue
            if src_a == src_b and (src_a == SourceType.MANUAL.value or sr_a.provider == sr_b.provider):
                # Allow same-provider duplicate detection between distinct OCR photos or distinct non-manual records
                if sr_a.source_type != SourceType.OCR_PHOTO:
                    continue

            pair_key = (min(sr_a.id, sr_b.id), max(sr_a.id, sr_b.id))
            existing = dup_by_unordered_sr.get(pair_key)
            if existing is not None and existing.status != ReconciliationStatus.PENDING:
                continue

            (in_sr, in_tx), (an_sr, an_tx) = _pick_duplicate_anchor_pair(
                (sr_a, tx_a),
                (sr_b, tx_b),
                accepted_bank_linked_tx_ids=accepted_bank_linked_tx_ids,
            )
            assert in_sr.id is not None and an_sr.id is not None
            assert in_tx.id is not None and an_tx.id is not None

            in_dt = _tx_utc_date(in_tx)
            an_dt = _tx_utc_date(an_tx)
            b_in = (
                (in_tx.currency or "").upper(),
                in_dt.date() if in_dt else None,
                quantize_money(abs(in_tx.total_amount)),
                in_tx.type,
            )
            b_an = (
                (an_tx.currency or "").upper(),
                an_dt.date() if an_dt else None,
                quantize_money(abs(an_tx.total_amount)),
                an_tx.type,
            )
            raw_bucket = max(bucket_counts.get(b_in, 0), bucket_counts.get(b_an, 0))
            conflict_count = (raw_bucket - 1) if raw_bucket > 2 else 1

            scored = _evaluate_receipt_duplicate_pair(
                incoming_sr=in_sr,
                incoming_tx=in_tx,
                anchor_sr=an_sr,
                anchor_tx=an_tx,
                same_day_conflict_count=conflict_count,
            )
            if scored is None:
                continue

            score, reasons = scored
            if existing is not None:
                seen_pending_pairs.add(pair_key)
                if (
                    existing.bank_source_record_id != in_sr.id
                    or existing.target_source_record_id != an_sr.id
                    or quantize_score(existing.score) != score
                    or existing.reasons != reasons
                ):
                    existing.bank_source_record_id = in_sr.id
                    existing.target_source_record_id = an_sr.id
                    existing.bank_transaction_id = in_tx.id
                    existing.target_transaction_id = an_tx.id
                    existing.score = score
                    existing.reasons = reasons
                    existing.updated_at = now
                    session.add(existing)
                continue

            seen_pending_pairs.add(pair_key)
            new_link = ReconciliationLink(
                budget_id=budget_id,
                bank_source_record_id=in_sr.id,
                target_source_record_id=an_sr.id,
                bank_transaction_id=in_tx.id,
                target_transaction_id=an_tx.id,
                match_kind=ReconciliationMatchKind.RECEIPT_DUPLICATE,
                status=ReconciliationStatus.PENDING,
                score=score,
                reasons=reasons,
                created_at=now,
                updated_at=now,
            )
            session.add(new_link)
            dup_by_unordered_sr[pair_key] = new_link
            upserted += 1

    for pair_key, existing in dup_by_unordered_sr.items():
        if existing.status == ReconciliationStatus.PENDING and pair_key not in seen_pending_pairs:
            session.delete(existing)

    if commit:
        session.commit()
    else:
        session.flush()
    return upserted


def _serialize_tx_summary(
    tx: Optional[Transaction],
    sr: Optional[SourceRecord],
    accounts_by_id: dict[int, Account],
) -> Optional[ReconciliationTransactionSummary]:
    if tx is None or tx.id is None:
        return None
    account_name = None
    if tx.account_id is not None and tx.account_id in accounts_by_id:
        account_name = accounts_by_id[tx.account_id].name
    return ReconciliationTransactionSummary(
        id=tx.id,
        merchant_name=tx.merchant_name,
        total_amount=quantize_money(tx.total_amount),
        currency=tx.currency,
        date=ensure_tz_aware(tx.date),
        type=tx.type,
        status=tx.status,
        account_id=tx.account_id,
        account_name=account_name,
        note=tx.note,
        source_type=sr.source_type if sr else None,
        provider=sr.provider if sr else None,
    )


def _serialize_link(
    link: ReconciliationLink,
    *,
    tx_by_id: dict[int, Transaction],
    sr_by_id: dict[int, SourceRecord],
    accounts_by_id: dict[int, Account],
) -> ReconciliationLinkRead:
    assert link.id is not None
    raw_signals = (link.reasons or {}).get("signals") or []
    signals = [
        ReconciliationSignalRead(
            code=str(sig.get("code", "")),
            matched=bool(sig.get("matched", False)),
            weight=quantize_score(sig.get("weight", "0.0000")),
            detail=dict(sig.get("detail") or {}),
        )
        for sig in raw_signals
        if isinstance(sig, dict)
    ]
    summary = (link.reasons or {}).get("summary") or {}
    confidence_tier = str((link.reasons or {}).get("confidence_tier") or _confidence_tier(link.score))

    return ReconciliationLinkRead(
        id=link.id,
        budget_id=link.budget_id,
        bank_source_record_id=link.bank_source_record_id,
        target_source_record_id=link.target_source_record_id,
        bank_transaction_id=link.bank_transaction_id,
        target_transaction_id=link.target_transaction_id,
        match_kind=link.match_kind,
        status=link.status,
        score=quantize_score(link.score),
        confidence_tier=confidence_tier,
        signals=signals,
        same_day_conflict_count=int(summary.get("same_day_conflict_count") or 0),
        bank_transaction=_serialize_tx_summary(
            tx_by_id.get(link.bank_transaction_id),
            sr_by_id.get(link.bank_source_record_id),
            accounts_by_id,
        ),
        target_transaction=_serialize_tx_summary(
            tx_by_id.get(link.target_transaction_id),
            sr_by_id.get(link.target_source_record_id),
            accounts_by_id,
        ),
        decided_at=ensure_tz_aware(link.decided_at),
        created_at=ensure_tz_aware(link.created_at) or datetime.now(timezone.utc),
        updated_at=ensure_tz_aware(link.updated_at) or datetime.now(timezone.utc),
    )


def _load_link_read(session: Session, link: ReconciliationLink) -> ReconciliationLinkRead:
    tx_ids = {link.bank_transaction_id, link.target_transaction_id}
    sr_ids = {link.bank_source_record_id, link.target_source_record_id}
    tx_rows = session.exec(select(Transaction).where(col(Transaction.id).in_(tx_ids))).all()
    sr_rows = session.exec(select(SourceRecord).where(col(SourceRecord.id).in_(sr_ids))).all()
    acc_ids = {tx.account_id for tx in tx_rows if tx.account_id is not None}
    acc_rows = (
        session.exec(select(Account).where(col(Account.id).in_(acc_ids))).all() if acc_ids else []
    )
    return _serialize_link(
        link,
        tx_by_id={tx.id: tx for tx in tx_rows if tx.id is not None},
        sr_by_id={sr.id: sr for sr in sr_rows if sr.id is not None},
        accounts_by_id={acc.id: acc for acc in acc_rows if acc.id is not None},
    )


def list_reconciliation_links(
    session: Session,
    *,
    budget_id: int,
    status: Optional[ReconciliationStatus] = None,
    auto_discover: bool = False,
) -> ReconciliationListResponse:
    """List reconciliation links/candidates and status counts for ``budget_id``."""
    if auto_discover:
        discover_reconciliation_candidates(session, budget_id=budget_id, commit=True)

    counts_rows = session.exec(
        select(ReconciliationLink.status, func.count(col(ReconciliationLink.id)))
        .where(ReconciliationLink.budget_id == budget_id)
        .group_by(col(ReconciliationLink.status))
    ).all()
    counts: dict[str, int] = {
        (st.value if isinstance(st, ReconciliationStatus) else str(st)): int(cnt)
        for st, cnt in counts_rows
    }

    stmt = select(ReconciliationLink).where(ReconciliationLink.budget_id == budget_id)
    if status is not None:
        stmt = stmt.where(col(ReconciliationLink.status) == status.value)
    stmt = stmt.order_by(col(ReconciliationLink.score).desc(), col(ReconciliationLink.id).desc())
    links = list(session.exec(stmt).all())

    if not links:
        return ReconciliationListResponse(
            candidates=[],
            pending_count=counts.get(ReconciliationStatus.PENDING.value, 0),
            accepted_count=counts.get(ReconciliationStatus.ACCEPTED.value, 0),
            rejected_count=counts.get(ReconciliationStatus.REJECTED.value, 0),
            unlinked_count=counts.get(ReconciliationStatus.UNLINKED.value, 0),
        )

    tx_ids = {link.bank_transaction_id for link in links} | {link.target_transaction_id for link in links}
    sr_ids = {link.bank_source_record_id for link in links} | {link.target_source_record_id for link in links}
    tx_rows = session.exec(select(Transaction).where(col(Transaction.id).in_(tx_ids))).all()
    sr_rows = session.exec(select(SourceRecord).where(col(SourceRecord.id).in_(sr_ids))).all()
    acc_ids = {tx.account_id for tx in tx_rows if tx.account_id is not None}
    acc_rows = (
        session.exec(select(Account).where(col(Account.id).in_(acc_ids))).all() if acc_ids else []
    )
    tx_by_id = {tx.id: tx for tx in tx_rows if tx.id is not None}
    sr_by_id = {sr.id: sr for sr in sr_rows if sr.id is not None}
    accounts_by_id = {acc.id: acc for acc in acc_rows if acc.id is not None}

    return ReconciliationListResponse(
        candidates=[
            _serialize_link(
                link,
                tx_by_id=tx_by_id,
                sr_by_id=sr_by_id,
                accounts_by_id=accounts_by_id,
            )
            for link in links
        ],
        pending_count=counts.get(ReconciliationStatus.PENDING.value, 0),
        accepted_count=counts.get(ReconciliationStatus.ACCEPTED.value, 0),
        rejected_count=counts.get(ReconciliationStatus.REJECTED.value, 0),
        unlinked_count=counts.get(ReconciliationStatus.UNLINKED.value, 0),
    )


def _get_scoped_link(session: Session, *, budget_id: int, link_id: int) -> ReconciliationLink:
    link = session.get(ReconciliationLink, link_id)
    if not link or link.budget_id != budget_id:
        raise ReconciliationNotFoundError("Reconciliation candidate not found")
    return link


def accept_reconciliation_link(
    session: Session,
    *,
    budget_id: int,
    link_id: int,
    user_id: int,
    commit: bool = True,
) -> ReconciliationActionResponse:
    """Confirm a candidate match cleanly while preventing incompatible source multi-links."""
    link = _get_scoped_link(session, budget_id=budget_id, link_id=link_id)
    if link.match_kind == ReconciliationMatchKind.RECEIPT_DUPLICATE:
        return merge_receipt_duplicate_link(
            session,
            budget_id=budget_id,
            link_id=link_id,
            user_id=user_id,
            keep_transaction_id=None,
            commit=commit,
        )
    if link.status == ReconciliationStatus.ACCEPTED:
        raise ReconciliationConflictError("Reconciliation link is already accepted")

    bank_sr = session.get(SourceRecord, link.bank_source_record_id)
    target_sr = session.get(SourceRecord, link.target_source_record_id)
    bank_tx = session.get(Transaction, link.bank_transaction_id)
    target_tx = session.get(Transaction, link.target_transaction_id)
    if not bank_sr or not target_sr or not bank_tx or not target_tx:
        raise ReconciliationNotFoundError("Underlying transaction or source record not found")
    if (
        bank_sr.budget_id != budget_id
        or target_sr.budget_id != budget_id
        or bank_tx.budget_id != budget_id
        or target_tx.budget_id != budget_id
    ):
        raise ReconciliationNotFoundError("Cross-budget reconciliation is forbidden")
    if bank_tx.id == target_tx.id or target_tx.reconciled_into_id is not None:
        raise ReconciliationConflictError("Target transaction cannot be reconciled")
    if (bank_tx.currency or "").upper() != (target_tx.currency or "").upper():
        raise ReconciliationConflictError("Transactions with different currencies cannot be linked")

    # Enforce 1:1 / compatible split invariants before committing.
    existing_bank_accepted = session.exec(
        select(ReconciliationLink).where(
            ReconciliationLink.budget_id == budget_id,
            ReconciliationLink.bank_source_record_id == link.bank_source_record_id,
            col(ReconciliationLink.status) == ReconciliationStatus.ACCEPTED.value,
            col(ReconciliationLink.id) != link.id,
        )
    ).first()
    if existing_bank_accepted is not None:
        raise ReconciliationConflictError("Bank source record is already linked to another transaction")

    existing_target_accepted = list(
        session.exec(
            select(ReconciliationLink).where(
                ReconciliationLink.budget_id == budget_id,
                ReconciliationLink.target_source_record_id == link.target_source_record_id,
                col(ReconciliationLink.status) == ReconciliationStatus.ACCEPTED.value,
                col(ReconciliationLink.id) != link.id,
            )
        ).all()
    )
    existing_exact_accepted = [
        other for other in existing_target_accepted if other.match_kind == ReconciliationMatchKind.EXACT
    ]
    existing_split_accepted = [
        other for other in existing_target_accepted if other.match_kind == ReconciliationMatchKind.SPLIT_PAYMENT
    ]
    existing_refund_accepted = [
        other for other in existing_target_accepted if other.match_kind == ReconciliationMatchKind.REFUND
    ]

    linked_sum = Decimal("0.00")
    target_total = quantize_money(abs(target_tx.total_amount))

    if link.match_kind == ReconciliationMatchKind.EXACT:
        if existing_exact_accepted or existing_split_accepted:
            raise ReconciliationConflictError("Target source record is already linked to another transaction")
    elif link.match_kind == ReconciliationMatchKind.SPLIT_PAYMENT:
        if existing_exact_accepted:
            raise ReconciliationConflictError("Target source record already has an incompatible exclusive link")
        if existing_split_accepted:
            existing_bank_tx_ids = [other.bank_transaction_id for other in existing_split_accepted]
            existing_bank_txs = list(
                session.exec(select(Transaction).where(col(Transaction.id).in_(existing_bank_tx_ids))).all()
            )
            linked_sum = sum(
                (quantize_money(abs(tx.total_amount)) for tx in existing_bank_txs),
                Decimal("0.00"),
            )
        new_total = linked_sum + quantize_money(abs(bank_tx.total_amount))
        if new_total > (target_total + AMOUNT_TOLERANCE):
            raise ReconciliationConflictError(
                "Split payment bank transactions exceed receipt total amount"
            )
    elif link.match_kind == ReconciliationMatchKind.REFUND:
        existing_refund_sum = Decimal("0.00")
        if existing_refund_accepted:
            refund_bank_tx_ids = [other.bank_transaction_id for other in existing_refund_accepted]
            refund_bank_txs = list(
                session.exec(select(Transaction).where(col(Transaction.id).in_(refund_bank_tx_ids))).all()
            )
            existing_refund_sum = sum(
                (quantize_money(abs(tx.total_amount)) for tx in refund_bank_txs),
                Decimal("0.00"),
            )
        new_refund_total = existing_refund_sum + quantize_money(abs(bank_tx.total_amount))
        if new_refund_total > (target_total + AMOUNT_TOLERANCE):
            raise ReconciliationConflictError(
                "Refund bank transactions exceed receipt total amount"
            )

    def _status_value(status_val: Any) -> str:
        return status_val.value if isinstance(status_val, TransactionStatus) else str(status_val)

    now = datetime.now(timezone.utc)
    affected_account_ids: set[int] = {
        acc_id
        for acc_id in (bank_tx.account_id, target_tx.account_id)
        if acc_id is not None
    }

    if link.match_kind == ReconciliationMatchKind.EXACT:
        link.previous_receipt_status = _status_value(target_tx.status)
    elif link.match_kind == ReconciliationMatchKind.SPLIT_PAYMENT:
        if existing_split_accepted and existing_split_accepted[0].previous_receipt_status is not None:
            link.previous_receipt_status = existing_split_accepted[0].previous_receipt_status
        else:
            link.previous_receipt_status = _status_value(target_tx.status)
    elif link.previous_receipt_status is None:
        link.previous_receipt_status = _status_value(target_tx.status)

    try:
        with session.begin_nested():
            if link.match_kind in (ReconciliationMatchKind.EXACT, ReconciliationMatchKind.SPLIT_PAYMENT):
                assert target_tx.id is not None
                bank_tx.reconciled_into_id = target_tx.id
                bank_sr.transaction_id = target_tx.id

                updated_reasons = dict(link.reasons or {})
                updated_reasons.pop("inherited_account_on_accept", None)
                if link.match_kind == ReconciliationMatchKind.EXACT:
                    if bank_tx.account_id is not None and target_tx.account_id != bank_tx.account_id:
                        updated_reasons["account_updated_on_accept"] = True
                        updated_reasons["previous_target_account_id"] = target_tx.account_id
                        target_tx.account_id = bank_tx.account_id
                    else:
                        updated_reasons.pop("account_updated_on_accept", None)
                        updated_reasons.pop("previous_target_account_id", None)
                    target_tx.status = TransactionStatus.CLEARED
                else:
                    # Keep target_tx.account_id untouched on split_payment; each bank_tx keeps its own account.
                    updated_reasons.pop("account_updated_on_accept", None)
                    updated_reasons.pop("previous_target_account_id", None)
                    combined = linked_sum + quantize_money(abs(bank_tx.total_amount))
                    if abs(combined - target_total) <= MONEY_QUANT:
                        target_tx.status = TransactionStatus.CLEARED

                link.reasons = updated_reasons
                session.add(bank_tx)
                session.add(bank_sr)
                session.add(target_tx)

            link.status = ReconciliationStatus.ACCEPTED
            link.decided_by_user_id = user_id
            link.decided_at = now
            link.updated_at = now
            session.add(link)

            # Remove superseded PENDING candidates for the claimed bank source record.
            superseded_bank_pending = session.exec(
                select(ReconciliationLink).where(
                    ReconciliationLink.budget_id == budget_id,
                    ReconciliationLink.bank_source_record_id == link.bank_source_record_id,
                    col(ReconciliationLink.status) == ReconciliationStatus.PENDING.value,
                    col(ReconciliationLink.id) != link.id,
                )
            ).all()
            for pending in superseded_bank_pending:
                session.delete(pending)

            if link.match_kind == ReconciliationMatchKind.EXACT:
                superseded_target_pending = session.exec(
                    select(ReconciliationLink).where(
                        ReconciliationLink.budget_id == budget_id,
                        ReconciliationLink.target_source_record_id == link.target_source_record_id,
                        col(ReconciliationLink.status) == ReconciliationStatus.PENDING.value,
                        col(ReconciliationLink.match_kind).in_(
                            [
                                ReconciliationMatchKind.EXACT.value,
                                ReconciliationMatchKind.SPLIT_PAYMENT.value,
                            ]
                        ),
                        col(ReconciliationLink.id) != link.id,
                    )
                ).all()
                for pending in superseded_target_pending:
                    session.delete(pending)
            elif link.match_kind == ReconciliationMatchKind.SPLIT_PAYMENT:
                superseded_exact_pending = session.exec(
                    select(ReconciliationLink).where(
                        ReconciliationLink.budget_id == budget_id,
                        ReconciliationLink.target_source_record_id == link.target_source_record_id,
                        col(ReconciliationLink.status) == ReconciliationStatus.PENDING.value,
                        col(ReconciliationLink.match_kind) == ReconciliationMatchKind.EXACT.value,
                        col(ReconciliationLink.id) != link.id,
                    )
                ).all()
                for pending in superseded_exact_pending:
                    session.delete(pending)

            session.flush()
    except IntegrityError as exc:
        raise ReconciliationConflictError(
            "Source record is already linked to another incompatible transaction"
        ) from exc

    if target_tx.account_id is not None:
        affected_account_ids.add(target_tx.account_id)
    conn = session.connection()
    for acc_id in affected_account_ids:
        recalculate_account_balance(conn, acc_id)

    if commit:
        session.commit()
    else:
        session.flush()
    session.refresh(link)
    return ReconciliationActionResponse(
        link=_load_link_read(session, link),
        message="Reconciliation link accepted",
    )


def merge_receipt_duplicate_link(
    session: Session,
    *,
    budget_id: int,
    link_id: int,
    user_id: int,
    keep_transaction_id: Optional[int] = None,
    auto_merged: bool = False,
    commit: bool = True,
) -> ReconciliationActionResponse:
    """Reversibly merge a cross-source duplicate receipt into the surviving transaction."""
    link = _get_scoped_link(session, budget_id=budget_id, link_id=link_id)
    if link.match_kind != ReconciliationMatchKind.RECEIPT_DUPLICATE:
        raise ReconciliationConflictError("Selected reconciliation link is not a duplicate receipt match")
    if link.status == ReconciliationStatus.ACCEPTED:
        raise ReconciliationConflictError("Duplicate merge link is already accepted")

    if keep_transaction_id is not None and keep_transaction_id not in (
        link.target_transaction_id,
        link.bank_transaction_id,
    ):
        raise ReconciliationConflictError("keep_transaction_id must match one side of the duplicate pair")

    # If the user chose to keep the incoming/absorbed side, swap directions so
    # bank_transaction_id ALWAYS represents the absorbed child (reconciled_into_id = target).
    if keep_transaction_id is not None and keep_transaction_id == link.bank_transaction_id:
        link.bank_source_record_id, link.target_source_record_id = (
            link.target_source_record_id,
            link.bank_source_record_id,
        )
        link.bank_transaction_id, link.target_transaction_id = (
            link.target_transaction_id,
            link.bank_transaction_id,
        )

    absorbed_sr = session.get(SourceRecord, link.bank_source_record_id)
    surviving_sr = session.get(SourceRecord, link.target_source_record_id)
    absorbed_tx = session.get(Transaction, link.bank_transaction_id)
    surviving_tx = session.get(Transaction, link.target_transaction_id)
    if not absorbed_sr or not surviving_sr or not absorbed_tx or not surviving_tx:
        raise ReconciliationNotFoundError("Underlying transaction or source record not found")
    if (
        absorbed_sr.budget_id != budget_id
        or surviving_sr.budget_id != budget_id
        or absorbed_tx.budget_id != budget_id
        or surviving_tx.budget_id != budget_id
    ):
        raise ReconciliationNotFoundError("Cross-budget duplicate merge is forbidden")
    if (
        absorbed_tx.id == surviving_tx.id
        or surviving_tx.reconciled_into_id is not None
        or absorbed_tx.reconciled_into_id is not None
        or _enum_str(absorbed_tx.review_status) == ReviewStatus.REJECTED.value
        or _enum_str(surviving_tx.review_status) == ReviewStatus.REJECTED.value
    ):
        raise ReconciliationConflictError("Duplicate transactions cannot be merged in their current state")
    if (absorbed_tx.currency or "").upper() != (surviving_tx.currency or "").upper():
        raise ReconciliationConflictError("Transactions with different currencies cannot be merged")

    existing_bank_accepted = session.exec(
        select(ReconciliationLink).where(
            ReconciliationLink.budget_id == budget_id,
            ReconciliationLink.bank_source_record_id == link.bank_source_record_id,
            col(ReconciliationLink.status) == ReconciliationStatus.ACCEPTED.value,
            col(ReconciliationLink.id) != link.id,
        )
    ).first()
    if existing_bank_accepted is not None:
        raise ReconciliationConflictError("Duplicate source record is already linked to another transaction")

    now = datetime.now(timezone.utc)
    affected_account_ids: set[int] = {
        acc_id
        for acc_id in (absorbed_tx.account_id, surviving_tx.account_id)
        if acc_id is not None
    }
    link.previous_receipt_status = _enum_str(surviving_tx.status)
    reasons = dict(link.reasons or {})
    reasons["previous_absorbed_review_status"] = _enum_str(absorbed_tx.review_status)
    reasons["previous_target_account_id"] = surviving_tx.account_id
    reasons["auto_merged"] = auto_merged

    copied_line_ids: list[int] = []
    moved_sr_ids: list[int] = []
    try:
        with session.begin_nested():
            assert surviving_tx.id is not None
            assert absorbed_tx.id is not None

            # Copy itemized basket lines when surviving tx has no lines or only a synthetic manual placeholder.
            surviving_lines = list(
                session.exec(
                    select(TransactionLine).where(TransactionLine.transaction_id == surviving_tx.id)
                ).all()
            )
            absorbed_lines = list(
                session.exec(
                    select(TransactionLine).where(TransactionLine.transaction_id == absorbed_tx.id)
                ).all()
            )
            has_synthetic_manual_placeholder = (
                bool(surviving_tx.is_manual)
                and len(surviving_lines) == 1
                and surviving_lines[0].name in ((surviving_tx.note or ""), "Manual entry", "Transfer")
            )
            if absorbed_lines and (not surviving_lines or has_synthetic_manual_placeholder):
                if has_synthetic_manual_placeholder:
                    orig = surviving_lines[0]
                    reasons["replaced_manual_line"] = {
                        "name": orig.name,
                        "price": str(orig.price),
                        "quantity": str(orig.quantity),
                        "category_id": orig.category_id,
                        "category_source": orig.category_source,
                    }
                    session.delete(orig)
                    session.flush()
                    session.expire(surviving_tx, ["lines"])
                else:
                    reasons.pop("replaced_manual_line", None)

                for src_line in absorbed_lines:
                    cloned = TransactionLine(
                        transaction_id=surviving_tx.id,
                        name=src_line.name,
                        price=src_line.price,
                        quantity=src_line.quantity,
                        category_id=src_line.category_id,
                        category_source=src_line.category_source,
                        original_price=src_line.original_price,
                        discount_total=src_line.discount_total,
                        final_price=src_line.final_price,
                        is_adjustment=src_line.is_adjustment,
                    )
                    session.add(cloned)
                    session.flush()
                    if cloned.id is not None:
                        copied_line_ids.append(cloned.id)

            # Inherit account/category only when the surviving anchor lacked them.
            if surviving_tx.account_id is None and absorbed_tx.account_id is not None:
                reasons["inherited_account_on_accept"] = True
                surviving_tx.account_id = absorbed_tx.account_id
                affected_account_ids.add(absorbed_tx.account_id)
            else:
                reasons.pop("inherited_account_on_accept", None)

            if surviving_tx.category_id is None and absorbed_tx.category_id is not None:
                reasons["inherited_category_on_accept"] = True
                reasons["previous_target_category_id"] = None
                surviving_tx.category_id = absorbed_tx.category_id
            else:
                reasons.pop("inherited_category_on_accept", None)

            if absorbed_sr.id is not None:
                absorbed_sr.transaction_id = surviving_tx.id
                moved_sr_ids.append(absorbed_sr.id)
                session.add(absorbed_sr)

            # Move any additional provenance records attached to the absorbed duplicate.
            extra_srs = list(
                session.exec(
                    select(SourceRecord).where(
                        SourceRecord.budget_id == budget_id,
                        SourceRecord.transaction_id == absorbed_tx.id,
                        col(SourceRecord.id) != link.bank_source_record_id,
                    )
                ).all()
            )
            for extra_sr in extra_srs:
                extra_sr.transaction_id = surviving_tx.id
                if extra_sr.id is not None:
                    moved_sr_ids.append(extra_sr.id)
                session.add(extra_sr)

            absorbed_tx.reconciled_into_id = surviving_tx.id
            absorbed_tx.review_status = ReviewStatus.APPROVED
            session.add(absorbed_tx)
            session.add(surviving_tx)

            reasons["copied_line_ids"] = copied_line_ids
            reasons["moved_source_record_ids"] = moved_sr_ids
            link.reasons = reasons
            link.status = ReconciliationStatus.ACCEPTED
            link.decided_by_user_id = user_id
            link.decided_at = now
            link.updated_at = now
            session.add(link)

            # Remove pending candidates targeting the absorbed child.
            superseded = list(
                session.exec(
                    select(ReconciliationLink).where(
                        ReconciliationLink.budget_id == budget_id,
                        col(ReconciliationLink.status) == ReconciliationStatus.PENDING.value,
                        col(ReconciliationLink.id) != link.id,
                        (
                            (col(ReconciliationLink.bank_transaction_id) == absorbed_tx.id)
                            | (col(ReconciliationLink.target_transaction_id) == absorbed_tx.id)
                        ),
                    )
                ).all()
            )
            for pending in superseded:
                session.delete(pending)

            session.flush()
    except IntegrityError as exc:
        raise ReconciliationConflictError(
            "Duplicate source record is already merged into another transaction"
        ) from exc

    conn = session.connection()
    for acc_id in affected_account_ids:
        recalculate_account_balance(conn, acc_id)

    if commit:
        session.commit()
    else:
        session.flush()
    session.refresh(link)
    return ReconciliationActionResponse(
        link=_load_link_read(session, link),
        message="Duplicate receipt merged cleanly",
    )


def apply_auto_merge_for_transaction(
    session: Session,
    *,
    budget_id: int,
    transaction_id: int,
    user_id: int,
    include_bank_exact: bool = True,
    commit: bool = False,
) -> Optional[ReconciliationLink]:
    """Automatically merge a newly ingested item iff a single unambiguous high-confidence match exists."""
    discover_reconciliation_candidates(session, budget_id=budget_id, commit=False)

    def _try_auto_accept(match_kind: ReconciliationMatchKind) -> Optional[ReconciliationLink]:
        pending_for_tx = list(
            session.exec(
                select(ReconciliationLink).where(
                    ReconciliationLink.budget_id == budget_id,
                    col(ReconciliationLink.match_kind) == match_kind.value,
                    col(ReconciliationLink.status) == ReconciliationStatus.PENDING.value,
                    (
                        (col(ReconciliationLink.bank_transaction_id) == transaction_id)
                        | (col(ReconciliationLink.target_transaction_id) == transaction_id)
                    ),
                )
            ).all()
        )
        if len(pending_for_tx) != 1:
            return None

        candidate = pending_for_tx[0]
        if candidate.id is None:
            return None
        if quantize_score(candidate.score) < AUTO_MERGE_SCORE_THRESHOLD:
            return None

        conflict_count = int((candidate.reasons or {}).get("summary", {}).get("same_day_conflict_count") or 0)
        if conflict_count > 1:
            return None

        other_tx_id = (
            candidate.target_transaction_id
            if candidate.bank_transaction_id == transaction_id
            else candidate.bank_transaction_id
        )
        pending_for_other = list(
            session.exec(
                select(ReconciliationLink.id).where(
                    ReconciliationLink.budget_id == budget_id,
                    col(ReconciliationLink.match_kind) == match_kind.value,
                    col(ReconciliationLink.status) == ReconciliationStatus.PENDING.value,
                    (
                        (col(ReconciliationLink.bank_transaction_id) == other_tx_id)
                        | (col(ReconciliationLink.target_transaction_id) == other_tx_id)
                    ),
                )
            ).all()
        )
        if len(pending_for_other) != 1:
            return None

        if match_kind == ReconciliationMatchKind.RECEIPT_DUPLICATE:
            merge_receipt_duplicate_link(
                session,
                budget_id=budget_id,
                link_id=candidate.id,
                user_id=user_id,
                keep_transaction_id=candidate.target_transaction_id,
                auto_merged=True,
                commit=commit,
            )
        else:
            other_tx = session.get(Transaction, other_tx_id)
            if other_tx is None or _enum_str(other_tx.review_status) != ReviewStatus.APPROVED.value:
                return None
            # Also ensure bank_tx settles as APPROVED when folded into target_tx so it exits Inbox.
            bank_tx_obj = session.get(Transaction, candidate.bank_transaction_id)
            if bank_tx_obj is not None and _enum_str(bank_tx_obj.review_status) == ReviewStatus.PENDING.value:
                bank_tx_obj.review_status = ReviewStatus.APPROVED
                session.add(bank_tx_obj)
                session.flush()
            accept_reconciliation_link(
                session,
                budget_id=budget_id,
                link_id=candidate.id,
                user_id=user_id,
                commit=commit,
            )
        return session.get(ReconciliationLink, candidate.id)

    merged_dup = _try_auto_accept(ReconciliationMatchKind.RECEIPT_DUPLICATE)
    if merged_dup is not None:
        return merged_dup

    if include_bank_exact:
        return _try_auto_accept(ReconciliationMatchKind.EXACT)

    return None


def reject_reconciliation_link(
    session: Session,
    *,
    budget_id: int,
    link_id: int,
    user_id: int,
) -> ReconciliationActionResponse:
    """Persist explicit rejection so future CSV re-imports do not re-propose the pair."""
    link = _get_scoped_link(session, budget_id=budget_id, link_id=link_id)
    if link.status == ReconciliationStatus.ACCEPTED:
        raise ReconciliationConflictError("Unlink an accepted match before rejecting it")

    now = datetime.now(timezone.utc)
    link.status = ReconciliationStatus.REJECTED
    link.decided_by_user_id = user_id
    link.decided_at = now
    link.updated_at = now
    session.add(link)
    session.commit()
    session.refresh(link)
    return ReconciliationActionResponse(
        link=_load_link_read(session, link),
        message="Reconciliation candidate rejected",
    )


def _revert_transaction_status(tx: Transaction, previous_status: Optional[str]) -> None:
    if previous_status:
        try:
            tx.status = TransactionStatus(previous_status)
            return
        except ValueError:
            pass
    tx.status = TransactionStatus.UNCLEARED


def unlink_reconciliation_link(
    session: Session,
    *,
    budget_id: int,
    link_id: int,
    user_id: int,
) -> ReconciliationActionResponse:
    """Reversibly unlink a previously accepted reconciliation link."""
    link = _get_scoped_link(session, budget_id=budget_id, link_id=link_id)
    if link.status != ReconciliationStatus.ACCEPTED:
        raise ReconciliationConflictError("Only accepted reconciliation links can be unlinked")

    bank_sr = session.get(SourceRecord, link.bank_source_record_id)
    bank_tx = session.get(Transaction, link.bank_transaction_id)
    target_tx = session.get(Transaction, link.target_transaction_id)

    affected_account_ids: set[int] = {
        acc_id
        for acc_id in (
            bank_tx.account_id if bank_tx is not None else None,
            target_tx.account_id if target_tx is not None else None,
        )
        if acc_id is not None
    }

    now = datetime.now(timezone.utc)
    if link.match_kind == ReconciliationMatchKind.RECEIPT_DUPLICATE:
        reasons = link.reasons or {}
        moved_sr_ids = [int(x) for x in (reasons.get("moved_source_record_ids") or []) if x is not None]
        if not moved_sr_ids and bank_sr is not None and bank_sr.id is not None:
            moved_sr_ids = [bank_sr.id]
        if moved_sr_ids:
            moved_srs = session.exec(select(SourceRecord).where(col(SourceRecord.id).in_(moved_sr_ids))).all()
            for sr in moved_srs:
                sr.transaction_id = link.bank_transaction_id
                session.add(sr)

        if bank_tx is not None:
            bank_tx.reconciled_into_id = None
            prev_review = reasons.get("previous_absorbed_review_status")
            if prev_review:
                try:
                    bank_tx.review_status = ReviewStatus(prev_review)
                except ValueError:
                    pass
            session.add(bank_tx)

        if target_tx is not None:
            copied_line_ids = [int(x) for x in (reasons.get("copied_line_ids") or []) if x is not None]
            if copied_line_ids:
                copied_lines = session.exec(
                    select(TransactionLine).where(
                        col(TransactionLine.id).in_(copied_line_ids),
                        TransactionLine.transaction_id == target_tx.id,
                    )
                ).all()
                for cline in copied_lines:
                    session.delete(cline)

            replaced_manual = reasons.get("replaced_manual_line")
            if isinstance(replaced_manual, dict) and target_tx.id is not None:
                session.add(
                    TransactionLine(
                        transaction_id=target_tx.id,
                        name=str(replaced_manual.get("name") or "Manual entry"),
                        price=Decimal(str(replaced_manual.get("price") or "0.00")),
                        quantity=Decimal(str(replaced_manual.get("quantity") or "1")),
                        category_id=replaced_manual.get("category_id"),
                        category_source=replaced_manual.get("category_source"),
                    )
                )

            if reasons.get("inherited_account_on_accept"):
                prev_acc_id = reasons.get("previous_target_account_id", None)
                target_tx.account_id = prev_acc_id
                if prev_acc_id is not None:
                    affected_account_ids.add(prev_acc_id)
            if reasons.get("inherited_category_on_accept"):
                target_tx.category_id = reasons.get("previous_target_category_id", None)
            session.add(target_tx)
    elif link.match_kind in (ReconciliationMatchKind.EXACT, ReconciliationMatchKind.SPLIT_PAYMENT):
        if bank_sr is not None:
            bank_sr.transaction_id = link.bank_transaction_id
            session.add(bank_sr)
        if bank_tx is not None:
            bank_tx.reconciled_into_id = None
            session.add(bank_tx)
        if target_tx is not None:
            remaining_purchase_accepted = session.exec(
                select(ReconciliationLink).where(
                    ReconciliationLink.budget_id == budget_id,
                    ReconciliationLink.target_transaction_id == link.target_transaction_id,
                    col(ReconciliationLink.status) == ReconciliationStatus.ACCEPTED.value,
                    col(ReconciliationLink.match_kind).in_(
                        [
                            ReconciliationMatchKind.EXACT.value,
                            ReconciliationMatchKind.SPLIT_PAYMENT.value,
                        ]
                    ),
                    col(ReconciliationLink.id) != link.id,
                )
            ).all()
            reasons = link.reasons or {}
            if link.match_kind == ReconciliationMatchKind.EXACT and (
                reasons.get("account_updated_on_accept") or reasons.get("inherited_account_on_accept")
            ):
                prev_acc_id = reasons.get("previous_target_account_id", None)
                target_tx.account_id = prev_acc_id
                if prev_acc_id is not None:
                    affected_account_ids.add(prev_acc_id)

            if not remaining_purchase_accepted:
                if link.previous_receipt_status:
                    _revert_transaction_status(target_tx, link.previous_receipt_status)
            elif link.match_kind == ReconciliationMatchKind.SPLIT_PAYMENT:
                rem_ids = [r.bank_transaction_id for r in remaining_purchase_accepted]
                rem_txs = session.exec(select(Transaction).where(col(Transaction.id).in_(rem_ids))).all()
                rem_sum = sum((quantize_money(abs(t.total_amount)) for t in rem_txs), Decimal("0.00"))
                if abs(rem_sum - quantize_money(abs(target_tx.total_amount))) > MONEY_QUANT and link.previous_receipt_status:
                    _revert_transaction_status(target_tx, link.previous_receipt_status)
            session.add(target_tx)

    link.status = ReconciliationStatus.UNLINKED
    link.decided_by_user_id = user_id
    link.decided_at = now
    link.updated_at = now
    session.add(link)
    session.flush()

    conn = session.connection()
    for acc_id in affected_account_ids:
        recalculate_account_balance(conn, acc_id)

    session.commit()
    session.refresh(link)
    return ReconciliationActionResponse(
        link=_load_link_read(session, link),
        message="Reconciliation link unlinked",
    )


def cleanup_reconciliation_before_transaction_delete(session: Session, *, transaction_id: int) -> None:
    """Restore any reconciled bank transactions/targets and delete affected links cleanly via ORM."""
    affected_account_ids: set[int] = set()

    # Any bank transaction that had been folded into the deleted target becomes standalone again.
    child_bank_txs = session.exec(
        select(Transaction).where(Transaction.reconciled_into_id == transaction_id)
    ).all()
    for child in child_bank_txs:
        child.reconciled_into_id = None
        if child.account_id is not None:
            affected_account_ids.add(child.account_id)
        session.add(child)

    source_ids = list(
        session.exec(select(SourceRecord.id).where(SourceRecord.transaction_id == transaction_id)).all()
    )
    clean_sr_ids = [sr_id for sr_id in source_ids if sr_id is not None]

    link_where = (col(ReconciliationLink.bank_transaction_id) == transaction_id) | (
        col(ReconciliationLink.target_transaction_id) == transaction_id
    )
    if clean_sr_ids:
        link_where = (
            link_where
            | col(ReconciliationLink.bank_source_record_id).in_(clean_sr_ids)
            | col(ReconciliationLink.target_source_record_id).in_(clean_sr_ids)
        )

    links_to_delete = list(session.exec(select(ReconciliationLink).where(link_where)).all())
    deleted_link_ids = {link.id for link in links_to_delete if link.id is not None}

    seen_links: set[int] = set()
    for link in links_to_delete:
        if link.id is not None:
            if link.id in seen_links:
                continue
            seen_links.add(link.id)

        if link.target_transaction_id == transaction_id and link.status == ReconciliationStatus.ACCEPTED and link.bank_transaction_id != transaction_id:
            bank_sr = session.get(SourceRecord, link.bank_source_record_id)
            if bank_sr is not None and bank_sr.transaction_id == transaction_id:
                bank_sr.transaction_id = link.bank_transaction_id
                session.add(bank_sr)
            reasons = link.reasons or {}
            moved_sr_ids = [int(x) for x in (reasons.get("moved_source_record_ids") or []) if x is not None]
            if moved_sr_ids:
                for sr in session.exec(select(SourceRecord).where(col(SourceRecord.id).in_(moved_sr_ids))).all():
                    if sr.transaction_id == transaction_id:
                        sr.transaction_id = link.bank_transaction_id
                        session.add(sr)
        elif (
            link.bank_transaction_id == transaction_id
            and link.status == ReconciliationStatus.ACCEPTED
            and link.match_kind == ReconciliationMatchKind.RECEIPT_DUPLICATE
            and link.target_transaction_id != transaction_id
        ):
            reasons = link.reasons or {}
            moved_sr_ids = [int(x) for x in (reasons.get("moved_source_record_ids") or []) if x is not None]
            if not moved_sr_ids:
                moved_sr_ids = [link.bank_source_record_id]
            for sr in session.exec(select(SourceRecord).where(col(SourceRecord.id).in_(moved_sr_ids))).all():
                if sr.transaction_id != transaction_id:
                    sr.transaction_id = transaction_id
                    session.add(sr)
            target_tx = session.get(Transaction, link.target_transaction_id)
            if target_tx is not None:
                if target_tx.account_id is not None:
                    affected_account_ids.add(target_tx.account_id)
                copied_line_ids = [int(x) for x in (reasons.get("copied_line_ids") or []) if x is not None]
                if copied_line_ids:
                    for cline in session.exec(
                        select(TransactionLine).where(
                            col(TransactionLine.id).in_(copied_line_ids),
                            TransactionLine.transaction_id == target_tx.id,
                        )
                    ).all():
                        session.delete(cline)
                replaced_manual = reasons.get("replaced_manual_line")
                if isinstance(replaced_manual, dict) and target_tx.id is not None:
                    session.add(
                        TransactionLine(
                            transaction_id=target_tx.id,
                            name=str(replaced_manual.get("name") or "Manual entry"),
                            price=Decimal(str(replaced_manual.get("price") or "0.00")),
                            quantity=Decimal(str(replaced_manual.get("quantity") or "1")),
                            category_id=replaced_manual.get("category_id"),
                            category_source=replaced_manual.get("category_source"),
                        )
                    )
                if reasons.get("inherited_account_on_accept"):
                    prev_acc_id = reasons.get("previous_target_account_id", None)
                    target_tx.account_id = prev_acc_id
                    if prev_acc_id is not None:
                        affected_account_ids.add(prev_acc_id)
                session.add(target_tx)
        elif (
            link.bank_transaction_id == transaction_id
            and link.status == ReconciliationStatus.ACCEPTED
            and link.match_kind in (ReconciliationMatchKind.EXACT, ReconciliationMatchKind.SPLIT_PAYMENT)
            and link.target_transaction_id != transaction_id
        ):
            # Re-attach bank_sr back to the deleted bank_tx so caller deletes it without leaving an orphan on target_tx.
            bank_sr = session.get(SourceRecord, link.bank_source_record_id)
            if bank_sr is not None and bank_sr.transaction_id != transaction_id:
                bank_sr.transaction_id = transaction_id
                session.add(bank_sr)

            target_tx = session.get(Transaction, link.target_transaction_id)
            if target_tx is not None:
                if target_tx.account_id is not None:
                    affected_account_ids.add(target_tx.account_id)
                reasons = link.reasons or {}
                if link.match_kind == ReconciliationMatchKind.EXACT:
                    if reasons.get("account_updated_on_accept") or reasons.get("inherited_account_on_accept"):
                        prev_acc_id = reasons.get("previous_target_account_id", None)
                        target_tx.account_id = prev_acc_id
                        if prev_acc_id is not None:
                            affected_account_ids.add(prev_acc_id)
                    if link.previous_receipt_status:
                        _revert_transaction_status(target_tx, link.previous_receipt_status)
                else:
                    remaining_purchase_links = [
                        rem
                        for rem in session.exec(
                            select(ReconciliationLink).where(
                                col(ReconciliationLink.target_transaction_id) == link.target_transaction_id,
                                col(ReconciliationLink.status) == ReconciliationStatus.ACCEPTED.value,
                                col(ReconciliationLink.match_kind).in_(
                                    [
                                        ReconciliationMatchKind.EXACT.value,
                                        ReconciliationMatchKind.SPLIT_PAYMENT.value,
                                    ]
                                ),
                            )
                        ).all()
                        if rem.id not in deleted_link_ids
                    ]
                    if not remaining_purchase_links:
                        if link.previous_receipt_status:
                            _revert_transaction_status(target_tx, link.previous_receipt_status)
                    else:
                        rem_ids = [r.bank_transaction_id for r in remaining_purchase_links]
                        rem_txs = session.exec(select(Transaction).where(col(Transaction.id).in_(rem_ids))).all()
                        rem_sum = sum((quantize_money(abs(t.total_amount)) for t in rem_txs), Decimal("0.00"))
                        if abs(rem_sum - quantize_money(abs(target_tx.total_amount))) > MONEY_QUANT and link.previous_receipt_status:
                            _revert_transaction_status(target_tx, link.previous_receipt_status)
                session.add(target_tx)

        session.delete(link)

    session.flush()
    if affected_account_ids:
        conn = session.connection()
        for acc_id in affected_account_ids:
            recalculate_account_balance(conn, acc_id)


def cleanup_reconciliation_for_budget(session: Session, *, budget_id: int) -> None:
    """Delete all reconciliation links belonging to ``budget_id``."""
    session.exec(delete(ReconciliationLink).where(col(ReconciliationLink.budget_id) == budget_id))
