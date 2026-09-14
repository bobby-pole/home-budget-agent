from decimal import Decimal

from app.receipt_schema import CanonicalItem, CanonicalReceipt
from app.receipt_normalizer import normalize_receipt
from app.lidl_parser import LidlReceiptParser
from app.biedronka_parser import BiedronkaReceiptParser
from app.zabka_parser import ZabkaReceiptParser
from app.receipt_validator import ReceiptValidator


def test_canonical_item_math():
    # Regular product without discount
    item1 = CanonicalItem(name="Mleko", unit_price="3.50", quantity="2")
    assert item1.unit_price == Decimal("3.50")
    assert item1.quantity == Decimal("2")
    assert item1.discount_total == Decimal("0")
    assert item1.final_line_total == Decimal("7.00")
    assert item1.effective_unit_price == Decimal("3.50")
    assert item1.original_price is None

    # Multi-pack with discount
    item2 = CanonicalItem(name="Piwo", unit_price="4.00", quantity="4", discount_total="-2.00")
    assert item2.final_line_total == Decimal("14.00")
    assert item2.effective_unit_price == Decimal("3.50")
    assert item2.original_price == Decimal("4.00")
    assert item2.final_price == Decimal("3.50")

    # Basket adjustment (e.g. deposit / kaucja)
    adj = CanonicalItem(name="Kaucja butelka", unit_price="1.00", quantity="1", is_adjustment=True)
    assert adj.is_adjustment is True
    assert adj.final_line_total == Decimal("1.00")
    assert adj.original_price is None

    # Dict access and mutation
    d = item2.to_dict()
    assert d["name"] == "Piwo"
    assert d["unit_price"] == 4.0
    assert d["price"] == 3.5
    assert d["quantity"] == 4.0
    assert d["discount_total"] == -2.0
    assert d["final_line_total"] == 14.0
    assert d["original_price"] == 4.0

    # __getitem__ and __setitem__
    assert item2["name"] == "Piwo"
    item2["category"] = "Napoje"
    assert item2["category"] == "Napoje"
    assert item2.category == "Napoje"


def test_discount_normalizer_folding():
    raw_receipt = {
        "merchant_name": "Sklep Test",
        "date": "2026-06-14",
        "total_amount": 18.00,
        "currency": "PLN",
        "items": [
            {"name": "Kawa 250g", "price": 20.00, "quantity": 1},
            {"name": "Rabat Kawa", "price": -5.00, "quantity": 1},
            {"name": "Kaucja butelka", "price": 3.00, "quantity": 1, "is_adjustment": True},
        ],
    }

    norm = normalize_receipt(raw_receipt)
    assert isinstance(norm, CanonicalReceipt)
    assert len(norm.items) == 2  # Discount folded into Kawa

    kawa = norm.items[0]
    assert kawa.name == "Kawa 250g"
    assert kawa.unit_price == Decimal("20.00")
    assert kawa.discount_total == Decimal("-5.00")
    assert kawa.final_line_total == Decimal("15.00")
    assert kawa.effective_unit_price == Decimal("15.00")
    assert kawa.is_adjustment is False

    kaucja = norm.items[1]
    assert kaucja.name == "Kaucja butelka"
    assert kaucja.is_adjustment is True
    assert kaucja.final_line_total == Decimal("3.00")

    assert norm.calculated_total == Decimal("18.00")
    assert norm.total_amount == Decimal("18.00")


def test_lidl_parser_canonical():
    lines = [
        "LIDL Sp. z o.o.",
        "PARAGON FISKALNY",
        "2026-05-10",
        "Chleb żytni",
        "1 x 4,50 4,50 A",
        "Jabłka Jonagold",
        "2 x 3,00 6,00 A",
        "RABAT 50 % -1,00",
        "SUMA PLN 9,50",
    ]
    parser = LidlReceiptParser()
    receipt = parser.parse(lines)
    assert isinstance(receipt, CanonicalReceipt)
    assert receipt.merchant_name == "Lidl"
    assert receipt.total_amount == Decimal("9.50")
    assert len(receipt.items) == 2

    jablka = receipt.items[1]
    assert jablka.name == "Jabłka Jonagold"
    assert jablka.unit_price == Decimal("3.00")
    assert jablka.quantity == Decimal("2.0")
    assert jablka.discount_total == Decimal("-1.00")
    assert jablka.final_line_total == Decimal("5.00")
    assert receipt.calculated_total == Decimal("9.50")


def test_biedronka_parser_single_and_multi_item():
    lines = [
        "Biedronka",
        "PARAGON FISKALNY",
        "2026-06-13",
        "Chleb Żytni 450g A 4,50",
        "PomidorPaprycz500g с 2x 14,99 29,98",
        "Opust -18,00",
        "11,98",
        "Kaucja butelka 1,00",
        "OPUSTY ŁĄCZNIE : -18,00",
        "Suma PLN 17,48",
    ]
    parser = BiedronkaReceiptParser()
    receipt = parser.parse(lines)
    assert isinstance(receipt, CanonicalReceipt)
    assert receipt.merchant_name == "Biedronka"
    assert receipt.total_amount == Decimal("17.48")
    assert len(receipt.items) == 3

    # Single item without multiplier
    chleb = receipt.items[0]
    assert "Chleb Żytni" in chleb.name
    assert chleb.unit_price == Decimal("4.50")
    assert chleb.quantity == Decimal("1.0")
    assert chleb.final_line_total == Decimal("4.50")

    # Multi-item with opust
    pomidor = receipt.items[1]
    assert "PomidorPaprycz500g" in pomidor.name
    assert pomidor.unit_price == Decimal("14.99")
    assert pomidor.quantity == Decimal("2.0")
    assert pomidor.discount_total == Decimal("-18.00")
    assert pomidor.final_line_total == Decimal("11.98")

    # Deposit
    kaucja = receipt.items[2]
    assert kaucja.is_adjustment is True
    assert kaucja.final_line_total == Decimal("1.00")

    assert receipt.calculated_total == Decimal("17.48")


def test_zabka_parser_canonical():
    lines = [
        "Sklep Żabka",
        "PARAGON FISKALNY",
        "2026-06-14",
        "Coca Cola 0.5L",
        "2szt. x 5.00 10.00 A",
        "OPUST Coca Cola 0.5L",
        "-2.00A",
        "SUMA PLN",
        "8.00",
    ]
    parser = ZabkaReceiptParser()
    receipt = parser.parse(lines)
    assert isinstance(receipt, CanonicalReceipt)
    assert receipt.merchant_name == "Żabka"
    assert receipt.total_amount == Decimal("8.00")
    assert len(receipt.items) == 1

    cola = receipt.items[0]
    assert cola.name == "Coca Cola 0.5L"
    assert cola.unit_price == Decimal("5.00")
    assert cola.quantity == Decimal("2.0")
    assert cola.discount_total == Decimal("-2.00")
    assert cola.final_line_total == Decimal("8.00")
    assert receipt.calculated_total == Decimal("8.00")


def test_receipt_validator_with_canonical_data():
    item = CanonicalItem(name="Ser Gouda", unit_price="12.00", quantity="1", discount_total="-2.00")
    receipt = CanonicalReceipt(
        merchant_name="Sklep",
        date="2026-05-01",
        total_amount=Decimal("10.00"),
        currency="PLN",
        items=[item],
    )
    result = ReceiptValidator().validate(receipt.to_dict(), receipt.total_amount)
    assert result.is_valid is True
    assert result.issues == []
    assert result.confidence == 1.0


def test_unicode_minus_and_lidl_detection():
    from app.ocr_pipeline import detect_merchant

    # Test merchant detection with bare "LiDL" and multi-line address
    header = [
        "LiDL",
        "Adres siedziby : Poznańska 48 , Jankowice",
        "62-080 Tarnowo",
        "Podgórne nr rej : BDO 000002265 Lidl sp .",
    ]
    assert detect_merchant(header) == "lidl"

    # Test parser with Unicode minus sign (\u2212)
    lines = [
        "LiDL",
        "2026-09-05",
        "Przekąska z serem",
        "2 1.52 3.04 C",
        "Nie marnuję −1,51",  # Unicode minus sign
        "Suma PLN 1,53",
    ]
    parser = LidlReceiptParser()
    receipt = parser.parse(lines)
    assert len(receipt.items) == 1
    assert receipt.items[0].discount_total == Decimal("-1.51")
    assert receipt.items[0].final_line_total == Decimal("1.53")
    assert receipt.calculated_total == Decimal("1.53")
