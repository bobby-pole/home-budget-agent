"""Dual source adapter contracts separating receipt ingestion from bank flows (#259).

Key architectural boundary:
- ``ReceiptSourceAdapter`` produces ``ReceiptAdapterResult`` carrying ``CanonicalReceipt``
  (store basket line items, VAT/tax hints, discounts, deposits).
- ``TransactionSourceAdapter`` produces ``TransactionBatchAdapterResult`` carrying
  ``CanonicalTransaction`` (bank account cashflows).
- Bank CSV/PDF adapters MUST implement ``TransactionSourceAdapter`` only and NEVER
  implement ``ReceiptSourceAdapter``; receipt-bank reconciliation lives in Import Inbox.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Literal, Optional

from app.models import RawPayloadPolicy, SourceType, ensure_tz_aware
from app.money import quantize_money, quantize_score
from app.provenance_service import normalize_external_id, normalize_hash
from app.receipt_schema import CanonicalReceipt

_ZERO = Decimal("0")


class AdapterContractError(ValueError):
    """Base error raised when an external or uploaded source breaks an adapter contract."""


class AdapterParseError(AdapterContractError):
    """Raised when source bytes cannot be decoded or parsed into the adapter structure."""


class AdapterSchemaError(AdapterContractError):
    """Raised when required source fields are missing or irreparably drifted."""


def degrade_quality(
    base_quality: Decimal | str | int,
    penalty: Decimal | str | int,
    *,
    floor: Decimal = Decimal("0.1000"),
) -> Decimal:
    """Apply a quantized score penalty while keeping the quality score within [0, 1]."""
    base = quantize_score(base_quality)
    pen = quantize_score(penalty)
    lowered = max(floor, base - pen)
    return quantize_score(min(Decimal("1"), lowered))


@dataclass(frozen=True)
class SourceProvenanceSpec:
    """Standardized provenance blueprint mapped by shared ingestion into ``SourceRecord``."""

    source_type: SourceType
    provider: str
    external_id: Optional[str] = None
    canonical_hash: Optional[str] = None
    adapter_version: str = "1.0"
    acquired_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    raw_payload_policy: RawPayloadPolicy = RawPayloadPolicy.NONE
    connection_id: Optional[int] = None

    def __post_init__(self) -> None:
        clean_provider = self.provider.strip() or self.source_type.value.lower()
        aware_dt = ensure_tz_aware(self.acquired_at) or datetime.now(timezone.utc)
        object.__setattr__(self, "provider", clean_provider)
        object.__setattr__(self, "external_id", normalize_external_id(self.external_id))
        object.__setattr__(self, "canonical_hash", normalize_hash(self.canonical_hash))
        object.__setattr__(self, "acquired_at", aware_dt)


@dataclass
class CanonicalTransaction:
    """Canonical representation of a bank statement cashflow entry (never a receipt basket)."""

    booked_at: datetime
    amount: Decimal
    currency: str = "PLN"
    counterparty: str = ""
    title: str = ""
    value_at: Optional[datetime] = None
    tx_type_hint: Optional[str] = None
    category_hint: Optional[str] = None
    notes: Optional[str] = None

    def __post_init__(self) -> None:
        aware_booked = ensure_tz_aware(self.booked_at)
        if aware_booked is None:
            raise AdapterSchemaError("booked_at must be a valid timestamp")
        self.booked_at = aware_booked
        self.value_at = ensure_tz_aware(self.value_at) if self.value_at is not None else None
        self.amount = quantize_money(self.amount)
        self.currency = (self.currency or "PLN").strip().upper() or "PLN"
        self.counterparty = (self.counterparty or "").strip()
        self.title = (self.title or "").strip()

    @property
    def abs_amount(self) -> Decimal:
        """Absolute quantized monetary magnitude of the cashflow."""
        return quantize_money(abs(self.amount))

    @property
    def direction(self) -> Literal["debit", "credit"]:
        """Return 'debit' for outflows (< 0) and 'credit' for inflows (>= 0)."""
        return "debit" if self.amount < _ZERO else "credit"


@dataclass
class ReceiptAdapterResult:
    """Standardized output contract returned by all ``ReceiptSourceAdapter`` providers."""

    receipt: CanonicalReceipt
    provenance: SourceProvenanceSpec
    warnings: list[str] = field(default_factory=list)
    quality: Decimal = Decimal("1.0000")
    processed_via: Optional[str] = None
    validation_status: str = "verified"
    validation_message: Optional[str] = None
    raw_ocr_text: Optional[str] = None
    reconstructed_lines: Optional[list[str]] = None

    def __post_init__(self) -> None:
        self.quality = quantize_score(self.quality)


@dataclass
class TransactionAdapterResult:
    """Standardized output contract for a single bank transaction extracted by an adapter."""

    transaction: CanonicalTransaction
    provenance: SourceProvenanceSpec
    warnings: list[str] = field(default_factory=list)
    quality: Decimal = Decimal("0.9500")

    def __post_init__(self) -> None:
        self.quality = quantize_score(self.quality)


@dataclass
class TransactionBatchAdapterResult:
    """Batch output returned by ``TransactionSourceAdapter`` statement parsers."""

    items: list[TransactionAdapterResult] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class ReceiptSourceAdapter(ABC):
    """Abstract contract for retail receipt, e-Paragon, and receipt OCR/PDF sources."""

    provider: str
    source_type: SourceType
    adapter_version: str

    @abstractmethod
    def extract(
        self,
        payload: Any,
        *,
        budget_id: int,
        connection_id: Optional[int] = None,
        filename: str = "",
        raw_payload_policy: Optional[RawPayloadPolicy] = None,
    ) -> ReceiptAdapterResult:
        """Normalize a raw merchant/receipt payload into ``ReceiptAdapterResult``."""


class TransactionSourceAdapter(ABC):
    """Abstract contract for bank statement / account cashflow sources (CSV, PDF, PSD2)."""

    provider: str
    source_type: SourceType = SourceType.BANK_CSV
    adapter_version: str

    @abstractmethod
    def extract_transactions(
        self,
        payload: bytes,
        *,
        budget_id: int,
        connection_id: Optional[int] = None,
        filename: str = "",
        raw_payload_policy: RawPayloadPolicy = RawPayloadPolicy.NONE,
    ) -> TransactionBatchAdapterResult:
        """Parse bank statement bytes into ``TransactionBatchAdapterResult``."""
