# backend/app/kaufland_parser.py
from __future__ import annotations

import re
from decimal import Decimal
from enum import Enum, auto
from typing import Any, Optional

from .lidl_parser import BaseDeterministicParser
from .receipt_normalizer import normalize_receipt
from .receipt_schema import CanonicalItem, CanonicalReceipt, to_decimal

# Backward-compatible aliases
ParsedReceipt = CanonicalReceipt
ParsedItem = CanonicalItem

# ── Regex patterns ─────────────────────────────────────────────────────────────

# "Data: 28.08.24" or "Date: 28.08.2024" or "2024-08-28"
_DATE_PATTERN = re.compile(
    r"(?:(?:\b(?:Data|Date):\s*(\d{2})[./-](\d{2})[./-](\d{2,4})\b)|\b(\d{4}-\d{2}-\d{2})\b)",
    re.IGNORECASE,
)

# Header end / products section trigger
_HEADER_TRIGGER = re.compile(r"^(?:Cena\s+PLN|PARAGON\s+FISKALNY)", re.IGNORECASE)

# "2 * 5,99 11,98 A" or "3 x 7,99 23,97 B"
_MULTIPLIER_LINE = re.compile(
    r"^\s*(\d+(?:[.,]\d+)?)\s*(?:kg)?\s*[*x×X]\s*(\d+[.,]\d+)\s+(\d+[.,]\d+)\s+([A-E])$",
    re.IGNORECASE,
)

# "0,534 kg * 3,99 2,13 A" or "0,534 kg x 3,99 2,13 A"
_WEIGHT_PRICE_LINE = re.compile(
    r"^\s*(\d+\s*[.,]\s*\d+)\s*kg\s*[*x×X]\s*(\d+[.,]\d+)\s+(\d+[.,]\d+)\s+([A-E])$",
    re.IGNORECASE,
)

# Single item with price on same line: "ViscoplastMikki10szt * 7,99 B" or "Müllermilch Zero 3,19 C"
_SINGLE_ITEM_LINE = re.compile(
    r"^(.*?)(?:\s+[*])?\s+(\d+[.,]\d+)\s+([A-E])$",
    re.IGNORECASE,
)

# Promotion section start: "----------------Promocja---------------"
_PROMO_START = re.compile(r"^[-—=]{2,}\s*Promocja\s*[-—=]{2,}", re.IGNORECASE)

# Promotion discount line: "Kup 2 + 1 gratis -7,99" or "Rabat -5,99"
_PROMO_LINE = re.compile(r"^(.+?)\s+([−\-\u2212]\d+[.,]\d+)\s*$", re.IGNORECASE)

# Promotion positions qualifier: "Pozycje:3" or "Pozycje: 2"
_PROMO_POSITIONS = re.compile(r"^Pozycje:\s*(\d+)", re.IGNORECASE)

# Subtotal / summary triggers
_SUBTOTAL_TRIGGER = re.compile(r"^(?:Suma\s+cząstkowa|Suma\s+częściowa)", re.IGNORECASE)

# Final total: "Suma 51,89" or "SUMA PLN 51,89"
_TOTAL_PATTERN = re.compile(r"^(?:Suma|SUMA(?:\s+PLN)?|RAZEM|DO\s+ZAPŁATY)\s+(\d+[.,]\d+)", re.IGNORECASE)

# Bottle deposits / basket adjustments
_ADJUSTMENT_LINE = re.compile(
    r"^(?:kaucja|butelka|opakowani).*?([−\-\u2212]?\d+[.,]\d+)",
    re.IGNORECASE,
)

# Non-product keywords to avoid falsely treating as single item
_IGNORED_KEYWORDS = re.compile(
    r"^(?:Za\s+ten\s+zakup|Podsumowanie|Kaufland|Al\.|ul\.|Nr\s+BDO|Cena\s+PLN|Vat|Płatność|Reszta|TID|MID|TRX|RRN|AID|Kasa|Market|BEZPŁATNA|Kochamy|Naprawdę|Data|Date|Suma|Kwota)",
    re.IGNORECASE,
)


class _State(Enum):
    HEADER = auto()
    PRODUCTS = auto()
    PROMOTIONS = auto()
    SUMMARY = auto()


class KauflandReceiptParser(BaseDeterministicParser):
    """
    Deterministic parser for Kaufland receipts (PDF e-paragon with text layer or OCR lines).
    Handles department category headers, multi-line items, promotion blocks, and deposit adjustments.
    """

    def parse(self, lines: list[str]) -> CanonicalReceipt:
        state = _State.HEADER
        items: list[CanonicalItem] = []
        promotions: list[dict[str, Any]] = []
        current_promo: Optional[dict[str, Any]] = None
        pending_name: Optional[str] = None
        total_amount = Decimal("0")
        date: str = ""

        for raw_line in lines:
            line = raw_line.strip()
            if not line:
                continue

            # Date extraction anywhere in the receipt
            m_date = _DATE_PATTERN.search(line)
            if m_date and not date:
                if m_date.group(1):
                    d, m, y = m_date.group(1), m_date.group(2), m_date.group(3)
                    if len(y) == 2:
                        y = "20" + y
                    date = f"{y}-{m}-{d}"
                elif m_date.group(4):
                    date = m_date.group(4)

            # ── State: HEADER ───────────────────────────────────────────────────
            if state == _State.HEADER:
                if _HEADER_TRIGGER.search(line):
                    state = _State.PRODUCTS
                    pending_name = None
                continue

            # ── State: PRODUCTS ─────────────────────────────────────────────────
            elif state == _State.PRODUCTS:
                # Transition to PROMOTIONS or SUMMARY
                if _PROMO_START.match(line):
                    pending_name = None
                    state = _State.PROMOTIONS
                    continue

                if _SUBTOTAL_TRIGGER.match(line):
                    pending_name = None
                    state = _State.PROMOTIONS  # often followed immediately by promo block
                    continue

                m_tot = _TOTAL_PATTERN.match(line)
                if m_tot:
                    pending_name = None
                    total_amount = to_decimal(m_tot.group(1))
                    state = _State.SUMMARY
                    continue

                # Check bottle deposit or adjustment inside products
                m_adj = _ADJUSTMENT_LINE.match(line)
                if m_adj:
                    adj_name = line[:m_adj.start(1)].strip() or line.split()[0]
                    items.append(CanonicalItem(
                        name=adj_name,
                        unit_price=to_decimal(m_adj.group(1)),
                        quantity=Decimal("1"),
                        is_adjustment=True,
                    ))
                    pending_name = None
                    continue

                # Check weight line: "0,534 kg * 3,99 2,13 A"
                m_weight = _WEIGHT_PRICE_LINE.match(line)
                if m_weight and pending_name:
                    qty = to_decimal(m_weight.group(1))
                    unit_p = to_decimal(m_weight.group(2))
                    items.append(CanonicalItem(
                        name=pending_name,
                        unit_price=unit_p,
                        quantity=qty,
                    ))
                    pending_name = None
                    continue

                # Check multiplier line: "2 * 5,99 11,98 A"
                m_mult = _MULTIPLIER_LINE.match(line)
                if m_mult and pending_name:
                    qty = to_decimal(m_mult.group(1))
                    unit_p = to_decimal(m_mult.group(2))
                    items.append(CanonicalItem(
                        name=pending_name,
                        unit_price=unit_p,
                        quantity=qty,
                    ))
                    pending_name = None
                    continue

                # Check single item line: "ViscoplastMikki10szt * 7,99 B"
                m_single = _SINGLE_ITEM_LINE.match(line)
                if m_single and not _IGNORED_KEYWORDS.match(line):
                    name = m_single.group(1).strip().rstrip("*").strip()
                    unit_p = to_decimal(m_single.group(2))
                    items.append(CanonicalItem(
                        name=name,
                        unit_price=unit_p,
                        quantity=Decimal("1"),
                    ))
                    pending_name = None
                    continue

                # Otherwise unpriced line (category header or pending product name).
                # Setting pending_name overwrites any previous category header.
                if not _IGNORED_KEYWORDS.match(line):
                    pending_name = line
                continue

            # ── State: PROMOTIONS ───────────────────────────────────────────────
            elif state == _State.PROMOTIONS:
                m_tot = _TOTAL_PATTERN.match(line)
                if m_tot:
                    total_amount = to_decimal(m_tot.group(1))
                    state = _State.SUMMARY
                    continue

                m_pos = _PROMO_POSITIONS.match(line)
                if m_pos and current_promo:
                    current_promo["positions"] = int(m_pos.group(1))
                    promotions.append(current_promo)
                    current_promo = None
                    continue

                m_pr = _PROMO_LINE.match(line)
                if m_pr:
                    if current_promo:
                        promotions.append(current_promo)
                    current_promo = {
                        "name": m_pr.group(1).strip(),
                        "discount": to_decimal(m_pr.group(2)),
                        "positions": None,
                    }
                    continue

            # ── State: SUMMARY ──────────────────────────────────────────────────
            elif state == _State.SUMMARY:
                m_tot = _TOTAL_PATTERN.match(line)
                if m_tot and total_amount == Decimal("0"):
                    total_amount = to_decimal(m_tot.group(1))

        if current_promo:
            promotions.append(current_promo)

        # ── Promotion Folding Strategy ─────────────────────────────────────────
        assigned_item_indices: set[int] = set()
        unassigned_promos: list[dict[str, Any]] = []

        for promo in promotions:
            disc = promo["discount"]  # negative decimal
            pos = promo.get("positions")
            matched_idx: Optional[int] = None

            # Strategy 1: Match item with exact quantity == positions
            if pos is not None:
                for idx, it in enumerate(items):
                    if idx not in assigned_item_indices and it.quantity == Decimal(pos):
                        matched_idx = idx
                        break

            # Strategy 2: Match item whose unit_price == abs(discount)
            if matched_idx is None:
                for idx, it in enumerate(items):
                    if idx not in assigned_item_indices and it.unit_price == abs(disc):
                        matched_idx = idx
                        break

            if matched_idx is not None:
                assigned_item_indices.add(matched_idx)
                items[matched_idx].discount_total += disc
            else:
                unassigned_promos.append(promo)

        # Any unassigned promotions are treated as basket adjustments
        for up in unassigned_promos:
            items.append(CanonicalItem(
                name=up["name"],
                unit_price=up["discount"],
                quantity=Decimal("1"),
                is_adjustment=True,
            ))

        receipt = CanonicalReceipt(
            merchant_name="Kaufland",
            date=date,
            total_amount=total_amount,
            currency="PLN",
            items=items,
        )
        return normalize_receipt(receipt)
