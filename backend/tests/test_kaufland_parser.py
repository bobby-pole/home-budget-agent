# backend/tests/test_kaufland_parser.py
from decimal import Decimal

from app.kaufland_parser import KauflandReceiptParser
from app.receipt_schema import CanonicalReceipt


def test_kaufland_parser_real_receipt_lines():
    lines = [
        "Za ten zakup otrzymałeś 51 punktów.",
        "Podsumowanie zakupów",
        "Kaufland Polska Markety Sp.z o.o.Sp.j.",
        "Al.Armii Krajowej 47, 50-541 Wrocław",
        "Nr BDO 000013346",
        "ul. Zebrzydowicka   1",
        "44-200    Rybnik  6863",
        "Cena PLN",
        "Beauty / Zdrowie / Dziecko",
        "ViscoplastMikki10szt *            7,99 B",
        "Czas wolny/Do czytania/aktywny wypocz.",
        "BL. TECH. KOL. A4/10",
        "2 * 5,99                        11,98 A",
        "Drogeria/Gosp.dom/Karmy dla zwierz/Tytoń",
        "DolinaNotKarmKot185g",
        "3 * 7,99                        23,97 B",
        "Nabiał / Sery/ Jaja chłodzone",
        "Müllermilch Zero                  3,19 C",
        "MüllermilchZero400g               3,19 C",
        "Napoje bezalkoholowe",
        "DawtonaDSMus180G",
        "2 * 2,99                         5,98 C",
        "ŻywiecZdrójWoda1,5L               2,39 A",
        "Podstawowe artykuły spożywcze",
        "TymbMuslyWiśRyJo170               3,59 C",
        "TymbMusOwoLeKasz170               3,59 C",
        "Suma cząstkowa         65,87",
        "----------------Promocja---------------",
        "Kup 2 + 1 gratis                 -7,99",
        "Pozycje:3",
        "Kup 2 płać za 1                  -5,99",
        "Pozycje:2",
        "Suma                             51,89",
        "Płatność kartą                   51,89",
        "Reszta                            0,00",
        "Data: 28.08.24 Czas:  13:38:55 Para76398",
    ]

    parser = KauflandReceiptParser()
    receipt = parser.parse(lines)

    assert isinstance(receipt, CanonicalReceipt)
    assert receipt.merchant_name == "Kaufland"
    assert receipt.date == "2024-08-28"
    assert receipt.total_amount == Decimal("51.89")
    assert len(receipt.items) == 9

    # Check promotion folding: DolinaNotKarmKot185g (qty 3) folded -7.99 promo
    cat_food = next(i for i in receipt.items if "DolinaNotKarmKot" in i.name)
    assert cat_food.unit_price == Decimal("7.99")
    assert cat_food.quantity == Decimal("3.0")
    assert cat_food.discount_total == Decimal("-7.99")
    assert cat_food.final_line_total == Decimal("15.98")

    # Check promotion folding: BL. TECH. KOL. A4/10 (qty 2) folded -5.99 promo
    paper = next(i for i in receipt.items if "BL. TECH" in i.name)
    assert paper.unit_price == Decimal("5.99")
    assert paper.quantity == Decimal("2.0")
    assert paper.discount_total == Decimal("-5.99")
    assert paper.final_line_total == Decimal("5.99")

    # Sum check invariant
    assert receipt.calculated_total == Decimal("51.89")


def test_kaufland_parser_weighted_item_and_deposit():
    lines = [
        "Kaufland",
        "Cena PLN",
        "Owoce i warzywa",
        "Jabłka Jonagold",
        "1,250 kg * 4,00 5,00 A",
        "Kaucja butelka 0,50",
        "Suma 5,50",
        "Data: 2026-09-01",
    ]
    parser = KauflandReceiptParser()
    receipt = parser.parse(lines)

    assert receipt.total_amount == Decimal("5.50")
    assert len(receipt.items) == 2

    apples = receipt.items[0]
    assert apples.name == "Jabłka Jonagold"
    assert apples.quantity == Decimal("1.250")
    assert apples.unit_price == Decimal("4.00")
    assert apples.final_line_total == Decimal("5.00")

    deposit = receipt.items[1]
    assert deposit.is_adjustment is True
    assert deposit.final_line_total == Decimal("0.50")

    assert receipt.calculated_total == Decimal("5.50")
