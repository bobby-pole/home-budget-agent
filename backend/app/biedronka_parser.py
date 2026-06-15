import re
from decimal import Decimal, InvalidOperation
from typing import Any

from .lidl_parser import ParsedReceipt, ParsedItem, BaseDeterministicParser
from .ocr_pipeline import EParagonJSONAdapter

_DATE_LINE = re.compile(r"^\d{4}-\d{2}-\d{2}")

# Example: "PomidorPaprycz500g с 2x 14,99 29,98" or "BułkaKajzerka55g 3x 0,34 1,02"
# Group 1: Name, Group 2: qty, Group 3: unit_price, Group 4: total
_BIEDRONKA_ITEM_LINE = re.compile(
    r"^(.*?)\s+(?:[A-Ea-zс]\s+)?(\d+(?:[.,]\d+)?)\s*[xX×]\s*(\d+[.,]\d+)\s+(\d+[.,]\d+)$",
    re.IGNORECASE
)

# Avoid matching "OPUSTY ŁĄCZNIE"
_DISCOUNT_LINE = re.compile(r"^(?:Rabat|Opust)\s+(-\d+[.,]\d+)", re.IGNORECASE)

_SUMA_TOTAL = re.compile(r"^(?:SUMA\s+PLN|RAZEM|DO\s+ZAPŁATY)\s*(\d+[.,]\d+)", re.IGNORECASE)


def _parse_decimal(s: str) -> Decimal:
    try:
        return Decimal(s.replace(",", ".").replace(" ", ""))
    except InvalidOperation:
        return Decimal("0")


class BiedronkaReceiptParser(BaseDeterministicParser):
    """
    Deterministic parser for Biedronka receipts.
    Supports parsing lines (from PDF/OCR) or JSON (e-paragon).
    """

    def parse_json(self, file_bytes: bytes) -> dict[str, Any]:
        """Wrapper for JSON e-paragon format."""
        return EParagonJSONAdapter.parse(file_bytes)

    def parse(self, lines: list[str]) -> ParsedReceipt:
        items: list[ParsedItem] = []
        date_str = ""
        total_amount = Decimal("0")
        
        state = "HEADER"
        
        for line in lines:
            m = _DATE_LINE.search(line)
            if m and not date_str:
                date_str = m.group(0)
                
        for i, line in enumerate(lines):
            line = line.strip()
            if not line:
                continue
                
            if state == "HEADER":
                if "PARAGON FISKALNY" in line.upper():
                    state = "PRODUCTS"
                continue
                
            if state == "SUMMARY":
                # Check for bare total line just in case, though Biedronka usually puts it on the same line.
                pass
                
            if state == "PRODUCTS":
                m_total = _SUMA_TOTAL.match(line)
                if m_total:
                    total_amount = _parse_decimal(m_total.group(1))
                    state = "SUMMARY"
                    continue
                    
                m_item = _BIEDRONKA_ITEM_LINE.match(line)
                if m_item:
                    name = m_item.group(1).strip()
                    qty = _parse_decimal(m_item.group(2))
                    unit = _parse_decimal(m_item.group(3))
                    
                    items.append(ParsedItem(
                        name=name,
                        quantity=qty,
                        price=unit,
                        original_price=unit,
                        discount_total=Decimal("0"),
                        is_adjustment=False
                    ))
                    continue
                    
                m_discount = _DISCOUNT_LINE.match(line)
                if m_discount and items:
                    discount_val = _parse_decimal(m_discount.group(1))
                    last = items[-1]
                    if last.original_price is None:
                        last.original_price = last.price
                    last.discount_total += discount_val
                    q = last.quantity if last.quantity > 0 else Decimal("1")
                    last.price = last.original_price + (last.discount_total / q)
                    last.final_price = last.price
                    continue

        return ParsedReceipt(
            merchant_name="Biedronka",
            date=date_str,
            total_amount=total_amount,
            currency="PLN",
            items=items,
        )
