# backend/app/receipt_normalizer.py
from __future__ import annotations

import re
from decimal import Decimal
from typing import Any, Union

from .receipt_schema import CanonicalItem, CanonicalReceipt, to_decimal


# Regex to detect basket-level adjustments (deposits, bottle returns, whole basket discounts)
_ADJUSTMENT_NAME_PATTERN = re.compile(
    r"^(kaucja|opakowania?\s+zwrotne|butelk[ai]\s+zwrotn[ae]|zwrot\s+butelek|łączny\s+rabat|rabat\s+koszyka|bon\s+rabatowy|kupon|voucher)",
    re.IGNORECASE,
)

# Regex to detect discount lines that should be folded into preceding product
_DISCOUNT_NAME_PATTERN = re.compile(
    r"(rabat|opust|zniżka|oszczędzasz|wielosztuka|kaufland\s+card|moja\s+biedronka|lidl\s+plus)",
    re.IGNORECASE,
)

# Trailing fiscal VAT markers commonly appended by OCR (e.g. "Chleb A", "Pomidor B", "Ser C")
_TRAILING_VAT_MARKER = re.compile(r"\s+[A-Ea-e]\s*$")


def _clean_product_name(name: str) -> str:
    """Strip unnecessary surrounding whitespace."""
    return name.strip()


def normalize_receipt(raw: Union[CanonicalReceipt, dict[str, Any]]) -> CanonicalReceipt:
    """
    Normalizes any parsed receipt (from deterministic parsers, e-paragon JSON, or AI structurizer)
    into a mathematically consistent CanonicalReceipt.

    Guarantees:
      1. Standalone discount rows are folded into the preceding product's `discount_total`.
      2. Bottle deposits and basket vouchers are flagged as `is_adjustment = True`.
      3. All monetary amounts use Decimal.
      4. Zero ghost items with negative prices.
    """
    if isinstance(raw, CanonicalReceipt):
        receipt_dict = raw.to_dict()
    else:
        receipt_dict = raw or {}

    merchant_name = str(receipt_dict.get("merchant_name") or "Unknown Merchant").strip()
    date_str = str(receipt_dict.get("date") or "").strip()
    total_amount = to_decimal(receipt_dict.get("total_amount", "0"))
    currency = str(receipt_dict.get("currency") or "PLN").strip()

    raw_items = receipt_dict.get("items") or []
    canonical_items: list[CanonicalItem] = []

    for item_data in raw_items:
        if isinstance(item_data, CanonicalItem):
            item = item_data
        else:
            name = str(item_data.get("name", "Unknown item")).strip()
            # If original_price was already captured, prioritize it as unit_price
            orig_price = item_data.get("original_price")
            raw_price = item_data.get("unit_price") if "unit_price" in item_data else item_data.get("price", "0")
            unit_price = to_decimal(orig_price if orig_price is not None else raw_price)
            quantity = to_decimal(item_data.get("quantity", "1.0"), default="1.0")
            discount_total = to_decimal(item_data.get("discount_total", "0"), default="0")
            is_adj = bool(item_data.get("is_adjustment", False))
            category = item_data.get("category")
            category_source = item_data.get("category_source")

            item = CanonicalItem(
                name=name,
                unit_price=unit_price,
                quantity=quantity,
                discount_total=discount_total,
                category=category,
                category_source=category_source,
                is_adjustment=is_adj,
                original_price=orig_price,
            )

        name = item.name.strip()

        # Check 1: Is this explicitly a basket adjustment? (e.g. kaucja, bottle deposit return)
        if item.is_adjustment or _ADJUSTMENT_NAME_PATTERN.search(name):
            item.is_adjustment = True
            item.name = _clean_product_name(name)
            canonical_items.append(item)
            continue

        # Check 2: Is this a standalone discount line?
        # Either negative unit_price OR explicit discount keyword in name with negative/zero net
        is_discount_line = (
            item.unit_price < Decimal("0")
            or item.discount_total < Decimal("0")
            or _DISCOUNT_NAME_PATTERN.search(name) is not None
        )

        if is_discount_line and item.unit_price < Decimal("0"):
            discount_amount = item.unit_price * item.quantity
            # Find the last product (non-adjustment) to fold this discount into
            folded = False
            for prev in reversed(canonical_items):
                if not prev.is_adjustment:
                    prev.discount_total += discount_amount
                    folded = True
                    break

            if not folded:
                # No preceding product exists: treat as basket-level adjustment
                item.is_adjustment = True
                item.unit_price = discount_amount
                item.quantity = Decimal("1.0")
                item.discount_total = Decimal("0")
                canonical_items.append(item)
            continue

        if is_discount_line and _DISCOUNT_NAME_PATTERN.search(name) and item.unit_price == Decimal("0"):
            # 0.00 price discount label (sometimes seen in AI output)
            continue

        # Regular product item
        item.name = _clean_product_name(name)
        canonical_items.append(item)

    return CanonicalReceipt(
        merchant_name=merchant_name,
        date=date_str,
        total_amount=total_amount,
        currency=currency,
        items=canonical_items,
    )
