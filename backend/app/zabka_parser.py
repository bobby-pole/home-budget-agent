# backend/app/zabka_parser.py
from __future__ import annotations

import re
from decimal import Decimal
from typing import Optional

from .lidl_parser import BaseDeterministicParser
from .receipt_schema import CanonicalItem, CanonicalReceipt, to_decimal
from .receipt_normalizer import normalize_receipt

# Backward-compatible aliases
ParsedReceipt = CanonicalReceipt
ParsedItem = CanonicalItem

_DATE_LINE = re.compile(r"^\d{4}-\d{2}-\d{2}")

# Example: "2 szt. x 5,50 11,00 A" or "1 x 6,50 6,50 A"
_ZABKA_PRICE_LINE = re.compile(
    r"^(\d+(?:[.,]\d+)?)\s*(?:szt\.?|kg)?\s*[x×X]\s*(\d+[.,]\d+)\s+(\d+[.,]\d+)\s*([A-E])",
    re.IGNORECASE,
)

# Single price line right under pending name: "6,50 A"
_ZABKA_SINGLE_PRICE_LINE = re.compile(r"^(\d+[.,]\d+)\s*([A-E])$", re.IGNORECASE)

# Negative discount amount line: "-2,00 A" or "-1,50"
_DISCOUNT_VAL_LINE = re.compile(r"^(-\d+[.,]\d+)\s*[A-E]?$")

# Named discount line: "Wielosztuka -2,00" or "Rabat -1,50"
_DISCOUNT_NAMED_LINE = re.compile(
    r"^(?:Wielosztuka|Rabat|Opust|Żabka).*?(-\d+[.,]\d+)",
    re.IGNORECASE,
)

# Bottle deposit adjustment: "Kaucja -1,00" or "Butelka zwrotna 0,50"
_ADJUSTMENT_LINE = re.compile(
    r"^(?:kaucja|butelka|opakowanie).*?(-?\d+[.,]\d+)",
    re.IGNORECASE,
)

_SUMA_PLN = re.compile(r"^SUMA\s+PLN(?:\s+(\d+[.,]\d+))?", re.IGNORECASE)
_SUMA_BARE = re.compile(r"^(\d+[.,]\d+)\s*(?:PLN|zł)?$", re.IGNORECASE)


class ZabkaReceiptParser(BaseDeterministicParser):
    """
    Deterministic parser for Zabka receipts.
    Supports parsing lines (from PDF/OCR) or JSON (e-paragon).
    """

    def parse_json(self, file_bytes: bytes) -> CanonicalReceipt:
        """Wrapper for JSON e-paragon format."""
        from .ocr_pipeline import EParagonJSONAdapter
        res = EParagonJSONAdapter.parse(file_bytes)
        if isinstance(res, CanonicalReceipt):
            return res
        return normalize_receipt(res)

    def parse(self, lines: list[str]) -> CanonicalReceipt:
        items: list[CanonicalItem] = []
        date_str = ""
        total_amount = Decimal("0")

        pending_name: Optional[str] = None
        state = "HEADER"

        # 1. Look for date anywhere
        for line in lines:
            m = _DATE_LINE.search(line)
            if m and not date_str:
                date_str = m.group(0)

        # 2. Main parse loop
        for line in lines:
            line = line.strip()
            if not line:
                continue

            if state == "HEADER":
                if "PARAGON FISKALNY" in line.upper():
                    state = "PRODUCTS"
                continue

            if state == "SUMMARY":
                m_total = _SUMA_BARE.match(line)
                if m_total and total_amount == Decimal("0"):
                    total_amount = to_decimal(m_total.group(1))
                else:
                    m_suma = _SUMA_PLN.match(line)
                    if m_suma and m_suma.group(1) and total_amount == Decimal("0"):
                        total_amount = to_decimal(m_suma.group(1))
                continue

            if state == "PRODUCTS":
                m_suma = _SUMA_PLN.match(line)
                if m_suma:
                    state = "SUMMARY"
                    pending_name = None
                    if m_suma.group(1):
                        total_amount = to_decimal(m_suma.group(1))
                    continue

                m_adj = _ADJUSTMENT_LINE.match(line)
                if m_adj:
                    items.append(CanonicalItem(
                        name=m_adj.group(1).strip(),
                        unit_price=to_decimal(m_adj.group(2)),
                        quantity=Decimal("1.0"),
                        is_adjustment=True,
                    ))
                    pending_name = None
                    continue

                m_price = _ZABKA_PRICE_LINE.match(line)
                if m_price:
                    if pending_name:
                        qty = to_decimal(m_price.group(1), default="1.0")
                        unit = to_decimal(m_price.group(2))

                        items.append(CanonicalItem(
                            name=pending_name,
                            unit_price=unit,
                            quantity=qty,
                            discount_total=Decimal("0"),
                            is_adjustment=False,
                        ))
                        pending_name = None
                    continue

                m_single = _ZABKA_SINGLE_PRICE_LINE.match(line)
                if m_single and pending_name:
                    unit = to_decimal(m_single.group(1))
                    items.append(CanonicalItem(
                        name=pending_name,
                        unit_price=unit,
                        quantity=Decimal("1.0"),
                        discount_total=Decimal("0"),
                        is_adjustment=False,
                    ))
                    pending_name = None
                    continue

                m_disc_val = _DISCOUNT_VAL_LINE.match(line)
                if m_disc_val and items:
                    discount_val = to_decimal(m_disc_val.group(1))
                    last = items[-1]
                    last.discount_total += discount_val
                    pending_name = None
                    continue

                m_disc_named = _DISCOUNT_NAMED_LINE.match(line)
                if m_disc_named and items:
                    discount_val = to_decimal(m_disc_named.group(1))
                    last = items[-1]
                    last.discount_total += discount_val
                    pending_name = None
                    continue

                # Skip discount title lines without amounts (value follows on next line)
                if line.upper().startswith("OPUST ") or line.upper().startswith("RABAT ") or line.upper().startswith("WIELOSZTUKA"):
                    continue

                # If nothing matches, this line is candidate for next product name
                pending_name = line

        receipt = CanonicalReceipt(
            merchant_name="Żabka",
            date=date_str,
            total_amount=total_amount,
            currency="PLN",
            items=items,
        )
        return normalize_receipt(receipt)
