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
    price: Decimal      # total amount paid; equals final_price when discounts are present
    quantity: Decimal = Decimal("1")
    category: Optional[str] = None
    original_price: Optional[Decimal] = None   # price before discounts
    discount_total: Decimal = Decimal("0")     # sum of all discounts (negative)
    final_price: Optional[Decimal] = None      # original_price + discount_total (what was actually charged)
    is_adjustment: bool = False                # True for basket-level discounts/refunds (e.g. kaucja)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "price": float(self.price),
            "quantity": float(self.quantity),
            "category": self.category,
            "original_price": float(self.original_price) if self.original_price is not None else None,
            "discount_total": float(self.discount_total),
            "final_price": float(self.final_price) if self.final_price is not None else None,
            "is_adjustment": self.is_adjustment,
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

# OCR sometimes glues "<qty>*<unit>" into one number — e.g. "3*4.99" → "34.99".
# Split first number into single-digit qty + remaining float and validate against the line total.
_MERGED_QTY_UNIT = re.compile(r"^(\d)(\d+[.,]\d+)$")

# "3 * 4,99 14,97 C", "2x4.99 9.98 C", or "1 7.49 7.49 C" (asterisk optional — OCR sometimes drops it)
_QTY_PRICE_LINE = re.compile(
    r"^(\d+)\s*(?:[*×xX]\s*)?(\d+[.,]\d+)\s+(\d+[.,]\d+)\s*([A-E])\s*$",
    re.IGNORECASE,
)

# "0,488 kg x 9,99 4,88 C"
_WEIGHT_PRICE_LINE = re.compile(
    r"^(\d+[.,]\d+)\s*kg\s*[x×xX]\s*(\d+[.,]\d+)\s+(\d+[.,]\d+)\s*([A-E])\s*$",
    re.IGNORECASE,
)

# "RABAT 50 % -10,00" / "Lidl Plus voucher -0,27" / "Nie marnuję -4,58"
_DISCOUNT_LINE = re.compile(r"^(.+?)\s+(-\d+[.,]\d+)\s*$")

# Basket-level adjustments inside the SUMMARY section.
# Matches "Opakowania zwrotne suma -3,70" (bottle deposit refund).
_BASKET_ADJUSTMENT_LINE = re.compile(
    r"^(Opakowania zwrotne suma|Kaucja zwrotna|Łączny rabat[^-\d]*|Rabat koszyka[^-\d]*)\s+(-\d+[.,]\d+)\s*$",
    re.IGNORECASE,
)

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

    # Accepts "Suma 302,63", "Suma 302,63 PLN", "Suma 302,63 zł"
    _SUMA_BARE = re.compile(
        r"^Suma\s+(\d+[.,]\d+)\s*(?:PLN|zł)?\s*$",
        re.IGNORECASE,
    )

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
                # In SUMMARY: capture basket-level adjustments (kaucja, basket coupons)
                # so items sum equals final total. Skip everything else.
                m = _BASKET_ADJUSTMENT_LINE.match(line)
                if m:
                    items.append(ParsedItem(
                        name=m.group(1).strip(),
                        price=_parse_decimal(m.group(2)),
                        quantity=Decimal("1"),
                        is_adjustment=True,
                    ))
                continue

            # ── PRODUCTS state ─────────────────────────────────────────────────

            if _SUMMARY_TRIGGER.match(line):
                pending_name = None
                state = _State.SUMMARY
                # Check this very line for a basket adjustment too (defensive).
                m = _BASKET_ADJUSTMENT_LINE.match(line)
                if m:
                    items.append(ParsedItem(
                        name=m.group(1).strip(),
                        price=_parse_decimal(m.group(2)),
                        quantity=Decimal("1"),
                        is_adjustment=True,
                    ))
                continue

            # Weight price: "0,488 kg x 9,99 4,88 C"
            m = _WEIGHT_PRICE_LINE.match(line)
            if m and pending_name:
                items.append(ParsedItem(
                    name=pending_name,
                    price=_parse_decimal(m.group(2)),    # unit price (per kg)
                    quantity=_parse_decimal(m.group(1)), # weight
                ))
                pending_name = None
                continue

            # Regular price: "34.99 14.97 C" — must be checked before _QTY_PRICE_LINE,
            # because the relaxed qty regex can backtrack and falsely match a regular price.
            m = _PRICE_LINE.match(line)
            if m and pending_name:
                first_num_raw = m.group(1)
                line_total = _parse_decimal(m.group(2))

                # OCR-merge heuristic: a qty like "3*4.99" gets glued to "34.99".
                # If splitting the first digit reproduces the line total, treat as qty form.
                m_split = _MERGED_QTY_UNIT.match(first_num_raw)
                if m_split:
                    qty_candidate = _parse_decimal(m_split.group(1))
                    unit_candidate = _parse_decimal(m_split.group(2))
                    if qty_candidate > 0 and abs(qty_candidate * unit_candidate - line_total) < Decimal("0.01"):
                        items.append(ParsedItem(
                            name=pending_name,
                            price=unit_candidate,
                            quantity=qty_candidate,
                        ))
                        pending_name = None
                        continue

                items.append(ParsedItem(
                    name=pending_name,
                    price=line_total,
                    quantity=Decimal("1"),
                ))
                pending_name = None
                continue

            # Quantity price: "3 * 4,99 14,97 C" or "1 7,49 7,49 C" (asterisk-less from OCR)
            m = _QTY_PRICE_LINE.match(line)
            if m and pending_name:
                items.append(ParsedItem(
                    name=pending_name,
                    price=_parse_decimal(m.group(2)),    # unit price
                    quantity=_parse_decimal(m.group(1)), # count
                ))
                pending_name = None
                continue

            # Discount: ends with negative amount — attach to last appended item
            m = _DISCOUNT_LINE.match(line)
            if m and items and not items[-1].is_adjustment:
                discount_val = _parse_decimal(m.group(2))  # total discount (negative)
                last = items[-1]
                if last.original_price is None:
                    last.original_price = last.price  # unit price at this point
                # discount_total tracks the full receipt-line discount (for display badge)
                last.discount_total += discount_val
                # Update unit price: spread discount across quantity
                qty = last.quantity if last.quantity > 0 else Decimal("1")
                last.price = last.original_price + (last.discount_total / qty)
                last.final_price = last.price
                continue
            # Orphaned discount (no items yet, or last item is itself an adjustment) —
            # treat as a basket-level adjustment so it does not contaminate a product.
            if m:
                items.append(ParsedItem(
                    name=m.group(1).strip(),
                    price=_parse_decimal(m.group(2)),
                    quantity=Decimal("1"),
                    is_adjustment=True,
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
