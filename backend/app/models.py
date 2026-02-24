# backend/app/models.py
from typing import List, Optional
from datetime import datetime
from sqlmodel import Field, Relationship, SQLModel


# ─── User ─────────────────────────────────────────────────────────────────────

class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(unique=True, index=True)
    hashed_password: str
    created_at: datetime = Field(default_factory=datetime.utcnow)

    owned_budgets: List["Budget"] = Relationship(back_populates="owner")
    memberships: List["BudgetMember"] = Relationship(back_populates="user")
    receipts: List["Receipt"] = Relationship(back_populates="uploader")


# ─── Budget (multi-tenant household container) ────────────────────────────────

class Budget(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    owner_id: Optional[int] = Field(default=None, foreign_key="user.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)

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


# ─── Receipt ──────────────────────────────────────────────────────────────────

class ReceiptBase(SQLModel):
    merchant_name: str = Field(index=True)
    date: Optional[datetime] = Field(default=None)
    total_amount: float = Field(default=0.0)
    currency: str = Field(default="PLN")
    image_path: Optional[str] = None
    status: str = Field(default="pending")
    content_hash: Optional[str] = Field(default=None, index=True)


class Receipt(ReceiptBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    budget_id: Optional[int] = Field(default=None, foreign_key="budget.id", index=True)
    uploaded_by: Optional[int] = Field(default=None, foreign_key="user.id")

    items: List["Item"] = Relationship(back_populates="receipt")
    budget: Optional[Budget] = Relationship(back_populates="receipts")
    uploader: Optional[User] = Relationship(back_populates="receipts")


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
    __tablename__ = "monthly_budget"

    id: Optional[int] = Field(default=None, primary_key=True)
    month: int = Field(index=True)
    year: int = Field(index=True)
    amount: float = Field(default=0.0)
    budget_id: Optional[int] = Field(default=None, foreign_key="budget.id", index=True)

    budget: Optional[Budget] = Relationship(back_populates="monthly_budgets")


# ─── API DTOs ────────────────────────────────────────────────────────────────

class ItemRead(ItemBase):
    id: int


class ReceiptRead(ReceiptBase):
    id: int
    items: List[ItemRead] = []
    budget_id: Optional[int] = None
    uploaded_by: Optional[int] = None


class ReceiptCreate(ReceiptBase):
    pass


class ReceiptUpdate(SQLModel):
    merchant_name: Optional[str] = None
    date: Optional[datetime] = None
    total_amount: Optional[float] = None
    currency: Optional[str] = None
    status: Optional[str] = None


class ItemUpdate(SQLModel):
    name: Optional[str] = None
    price: Optional[float] = None
    quantity: Optional[float] = None
    category: Optional[str] = None


class MonthlyBudgetUpdate(SQLModel):
    amount: float
