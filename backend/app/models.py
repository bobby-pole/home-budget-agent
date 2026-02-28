# backend/app/models.py
from typing import List, Optional
from datetime import datetime, timezone
from sqlmodel import Field, Relationship, SQLModel


# ─── User ─────────────────────────────────────────────────────────────────────

class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(unique=True, index=True)
    hashed_password: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    owned_budgets: List["Budget"] = Relationship(back_populates="owner")
    memberships: List["BudgetMember"] = Relationship(back_populates="user")
    transactions: List["Transaction"] = Relationship(back_populates="uploader")


# ─── Budget (multi-tenant household container) ────────────────────────────────

class Budget(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    owner_id: Optional[int] = Field(default=None, foreign_key="user.id")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    owner: Optional[User] = Relationship(back_populates="owned_budgets")
    members: List["BudgetMember"] = Relationship(back_populates="budget")
    transactions: List["Transaction"] = Relationship(back_populates="budget")
    monthly_budgets: List["MonthlyBudget"] = Relationship(back_populates="budget")


# ─── BudgetMember ─────────────────────────────────────────────────────────────

class BudgetMember(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    budget_id: Optional[int] = Field(default=None, foreign_key="budget.id")
    user_id: Optional[int] = Field(default=None, foreign_key="user.id")
    role: str = Field(default="viewer")  # owner / editor / viewer

    budget: Optional[Budget] = Relationship(back_populates="members")
    user: Optional[User] = Relationship(back_populates="memberships")


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
    owner_id: Optional[int] = Field(default=None, foreign_key="user.id")

    parent: Optional["Category"] = Relationship(
        back_populates="subcategories",
        sa_relationship_kwargs=dict(remote_side="Category.id")
    )
    subcategories: List["Category"] = Relationship(back_populates="parent")
    transactions: List["Transaction"] = Relationship(back_populates="category")


class TagBase(SQLModel):
    name: str
    color: Optional[str] = None


class TransactionTagLink(SQLModel, table=True):
    transaction_id: Optional[int] = Field(default=None, foreign_key="transaction.id", primary_key=True)
    tag_id: Optional[int] = Field(default=None, foreign_key="tag.id", primary_key=True)


class Tag(TagBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    owner_id: Optional[int] = Field(default=None, foreign_key="user.id")

    transactions: List["Transaction"] = Relationship(back_populates="tags", link_model=TransactionTagLink)


# ─── Transaction ──────────────────────────────────────────────────────────────

class TransactionBase(SQLModel):
    merchant_name: str = Field(index=True)
    date: Optional[datetime] = Field(default=None)
    total_amount: float = Field(default=0.0)
    currency: str = Field(default="PLN")
    is_manual: bool = Field(default=False)
    type: str = Field(default="expense")  # expense | income | transfer


class Transaction(TransactionBase, table=True):
    __tablename__: str = "transaction"  # type: ignore

    id: Optional[int] = Field(default=None, primary_key=True)
    budget_id: Optional[int] = Field(default=None, foreign_key="budget.id", index=True)
    uploaded_by: Optional[int] = Field(default=None, foreign_key="user.id")
    category_id: Optional[int] = Field(default=None, foreign_key="category.id")

    lines: List["TransactionLine"] = Relationship(back_populates="transaction")
    receipt_scan: Optional["ReceiptScan"] = Relationship(back_populates="transaction")
    budget: Optional[Budget] = Relationship(back_populates="transactions")
    uploader: Optional[User] = Relationship(back_populates="transactions")
    category: Optional["Category"] = Relationship(back_populates="transactions")
    tags: List["Tag"] = Relationship(back_populates="transactions", link_model=TransactionTagLink)


# ─── ReceiptScan ──────────────────────────────────────────────────────────────

class ReceiptScan(SQLModel, table=True):
    __tablename__: str = "receiptscan"  # type: ignore

    id: Optional[int] = Field(default=None, primary_key=True)
    transaction_id: int = Field(foreign_key="transaction.id", index=True)
    image_path: Optional[str] = None
    status: str = Field(default="processing")  # processing | done | error | needs_review
    content_hash: Optional[str] = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    transaction: Optional[Transaction] = Relationship(back_populates="receipt_scan")


# ─── TransactionLine ──────────────────────────────────────────────────────────

class TransactionLineBase(SQLModel):
    name: str
    price: float
    quantity: float = Field(default=1.0)
    category_id: Optional[int] = Field(default=None, foreign_key="category.id")


class TransactionLine(TransactionLineBase, table=True):
    __tablename__: str = "transactionline"  # type: ignore

    id: Optional[int] = Field(default=None, primary_key=True)
    transaction_id: Optional[int] = Field(default=None, foreign_key="transaction.id")
    transaction: Optional[Transaction] = Relationship(back_populates="lines")


# ─── MonthlyBudget (spending limit per month) ────────────────────────────────

class MonthlyBudget(SQLModel, table=True):
    __tablename__: str = "monthly_budget"  # type: ignore

    id: Optional[int] = Field(default=None, primary_key=True)
    month: int = Field(index=True)
    year: int = Field(index=True)
    amount: float = Field(default=0.0)
    budget_id: Optional[int] = Field(default=None, foreign_key="budget.id", index=True)
    user_id: Optional[int] = Field(default=None, foreign_key="user.id", index=True)

    budget: Optional[Budget] = Relationship(back_populates="monthly_budgets")


# ─── API DTOs ────────────────────────────────────────────────────────────────

class TransactionLineRead(TransactionLineBase):
    id: int


class ReceiptScanRead(SQLModel):
    id: int
    status: str
    image_path: Optional[str] = None
    content_hash: Optional[str] = None
    created_at: datetime


class TransactionRead(TransactionBase):
    id: int
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
    tag_ids: Optional[List[int]] = None
    type: Optional[str] = None


class TransactionLineCreate(SQLModel):
    name: str
    price: float
    quantity: float = 1.0
    category_id: Optional[int] = None


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


class TransactionLineUpdate(SQLModel):
    name: Optional[str] = None
    price: Optional[float] = None
    quantity: Optional[float] = None
    category_id: Optional[int] = None


class MonthlyBudgetUpdate(SQLModel):
    amount: float


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
    owner_id: Optional[int] = None


class TagCreate(TagBase):
    pass


class TagUpdate(SQLModel):
    name: Optional[str] = None
    color: Optional[str] = None


class TagRead(TagBase):
    id: int
    owner_id: Optional[int] = None


# ─── Auth DTOs ────────────────────────────────────────────────────────────────

class UserCreate(SQLModel):
    email: str
    password: str


class UserRead(SQLModel):
    id: int
    email: str
    created_at: datetime


class Token(SQLModel):
    access_token: str
    token_type: str = "bearer"
    user: UserRead
