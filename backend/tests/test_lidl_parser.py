from decimal import Decimal


from app.lidl_parser import LidlReceiptParser, ParsedReceipt


def _parse(lines: list[str]) -> ParsedReceipt:
    return LidlReceiptParser().parse(lines)


# ── Header / date ─────────────────────────────────────────────────────────────

def test_extracts_date():
    receipt = _parse([
        "LiDL", "ul. Poznańska 48", "2026-04-18",
        "Chleb", "3.99 3.99 C",
        "Suma PLN 3,99",
    ])
    assert receipt.date == "2026-04-18"


def test_no_date_returns_empty_string():
    receipt = _parse(["LiDL", "ul. Poznańska 48"])
    assert receipt.date == ""


def test_ignores_lines_before_date():
    receipt = _parse([
        "LiDL",
        "Chleb",         # this looks like a product name but is in HEADER
        "3.99 3.99 C",   # also in HEADER — should be ignored
        "2026-04-18",
        "Mleko", "2.99 2.99 A",
        "Suma PLN 2,99",
    ])
    assert len(receipt.items) == 1
    assert receipt.items[0].name == "Mleko"


# ── Basic product parsing ─────────────────────────────────────────────────────

def test_single_product():
    receipt = _parse([
        "2026-04-18",
        "Masło Ekstra",
        "4.99 4.99 C",
        "Suma PLN 4,99",
    ])
    assert len(receipt.items) == 1
    assert receipt.items[0].name == "Masło Ekstra"
    assert receipt.items[0].price == Decimal("4.99")
    assert receipt.items[0].quantity == Decimal("1")


def test_price_line_uses_total_not_unit_price():
    # "34.99 14.97 C" — unit price 34.99, total 14.97 (e.g. promo price)
    receipt = _parse(["2026-04-18", "Masło Ekstra", "34.99 14.97 C", "Suma PLN 14,97"])
    assert receipt.items[0].price == Decimal("14.97")


def test_price_line_with_comma_decimal():
    receipt = _parse(["2026-04-18", "Jogurt", "3,49 3,49 C", "Suma PLN 3,49"])
    assert receipt.items[0].price == Decimal("3.49")


def test_multiple_products():
    receipt = _parse([
        "2026-04-18",
        "Mleko", "3.49 3.49 A",
        "Chleb", "4.99 4.99 C",
        "Masło", "8.99 8.99 C",
        "Suma PLN 17,47",
    ])
    assert len(receipt.items) == 3
    assert [i.name for i in receipt.items] == ["Mleko", "Chleb", "Masło"]


# ── Discount lines ────────────────────────────────────────────────────────────

def test_lidl_plus_voucher():
    receipt = _parse([
        "2026-04-18",
        "Masło Ekstra", "34.99 14.97 C",
        "Lidl Plus voucher -0,27",
        "Suma PLN 14,70",
    ])
    assert len(receipt.items) == 2
    assert receipt.items[1].name == "Lidl Plus voucher"
    assert receipt.items[1].price == Decimal("-0.27")


def test_rabat_50_percent():
    receipt = _parse([
        "2026-04-18",
        "Polędwica sopockaXXL", "29.99 19.98 C",
        "RABAT 50 % -10,00",
        "Suma PLN 9,98",
    ])
    assert receipt.items[1].name == "RABAT 50 %"
    assert receipt.items[1].price == Decimal("-10.00")


def test_nie_marnuje_discount():
    receipt = _parse([
        "2026-04-18",
        "Frusta Prosciutto", "13.98 13.98 C",
        "Nie marnuję -6,99",
        "Suma PLN 6,99",
    ])
    assert receipt.items[1].name == "Nie marnuję"
    assert receipt.items[1].price == Decimal("-6.99")


def test_multiple_discounts_on_one_product():
    receipt = _parse([
        "2026-04-18",
        "Masło Ekstra", "34.99 14.97 C",
        "Lidl Plus kupon -12,12",
        "Lidl Plus voucher -0,27",
        "Suma PLN 2,58",
    ])
    assert len(receipt.items) == 3
    assert receipt.items[0].price == Decimal("14.97")
    assert receipt.items[1].price == Decimal("-12.12")
    assert receipt.items[2].price == Decimal("-0.27")


# ── Quantity and weight products ──────────────────────────────────────────────

def test_quantity_product():
    receipt = _parse([
        "2026-04-18",
        "Fasolka w sosie",
        "3 * 4,99 14,97 C",
        "Suma PLN 14,97",
    ])
    assert receipt.items[0].price == Decimal("14.97")
    assert receipt.items[0].quantity == Decimal("3")


def test_weight_product():
    receipt = _parse([
        "2026-04-18",
        "Marchew luz",
        "0,488 kg x 3,99 1,95 C",
        "Suma PLN 1,95",
    ])
    assert receipt.items[0].price == Decimal("1.95")
    assert receipt.items[0].quantity == Decimal("0.488")


# ── Summary / total ───────────────────────────────────────────────────────────

def test_extracts_total_from_suma_pln():
    receipt = _parse([
        "2026-04-18",
        "Chleb", "3.99 3.99 C",
        "Suma PLN 3,99",
    ])
    assert receipt.total_amount == Decimal("3.99")


def test_stops_parsing_products_after_summary():
    receipt = _parse([
        "2026-04-18",
        "Chleb", "3.99 3.99 C",
        "Suma PLN 3,99",
        "A 0 % 0,00",
        "C 8 % 3,99",       # VAT breakdown — should not become items
        "Gotówka 3,99",     # payment line — should not become an item
    ])
    assert len(receipt.items) == 1


# ── Output format ─────────────────────────────────────────────────────────────

def test_to_dict_structure():
    receipt = _parse([
        "2026-04-18",
        "Mleko", "3.49 3.49 A",
        "Suma PLN 3,49",
    ])
    d = receipt.to_dict()
    assert d["merchant_name"] == "Lidl"
    assert d["date"] == "2026-04-18"
    assert d["currency"] == "PLN"
    assert d["total_amount"] == 3.49
    assert len(d["items"]) == 1
    item = d["items"][0]
    assert item["name"] == "Mleko"
    assert item["price"] == 3.49
    assert item["quantity"] == 1.0
    assert item["category"] is None


# ── Integration: real receipt sample ─────────────────────────────────────────

SAMPLE_LINES = [
    "LiDL",
    "Adres siedziby : Poznańska 48 , Jankowice",
    "62-080 Tarnowo",
    "Podgórne nr rej : BDO 000002265 Lidl sp .",
    "z o . o . sp . k .",
    "ul . Orzepowicka 29a , 44-217 Rybnik",
    "2026-04-18",
    "Masło Ekstra",
    "34.99 14.97 C",
    "Lidl Plus kupon -12,12",
    "Lidl Plus voucher -0,27",
    "Polędwica sopockaXXL",
    "29.99 19.98 C",
    "RABAT 50 % -10,00",
    "Lidl Plus voucher -0,96",
    "Pure Boczek wędzony",
    "35.99 17.97 C",
    "RABAT 50 % -9,00",
    "Lidl Plus voucher -0,87",
    "Pieczarki 500g",
    "15.98 15.98 C",
    "RABAT 50 % -8,00",
    "Mleko 1,5 % b.laktozy",
    "3.49 3.49 A",
    "Suma PLN 30,17",
]


def test_sample_receipt_product_count():
    receipt = _parse(SAMPLE_LINES)
    product_items = [i for i in receipt.items if i.price > 0]
    discount_items = [i for i in receipt.items if i.price < 0]
    assert len(product_items) == 5
    assert len(discount_items) == 7


def test_sample_receipt_date_and_total():
    receipt = _parse(SAMPLE_LINES)
    assert receipt.date == "2026-04-18"
    assert receipt.total_amount == Decimal("30.17")


def test_sample_receipt_first_product():
    receipt = _parse(SAMPLE_LINES)
    assert receipt.items[0].name == "Masło Ekstra"
    assert receipt.items[0].price == Decimal("14.97")


def test_sample_receipt_merchant():
    receipt = _parse(SAMPLE_LINES)
    assert receipt.merchant_name == "Lidl"
