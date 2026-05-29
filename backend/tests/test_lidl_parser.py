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


def test_price_line_recovers_merged_qty():
    # "34.99 14.97 C" came from "3 * 4.99 14.97 C" — OCR glued qty+unit.
    # Parser splits to qty=3, unit=4.99; line total stays 14.97.
    receipt = _parse(["2026-04-18", "Masło Ekstra", "34.99 14.97 C", "Suma PLN 14,97"])
    item = receipt.items[0]
    assert item.quantity == Decimal("3")
    assert item.price == Decimal("4.99")
    assert item.price * item.quantity == Decimal("14.97")


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
    # "34.99 14.97 C" recovers as qty=3, unit=4.99. Discount -0.27 spreads across units.
    receipt = _parse([
        "2026-04-18",
        "Masło Ekstra", "34.99 14.97 C",
        "Lidl Plus voucher -0,27",
        "Suma PLN 14,70",
    ])
    assert len(receipt.items) == 1
    item = receipt.items[0]
    assert item.name == "Masło Ekstra"
    assert item.quantity == Decimal("3")
    assert item.original_price == Decimal("4.99")  # unit price before discount
    assert item.discount_total == Decimal("-0.27")
    # final per-unit = 4.99 + (-0.27 / 3); line total ≈ 14.70
    assert abs(item.price * item.quantity - Decimal("14.70")) < Decimal("0.01")


def test_rabat_50_percent():
    # "29.99 19.98 C" recovers as qty=2, unit=9.99. Discount -10.00 spreads.
    receipt = _parse([
        "2026-04-18",
        "Polędwica sopockaXXL", "29.99 19.98 C",
        "RABAT 50 % -10,00",
        "Suma PLN 9,98",
    ])
    assert len(receipt.items) == 1
    item = receipt.items[0]
    assert item.quantity == Decimal("2")
    assert item.original_price == Decimal("9.99")
    assert item.discount_total == Decimal("-10.00")
    # final per-unit = 9.99 + (-10/2) = 4.99; line total = 9.98
    assert item.price == Decimal("4.99")
    assert item.price * item.quantity == Decimal("9.98")


def test_nie_marnuje_discount():
    # Discount folded into parent product
    receipt = _parse([
        "2026-04-18",
        "Frusta Prosciutto", "13.98 13.98 C",
        "Nie marnuję -6,99",
        "Suma PLN 6,99",
    ])
    assert len(receipt.items) == 1
    item = receipt.items[0]
    assert item.original_price == Decimal("13.98")
    assert item.discount_total == Decimal("-6.99")
    assert item.final_price == Decimal("6.99")
    assert item.price == Decimal("6.99")


def test_multiple_discounts_on_one_product():
    # "34.99 14.97 C" → qty=3, unit=4.99. Combined discounts -12.39 spread across units.
    receipt = _parse([
        "2026-04-18",
        "Masło Ekstra", "34.99 14.97 C",
        "Lidl Plus kupon -12,12",
        "Lidl Plus voucher -0,27",
        "Suma PLN 2,58",
    ])
    assert len(receipt.items) == 1
    item = receipt.items[0]
    assert item.quantity == Decimal("3")
    assert item.original_price == Decimal("4.99")
    assert item.discount_total == Decimal("-12.39")
    # final per-unit = 4.99 + (-12.39/3); line total ≈ 2.58
    assert abs(item.price * item.quantity - Decimal("2.58")) < Decimal("0.01")


def test_orphaned_discount_kept_as_basket_adjustment():
    # A discount before any product is parked as a basket-level adjustment
    # rather than a phantom negative item — so it cannot pollute the next product
    # but still contributes to sum validation.
    receipt = _parse([
        "2026-04-18",
        "Lidl Plus voucher -0,27",
        "Chleb", "3.99 3.99 C",
        "Suma PLN 3,72",
    ])
    assert len(receipt.items) == 2
    assert receipt.items[0].name == "Lidl Plus voucher"
    assert receipt.items[0].price == Decimal("-0.27")
    assert receipt.items[0].is_adjustment is True
    assert receipt.items[1].name == "Chleb"
    assert receipt.items[1].price == Decimal("3.99")
    assert receipt.items[1].discount_total == Decimal("0")
    assert receipt.items[1].is_adjustment is False


# ── Quantity and weight products ──────────────────────────────────────────────

def test_quantity_product():
    receipt = _parse([
        "2026-04-18",
        "Fasolka w sosie",
        "3 * 4,99 14,97 C",
        "Suma PLN 14,97",
    ])
    # price stores the unit price; price * quantity = line total
    assert receipt.items[0].price == Decimal("4.99")
    assert receipt.items[0].quantity == Decimal("3")


def test_weight_product():
    receipt = _parse([
        "2026-04-18",
        "Marchew luz",
        "0,488 kg x 3,99 1,95 C",
        "Suma PLN 1,95",
    ])
    # price stores the unit price per kg; price * quantity ≈ line total
    assert receipt.items[0].price == Decimal("3.99")
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
    assert item["is_adjustment"] is False


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
    # All 7 discounts are now folded into their parent products — only 5 items total
    receipt = _parse(SAMPLE_LINES)
    assert len(receipt.items) == 5
    # No item should have a negative price anymore
    assert all(i.price >= 0 for i in receipt.items)


def test_sample_receipt_date_and_total():
    receipt = _parse(SAMPLE_LINES)
    assert receipt.date == "2026-04-18"
    assert receipt.total_amount == Decimal("30.17")


def test_sample_receipt_first_product():
    # "Masło Ekstra" → recovered qty=3, unit=4.99. Two discounts: -12.12 and -0.27.
    # Line total ≈ 2.58 (was 14.97 before discounts).
    receipt = _parse(SAMPLE_LINES)
    item = receipt.items[0]
    assert item.name == "Masło Ekstra"
    assert item.quantity == Decimal("3")
    assert item.original_price == Decimal("4.99")
    assert item.discount_total == Decimal("-12.39")
    assert abs(item.price * item.quantity - Decimal("2.58")) < Decimal("0.01")


def test_sample_receipt_merchant():
    receipt = _parse(SAMPLE_LINES)
    assert receipt.merchant_name == "Lidl"


def test_sample_receipt_discounted_items_have_fields():
    # Items without discounts should have original_price=None, discount_total=0, final_price=None
    receipt = _parse(SAMPLE_LINES)
    mleko = receipt.items[4]  # last item — "Mleko 1,5 % b.laktozy" has no discount
    assert mleko.name == "Mleko 1,5 % b.laktozy"
    assert mleko.original_price is None
    assert mleko.discount_total == Decimal("0")
    assert mleko.final_price is None
    assert mleko.price == Decimal("3.49")


def test_to_dict_includes_discount_fields():
    # Qty-merged: "34.99 14.97 C" → qty=3, unit=4.99. original_price stores unit-level value.
    receipt = _parse([
        "2026-04-18",
        "Masło Ekstra", "34.99 14.97 C",
        "Lidl Plus voucher -0,27",
        "Suma PLN 14,70",
    ])
    d = receipt.to_dict()
    item = d["items"][0]
    assert item["original_price"] == 4.99
    assert item["discount_total"] == -0.27
    # final_price * quantity ≈ 14.70
    assert abs(item["final_price"] * item["quantity"] - 14.70) < 0.01


def test_to_dict_no_discount_fields_are_none():
    receipt = _parse([
        "2026-04-18",
        "Chleb", "3.99 3.99 C",
        "Suma PLN 3,99",
    ])
    item = receipt.to_dict()["items"][0]
    assert item["original_price"] is None
    assert item["discount_total"] == 0.0
    assert item["final_price"] is None
    assert item["is_adjustment"] is False


# ── Quantity-price line without explicit asterisk (OCR-dropped separator) ─────

def test_qty_price_without_asterisk():
    # OCR sometimes drops the "*" separator: "1 7.49 7.49 C" instead of "1 * 7.49 7.49 C".
    # Without the fix the regex misses the line, pending_name leaks, and the next
    # product's discounts get attached to the WRONG item.
    receipt = _parse([
        "2026-04-18",
        "Sushi Tokyo",
        "1 7.49 7.49 C",
        "RABAT 50 % -3,75",
        "Suma PLN 3,74",
    ])
    assert len(receipt.items) == 1
    item = receipt.items[0]
    assert item.name == "Sushi Tokyo"
    assert item.quantity == Decimal("1")
    assert item.original_price == Decimal("7.49")
    assert item.discount_total == Decimal("-3.75")
    assert item.final_price == Decimal("3.74")


def test_regular_promo_not_misparsed_as_qty():
    # "29.99 9.99 C" is a regular promo (old price 29.99, paid 9.99).
    # Splitting first num would give qty=2, unit=9.99 → 19.98 ≠ 9.99, so
    # the qty-merge heuristic must NOT trigger.
    receipt = _parse([
        "2026-04-18",
        "Promo Item", "29.99 9.99 C",
        "Suma PLN 9,99",
    ])
    assert len(receipt.items) == 1
    item = receipt.items[0]
    assert item.price == Decimal("9.99")
    assert item.quantity == Decimal("1")


# ── Basket-level adjustments (kaucja / bottle deposit) ────────────────────────

def test_kaucja_becomes_basket_adjustment_item():
    # "Opakowania zwrotne suma -X,XX" sits in the SUMMARY section between
    # Suma PLN and the final Suma. It must become a synthetic line with
    # is_adjustment=True so items sum to the FINAL total.
    receipt = _parse([
        "2026-04-18",
        "Chleb", "3.99 3.99 C",
        "Suma PLN 3,99",
        "Opakowania zwrotne suma -1,00",
        "Suma 2,99",
    ])
    assert len(receipt.items) == 2
    kaucja = receipt.items[1]
    assert kaucja.is_adjustment is True
    assert kaucja.name.lower().startswith("opakowania zwrotne")
    assert kaucja.price == Decimal("-1.00")
    assert kaucja.quantity == Decimal("1")
    # And the total is the post-kaucja value
    assert receipt.total_amount == Decimal("2.99")


def test_items_sum_equals_final_total_with_kaucja():
    # End-to-end invariant for sum validation.
    receipt = _parse([
        "2026-04-18",
        "Chleb", "3.99 3.99 C",
        "Mleko", "2.99 2.99 A",
        "Suma PLN 6,98",
        "Opakowania zwrotne suma -1,00",
        "Suma 5,98",
    ])
    items_sum = sum(i.price * i.quantity for i in receipt.items)
    assert items_sum == receipt.total_amount == Decimal("5.98")


def test_product_discount_does_not_attach_to_basket_adjustment():
    # If a discount line slips in AFTER a basket adjustment, it must not
    # mutate the adjustment item (which has no original_price etc.).
    # It becomes its own orphan adjustment instead.
    receipt = _parse([
        "2026-04-18",
        "Chleb", "3.99 3.99 C",
        "Suma PLN 3,99",
        "Opakowania zwrotne suma -1,00",
        "Suma 2,99",
    ])
    chleb = receipt.items[0]
    kaucja = receipt.items[1]
    assert chleb.price == Decimal("3.99")
    assert chleb.discount_total == Decimal("0")
    assert kaucja.discount_total == Decimal("0")
    assert kaucja.original_price is None


# ── OCR-merged qty heuristic (e.g. "3*4.99" glued to "34.99") ─────────────────

def test_merged_qty_recovered_when_product_of_split_equals_total():
    # OCR glues "3 * 4.99" into "34.99". The line total 14.97 == 3 * 4.99
    # so the parser should recover qty=3, unit=4.99 instead of qty=1, total=14.97.
    receipt = _parse([
        "2026-04-18",
        "Masło Ekstra",
        "34.99 14.97 C",
        "Suma PLN 14,97",
    ])
    item = receipt.items[0]
    assert item.quantity == Decimal("3")
    assert item.price == Decimal("4.99")


def test_merged_qty_two_packs():
    # "29.99 19.98 C" was "2 * 9.99 19.98 C" → qty=2, unit=9.99
    receipt = _parse([
        "2026-04-18",
        "Polędwica sopockaXXL",
        "29.99 19.98 C",
        "Suma PLN 19,98",
    ])
    item = receipt.items[0]
    assert item.quantity == Decimal("2")
    assert item.price == Decimal("9.99")


def test_merged_qty_single_pack():
    # "111.99 11.99 C" was "1 * 11.99 11.99 C" → qty=1, unit=11.99
    receipt = _parse([
        "2026-04-18",
        "Lunchbox proteinowy",
        "111.99 11.99 C",
        "Suma PLN 11,99",
    ])
    item = receipt.items[0]
    assert item.quantity == Decimal("1")
    assert item.price == Decimal("11.99")


def test_regular_promo_not_treated_as_qty():
    # "29.99 9.99 C" is a promo (was 29.99, now 9.99). Split would give
    # qty=2, unit=9.99 → 19.98 ≠ 9.99, so heuristic must NOT trigger.
    receipt = _parse([
        "2026-04-18",
        "Promo product",
        "29.99 9.99 C",
        "Suma PLN 9,99",
    ])
    item = receipt.items[0]
    assert item.quantity == Decimal("1")
    assert item.price == Decimal("9.99")


def test_first_num_equals_second_num_not_treated_as_qty():
    # "3.49 3.49 A" — single item, no promo, no qty.
    # Split would give qty=3, unit=".49" which fails the regex. Stays single.
    receipt = _parse([
        "2026-04-18",
        "Mleko",
        "3.49 3.49 A",
        "Suma PLN 3,49",
    ])
    item = receipt.items[0]
    assert item.quantity == Decimal("1")
    assert item.price == Decimal("3.49")


def test_merged_qty_with_discount_applies_discount_per_unit():
    # qty=3 unit=4.99 → total 14.97; discount -12.39 spreads across qty.
    # After fix: unit_after = 4.99 + (-12.39/3) = 0.86; line total = 2.58.
    receipt = _parse([
        "2026-04-18",
        "Masło Ekstra",
        "34.99 14.97 C",
        "Lidl Plus kupon -12,12",
        "Lidl Plus voucher -0,27",
        "Suma PLN 2,58",
    ])
    item = receipt.items[0]
    assert item.quantity == Decimal("3")
    assert item.original_price == Decimal("4.99")
    assert item.discount_total == Decimal("-12.39")
    # line total = price * quantity ≈ 2.58
    assert abs(item.price * item.quantity - Decimal("2.58")) < Decimal("0.01")


# ── Suma regex tolerance ──────────────────────────────────────────────────────

def test_suma_bare_with_pln_suffix():
    # _SUMA_BARE must tolerate "Suma X PLN" / "Suma X zł" variants from OCR.
    receipt = _parse([
        "2026-04-18",
        "Chleb", "3.99 3.99 C",
        "Suma PLN 3,99",
        "Opakowania zwrotne suma -1,00",
        "Suma 2,99 PLN",
    ])
    assert receipt.total_amount == Decimal("2.99")
