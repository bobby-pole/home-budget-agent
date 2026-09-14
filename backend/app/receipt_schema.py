# backend/app/receipt_schema.py
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Optional


def to_decimal(value: Any, default: str = "0") -> Decimal:
    """Safely convert any numeric, float, or string value into a Decimal."""
    if isinstance(value, Decimal):
        return value
    if value is None:
        return Decimal(default)
    try:
        s = str(value).replace(",", ".").replace(" ", "").strip()
        if not s:
            return Decimal(default)
        return Decimal(s)
    except (InvalidOperation, ValueError):
        return Decimal(default)


@dataclass
class CanonicalItem:
    """
    Canonical representation of a single receipt line item or adjustment.
    All monetary calculations are performed using Decimal.
    """
    name: str
    unit_price: Decimal                           # Regular unit price before any discount
    quantity: Decimal = Decimal("1.0")            # Quantity or weight (kg)
    discount_total: Decimal = Decimal("0")        # Combined discount amount for this line (always <= 0)
    category: Optional[str] = None                # Category name (e.g., 'Groceries', 'Household')
    category_source: Optional[str] = None         # 'cache', 'ai', 'user'
    is_adjustment: bool = False                   # True for basket-level adjustments (kaucja, vouchers)
    _original_price: Optional[Decimal] = None     # Optional explicit regular price

    def __init__(
        self,
        name: str,
        unit_price: Any,
        quantity: Any = Decimal("1.0"),
        discount_total: Any = Decimal("0"),
        category: Optional[str] = None,
        category_source: Optional[str] = None,
        is_adjustment: bool = False,
        original_price: Optional[Any] = None,
        final_price: Optional[Any] = None,
        price: Optional[Any] = None,
    ) -> None:
        self.name = str(name)
        self.unit_price = to_decimal(unit_price)
        self.quantity = to_decimal(quantity, default="1.0")
        self.discount_total = to_decimal(discount_total, default="0")
        if self.discount_total > Decimal("0"):
            self.discount_total = -self.discount_total
        self.category = category
        self.category_source = category_source
        self.is_adjustment = bool(is_adjustment)
        self._original_price = to_decimal(original_price) if original_price is not None else None
        self._extra: dict[str, Any] = {}

    @property
    def final_line_total(self) -> Decimal:
        """
        Total amount payable for this line item.
        For adjustments and regular products: (quantity * unit_price) + discount_total.
        """
        total = (self.quantity * self.unit_price) + self.discount_total
        return total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    @property
    def effective_unit_price(self) -> Decimal:
        """Effective unit price after applying discounts across the quantity."""
        if self.is_adjustment or self.quantity <= Decimal("0"):
            return self.unit_price
        if self.discount_total == Decimal("0"):
            return self.unit_price
        return (self.final_line_total / self.quantity).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)

    @property
    def price(self) -> Decimal:
        """Backward-compatible alias for effective_unit_price (or unit_price)."""
        return self.effective_unit_price

    @property
    def original_price(self) -> Optional[Decimal]:
        """Backward-compatible regular price before discount."""
        if self._original_price is not None:
            return self._original_price
        if self.discount_total < Decimal("0") and not self.is_adjustment:
            return self.unit_price
        return None

    @property
    def final_price(self) -> Optional[Decimal]:
        """Backward-compatible final price after discount."""
        if self.discount_total < Decimal("0"):
            return self.effective_unit_price
        return None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict compatible with API, Database models, and UI."""
        if self._original_price is not None:
            orig_price = float(self._original_price)
        elif self.discount_total < Decimal("0") and not self.is_adjustment:
            orig_price = float(self.unit_price)
        else:
            orig_price = None

        final_unit = float(self.effective_unit_price) if self.discount_total < Decimal("0") else float(self.unit_price)

        d = {
            "name": self.name,
            "unit_price": float(self.unit_price),
            "price": float(self.effective_unit_price),
            "quantity": float(self.quantity),
            "category": self.category,
            "category_source": self.category_source,
            "original_price": orig_price,
            "discount_total": float(self.discount_total),
            "final_price": final_unit if self.discount_total < Decimal("0") else None,
            "final_line_total": float(self.final_line_total),
            "is_adjustment": self.is_adjustment,
        }
        if hasattr(self, "_extra"):
            d.update(self._extra)
        return d

    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]

    def __setitem__(self, key: str, value: Any) -> None:
        if hasattr(self, key) and key not in ("price", "final_line_total", "effective_unit_price", "original_price", "final_price"):
            setattr(self, key, value)
        else:
            if not hasattr(self, "_extra"):
                self._extra = {}
            self._extra[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        return self.to_dict().get(key, default)

    def __contains__(self, key: str) -> bool:
        return key in self.to_dict()


@dataclass
class CanonicalReceipt:
    """
    Canonical representation of a parsed receipt from any source.
    """
    merchant_name: str
    date: str                                     # YYYY-MM-DD
    total_amount: Decimal                         # Final total payable from summary
    currency: str = "PLN"
    items: list[CanonicalItem] = field(default_factory=list)
    _extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.total_amount = to_decimal(self.total_amount)
        if not self.currency:
            self.currency = "PLN"
        if not hasattr(self, "_extra"):
            self._extra = {}

    @property
    def calculated_total(self) -> Decimal:
        """Sum of all line items (including adjustments)."""
        return sum((item.final_line_total for item in self.items), Decimal("0")).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict compatible with PipelineRunner, API, and validation."""
        d = {
            "merchant_name": self.merchant_name,
            "date": self.date,
            "total_amount": float(self.total_amount),
            "currency": self.currency,
            "items": [item.to_dict() for item in self.items],
        }
        if hasattr(self, "_extra"):
            d.update(self._extra)
        return d

    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]

    def __setitem__(self, key: str, value: Any) -> None:
        if hasattr(self, key) and key not in ("calculated_total",):
            setattr(self, key, value)
        else:
            if not hasattr(self, "_extra"):
                self._extra = {}
            self._extra[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        return self.to_dict().get(key, default)

    def __contains__(self, key: str) -> bool:
        return key in self.to_dict()
