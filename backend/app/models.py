# backend/app/models.py
from enum import Enum
from decimal import Decimal
from typing import Any, List, Optional
from datetime import date, datetime, timezone
from pydantic import field_validator
from sqlalchemy import UniqueConstraint, Index, String, Column, JSON, Numeric, DateTime, TypeDecorator, event, or_, select, text, update, Boolean
from sqlmodel import Field, Relationship, SQLModel, col
from sqlmodel._compat import SQLModelConfig

from app.money import MoneyDecimal, QuantityDecimal, ScoreDecimal, UnitPriceDecimal, quantize_money


def ensure_tz_aware(v: Any) -> Optional[datetime]:
    """Coerce string or naive datetime into a UTC-aware datetime.

    Prevents SQLModel/SQLAlchemy StatementError when writing naive datetimes
    to timezone-aware columns:
    'Datetime values must have timezone information. Use datetime.now(timezone.utc)...'
    """
    if v is None:
        return None
    if isinstance(v, str):
        v = v.strip()
        if not v:
            return None
        if len(v) == 10 and v.count("-") == 2:
            try:
                return datetime.strptime(v, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            except ValueError:
                pass
        try:
            dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                return dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            pass
    elif isinstance(v, datetime):
        if v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v
    elif isinstance(v, date):
        return datetime.combine(v, datetime.min.time(), tzinfo=timezone.utc)
    return v


class UTCDateTime(TypeDecorator):
    """Normalize datetimes to UTC on bind and restore tzinfo on SQLite reads."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Any) -> Optional[datetime]:
        dt = ensure_tz_aware(value)
        if isinstance(dt, datetime):
            return dt.astimezone(timezone.utc)
        return None

    def process_result_value(self, value: Any, dialect: Any) -> Optional[datetime]:
        dt = ensure_tz_aware(value)
        if isinstance(dt, datetime):
            return dt.astimezone(timezone.utc)
        return None


class ScanStatus(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    OCR_OK = "OCR_OK"
    PARSING_OK = "PARSING_OK"
    CATEGORIZATION_OK = "CATEGORIZATION_OK"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    DONE = "DONE"
    FAILED = "FAILED"

    @classmethod
    def _missing_(cls, value: object) -> "ScanStatus":
        _legacy_map = {
            "processing": cls.RUNNING,
            "done": cls.DONE,
            "error": cls.FAILED,
            "needs_review": cls.NEEDS_REVIEW,
            "categorization_ok": cls.CATEGORIZATION_OK,
        }
        if isinstance(value, str):
            mapped = _legacy_map.get(value.lower())
            if mapped is not None:
                return mapped
        return cls.FAILED


class TransactionStatus(str, Enum):
    CLEARED = "cleared"
    UNCLEARED = "uncleared"
    PENDING = "pending"


class ReviewStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class AutoMergePolicy(str, Enum):
    AUTO = "auto"
    MANUAL = "manual"


class SourceType(str, Enum):
    MERCHANT_API = "MERCHANT_API"
    E_RECEIPT = "E_RECEIPT"
    BANK_CSV = "BANK_CSV"
    OCR_PHOTO = "OCR_PHOTO"
    MANUAL = "MANUAL"


class RawPayloadPolicy(str, Enum):
    NONE = "none"
    EPHEMERAL_IMAGE = "ephemeral_image"
    RETAINED_IMAGE = "retained_image"
    CANONICAL_ONLY = "canonical_only"


# ─── User ─────────────────────────────────────────────────────────────────────

class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(unique=True, index=True)
    hashed_password: str
    default_budget_id: Optional[int] = Field(default=None, foreign_key="budget.id", ondelete="SET NULL")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    owned_budgets: List["Budget"] = Relationship(
        back_populates="owner",
        sa_relationship_kwargs={"foreign_keys": "[Budget.owner_id]"}
    )
    memberships: List["BudgetMember"] = Relationship(back_populates="user")
    transactions: List["Transaction"] = Relationship(back_populates="uploader")
    receipt_connections: List["ExternalReceiptConnection"] = Relationship(back_populates="owner")


# ─── Budget (multi-tenant household container) ────────────────────────────────

class BudgetCreate(SQLModel):
    name: str

class BudgetUpdate(SQLModel):
    name: str

class Budget(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    owner_id: Optional[int] = Field(default=None, foreign_key="user.id")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    owner: Optional[User] = Relationship(
        back_populates="owned_budgets",
        sa_relationship_kwargs={"foreign_keys": "[Budget.owner_id]"}
    )
    members: List["BudgetMember"] = Relationship(back_populates="budget")
    transactions: List["Transaction"] = Relationship(back_populates="budget")
    envelope_allocations: List["EnvelopeAllocation"] = Relationship(back_populates="budget")
    accounts: List["Account"] = Relationship(back_populates="budget")
    receipt_connections: List["ExternalReceiptConnection"] = Relationship(back_populates="budget")


# ─── BudgetMember ─────────────────────────────────────────────────────────────

class BudgetMember(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    budget_id: Optional[int] = Field(default=None, foreign_key="budget.id")
    user_id: Optional[int] = Field(default=None, foreign_key="user.id")
    role: str = Field(default="viewer")  # owner / editor / viewer

    budget: Optional[Budget] = Relationship(back_populates="members")
    user: Optional[User] = Relationship(back_populates="memberships")


# ─── Account ──────────────────────────────────────────────────────────────────

ACCOUNT_TYPES = {
    "checking",
    "savings",
    "cash",
    "credit",
    "tracking_asset",
    "tracking_liability",
}


class AccountBase(SQLModel):
    name: str = Field(min_length=1, max_length=120)
    type: str = Field(default="checking")  # checking, savings, cash, credit, tracking_asset, tracking_liability
    currency: str = Field(default="PLN", min_length=3, max_length=3)
    initial_balance: MoneyDecimal = Field(default=Decimal("0.00"), sa_type=Numeric(12, 2))  # type: ignore[arg-type]
    current_balance: MoneyDecimal = Field(default=Decimal("0.00"), sa_type=Numeric(12, 2))  # type: ignore[arg-type]
    is_on_budget: bool = Field(default=True)
    is_active: bool = Field(default=True)
    category_id: Optional[int] = Field(default=None, foreign_key="category.id")

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Account name cannot be blank")
        return value

    @field_validator("type")
    @classmethod
    def validate_type(cls, value: str) -> str:
        value = value.strip().lower()
        if value not in ACCOUNT_TYPES:
            raise ValueError(f"Unsupported account type: {value}")
        return value

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, value: str) -> str:
        value = value.strip().upper()
        if len(value) != 3 or not value.isalpha():
            raise ValueError("Currency must be a three-letter ISO code")
        return value

    @field_validator("initial_balance", "current_balance")
    @classmethod
    def validate_balance(cls, value: Decimal) -> Decimal:
        if not value.is_finite():
            raise ValueError("Balance must be finite")
        return value


class Account(AccountBase, table=True):
    __tablename__: str = "account"  # type: ignore

    id: Optional[int] = Field(default=None, primary_key=True)
    budget_id: Optional[int] = Field(default=None, foreign_key="budget.id", index=True)

    budget: Optional[Budget] = Relationship(back_populates="accounts")
    transactions: List["Transaction"] = Relationship(
        back_populates="account",
        sa_relationship_kwargs={"foreign_keys": "[Transaction.account_id]"}
    )
    transfers_in: List["Transaction"] = Relationship(
        back_populates="transfer_account",
        sa_relationship_kwargs={"foreign_keys": "[Transaction.transfer_id]"}
    )
    category: Optional["Category"] = Relationship(back_populates="accounts")


# ─── Category & Tag ───────────────────────────────────────────────────────────

class CategoryBase(SQLModel):
    name: str
    icon: Optional[str] = None
    color: Optional[str] = None
    is_system: bool = False
    parent_id: Optional[int] = Field(default=None, foreign_key="category.id")
    order_index: int = Field(default=0)


class Category(CategoryBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    budget_id: Optional[int] = Field(default=None, foreign_key="budget.id")

    parent: Optional["Category"] = Relationship(
        back_populates="subcategories",
        sa_relationship_kwargs=dict(remote_side="Category.id")
    )
    subcategories: List["Category"] = Relationship(back_populates="parent")
    transactions: List["Transaction"] = Relationship(back_populates="category")
    envelope_allocations: List["EnvelopeAllocation"] = Relationship(back_populates="category")
    accounts: List["Account"] = Relationship(back_populates="category")


class ProductCategoryCache(SQLModel, table=True):
    __tablename__: str = "product_category_cache"  # type: ignore
    __table_args__ = (
        UniqueConstraint("user_id", "normalized_name", name="uq_user_normalized_name"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    normalized_name: str = Field(index=True)
    original_name: str
    category_id: int = Field(foreign_key="category.id")
    hit_count: int = Field(default=1)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class TagBase(SQLModel):
    name: str
    color: Optional[str] = None


class TransactionTagLink(SQLModel, table=True):
    transaction_id: Optional[int] = Field(default=None, foreign_key="transaction.id", primary_key=True)
    tag_id: Optional[int] = Field(default=None, foreign_key="tag.id", primary_key=True)


class Tag(TagBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    budget_id: Optional[int] = Field(default=None, foreign_key="budget.id")

    transactions: List["Transaction"] = Relationship(back_populates="tags", link_model=TransactionTagLink)


# ─── Transaction ──────────────────────────────────────────────────────────────

class TransactionBase(SQLModel):
    merchant_name: str = Field(index=True)
    date: Optional[datetime] = Field(default=None)
    total_amount: MoneyDecimal = Field(default=Decimal("0.00"), sa_type=Numeric(12, 2))  # type: ignore[arg-type]
    currency: str = Field(default="PLN")
    is_manual: bool = Field(default=False)
    type: str = Field(default="expense")  # expense | income | transfer
    status: TransactionStatus = Field(
        default=TransactionStatus.UNCLEARED,
        sa_column=Column(String, index=True, nullable=False, server_default=TransactionStatus.UNCLEARED.value),
    )
    review_status: ReviewStatus = Field(
        default=ReviewStatus.APPROVED,
        sa_column=Column(String, index=True, nullable=False, server_default=ReviewStatus.APPROVED.value),
    )
    import_hash: Optional[str] = Field(default=None, index=True)
    account_id: Optional[int] = Field(default=None, foreign_key="account.id", index=True)
    transfer_id: Optional[int] = Field(default=None, foreign_key="account.id", index=True)

    @field_validator("date", mode="before")
    @classmethod
    def validate_date_tz(cls, v: Any) -> Optional[datetime]:
        return ensure_tz_aware(v)


class Transaction(TransactionBase, table=True):
    __tablename__: str = "transaction"  # type: ignore
    __table_args__ = (
        Index("ix_transaction_budget_type_date", "budget_id", "type", "date"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    note: Optional[str] = Field(default=None)
    budget_id: Optional[int] = Field(default=None, foreign_key="budget.id", index=True)
    uploaded_by: Optional[int] = Field(default=None, foreign_key="user.id")
    category_id: Optional[int] = Field(default=None, foreign_key="category.id")
    reconciled_into_id: Optional[int] = Field(default=None, foreign_key="transaction.id", index=True)
    rejected_at: Optional[datetime] = Field(default=None, sa_column=Column(UTCDateTime(), nullable=True))
    rejection_reason: Optional[str] = Field(default=None)
    import_batch_id: Optional[str] = Field(default=None, index=True)

    @field_validator("rejected_at", mode="before")
    @classmethod
    def validate_rejected_at_tz(cls, v: Any) -> Optional[datetime]:
        return ensure_tz_aware(v)

    lines: List["TransactionLine"] = Relationship(
        back_populates="transaction",
        sa_relationship_kwargs={"lazy": "selectin"},
    )
    receipt_scan: Optional["ReceiptScan"] = Relationship(
        back_populates="transaction",
        sa_relationship_kwargs={"lazy": "selectin"},
    )
    budget: Optional[Budget] = Relationship(back_populates="transactions")
    uploader: Optional[User] = Relationship(back_populates="transactions")
    category: Optional["Category"] = Relationship(back_populates="transactions")
    tags: List["Tag"] = Relationship(
        back_populates="transactions",
        link_model=TransactionTagLink,
        sa_relationship_kwargs={"lazy": "selectin"},
    )
    account: Optional[Account] = Relationship(
        back_populates="transactions",
        sa_relationship_kwargs={"foreign_keys": "[Transaction.account_id]"}
    )
    transfer_account: Optional[Account] = Relationship(
        back_populates="transfers_in",
        sa_relationship_kwargs={"foreign_keys": "[Transaction.transfer_id]"}
    )
    source_records: List["SourceRecord"] = Relationship(
        back_populates="transaction",
        sa_relationship_kwargs={"lazy": "selectin", "passive_deletes": True},
    )


# ─── ReceiptScan ──────────────────────────────────────────────────────────────

class ReceiptScan(SQLModel, table=True):
    __tablename__: str = "receiptscan"  # type: ignore

    id: Optional[int] = Field(default=None, primary_key=True)
    transaction_id: int = Field(foreign_key="transaction.id", index=True)
    image_path: Optional[str] = None
    status: str = Field(
        sa_column=Column(String, index=True, nullable=False, default=ScanStatus.QUEUED.value),
    )
    processed_via: Optional[str] = Field(default=None)
    error_message: Optional[str] = Field(default=None)
    content_hash: Optional[str] = Field(default=None, index=True)
    keep_image: bool = Field(default=False)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    validation_message: Optional[str] = Field(default=None)
    original_date: Optional[str] = Field(default=None)
    raw_ocr_text: Optional[str] = Field(default=None)
    reconstructed_lines: Optional[list[str]] = Field(default=None, sa_column=Column(JSON))
    needs_review: bool = Field(
        default=False,
        sa_column=Column(Boolean, index=True, nullable=False, server_default=text("0")),
    )

    transaction: Optional[Transaction] = Relationship(back_populates="receipt_scan")
    source_records: List["SourceRecord"] = Relationship(
        back_populates="receipt_scan",
        sa_relationship_kwargs={"lazy": "selectin", "passive_deletes": True},
    )


# ─── SourceRecord (Provenance & Idempotency) ─────────────────────────────────

class SourceRecord(SQLModel, table=True):
    """Immutable provenance and idempotency anchor for every ingested or manual financial record."""

    __tablename__: str = "source_record"  # type: ignore
    __table_args__ = (
        Index(
            "uq_source_record_budget_provider_external_id",
            "budget_id",
            "provider",
            "external_id",
            unique=True,
            sqlite_where=text("external_id IS NOT NULL"),
            postgresql_where=text("external_id IS NOT NULL"),
        ),
        Index(
            "uq_source_record_budget_canonical_hash",
            "budget_id",
            "canonical_hash",
            unique=True,
            sqlite_where=text("canonical_hash IS NOT NULL"),
            postgresql_where=text("canonical_hash IS NOT NULL"),
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    budget_id: int = Field(foreign_key="budget.id", index=True)
    transaction_id: Optional[int] = Field(
        default=None, foreign_key="transaction.id", index=True, ondelete="CASCADE"
    )
    receipt_scan_id: Optional[int] = Field(
        default=None, foreign_key="receiptscan.id", index=True, ondelete="SET NULL"
    )
    connection_id: Optional[int] = Field(
        default=None, foreign_key="external_receipt_connection.id", index=True, ondelete="SET NULL"
    )
    source_type: SourceType = Field(sa_column=Column(String, index=True, nullable=False))
    provider: str = Field(index=True)
    external_id: Optional[str] = Field(default=None)
    canonical_hash: Optional[str] = Field(default=None)
    adapter_version: str = Field(default="1.0")
    acquired_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    quality: Optional[ScoreDecimal] = Field(default=None, sa_type=Numeric(5, 4))  # type: ignore[arg-type]
    raw_payload_policy: RawPayloadPolicy = Field(
        default=RawPayloadPolicy.NONE,
        sa_column=Column(String, nullable=False, server_default=RawPayloadPolicy.NONE.value),
    )

    transaction: Optional[Transaction] = Relationship(back_populates="source_records")
    receipt_scan: Optional[ReceiptScan] = Relationship(back_populates="source_records")

    @field_validator("acquired_at", mode="before")
    @classmethod
    def validate_acquired_at_tz(cls, v: Any) -> Optional[datetime]:
        return ensure_tz_aware(v)


class ReconciliationStatus(str, Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    UNLINKED = "unlinked"


class ReconciliationMatchKind(str, Enum):
    EXACT = "exact"
    REFUND = "refund"
    SPLIT_PAYMENT = "split_payment"
    RECEIPT_DUPLICATE = "receipt_duplicate"


class ReconciliationLink(SQLModel, table=True):
    """Persistent, reversible reconciliation candidate or link between a bank source and a receipt/manual source."""

    __tablename__: str = "reconciliation_link"  # type: ignore
    __table_args__ = (
        UniqueConstraint(
            "budget_id",
            "bank_source_record_id",
            "target_source_record_id",
            name="uq_reconciliation_budget_source_pair",
        ),
        Index(
            "uq_reconciliation_active_bank_source",
            "bank_source_record_id",
            unique=True,
            sqlite_where=text("status = 'accepted'"),
            postgresql_where=text("status = 'accepted'"),
        ),
        Index(
            "uq_reconciliation_active_target_purchase_exclusive",
            "target_source_record_id",
            unique=True,
            sqlite_where=text("status = 'accepted' AND match_kind = 'exact'"),
            postgresql_where=text("status = 'accepted' AND match_kind = 'exact'"),
        ),
        Index("ix_reconciliation_link_budget_status", "budget_id", "status", "score"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    budget_id: int = Field(foreign_key="budget.id", index=True)
    bank_source_record_id: int = Field(foreign_key="source_record.id", index=True)
    target_source_record_id: int = Field(foreign_key="source_record.id", index=True)
    bank_transaction_id: int = Field(foreign_key="transaction.id", index=True)
    target_transaction_id: int = Field(foreign_key="transaction.id", index=True)
    match_kind: ReconciliationMatchKind = Field(
        default=ReconciliationMatchKind.EXACT,
        sa_column=Column(String, nullable=False, server_default=ReconciliationMatchKind.EXACT.value),
    )
    status: ReconciliationStatus = Field(
        default=ReconciliationStatus.PENDING,
        sa_column=Column(String, index=True, nullable=False, server_default=ReconciliationStatus.PENDING.value),
    )
    score: ScoreDecimal = Field(default=Decimal("0.0000"), sa_type=Numeric(5, 4))  # type: ignore[arg-type]
    reasons: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    previous_receipt_status: Optional[str] = Field(default=None)
    decided_by_user_id: Optional[int] = Field(default=None, foreign_key="user.id")
    decided_at: Optional[datetime] = Field(default=None, sa_column=Column(UTCDateTime(), nullable=True))
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(UTCDateTime(), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(UTCDateTime(), nullable=False),
    )

    @field_validator("decided_at", "created_at", "updated_at", mode="before")
    @classmethod
    def validate_dates_tz(cls, v: Any) -> Optional[datetime]:
        return ensure_tz_aware(v)


# ─── ScanUsageLog (Demo Rate Limiting & Abuse Prevention) ─────────────────────

class ScanUsageLog(SQLModel, table=True):
    __tablename__: str = "scan_usage_log"  # type: ignore

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)
    scan_type: str = Field(index=True)  # 'custom', 'sample_biedronka', 'sample_lidl'
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        index=True,
    )



# ─── TransactionLine ──────────────────────────────────────────────────────────

class TransactionLineBase(SQLModel):
    name: str
    price: UnitPriceDecimal = Field(sa_type=Numeric(12, 4))  # type: ignore[arg-type]
    quantity: QuantityDecimal = Field(default=Decimal("1"), sa_type=Numeric(12, 4))  # type: ignore[arg-type]
    category_id: Optional[int] = Field(default=None, foreign_key="category.id")
    category_source: Optional[str] = Field(default=None)
    original_price: Optional[UnitPriceDecimal] = Field(default=None, sa_type=Numeric(12, 4))  # type: ignore[arg-type]
    discount_total: MoneyDecimal = Field(default=Decimal("0.00"), sa_type=Numeric(12, 2))  # type: ignore[arg-type]
    final_price: Optional[UnitPriceDecimal] = Field(default=None, sa_type=Numeric(12, 4))  # type: ignore[arg-type]
    is_adjustment: bool = Field(default=False)


class TransactionLine(TransactionLineBase, table=True):
    __tablename__: str = "transactionline"  # type: ignore

    id: Optional[int] = Field(default=None, primary_key=True)
    transaction_id: Optional[int] = Field(default=None, foreign_key="transaction.id")
    transaction: Optional[Transaction] = Relationship(back_populates="lines")


# ─── EnvelopeAllocation (Zero-Based Budgeting per Category) ───────────────────

class EnvelopeAllocation(SQLModel, table=True):
    __tablename__: str = "envelope_allocation"  # type: ignore
    __table_args__ = (
        UniqueConstraint("budget_id", "category_id", "month", "year", name="uq_envelope_allocation"),
        Index("ix_envelope_allocation_budget_date", "budget_id", "year", "month"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    budget_id: int = Field(foreign_key="budget.id", index=True)
    category_id: int = Field(foreign_key="category.id", index=True)
    month: int = Field(index=True)
    year: int = Field(index=True)
    amount: MoneyDecimal = Field(default=Decimal("0.00"), sa_type=Numeric(12, 2))  # type: ignore[arg-type]

    budget: Optional[Budget] = Relationship(back_populates="envelope_allocations")
    category: Optional["Category"] = Relationship(back_populates="envelope_allocations")

# ─── BudgetAlert (Notifications for Zeroed Envelopes) ──────────────────────────

class BudgetAlert(SQLModel, table=True):
    __tablename__: str = "budgetalert"  # type: ignore

    id: Optional[int] = Field(default=None, primary_key=True)
    budget_id: int = Field(foreign_key="budget.id", index=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    category_name: str
    message: str
    is_read: bool = Field(default=False)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), index=True)

    budget: Optional[Budget] = Relationship()
    user: Optional[User] = Relationship()


# ─── ExternalReceiptConnection (Store / Merchant Ingestion Lifecycle) ─────────

class ConnectionStatus(str, Enum):
    ACTIVE = "active"
    EXPIRED = "expired"
    REAUTH_REQUIRED = "reauth_required"
    SYNC_ERROR = "sync_error"
    DISCONNECTED = "disconnected"


class ConnectionErrorCode(str, Enum):
    AUTH_EXPIRED = "AUTH_EXPIRED"
    REAUTH_REQUIRED = "REAUTH_REQUIRED"
    MFA_REQUIRED = "MFA_REQUIRED"
    RATE_LIMITED = "RATE_LIMITED"
    NETWORK_ERROR = "NETWORK_ERROR"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    PROVIDER_SCHEMA_CHANGED = "PROVIDER_SCHEMA_CHANGED"
    PROVIDER_REVOCATION_UNAVAILABLE = "PROVIDER_REVOCATION_UNAVAILABLE"
    ENCRYPTION_KEY_MISSING = "ENCRYPTION_KEY_MISSING"
    TOKEN_DECRYPTION_FAILED = "TOKEN_DECRYPTION_FAILED"
    CONNECTOR_DISABLED = "CONNECTOR_DISABLED"
    SYNC_FAILED = "SYNC_FAILED"


class ExternalReceiptConnectionBase(SQLModel):
    provider: str = Field(index=True)
    consented_scopes: Optional[str] = Field(default=None)
    status: ConnectionStatus = Field(
        default=ConnectionStatus.REAUTH_REQUIRED,
        sa_column=Column(String, nullable=False, index=True, server_default="reauth_required"),
    )
    last_error_code: Optional[str] = Field(default=None)
    is_enabled: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default=text("1")),
    )
    default_account_id: Optional[int] = Field(
        default=None, foreign_key="account.id", ondelete="SET NULL", index=True
    )
    auto_merge_policy: AutoMergePolicy = Field(
        default=AutoMergePolicy.AUTO,
        sa_column=Column(String, nullable=False, server_default=AutoMergePolicy.AUTO.value),
    )
    auto_approve_clean: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default=text("1")),
    )
    sync_from_date: Optional[date] = Field(default=None)


class ExternalReceiptConnection(ExternalReceiptConnectionBase, table=True):
    __tablename__: str = "external_receipt_connection"  # type: ignore
    __table_args__ = (
        UniqueConstraint(
            "budget_id",
            "owner_user_id",
            "provider",
            name="uq_connection_budget_owner_provider",
        ),
        Index("ix_connection_budget_status", "budget_id", "status"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    budget_id: int = Field(foreign_key="budget.id", index=True)
    owner_user_id: int = Field(foreign_key="user.id", index=True)

    consented_at: Optional[datetime] = Field(default=None)
    encrypted_refresh_token: Optional[str] = Field(default=None)
    encryption_key_id: Optional[str] = Field(default=None)
    encrypted_oauth_attempt: Optional[str] = Field(default=None)
    oauth_attempt_key_id: Optional[str] = Field(default=None)
    oauth_attempt_expires_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(UTCDateTime(), nullable=True),
    )

    last_success_at: Optional[datetime] = Field(default=None)
    next_sync_at: Optional[datetime] = Field(default=None)
    sync_requested_at: Optional[datetime] = Field(default=None)

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    budget: Optional[Budget] = Relationship(back_populates="receipt_connections")
    owner: Optional[User] = Relationship(back_populates="receipt_connections")


# ─── ImportJob & Provider Rate Limits (Durable Scheduler #257) ───────────────


class ImportJobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class ImportJob(SQLModel, table=True):
    """Durable SQLite-backed job queue entry for external source synchronization.

    Privacy boundary: never store plaintext OAuth tokens, encryption keys,
    authorization codes, PKCE verifiers, raw receipts, or personal transaction
    text in cursor, last_error_code, or any other column.
    """

    __tablename__: str = "import_jobs"  # type: ignore
    __table_args__ = (
        Index("ix_import_jobs_claimable", "status", "next_retry_at", "lease_expires_at"),
        Index("ix_import_jobs_connection_status", "connection_id", "status"),
        Index("ix_import_jobs_provider_status", "provider", "status"),
        Index("ix_import_jobs_batch_status", "import_batch_id", "status"),
        Index(
            "uq_import_jobs_active_connection_type",
            "connection_id",
            "job_type",
            unique=True,
            sqlite_where=text("status IN ('pending', 'running') AND connection_id IS NOT NULL"),
            postgresql_where=text("status IN ('pending', 'running') AND connection_id IS NOT NULL"),
        ),
        Index(
            "uq_import_jobs_active_scan_type",
            "receipt_scan_id",
            "job_type",
            unique=True,
            sqlite_where=text("status IN ('pending', 'running') AND receipt_scan_id IS NOT NULL"),
            postgresql_where=text("status IN ('pending', 'running') AND receipt_scan_id IS NOT NULL"),
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    job_type: str = Field(default="connection_sync", index=True)
    provider: str = Field(index=True)
    connection_id: Optional[int] = Field(
        default=None, foreign_key="external_receipt_connection.id", index=True
    )
    budget_id: int = Field(foreign_key="budget.id", index=True)
    transaction_id: Optional[int] = Field(
        default=None, foreign_key="transaction.id", index=True
    )
    receipt_scan_id: Optional[int] = Field(
        default=None, foreign_key="receiptscan.id", index=True
    )
    import_batch_id: Optional[str] = Field(default=None, index=True)
    source_filename: Optional[str] = Field(default=None)

    status: ImportJobStatus = Field(
        default=ImportJobStatus.PENDING,
        sa_column=Column(String, nullable=False, index=True, server_default="pending"),
    )
    attempt_count: int = Field(default=0)
    max_attempts: int = Field(default=5)

    next_retry_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(UTCDateTime(), nullable=False, index=True),
    )
    cursor: Optional[str] = Field(default=None)
    correlation_id: str = Field(index=True)

    lease_owner: Optional[str] = Field(default=None, index=True)
    lease_expires_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(UTCDateTime(), nullable=True, index=True),
    )
    last_error_code: Optional[str] = Field(default=None)

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(UTCDateTime(), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(UTCDateTime(), nullable=False),
    )
    completed_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(UTCDateTime(), nullable=True),
    )

    @field_validator(
        "next_retry_at",
        "lease_expires_at",
        "created_at",
        "updated_at",
        "completed_at",
        mode="before",
    )
    @classmethod
    def validate_tz_fields(cls, v: Any) -> Optional[datetime]:
        return ensure_tz_aware(v)


class ImportProviderLimit(SQLModel, table=True):
    """Cross-worker persistent throttling & cooldown state per merchant provider."""

    __tablename__: str = "import_provider_limits"  # type: ignore

    provider: str = Field(primary_key=True)
    cooldown_until: Optional[datetime] = Field(
        default=None,
        sa_column=Column(UTCDateTime(), nullable=True),
    )
    last_dispatched_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(UTCDateTime(), nullable=True),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(UTCDateTime(), nullable=False),
    )

    @field_validator("cooldown_until", "last_dispatched_at", "updated_at", mode="before")
    @classmethod
    def validate_tz_fields(cls, v: Any) -> Optional[datetime]:
        return ensure_tz_aware(v)


# ─── API DTOs ────────────────────────────────────────────────────────────────

class ExternalReceiptConnectionRead(SQLModel):
    id: int
    budget_id: int
    owner_user_id: int
    provider: str
    consented_scopes: Optional[str] = None
    consented_at: Optional[datetime] = None
    status: ConnectionStatus
    is_enabled: bool = True
    default_account_id: Optional[int] = None
    auto_merge_policy: AutoMergePolicy = AutoMergePolicy.AUTO
    auto_approve_clean: bool = True
    sync_from_date: Optional[date] = None
    budget_first_month_date: Optional[date] = None
    suggested_account_id: Optional[int] = None
    has_token: bool = False
    last_success_at: Optional[datetime] = None
    last_error_code: Optional[str] = None
    next_sync_at: Optional[datetime] = None
    sync_requested_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class ConnectionSettingsUpdate(SQLModel):
    """Update connector account, duplicate merge policy, and sync date range."""

    model_config = SQLModelConfig(extra="forbid")

    default_account_id: Optional[int] = None
    auto_merge_policy: Optional[AutoMergePolicy] = None
    auto_approve_clean: Optional[bool] = None
    sync_from_date: Optional[date] = None


class ConnectionToggleRequest(SQLModel):
    """Enable or pause automatic synchronization for a connection without deleting credentials."""

    model_config = SQLModelConfig(extra="forbid")

    enabled: bool


class ExternalReceiptConnectionCreate(SQLModel):
    """Create a local authorization placeholder; it never accepts credentials."""

    model_config = SQLModelConfig(extra="forbid")

    provider: str


class ConnectionSyncNowResponse(SQLModel):
    connection_id: int
    status: ConnectionStatus
    sync_requested_at: datetime
    message: str
    imported_count: int = 0
    skipped_count: int = 0
    failed_count: int = 0


class ConnectionOAuthStartResponse(SQLModel):
    connection_id: int
    provider: str
    authorize_url: str
    state: str
    redirect_uri: str


class ConnectionOAuthCallbackRequest(SQLModel):
    model_config = SQLModelConfig(extra="forbid")

    callback_url_or_code: str


class ConnectionDisconnectResponse(SQLModel):
    connection_id: int
    status: str
    revocation_status: str
    message: str

class AccountRead(AccountBase):
    id: int
    budget_id: Optional[int] = None

class AccountCreate(AccountBase):
    model_config = SQLModelConfig(extra="forbid")

    @field_validator("current_balance")
    @classmethod
    def validate_client_current_balance(cls, value: Decimal) -> Decimal:
        if value != Decimal("0"):
            raise ValueError("current_balance is calculated from transactions")
        return value

class AccountUpdate(SQLModel):
    model_config = SQLModelConfig(extra="forbid")

    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    type: Optional[str] = None
    currency: Optional[str] = Field(default=None, min_length=3, max_length=3)
    is_on_budget: Optional[bool] = None
    category_id: Optional[int] = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        value = value.strip()
        if not value:
            raise ValueError("Account name cannot be blank")
        return value

    @field_validator("type")
    @classmethod
    def validate_type(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        value = value.strip().lower()
        if value not in ACCOUNT_TYPES:
            raise ValueError(f"Unsupported account type: {value}")
        return value

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        value = value.strip().upper()
        if len(value) != 3 or not value.isalpha():
            raise ValueError("Currency must be a three-letter ISO code")
        return value


class EnvelopeAllocationRead(SQLModel):
    id: int
    budget_id: int
    category_id: int
    month: int
    year: int
    amount: MoneyDecimal


class EnvelopeAllocationCreate(SQLModel):
    category_id: int
    month: int
    year: int
    amount: MoneyDecimal



class TransactionLineRead(TransactionLineBase):
    id: int


class SourceRecordRead(SQLModel):
    id: int
    budget_id: int
    transaction_id: Optional[int] = None
    receipt_scan_id: Optional[int] = None
    connection_id: Optional[int] = None
    source_type: SourceType
    provider: str
    external_id: Optional[str] = None
    canonical_hash: Optional[str] = None
    adapter_version: str
    acquired_at: datetime
    quality: Optional[ScoreDecimal] = None
    raw_payload_policy: RawPayloadPolicy


class ReceiptScanRead(SQLModel):
    id: int
    status: str
    processed_via: Optional[str] = None
    needs_review: bool = False
    image_path: Optional[str] = None
    content_hash: Optional[str] = None
    created_at: datetime
    validation_message: Optional[str] = None
    original_date: Optional[str] = None
    error_message: Optional[str] = None
    raw_ocr_text: Optional[str] = None
    reconstructed_lines: Optional[list[str]] = None


class ImportJobRead(SQLModel):
    id: int
    job_type: str
    provider: str
    connection_id: Optional[int] = None
    budget_id: int
    transaction_id: Optional[int] = None
    receipt_scan_id: Optional[int] = None
    import_batch_id: Optional[str] = None
    source_filename: Optional[str] = None
    status: ImportJobStatus
    attempt_count: int
    max_attempts: int
    next_retry_at: datetime
    last_error_code: Optional[str] = None
    is_retryable: bool = False
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime] = None


class BatchUploadItemResult(SQLModel):
    filename: str
    status: str  # queued | duplicate | rejected | rate_limited
    error_code: Optional[str] = None
    detail: Optional[str] = None
    transaction_id: Optional[int] = None
    receipt_scan_id: Optional[int] = None
    job_id: Optional[int] = None


class BatchDocumentUploadResponse(SQLModel):
    import_batch_id: str
    total_files: int
    queued_count: int
    duplicate_count: int
    failed_count: int
    rate_limited_count: int
    results: List[BatchUploadItemResult] = []


class TransactionRead(TransactionBase):
    id: int
    note: Optional[str] = None
    category_id: Optional[int] = None
    reconciled_into_id: Optional[int] = None
    rejected_at: Optional[datetime] = None
    rejection_reason: Optional[str] = None
    import_batch_id: Optional[str] = None
    suggested_account_id: Optional[int] = None
    review_reasons: List[str] = Field(default_factory=list)
    canonical_total_valid: Optional[bool] = None
    import_job: Optional[ImportJobRead] = None
    lines: List[TransactionLineRead] = []
    budget_id: Optional[int] = None
    uploaded_by: Optional[int] = None
    tags: List["TagRead"] = []
    receipt_scan: Optional[ReceiptScanRead] = None
    source_records: List[SourceRecordRead] = []


class BankCsvPreviewRow(SQLModel):
    date: datetime
    merchant_name: str
    title: str
    amount: MoneyDecimal
    currency: str = "PLN"
    detected_type: str
    is_duplicate: bool = False


class BankCsvPreviewResponse(SQLModel):
    filename: str
    total_rows: int
    new_count: int
    duplicate_count: int
    suggested_account_id: Optional[int] = None
    warnings: List[str] = []
    rows: List[BankCsvPreviewRow] = []


class InboxBulkApproveRequest(SQLModel):
    model_config = SQLModelConfig(extra="forbid")

    transaction_ids: List[int]
    account_id: int


class InboxBulkActionResponse(SQLModel):
    approved_count: int
    skipped_ids: List[int] = []
    errors: List[dict[str, Any]] = []


class InboxRejectRequest(SQLModel):
    model_config = SQLModelConfig(extra="forbid")

    reason: Optional[str] = None


class DuplicateMergeRequest(SQLModel):
    model_config = SQLModelConfig(extra="forbid")

    keep_transaction_id: Optional[int] = None
    account_id: Optional[int] = None


class ReconciliationTransactionSummary(SQLModel):
    id: int
    merchant_name: str
    total_amount: MoneyDecimal
    currency: str
    date: Optional[datetime] = None
    type: str
    status: TransactionStatus
    account_id: Optional[int] = None
    account_name: Optional[str] = None
    note: Optional[str] = None
    source_type: Optional[SourceType] = None
    provider: Optional[str] = None


class ReconciliationSignalRead(SQLModel):
    code: str
    matched: bool
    weight: ScoreDecimal
    detail: dict[str, Any] = Field(default_factory=dict)


class ReconciliationLinkRead(SQLModel):
    id: int
    budget_id: int
    bank_source_record_id: int
    target_source_record_id: int
    bank_transaction_id: int
    target_transaction_id: int
    match_kind: ReconciliationMatchKind
    status: ReconciliationStatus
    score: ScoreDecimal
    confidence_tier: str
    signals: List[ReconciliationSignalRead] = []
    same_day_conflict_count: int = 0
    bank_transaction: Optional[ReconciliationTransactionSummary] = None
    target_transaction: Optional[ReconciliationTransactionSummary] = None
    decided_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class ReconciliationListResponse(SQLModel):
    candidates: List[ReconciliationLinkRead] = []
    pending_count: int = 0
    accepted_count: int = 0
    rejected_count: int = 0
    unlinked_count: int = 0


class ReconciliationActionResponse(SQLModel):
    link: ReconciliationLinkRead
    message: str


class TransactionCreate(TransactionBase):
    pass


class TransactionUpdate(SQLModel):
    merchant_name: Optional[str] = None
    date: Optional[datetime] = None
    total_amount: Optional[MoneyDecimal] = Field(default=None, ge=0)
    currency: Optional[str] = None
    category_id: Optional[int] = None
    note: Optional[str] = None
    tag_ids: Optional[List[int]] = None
    type: Optional[str] = None
    status: Optional[TransactionStatus] = None
    account_id: Optional[int] = None
    transfer_id: Optional[int] = None

    @field_validator("date", mode="before")
    @classmethod
    def validate_date_tz(cls, v: Any) -> Optional[datetime]:
        return ensure_tz_aware(v)


class TransactionLineCreate(SQLModel):
    name: str
    price: UnitPriceDecimal
    quantity: QuantityDecimal = Field(default=Decimal("1"), gt=0)
    category_id: Optional[int] = None
    original_price: Optional[UnitPriceDecimal] = None
    discount_total: MoneyDecimal = Decimal("0.00")
    final_price: Optional[UnitPriceDecimal] = None
    is_adjustment: bool = False


class ManualTransactionCreate(SQLModel):
    merchant_name: str
    total_amount: MoneyDecimal = Field(ge=0)
    currency: str = "PLN"
    date: Optional[datetime] = None
    category_id: Optional[int] = None
    note: Optional[str] = None
    tag_ids: List[int] = Field(default_factory=list)
    lines: List[TransactionLineCreate] = Field(default_factory=list)
    type: str = "expense"  # expense | income | transfer
    status: TransactionStatus = TransactionStatus.UNCLEARED
    account_id: Optional[int] = None
    transfer_id: Optional[int] = None

    @field_validator("date", mode="before")
    @classmethod
    def validate_date_tz(cls, v: Any) -> Optional[datetime]:
        return ensure_tz_aware(v)


class TransferCreate(SQLModel):
    source_account_id: int
    destination_account_id: int
    amount: MoneyDecimal = Field(gt=0)
    currency: str = Field(default="PLN", min_length=3, max_length=3)
    date: Optional[datetime] = None
    note: Optional[str] = None
    category_id: Optional[int] = None
    status: TransactionStatus = TransactionStatus.UNCLEARED

    @field_validator("date", mode="before")
    @classmethod
    def validate_date_tz(cls, v: Any) -> Optional[datetime]:
        return ensure_tz_aware(v)


class TransactionLineUpdate(SQLModel):
    name: Optional[str] = None
    price: Optional[UnitPriceDecimal] = None
    quantity: Optional[QuantityDecimal] = Field(default=None, gt=0)
    category_id: Optional[int] = None
    original_price: Optional[UnitPriceDecimal] = None
    discount_total: Optional[MoneyDecimal] = None
    final_price: Optional[UnitPriceDecimal] = None
    is_adjustment: Optional[bool] = None



class VerifyRequest(SQLModel):
    """Body for POST /transactions/{id}/verify — user confirms AI-parsed receipt."""
    transaction_update: TransactionUpdate
    lines_update: Optional[List[TransactionLineUpdate]] = None
    keep_image: bool = False


class EnvelopeAllocationUpdate(SQLModel):
    amount: MoneyDecimal = Field(ge=0)


class BudgetMemberRead(SQLModel):
    id: int
    budget_id: int
    user_id: int
    role: str


class BudgetMemberCreate(SQLModel):
    email: str
    role: str = "viewer"


class UserBudgetRead(SQLModel):
    id: int
    name: str
    role: str


class ChangePasswordRequest(SQLModel):
    old_password: str
    new_password: str = Field(min_length=6)


class CategoryBudgetSummaryItem(SQLModel):
    category_id: int
    category_name: str
    planned: MoneyDecimal
    spent: MoneyDecimal
    remaining: MoneyDecimal


class MonthlyBudgetSummary(SQLModel):
    year: int
    month: int
    total_planned: MoneyDecimal
    total_spent: MoneyDecimal
    net_cash_flow: MoneyDecimal
    total_income: MoneyDecimal
    categories: List[CategoryBudgetSummaryItem]


class CategoryCreate(CategoryBase):
    pass


class CategoryUpdate(SQLModel):
    name: Optional[str] = None
    icon: Optional[str] = None
    color: Optional[str] = None
    parent_id: Optional[int] = None
    order_index: Optional[int] = None


class CategoryRead(CategoryBase):
    id: int
    budget_id: Optional[int] = None


class TagCreate(TagBase):
    pass


class TagUpdate(SQLModel):
    name: Optional[str] = None
    color: Optional[str] = None


class TagRead(TagBase):
    id: int
    budget_id: Optional[int] = None


# ─── Auth DTOs ────────────────────────────────────────────────────────────────

class UserCreate(SQLModel):
    email: str
    password: str


class UserUpdate(SQLModel):
    default_budget_id: Optional[int] = None

class UserRead(SQLModel):
    id: int
    email: str
    default_budget_id: Optional[int] = None
    created_at: datetime


class Token(SQLModel):
    access_token: str
    token_type: str = "bearer"
    user: UserRead


class BudgetAlertRead(SQLModel):
    id: int
    budget_id: int
    user_id: int
    category_name: str
    message: str
    is_read: bool
    created_at: datetime


class AppStatusRead(SQLModel):
    inbox_items: List[TransactionRead]
    unread_alerts: List[BudgetAlertRead]


class AppConfigRead(SQLModel):
    demo_mode: bool
    environment: str
    import_worker_role: str = "central_vps"
    trusted_local: bool = False
    desktop_oauth_available: bool = False
    lidl_connector_enabled: bool = True

# ─── SQLAlchemy Events ────────────────────────────────────────────────────────

def _transaction_account_ids(transaction: Transaction) -> set[int]:
    return {
        account_id
        for account_id in (transaction.account_id, transaction.transfer_id)
        if account_id is not None
    }


@event.listens_for(Transaction, "before_update")
def remember_previous_transaction_accounts(mapper, connection, target):
    """Keep both sides of an account reassignment available after the flush."""
    previous_values = connection.execute(
        text('SELECT account_id, transfer_id FROM "transaction" WHERE id = :id'),
        {"id": target.id},
    ).one_or_none()
    previous_ids = {
        account_id
        for account_id in (previous_values or ())
        if account_id is not None
    }
    target.__dict__["_balance_recalc_previous_account_ids"] = previous_ids


def recalculate_account_balance(connection: Any, acc_id: int) -> None:
    """Recompute and persist ``Account.current_balance`` for ``acc_id``.

    Excludes bank transactions folded via ``reconciled_into_id`` for exact matches,
    while attributing accepted ``split_payment`` outflows directly to each bank
    transaction's own account and counting only the uncovered remainder (if any)
    on a pre-assigned target account.
    """
    split_links = connection.execute(
        select(
            col(ReconciliationLink.target_transaction_id),
            col(ReconciliationLink.bank_transaction_id),
        ).where(
            col(ReconciliationLink.status) == ReconciliationStatus.ACCEPTED.value,
            col(ReconciliationLink.match_kind) == ReconciliationMatchKind.SPLIT_PAYMENT.value,
        )
    ).fetchall()

    split_bank_by_target: dict[int, list[int]] = {}
    split_bank_ids: set[int] = set()
    for target_tx_id, bank_tx_id in split_links:
        if target_tx_id is not None and bank_tx_id is not None:
            split_bank_by_target.setdefault(target_tx_id, []).append(bank_tx_id)
            split_bank_ids.add(bank_tx_id)
    split_target_ids = set(split_bank_by_target.keys())

    approved_filter = col(Transaction.review_status) == ReviewStatus.APPROVED.value
    regular_filter = (col(Transaction.reconciled_into_id).is_(None)) & approved_filter
    if split_target_ids:
        regular_filter = regular_filter & col(Transaction.id).not_in(split_target_ids)
    out_filter = (
        or_(regular_filter, (col(Transaction.id).in_(split_bank_ids)) & approved_filter)
        if split_bank_ids
        else regular_filter
    )

    res_out = connection.execute(
        select(col(Transaction.type), col(Transaction.total_amount)).where(
            col(Transaction.account_id) == acc_id,
            out_filter,
        )
    ).fetchall()

    split_target_rows = []
    if split_target_ids:
        split_target_rows = connection.execute(
            select(col(Transaction.id), col(Transaction.type), col(Transaction.total_amount)).where(
                col(Transaction.account_id) == acc_id,
                col(Transaction.id).in_(split_target_ids),
                col(Transaction.reconciled_into_id).is_(None),
                approved_filter,
            )
        ).fetchall()

    covered_bank_amounts: dict[int, Decimal] = {}
    if split_target_rows:
        needed_bank_ids = {
            b_id
            for t_id, _, _ in split_target_rows
            for b_id in split_bank_by_target.get(t_id, [])
        }
        if needed_bank_ids:
            bank_rows = connection.execute(
                select(col(Transaction.id), col(Transaction.total_amount)).where(
                    col(Transaction.id).in_(needed_bank_ids),
                    approved_filter,
                )
            ).fetchall()
            for b_id, b_amt in bank_rows:
                if b_id is not None and b_amt is not None:
                    covered_bank_amounts[b_id] = quantize_money(abs(b_amt))

    res_in_rows = connection.execute(
        select(col(Transaction.total_amount)).where(
            col(Transaction.transfer_id) == acc_id,
            col(Transaction.type) == "transfer",
            col(Transaction.reconciled_into_id).is_(None),
            approved_filter,
        )
    ).scalars().all()

    init_bal_raw = connection.execute(
        select(col(Account.initial_balance)).where(col(Account.id) == acc_id)
    ).scalar()

    balance = quantize_money(init_bal_raw or Decimal("0.00"))
    for tx_type, amount in res_out:
        if amount is None:
            continue
        dec_amount = quantize_money(amount)
        if tx_type == "income":
            balance += dec_amount
        elif tx_type in ("expense", "transfer"):
            balance -= dec_amount

    for target_tx_id, tx_type, target_amount in split_target_rows:
        if target_amount is None:
            continue
        covered_sum = sum(
            (covered_bank_amounts.get(b_id, Decimal("0.00")) for b_id in split_bank_by_target.get(target_tx_id, [])),
            Decimal("0.00"),
        )
        uncovered = max(Decimal("0.00"), quantize_money(target_amount) - covered_sum)
        if uncovered <= Decimal("0.00"):
            continue
        if tx_type == "income":
            balance += uncovered
        elif tx_type in ("expense", "transfer"):
            balance -= uncovered

    for transfer_in_amount in res_in_rows:
        if transfer_in_amount is not None:
            balance += quantize_money(transfer_in_amount)

    connection.execute(
        update(Account)
        .where(Account.id == acc_id)  # type: ignore[arg-type]
        .values(current_balance=quantize_money(balance))
    )


@event.listens_for(Transaction, "after_insert")
@event.listens_for(Transaction, "after_update")
@event.listens_for(Transaction, "after_delete")
def transaction_changed_update_balance(mapper, connection, target):
    account_ids = _transaction_account_ids(target)
    account_ids.update(target.__dict__.pop("_balance_recalc_previous_account_ids", set()))
    if not account_ids:
        return

    for acc_id in account_ids:
        recalculate_account_balance(connection, acc_id)
