# backend/app/models.py
from enum import Enum
from decimal import Decimal
from typing import Any, List, Optional
from datetime import date, datetime, timezone
from pydantic import field_validator
from sqlalchemy import UniqueConstraint, Index, String, Column, JSON, Numeric, DateTime, event, select, text, update, Boolean
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
    RATE_LIMITED = "RATE_LIMITED"
    NETWORK_ERROR = "NETWORK_ERROR"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    PROVIDER_REVOCATION_UNAVAILABLE = "PROVIDER_REVOCATION_UNAVAILABLE"
    ENCRYPTION_KEY_MISSING = "ENCRYPTION_KEY_MISSING"
    TOKEN_DECRYPTION_FAILED = "TOKEN_DECRYPTION_FAILED"
    SYNC_FAILED = "SYNC_FAILED"


class ExternalReceiptConnectionBase(SQLModel):
    provider: str = Field(index=True)
    consented_scopes: Optional[str] = Field(default=None)
    status: ConnectionStatus = Field(
        default=ConnectionStatus.REAUTH_REQUIRED,
        sa_column=Column(String, nullable=False, index=True, server_default="reauth_required"),
    )
    last_error_code: Optional[str] = Field(default=None)


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

    last_success_at: Optional[datetime] = Field(default=None)
    next_sync_at: Optional[datetime] = Field(default=None)
    sync_requested_at: Optional[datetime] = Field(default=None)

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    budget: Optional[Budget] = Relationship(back_populates="receipt_connections")
    owner: Optional[User] = Relationship(back_populates="receipt_connections")


# ─── API DTOs ────────────────────────────────────────────────────────────────

class ExternalReceiptConnectionRead(SQLModel):
    id: int
    budget_id: int
    owner_user_id: int
    provider: str
    consented_scopes: Optional[str] = None
    consented_at: Optional[datetime] = None
    status: ConnectionStatus
    has_token: bool = False
    last_success_at: Optional[datetime] = None
    last_error_code: Optional[str] = None
    next_sync_at: Optional[datetime] = None
    sync_requested_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


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


class TransactionRead(TransactionBase):
    id: int
    note: Optional[str] = None
    category_id: Optional[int] = None
    lines: List[TransactionLineRead] = []
    budget_id: Optional[int] = None
    uploaded_by: Optional[int] = None
    tags: List["TagRead"] = []
    receipt_scan: Optional[ReceiptScanRead] = None
    source_records: List[SourceRecordRead] = []


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


@event.listens_for(Transaction, "after_insert")
@event.listens_for(Transaction, "after_update")
@event.listens_for(Transaction, "after_delete")
def transaction_changed_update_balance(mapper, connection, target):
    account_ids = _transaction_account_ids(target)
    account_ids.update(target.__dict__.pop("_balance_recalc_previous_account_ids", set()))
    if not account_ids:
        return

    for acc_id in account_ids:
        res_out = connection.execute(
            select(col(Transaction.type), col(Transaction.total_amount)).where(col(Transaction.account_id) == acc_id)
        ).fetchall()

        res_in_rows = connection.execute(
            select(col(Transaction.total_amount)).where(
                col(Transaction.transfer_id) == acc_id,
                col(Transaction.type) == "transfer",
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

        for transfer_in_amount in res_in_rows:
            if transfer_in_amount is not None:
                balance += quantize_money(transfer_in_amount)

        connection.execute(
            update(Account)
            .where(Account.id == acc_id)  # type: ignore[arg-type]
            .values(current_balance=quantize_money(balance))
        )
