# backend/app/biedronka_parser.py
from __future__ import annotations

import re
from decimal import Decimal

from .lidl_parser import BaseDeterministicParser
from .receipt_schema import CanonicalItem, CanonicalReceipt, to_decimal
from .receipt_normalizer import normalize_receipt

# Backward-compatible aliases
ParsedReceipt = CanonicalReceipt
ParsedItem = CanonicalItem

_DATE_LINE = re.compile(r"(?:\b(\d{4}-\d{2}-\d{2})\b|\b(\d{2})[/.-](\d{2})[/.-](\d{4})\b)")

# Example with multiplier: "PomidorPaprycz500g с 2x 14,99 29,98" or "BułkaKajzerka55g 3x 0,34 1,02"
# Group 1: Name, Group 2: qty, Group 3: unit_price, Group 4: total
_BIEDRONKA_ITEM_LINE = re.compile(
    r"^(.*?)\s+(?:[A-Ea-zс]\s+)?(\d+(?:[.,]\d+)?)\s*[xX×]\s*(\d+[.,]\d+)\s+(\d+[.,]\d+)$",
    re.IGNORECASE,
)

# Example without multiplier (single item): "Chleb Żytni 450g A 4,50" or "Masło Ekstra 200g 7,99 A"
_BIEDRONKA_SINGLE_ITEM_LINE = re.compile(
    r"^(.*?)\s+(?:([A-Ea-zс])\s+)?(\d+[.,]\d+)(?:\s+([A-Ea-zс]))?$",
    re.IGNORECASE,
)

# Multi-variant discounts in Biedronka
_DISCOUNT_LINE = re.compile(
    r"^(?:Rabat|Opust|Moja\s+Biedronka|Oszczędzasz(?:\s+z\s+kartą)?|Wielosztuka|Supercena)(?!\s+(?:łącznie|razem)).*?(-\d+[.,]\d+)",
    re.IGNORECASE,
)

# Bottle deposits / basket adjustments
_ADJUSTMENT_LINE = re.compile(
    r"^(?:kaucja\s+zwrotna|butelka\s+zwrotna|opakowania\s+zwrotne|kaucja)\s+(-?\d+[.,]\d+)",
    re.IGNORECASE,
)

_SUMMARY_START = re.compile(
    r"^(?:OPUSTY\s+ŁĄCZNIE|RABATY\s+ŁĄCZNIE|SPRZEDAŻ\s+OPODATKOWANA|PTU\s+[A-Z]|SUMA\s+PLN|SUMA\s+PTU|RAZEM|DO\s+ZAPŁATY|SUMA)",
    re.IGNORECASE,
)

_SUMA_TOTAL = re.compile(
    r"^(?:SUMA\s+PLN|RAZEM|DO\s+ZAPŁATY|SUMA)\s*(\d+[.,]\d+)",
    re.IGNORECASE,
)

# Non-product keywords to exclude from single item regex matching
_IGNORED_NAME_KEYWORDS = re.compile(
    r"^(PARAGON|SUMA|RAZEM|PTU|KASJER|KASA|BDO|NIP|SPRZEDAŻ|OPUSTY|RABAT|ROZLICZENIE|PŁATNOŚĆ|KARTA|KOD|RABATY|CENA)",
    re.IGNORECASE,
)


class BiedronkaReceiptParser(BaseDeterministicParser):
    """
    Deterministic parser for Biedronka receipts.
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

        state = "HEADER"

        for line in lines:
            m = _DATE_LINE.search(line)
            if m and not date_str:
                if m.group(1):
                    date_str = m.group(1)
                elif m.group(2) and m.group(3) and m.group(4):
                    date_str = f"{m.group(4)}-{m.group(3)}-{m.group(2)}"

        for line in lines:
            line = line.strip()
            if not line:
                continue

            if state == "HEADER":
                if "PARAGON FISKALNY" in line.upper():
                    state = "PRODUCTS"
                continue

            if state == "SUMMARY":
                m_total = _SUMA_TOTAL.match(line)
                if m_total and total_amount == Decimal("0"):
                    total_amount = to_decimal(m_total.group(1))
                continue

            if state == "PRODUCTS":
                if _SUMMARY_START.match(line):
                    state = "SUMMARY"
                    m_total = _SUMA_TOTAL.match(line)
                    if m_total and total_amount == Decimal("0"):
                        total_amount = to_decimal(m_total.group(1))
                    continue

                # Skip bare numbers (e.g. subtotal lines after discounts or random barcode fragments)
                if re.match(r"^\d+(?:[.,]\d+)?$", line):
                    continue

                m_adj = _ADJUSTMENT_LINE.match(line)
                if m_adj:
                    items.append(CanonicalItem(
                        name=m_adj.group(1).strip(),
                        unit_price=to_decimal(m_adj.group(2)),
                        quantity=Decimal("1.0"),
                        is_adjustment=True,
                    ))
                    continue

                m_discount = _DISCOUNT_LINE.match(line)
                if m_discount and items:
                    discount_val = to_decimal(m_discount.group(1))
                    last = items[-1]
                    last.discount_total += discount_val
                    continue

                # 1. Multiplier line: "2x 14.99 29.98"
                m_item = _BIEDRONKA_ITEM_LINE.match(line)
                if m_item:
                    name = m_item.group(1).strip()
                    qty = to_decimal(m_item.group(2), default="1.0")
                    unit = to_decimal(m_item.group(3))

                    items.append(CanonicalItem(
                        name=name,
                        unit_price=unit,
                        quantity=qty,
                        discount_total=Decimal("0"),
                        is_adjustment=False,
                    ))
                    continue

                # 2. Single item without multiplier: "Chleb Żytni A 4,50"
                m_single = _BIEDRONKA_SINGLE_ITEM_LINE.match(line)
                if m_single:
                    name = m_single.group(1).strip()
                    # Skip common headers/metadata lines
                    if not _IGNORED_NAME_KEYWORDS.search(name) and len(name) >= 3:
                        price = to_decimal(m_single.group(3))
                        items.append(CanonicalItem(
                            name=name,
                            unit_price=price,
                            quantity=Decimal("1.0"),
                            discount_total=Decimal("0"),
                            is_adjustment=False,
                        ))
                        continue

        receipt = CanonicalReceipt(
            merchant_name="Biedronka",
            date=date_str,
            total_amount=total_amount,
            currency="PLN",
            items=items,
        )
        return normalize_receipt(receipt)
