# backend/app/models.py
from typing import List, Optional
from datetime import datetime
from sqlmodel import Field, Relationship, SQLModel

# --- Base Models ---
class ReceiptBase(SQLModel):
    merchant_name: str = Field(index=True)
    date: datetime = Field(default_factory=datetime.utcnow)
    total_amount: float = Field(default=0.0)
    currency: str = Field(default="PLN")
    image_path: Optional[str] = None
    status: str = Field(default="pending")

class ItemBase(SQLModel):
    name: str
    price: float
    quantity: float = Field(default=1.0)
    category: Optional[str] = None

# --- Database Models ---
class Receipt(ReceiptBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    items: List["Item"] = Relationship(back_populates="receipt")

class Item(ItemBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    receipt_id: Optional[int] = Field(default=None, foreign_key="receipt.id")
    receipt: Optional[Receipt] = Relationship(back_populates="items")

# --- API Models (DTO) ---
class ItemRead(ItemBase):
    id: int

class ReceiptRead(ReceiptBase):
    id: int
    items: List[ItemRead] = []

class ReceiptCreate(ReceiptBase):
    pass

