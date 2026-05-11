# backend/app/lidl_parser.py
from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from enum import Enum, auto
from typing import Optional


# ── Data types ─────────────────────────────────────────────────────────────────

@dataclass
class ParsedItem:
    name: str
    price: Decimal      # total amount paid (negative for discounts)
    quantity: Decimal = Decimal("1")
    category: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "price": float(self.price),
            "quantity": float(self.quantity),
            "category": self.category,
        }


@dataclass
class ParsedReceipt:
    merchant_name: str
    date: str           # YYYY-MM-DD
    total_amount: Decimal
    currency: str
    items: list[ParsedItem] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "merchant_name": self.merchant_name,
            "date": self.date,
            "total_amount": float(self.total_amount),
            "currency": self.currency,
            "items": [item.to_dict() for item in self.items],
        }


# ── Base parser ────────────────────────────────────────────────────────────────

class BaseDeterministicParser(ABC):
    """Abstract base for merchant-specific deterministic parsers."""

    @abstractmethod
    def parse(self, lines: list[str]) -> ParsedReceipt:
        ...


# ── Regex patterns ─────────────────────────────────────────────────────────────

_DATE_LINE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# "34.99 14.97 C" or "4.99 4.99C" — unit_price total VAT_rate
_PRICE_LINE = re.compile(
    r"^(\d+[.,]\d+)\s+(\d+[.,]\d+)\s*([A-E])\s*$",
    re.IGNORECASE,
)

# "3 * 4,99 14,97 C" or "2x4.99 9.98 C"
_QTY_PRICE_LINE = re.compile(
    r"^(\d+)\s*[*×xX]\s*(\d+[.,]\d+)\s+(\d+[.,]\d+)\s*([A-E])\s*$",
    re.IGNORECASE,
)

# "0,488 kg x 9,99 4,88 C"
_WEIGHT_PRICE_LINE = re.compile(
    r"^(\d+[.,]\d+)\s*kg\s*[x×xX]\s*(\d+[.,]\d+)\s+(\d+[.,]\d+)\s*([A-E])\s*$",
    re.IGNORECASE,
)

# "RABAT 50 % -10,00" / "Lidl Plus voucher -0,27" / "Nie marnuję -4,58"
_DISCOUNT_LINE = re.compile(r"^(.+?)\s+(-\d+[.,]\d+)\s*$")

# Signals end of product section
_SUMMARY_TRIGGER = re.compile(
    r"^(Suma\s+PLN|Suma|SUMA|Razem|RAZEM|Do\s+zapłaty|Numer\s+kasy|Kasa\s+nr)",
    re.IGNORECASE,
)


def _parse_decimal(s: str) -> Decimal:
    try:
        return Decimal(s.replace(",", ".").replace(" ", ""))
    except InvalidOperation:
        return Decimal("0")


# ── Lidl Parser ────────────────────────────────────────────────────────────────

class _State(Enum):
    HEADER = auto()
    PRODUCTS = auto()
    SUMMARY = auto()


class LidlReceiptParser(BaseDeterministicParser):
    """
    State machine parser for Lidl Plus PNG receipts.

    Lidl receipt structure:
      HEADER  — store address, date
      PRODUCTS — name line + price line + optional discount lines
      SUMMARY — totals, VAT breakdown, payment info

    Price line format: "<unit_price> <total> <VAT_rate>"
    The second number (total) is always the amount charged for that line.
    """

    _SUMA_BARE = re.compile(r"^Suma\s+(\d+[.,]\d+)\s*$", re.IGNORECASE)

    @staticmethod
    def _extract_total(lines: list[str]) -> Decimal:
        # Find first "Suma PLN X" — subtotal before any deposit-return adjustments.
        suma_pln_idx: Optional[int] = None
        suma_pln_val = Decimal("0")
        for i, line in enumerate(lines):
            m = re.search(r"Suma\s+PLN\s+(\d+[.,]\d+)", line, re.IGNORECASE)
            if m:
                suma_pln_idx = i
                suma_pln_val = _parse_decimal(m.group(1))
                break

        if suma_pln_idx is None:
            return Decimal("0")

        # Receipts with deposit returns print a bare "Suma X" (no PLN) AFTER
        # "Suma PLN X" representing the final amount after kaucja adjustments.
        for line in lines[suma_pln_idx + 1:]:
            m = LidlReceiptParser._SUMA_BARE.match(line)
            if m:
                return _parse_decimal(m.group(1))

        return suma_pln_val

    def parse(self, lines: list[str]) -> ParsedReceipt:
        state = _State.HEADER
        items: list[ParsedItem] = []
        date = ""
        total_amount = self._extract_total(lines)
        pending_name: Optional[str] = None

        for raw_line in lines:
            line = raw_line.strip()
            if not line:
                continue

            if state == _State.HEADER:
                if _DATE_LINE.match(line):
                    date = line
                    state = _State.PRODUCTS
                continue

            if state == _State.SUMMARY:
                continue

            # ── PRODUCTS state ─────────────────────────────────────────────────

            if _SUMMARY_TRIGGER.match(line):
                pending_name = None
                state = _State.SUMMARY
                continue

            # Weight price: "0,488 kg x 9,99 4,88 C"
            m = _WEIGHT_PRICE_LINE.match(line)
            if m and pending_name:
                items.append(ParsedItem(
                    name=pending_name,
                    price=_parse_decimal(m.group(3)),
                    quantity=_parse_decimal(m.group(1)),
                ))
                pending_name = None
                continue

            # Quantity price: "3 * 4,99 14,97 C"
            m = _QTY_PRICE_LINE.match(line)
            if m and pending_name:
                items.append(ParsedItem(
                    name=pending_name,
                    price=_parse_decimal(m.group(3)),
                    quantity=_parse_decimal(m.group(1)),
                ))
                pending_name = None
                continue

            # Regular price: "34.99 14.97 C"
            m = _PRICE_LINE.match(line)
            if m and pending_name:
                items.append(ParsedItem(
                    name=pending_name,
                    price=_parse_decimal(m.group(2)),
                    quantity=Decimal("1"),
                ))
                pending_name = None
                continue

            # Discount: ends with negative amount
            m = _DISCOUNT_LINE.match(line)
            if m:
                items.append(ParsedItem(
                    name=m.group(1).strip(),
                    price=_parse_decimal(m.group(2)),
                    quantity=Decimal("1"),
                ))
                continue

            # Product name
            pending_name = line

        return ParsedReceipt(
            merchant_name="Lidl",
            date=date,
            total_amount=total_amount,
            currency="PLN",
            items=items,
        )
