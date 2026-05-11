# backend/app/receipt_validator.py
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Optional


class ValidationIssue(str, Enum):
    TOTAL_MISMATCH = "TOTAL_MISMATCH"
    INVALID_PRICE = "INVALID_PRICE"
    FUTURE_DATE = "FUTURE_DATE"
    EMPTY_RECEIPT = "EMPTY_RECEIPT"


@dataclass
class ValidationResult:
    is_valid: bool
    issues: list[ValidationIssue] = field(default_factory=list)
    confidence: float = 1.0
    # Human-readable summary of the worst issue (used in UI alert)
    message: Optional[str] = None


# Tolerance for floating-point receipt totals (±0.01 PLN)
_TOLERANCE = Decimal("0.01")


class ReceiptValidator:
    """
    Validates a parsed receipt dict (as returned by parser/AI) against the
    receipt total extracted from OCR text.

    Rules:
      EMPTY_RECEIPT   — no items at all → FAILED (confidence 0)
      INVALID_PRICE   — any item with price == 0 and quantity > 0 → FAILED
      FUTURE_DATE     — receipt date is in the future → FAILED
      TOTAL_MISMATCH  — |sum(items) - ocr_total| > 0.01 → NEEDS_REVIEW (confidence lowered)

    TOTAL_MISMATCH alone → is_valid=True so the pipeline sets NEEDS_REVIEW (not FAILED).
    Any other issue → is_valid=False → FAILED.
    """

    def validate(self, parsed: dict, ocr_total: Decimal) -> ValidationResult:
        issues: list[ValidationIssue] = []

        items = parsed.get("items") or []

        # ── EMPTY_RECEIPT ──────────────────────────────────────────────────────
        if not items:
            return ValidationResult(
                is_valid=False,
                issues=[ValidationIssue.EMPTY_RECEIPT],
                confidence=0.0,
                message="Paragon nie zawiera żadnych pozycji.",
            )

        # ── INVALID_PRICE ──────────────────────────────────────────────────────
        for item in items:
            price = Decimal(str(item.get("price", 0)))
            quantity = Decimal(str(item.get("quantity", 1)))
            if quantity > 0 and price == Decimal("0"):
                issues.append(ValidationIssue.INVALID_PRICE)
                break

        # ── FUTURE_DATE ────────────────────────────────────────────────────────
        date_str = parsed.get("date", "")
        if date_str:
            try:
                receipt_date = datetime.strptime(date_str, "%Y-%m-%d").date()
                today = datetime.now(timezone.utc).date()
                if receipt_date > today:
                    issues.append(ValidationIssue.FUTURE_DATE)
            except ValueError:
                pass  # unparseable date is not a hard failure here

        if issues:
            return ValidationResult(
                is_valid=False,
                issues=issues,
                confidence=0.0,
                message=self._describe(issues[0], None),
            )

        # ── TOTAL_MISMATCH (soft — NEEDS_REVIEW, not FAILED) ──────────────────
        items_sum = sum(
            Decimal(str(i.get("price", 0))) * Decimal(str(i.get("quantity", 1)))
            for i in items
        )
        delta = abs(items_sum - ocr_total)

        if delta > _TOLERANCE:
            confidence = max(0.0, float(1 - delta / (ocr_total if ocr_total else Decimal("1"))))
            return ValidationResult(
                is_valid=True,  # NEEDS_REVIEW, not FAILED
                issues=[ValidationIssue.TOTAL_MISMATCH],
                confidence=round(confidence, 4),
                message=self._describe(ValidationIssue.TOTAL_MISMATCH, delta),
            )

        return ValidationResult(is_valid=True, issues=[], confidence=1.0)

    @staticmethod
    def _describe(issue: ValidationIssue, delta: Optional[Decimal]) -> str:
        if issue == ValidationIssue.TOTAL_MISMATCH:
            return f"Suma pozycji różni się od paragonu o {delta:.2f} zł."
        if issue == ValidationIssue.INVALID_PRICE:
            return "Co najmniej jedna pozycja ma cenę 0,00 zł."
        if issue == ValidationIssue.FUTURE_DATE:
            return "Data na paragonie jest w przyszłości."
        if issue == ValidationIssue.EMPTY_RECEIPT:
            return "Paragon nie zawiera żadnych pozycji."
        return "Nieznany problem z paragonem."
