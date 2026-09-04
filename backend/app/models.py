# backend/app/models.py
from enum import Enum
from typing import List, Optional
from datetime import datetime, timezone
import math
from pydantic import field_validator
from sqlalchemy import UniqueConstraint, Index, String, Column, JSON, event, text
from sqlmodel import Field, Relationship, SQLModel
from sqlmodel._compat import SQLModelConfig


class ScanStatus(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    OCR_OK = "OCR_OK"
    PARSING_OK = "PARSING_OK"
    CATEGORIZATION_OK = "CATEGORIZATION_OK"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    FAILED = "FAILED"

    @classmethod
    def _missing_(cls, value: object) -> "ScanStatus":
        _legacy_map = {
            "processing": cls.RUNNING,
            "done": cls.CATEGORIZATION_OK,
            "error": cls.FAILED,
        }
        if isinstance(value, str):
            mapped = _legacy_map.get(value.lower())
            if mapped is not None:
                return mapped
        return cls.FAILED


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
    initial_balance: float = Field(default=0.0)
    current_balance: float = Field(default=0.0)
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
    def validate_balance(cls, value: float) -> float:
        if not math.isfinite(value):
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
    total_amount: float = Field(default=0.0)
    currency: str = Field(default="PLN")
    is_manual: bool = Field(default=False)
    type: str = Field(default="expense")  # expense | income | transfer
    import_hash: Optional[str] = Field(default=None, index=True)
    account_id: Optional[int] = Field(default=None, foreign_key="account.id", index=True)
    transfer_id: Optional[int] = Field(default=None, foreign_key="account.id", index=True)


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

    lines: List["TransactionLine"] = Relationship(back_populates="transaction")
    receipt_scan: Optional["ReceiptScan"] = Relationship(back_populates="transaction")
    budget: Optional[Budget] = Relationship(back_populates="transactions")
    uploader: Optional[User] = Relationship(back_populates="transactions")
    category: Optional["Category"] = Relationship(back_populates="transactions")
    tags: List["Tag"] = Relationship(back_populates="transactions", link_model=TransactionTagLink)
    account: Optional[Account] = Relationship(
        back_populates="transactions",
        sa_relationship_kwargs={"foreign_keys": "[Transaction.account_id]"}
    )
    transfer_account: Optional[Account] = Relationship(
        back_populates="transfers_in",
        sa_relationship_kwargs={"foreign_keys": "[Transaction.transfer_id]"}
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
    error_message: Optional[str] = Field(default=None)
    content_hash: Optional[str] = Field(default=None, index=True)
    keep_image: bool = Field(default=False)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    validation_message: Optional[str] = Field(default=None)
    raw_ocr_text: Optional[str] = Field(default=None)
    reconstructed_lines: Optional[list[str]] = Field(default=None, sa_column=Column(JSON))

    transaction: Optional[Transaction] = Relationship(back_populates="receipt_scan")


# ─── TransactionLine ──────────────────────────────────────────────────────────

class TransactionLineBase(SQLModel):
    name: str
    price: float
    quantity: float = Field(default=1.0)
    category_id: Optional[int] = Field(default=None, foreign_key="category.id")
    category_source: Optional[str] = Field(default=None)
    original_price: Optional[float] = Field(default=None)
    discount_total: float = Field(default=0.0)
    final_price: Optional[float] = Field(default=None)
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
    amount: float = Field(default=0.0)

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

# ─── API DTOs ────────────────────────────────────────────────────────────────

class AccountRead(AccountBase):
    id: int
    budget_id: Optional[int] = None

class AccountCreate(AccountBase):
    model_config = SQLModelConfig(extra="forbid")

    @field_validator("current_balance")
    @classmethod
    def validate_client_current_balance(cls, value: float) -> float:
        if value != 0:
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
    amount: float


class EnvelopeAllocationCreate(SQLModel):
    category_id: int
    month: int
    year: int
    amount: float



class TransactionLineRead(TransactionLineBase):
    id: int


class ReceiptScanRead(SQLModel):
    id: int
    status: str
    image_path: Optional[str] = None
    content_hash: Optional[str] = None
    created_at: datetime
    validation_message: Optional[str] = None
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


class TransactionCreate(TransactionBase):
    pass


class TransactionUpdate(SQLModel):
    merchant_name: Optional[str] = None
    date: Optional[datetime] = None
    total_amount: Optional[float] = None
    currency: Optional[str] = None
    category_id: Optional[int] = None
    note: Optional[str] = None
    tag_ids: Optional[List[int]] = None
    type: Optional[str] = None
    account_id: Optional[int] = None
    transfer_id: Optional[int] = None


class TransactionLineCreate(SQLModel):
    name: str
    price: float
    quantity: float = 1.0
    category_id: Optional[int] = None
    original_price: Optional[float] = None
    discount_total: float = 0.0
    final_price: Optional[float] = None
    is_adjustment: bool = False


class ManualTransactionCreate(SQLModel):
    merchant_name: str
    total_amount: float
    currency: str = "PLN"
    date: Optional[datetime] = None
    category_id: Optional[int] = None
    note: Optional[str] = None
    tag_ids: List[int] = Field(default_factory=list)
    lines: List[TransactionLineCreate] = Field(default_factory=list)
    type: str = "expense"  # expense | income | transfer
    account_id: Optional[int] = None
    transfer_id: Optional[int] = None


class TransferCreate(SQLModel):
    source_account_id: int
    destination_account_id: int
    amount: float = Field(gt=0)
    currency: str = Field(default="PLN", min_length=3, max_length=3)
    date: Optional[datetime] = None
    note: Optional[str] = None
    category_id: Optional[int] = None


class TransactionLineUpdate(SQLModel):
    name: Optional[str] = None
    price: Optional[float] = None
    quantity: Optional[float] = None
    category_id: Optional[int] = None
    original_price: Optional[float] = None
    discount_total: Optional[float] = None
    final_price: Optional[float] = None
    is_adjustment: Optional[bool] = None



class VerifyRequest(SQLModel):
    """Body for POST /transactions/{id}/verify — user confirms AI-parsed receipt."""
    transaction_update: TransactionUpdate
    lines_update: Optional[List[TransactionLineUpdate]] = None
    keep_image: bool = False


class EnvelopeAllocationUpdate(SQLModel):
    amount: float


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
    planned: float
    spent: float
    remaining: float


class MonthlyBudgetSummary(SQLModel):
    year: int
    month: int
    total_planned: float
    total_spent: float
    net_cash_flow: float
    total_income: float
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
        query_out = text("""
            SELECT type, SUM(total_amount)
            FROM "transaction"
            WHERE account_id = :acc_id
            GROUP BY type
        """)
        res_out = connection.execute(query_out, {"acc_id": acc_id}).fetchall()

        query_in = text("""
            SELECT SUM(total_amount)
            FROM "transaction"
            WHERE transfer_id = :acc_id AND type = 'transfer'
        """)
        res_in = connection.execute(query_in, {"acc_id": acc_id}).scalar() or 0.0

        query_init = text("""
            SELECT initial_balance FROM account WHERE id = :acc_id
        """)
        init_bal = connection.execute(query_init, {"acc_id": acc_id}).scalar() or 0.0

        balance = init_bal
        for tx_type, total in res_out:
            if total:
                if tx_type == "income":
                    balance += total
                elif tx_type in ("expense", "transfer"):
                    balance -= total

        balance += res_in

        connection.execute(
            text("UPDATE account SET current_balance = :bal WHERE id = :acc_id"),
            {"bal": round(balance, 2), "acc_id": acc_id}
        )
