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
    receipts: List["Receipt"] = Relationship(back_populates="uploader")


# ─── Budget (multi-tenant household container) ────────────────────────────────

class Budget(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    owner_id: Optional[int] = Field(default=None, foreign_key="user.id")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    owner: Optional[User] = Relationship(back_populates="owned_budgets")
    members: List["BudgetMember"] = Relationship(back_populates="budget")
    receipts: List["Receipt"] = Relationship(back_populates="budget")
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
    receipts: List["Receipt"] = Relationship(back_populates="category")


class TagBase(SQLModel):
    name: str
    color: Optional[str] = None


class ReceiptTagLink(SQLModel, table=True):
    receipt_id: Optional[int] = Field(default=None, foreign_key="receipt.id", primary_key=True)
    tag_id: Optional[int] = Field(default=None, foreign_key="tag.id", primary_key=True)


class Tag(TagBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    owner_id: Optional[int] = Field(default=None, foreign_key="user.id")

    receipts: List["Receipt"] = Relationship(back_populates="tags", link_model=ReceiptTagLink)


# ─── Receipt ──────────────────────────────────────────────────────────────────

class ReceiptBase(SQLModel):
    merchant_name: str = Field(index=True)
    date: Optional[datetime] = Field(default=None)
    total_amount: float = Field(default=0.0)
    currency: str = Field(default="PLN")
    image_path: Optional[str] = None
    status: str = Field(default="pending")
    content_hash: Optional[str] = Field(default=None, index=True)
    is_manual: bool = Field(default=False)


class Receipt(ReceiptBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    budget_id: Optional[int] = Field(default=None, foreign_key="budget.id", index=True)
    uploaded_by: Optional[int] = Field(default=None, foreign_key="user.id")
    category_id: Optional[int] = Field(default=None, foreign_key="category.id")

    items: List["Item"] = Relationship(back_populates="receipt")
    budget: Optional[Budget] = Relationship(back_populates="receipts")
    uploader: Optional[User] = Relationship(back_populates="receipts")
    category: Optional["Category"] = Relationship(back_populates="receipts")
    tags: List["Tag"] = Relationship(back_populates="receipts", link_model=ReceiptTagLink)


# ─── Item ─────────────────────────────────────────────────────────────────────

class ItemBase(SQLModel):
    name: str
    price: float
    quantity: float = Field(default=1.0)
    category: Optional[str] = None


class Item(ItemBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    receipt_id: Optional[int] = Field(default=None, foreign_key="receipt.id")
    receipt: Optional[Receipt] = Relationship(back_populates="items")


# ─── MonthlyBudget (spending limit per month) ────────────────────────────────

class MonthlyBudget(SQLModel, table=True):
    __tablename__: str = "monthly_budget" # type: ignore

    id: Optional[int] = Field(default=None, primary_key=True)
    month: int = Field(index=True)
    year: int = Field(index=True)
    amount: float = Field(default=0.0)
    budget_id: Optional[int] = Field(default=None, foreign_key="budget.id", index=True)
    user_id: Optional[int] = Field(default=None, foreign_key="user.id", index=True)

    budget: Optional[Budget] = Relationship(back_populates="monthly_budgets")


# ─── API DTOs ────────────────────────────────────────────────────────────────

class ItemRead(ItemBase):
    id: int


class ReceiptRead(ReceiptBase):
    id: int
    items: List[ItemRead] = []
    budget_id: Optional[int] = None
    uploaded_by: Optional[int] = None
    tags: List["TagRead"] = []


class ReceiptCreate(ReceiptBase):
    pass


class ReceiptUpdate(SQLModel):
    merchant_name: Optional[str] = None
    date: Optional[datetime] = None
    total_amount: Optional[float] = None
    currency: Optional[str] = None
    status: Optional[str] = None
    category_id: Optional[int] = None
    tag_ids: Optional[List[int]] = None


class ManualItemCreate(SQLModel):
    name: str
    price: float
    quantity: float = 1.0
    category: str = "Other"


class ManualReceiptCreate(SQLModel):
    merchant_name: str
    total_amount: float
    currency: str = "PLN"
    date: Optional[datetime] = None
    category_id: Optional[int] = None
    note: Optional[str] = None
    tag_ids: List[int] = Field(default_factory=list)
    items: List[ManualItemCreate] = Field(default_factory=list)


class ItemUpdate(SQLModel):
    name: Optional[str] = None
    price: Optional[float] = None
    quantity: Optional[float] = None
    category: Optional[str] = None


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
