from decimal import Decimal


from app.receipt_validator import ReceiptValidator, ValidationIssue


def _item(name: str, price: float, quantity: float = 1.0) -> dict:
    return {"name": name, "price": price, "quantity": quantity, "category": None}


def _receipt(items: list[dict], total: float, date: str = "2026-04-18") -> tuple[dict, Decimal]:
    return {"items": items, "total_amount": total, "date": date}, Decimal(str(total))


validator = ReceiptValidator()


# ── Valid receipts ────────────────────────────────────────────────────────────

def test_valid_single_item():
    data, total = _receipt([_item("Mleko", 3.49)], 3.49)
    result = validator.validate(data, total)
    assert result.is_valid
    assert result.issues == []
    assert result.confidence == 1.0


def test_valid_multiple_items():
    items = [_item("Masło", 14.97), _item("RABAT 50 %", -10.0), _item("Chleb", 5.00)]
    data, _ = _receipt(items, 9.97)
    result = validator.validate(data, Decimal("9.97"))
    assert result.is_valid
    assert result.issues == []


def test_valid_within_tolerance_low():
    items = [_item("Jogurt", 3.49)]
    data, _ = _receipt(items, 3.49)
    result = validator.validate(data, Decimal("3.50"))  # 0.01 diff — at edge
    assert result.is_valid
    assert result.issues == []


def test_valid_quantity_product():
    items = [_item("Fasolka", 14.97, quantity=3.0)]
    # sum = 14.97 * 3 = 44.91, but price is total (as stored), not unit
    # The validator treats price as total for that line
    data = {"items": items, "total_amount": 14.97, "date": "2026-04-18"}
    result = validator.validate(data, Decimal("14.97"))
    # 14.97 * 3 = 44.91 vs total 14.97 → mismatch
    assert ValidationIssue.TOTAL_MISMATCH in result.issues


# ── EMPTY_RECEIPT ─────────────────────────────────────────────────────────────

def test_empty_items_list():
    data = {"items": [], "total_amount": 10.0, "date": "2026-04-18"}
    result = validator.validate(data, Decimal("10.0"))
    assert not result.is_valid
    assert ValidationIssue.EMPTY_RECEIPT in result.issues
    assert result.confidence == 0.0


def test_missing_items_key():
    data = {"total_amount": 10.0, "date": "2026-04-18"}
    result = validator.validate(data, Decimal("10.0"))
    assert not result.is_valid
    assert ValidationIssue.EMPTY_RECEIPT in result.issues


# ── INVALID_PRICE ─────────────────────────────────────────────────────────────

def test_zero_price_item():
    items = [_item("Mleko", 0.0), _item("Chleb", 3.0)]
    data, total = _receipt(items, 3.0)
    result = validator.validate(data, total)
    assert not result.is_valid
    assert ValidationIssue.INVALID_PRICE in result.issues


def test_negative_price_discount_is_allowed():
    # Discounts have negative prices — they are valid, quantity doesn't apply in same way
    items = [_item("Masło", 14.97), _item("RABAT 50 %", -10.0)]
    data, _ = _receipt(items, 4.97)
    result = validator.validate(data, Decimal("4.97"))
    assert result.is_valid
    assert ValidationIssue.INVALID_PRICE not in result.issues


# ── FUTURE_DATE ───────────────────────────────────────────────────────────────

def test_future_date():
    items = [_item("Mleko", 3.49)]
    data = {"items": items, "total_amount": 3.49, "date": "2099-12-31"}
    result = validator.validate(data, Decimal("3.49"))
    assert not result.is_valid
    assert ValidationIssue.FUTURE_DATE in result.issues


def test_today_date_is_valid():
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    items = [_item("Mleko", 3.49)]
    data = {"items": items, "total_amount": 3.49, "date": today}
    result = validator.validate(data, Decimal("3.49"))
    assert result.is_valid


def test_missing_date_does_not_fail():
    items = [_item("Mleko", 3.49)]
    data = {"items": items, "total_amount": 3.49, "date": ""}
    result = validator.validate(data, Decimal("3.49"))
    assert ValidationIssue.FUTURE_DATE not in result.issues


# ── TOTAL_MISMATCH ────────────────────────────────────────────────────────────

def test_total_mismatch_is_needs_review_not_failed():
    items = [_item("Masło", 14.97)]
    data = {"items": items, "total_amount": 20.00, "date": "2026-04-18"}
    result = validator.validate(data, Decimal("20.00"))
    assert result.is_valid  # NEEDS_REVIEW — not hard failure
    assert ValidationIssue.TOTAL_MISMATCH in result.issues
    assert result.confidence < 1.0


def test_total_mismatch_message_contains_diff():
    items = [_item("Masło", 14.97)]
    data = {"items": items, "total_amount": 20.00, "date": "2026-04-18"}
    result = validator.validate(data, Decimal("20.00"))
    assert result.message is not None
    assert "5.03" in result.message  # 20.00 - 14.97


def test_mismatch_just_over_tolerance():
    items = [_item("Mleko", 3.49)]
    data = {"items": items, "total_amount": 3.49, "date": "2026-04-18"}
    result = validator.validate(data, Decimal("3.51"))  # 0.02 diff > 0.01
    assert ValidationIssue.TOTAL_MISMATCH in result.issues


def test_tolerance_boundary_exact():
    items = [_item("Mleko", 3.49)]
    data = {"items": items, "total_amount": 3.49, "date": "2026-04-18"}
    result = validator.validate(data, Decimal("3.49"))
    assert result.issues == []


# ── Real receipt (Lidl sample) ────────────────────────────────────────────────

SAMPLE_ITEMS = [
    _item("Masło Ekstra", 14.97),
    _item("Lidl Plus kupon", -12.12),
    _item("Lidl Plus voucher", -0.27),
    _item("Polędwica sopockaXXL", 19.98),
    _item("RABAT 50 %", -10.0),
    _item("Lidl Plus voucher", -0.96),
    _item("Pure Boczek wędzony", 17.97),
    _item("RABAT 50 %", -9.0),
    _item("Lidl Plus voucher", -0.87),
    _item("Pieczarki 500g", 15.98),
    _item("RABAT 50 %", -8.0),
    _item("Mleko 1,5 % b.laktozy", 3.49),
]
SAMPLE_TOTAL = Decimal("31.17")  # actual sum of SAMPLE_ITEMS above


def test_sample_receipt_passes_validation():
    data = {"items": SAMPLE_ITEMS, "total_amount": float(SAMPLE_TOTAL), "date": "2026-04-18"}
    result = validator.validate(data, SAMPLE_TOTAL)
    assert result.is_valid
    assert result.issues == []
    assert result.confidence == 1.0


def test_sample_receipt_missing_item_triggers_mismatch():
    truncated = SAMPLE_ITEMS[:-1]  # remove last item (Mleko 3.49)
    data = {"items": truncated, "total_amount": float(SAMPLE_TOTAL), "date": "2026-04-18"}
    result = validator.validate(data, SAMPLE_TOTAL)
    assert result.is_valid  # soft failure → NEEDS_REVIEW
    assert ValidationIssue.TOTAL_MISMATCH in result.issues
