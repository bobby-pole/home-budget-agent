"""Monetary and quantity Decimal precision helpers and Pydantic field types."""

from __future__ import annotations

import math
import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Annotated, Any

from pydantic import BeforeValidator, PlainSerializer, WithJsonSchema

MONEY_QUANT = Decimal("0.01")
UNIT_PRICE_QUANT = Decimal("0.0001")
QTY_QUANT = Decimal("0.0001")
SCORE_QUANT = Decimal("0.0001")

_ZERO = Decimal("0")
_WHITESPACE_RE = re.compile(r"[\s\u00a0\u202f]+")


def parse_decimal(value: Any) -> Decimal:
    """Parse monetary or quantity input into a finite Decimal without float drift.

    Supports Decimal, int (excluding bool), finite float (via str), and strings
    with Polish decimal commas, non-breaking spaces, or unicode minus signs.
    """
    if isinstance(value, bool):
        raise ValueError("Boolean is not a valid decimal value")

    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("Non-finite Decimal value is not allowed")
        return value

    if isinstance(value, int):
        return Decimal(value)

    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("Non-finite float value is not allowed")
        return Decimal(str(value))

    if isinstance(value, str):
        cleaned = _WHITESPACE_RE.sub("", value.strip())
        cleaned = cleaned.replace("\u2212", "-").replace("\u2013", "-")
        if not cleaned:
            raise ValueError("Empty string is not a valid decimal value")

        has_comma = "," in cleaned
        has_dot = "." in cleaned
        if has_comma and has_dot:
            if cleaned.rfind(",") > cleaned.rfind("."):
                cleaned = cleaned.replace(".", "").replace(",", ".")
            else:
                cleaned = cleaned.replace(",", "")
        elif has_comma:
            if cleaned.count(",") == 1:
                cleaned = cleaned.replace(",", ".")
            else:
                raise ValueError(f"Ambiguous decimal format: {value!r}")

        try:
            parsed = Decimal(cleaned)
        except InvalidOperation as exc:
            raise ValueError(f"Invalid decimal value: {value!r}") from exc

        if not parsed.is_finite():
            raise ValueError("Non-finite decimal value is not allowed")
        return parsed

    raise ValueError(f"Unsupported type for decimal conversion: {type(value).__name__}")


def quantize_money(value: Any) -> Decimal:
    """Parse and quantize a monetary amount to 2 decimal places (ROUND_HALF_UP)."""
    dec = parse_decimal(value).quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)
    return _ZERO.quantize(MONEY_QUANT) if dec == _ZERO else dec


def quantize_unit_price(value: Any) -> Decimal:
    """Parse and quantize a unit price to 4 decimal places (ROUND_HALF_UP)."""
    dec = parse_decimal(value).quantize(UNIT_PRICE_QUANT, rounding=ROUND_HALF_UP)
    return _ZERO.quantize(UNIT_PRICE_QUANT) if dec == _ZERO else dec


def quantize_quantity(value: Any) -> Decimal:
    """Parse and quantize a quantity to 4 decimal places (ROUND_HALF_UP)."""
    dec = parse_decimal(value).quantize(QTY_QUANT, rounding=ROUND_HALF_UP)
    return _ZERO.quantize(QTY_QUANT) if dec == _ZERO else dec


def quantize_score(value: Any) -> Decimal:
    """Parse and quantize a normalized quality/confidence score to 4 decimal places."""
    dec = parse_decimal(value).quantize(SCORE_QUANT, rounding=ROUND_HALF_UP)
    if dec < _ZERO or dec > Decimal("1"):
        raise ValueError(f"Quality score must be between 0 and 1 (got {dec})")
    return _ZERO.quantize(SCORE_QUANT) if dec == _ZERO else dec


def format_money(value: Any) -> str:
    """Format a monetary Decimal cleanly to fixed 2 decimal places (e.g. '10.99')."""
    return format(quantize_money(value), "f")


def format_unit_price(value: Any) -> str:
    """Format a 4-decimal unit price trimming trailing zeros after 2 decimal places."""
    text = format(quantize_unit_price(value), "f")
    integer_part, frac_part = text.split(".")
    trimmed_frac = frac_part.rstrip("0")
    if len(trimmed_frac) < 2:
        trimmed_frac = frac_part[:2]
    return f"{integer_part}.{trimmed_frac}"


def format_quantity(value: Any) -> str:
    """Format a quantity without scientific notation, trimming unnecessary trailing zeros."""
    text = format(quantize_quantity(value), "f")
    if "." not in text:
        return text
    trimmed = text.rstrip("0").rstrip(".")
    return "0" if trimmed in {"", "-0"} else trimmed


MoneyDecimal = Annotated[
    Decimal,
    BeforeValidator(quantize_money),
    PlainSerializer(format_money, return_type=str, when_used="json"),
    WithJsonSchema(
        {
            "type": "string",
            "pattern": r"^-?\d+(\.\d{1,2})?$",
            "example": "10.99",
        }
    ),
]

UnitPriceDecimal = Annotated[
    Decimal,
    BeforeValidator(quantize_unit_price),
    PlainSerializer(format_unit_price, return_type=str, when_used="json"),
    WithJsonSchema(
        {
            "type": "string",
            "pattern": r"^-?\d+(\.\d{1,4})?$",
            "example": "10.99",
        }
    ),
]

QuantityDecimal = Annotated[
    Decimal,
    BeforeValidator(quantize_quantity),
    PlainSerializer(format_quantity, return_type=str, when_used="json"),
    WithJsonSchema(
        {
            "type": "string",
            "pattern": r"^-?\d+(\.\d{1,4})?$",
            "example": "1",
        }
    ),
]


def format_score(value: Any) -> str:
    """Format a normalized quality score cleanly without trailing fractional zeros after 2 decimals."""
    text = format(quantize_score(value), "f")
    integer_part, frac_part = text.split(".")
    trimmed_frac = frac_part.rstrip("0")
    if len(trimmed_frac) < 2:
        trimmed_frac = frac_part[:2]
    return f"{integer_part}.{trimmed_frac}"


ScoreDecimal = Annotated[
    Decimal,
    BeforeValidator(quantize_score),
    PlainSerializer(format_score, return_type=str, when_used="json"),
    WithJsonSchema(
        {
            "type": "string",
            "pattern": r"^(0(\.\d{1,4})?|1(\.0{1,4})?)$",
            "example": "1.00",
        }
    ),
]
