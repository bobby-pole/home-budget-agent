import re
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from .lidl_parser import ParsedReceipt, ParsedItem, BaseDeterministicParser
from .ocr_pipeline import EParagonJSONAdapter

_DATE_LINE = re.compile(r"^\d{4}-\d{2}-\d{2}")
_ZABKA_PRICE_LINE = re.compile(
    r"^(\d+(?:[.,]\d+)?)\s*(?:szt\.?|kg)?\s*[x×X]\s*(\d+[.,]\d+)\s+(\d+[.,]\d+)\s*([A-E])",
    re.IGNORECASE
)
_DISCOUNT_VAL_LINE = re.compile(r"^(-\d+[.,]\d+)\s*[A-E]?$")
_SUMA_PLN = re.compile(r"^SUMA\s+PLN", re.IGNORECASE)
_SUMA_BARE = re.compile(r"^(\d+[.,]\d+)\s*(?:PLN|zł)?$", re.IGNORECASE)


def _parse_decimal(s: str) -> Decimal:
    try:
        return Decimal(s.replace(",", ".").replace(" ", ""))
    except InvalidOperation:
        return Decimal("0")


class ZabkaReceiptParser(BaseDeterministicParser):
    """
    Deterministic parser for Zabka receipts.
    Supports parsing lines (from PDF/OCR) or JSON (e-paragon).
    """

    def parse_json(self, file_bytes: bytes) -> dict[str, Any]:
        """Wrapper for JSON e-paragon format."""
        return EParagonJSONAdapter.parse(file_bytes)

    def parse(self, lines: list[str]) -> ParsedReceipt:
        items: list[ParsedItem] = []
        date_str = ""
        total_amount = Decimal("0")
        
        pending_name: Optional[str] = None
        state = "HEADER"
        
        # Look for date anywhere
        for line in lines:
            m = _DATE_LINE.search(line)
            if m and not date_str:
                date_str = m.group(0)
                
        # Main parse loop
        for i, line in enumerate(lines):
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
                    total_amount = _parse_decimal(m_total.group(1))
                continue
                
            if state == "PRODUCTS":
                if _SUMA_PLN.match(line) or line.upper() == "SUMA PLN":
                    state = "SUMMARY"
                    continue
                    
                m_price = _ZABKA_PRICE_LINE.match(line)
                if m_price:
                    if pending_name:
                        qty = _parse_decimal(m_price.group(1))
                        unit = _parse_decimal(m_price.group(2))
                        # For Zabka, we can use unit price. Or we can just use the line total.
                        # We'll stick to unit_price as price, and calculate total.
                        # Wait, lidl parser uses unit_price as `price`, let's do the same.
                        
                        items.append(ParsedItem(
                            name=pending_name,
                            quantity=qty,
                            price=unit,
                            original_price=unit,
                            discount_total=Decimal("0"),
                            is_adjustment=False
                        ))
                        pending_name = None
                    continue
                    
                m_discount = _DISCOUNT_VAL_LINE.match(line)
                if m_discount and items:
                    discount_val = _parse_decimal(m_discount.group(1))
                    last = items[-1]
                    if last.original_price is None:
                        last.original_price = last.price
                    last.discount_total += discount_val
                    # Adjust final price
                    q = last.quantity if last.quantity > 0 else Decimal("1")
                    last.price = last.original_price + (last.discount_total / q)
                    last.final_price = last.price
                    pending_name = None
                    continue
                    
                if line.upper().startswith("OPUST ") or line.upper().startswith("RABAT "):
                    continue # Skip discount name, we'll catch the value on the next line
                    
                # If nothing matches, it's a product name
                pending_name = line

        return ParsedReceipt(
            merchant_name="Żabka",
            date=date_str,
            total_amount=total_amount,
            currency="PLN",
            items=items,
        )
