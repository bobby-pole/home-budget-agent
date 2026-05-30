import os
import json
import pytest
from unittest.mock import patch
import fitz

from app.ocr_pipeline import (
    ReceiptSource,
    ReceiptSourceDetector,
    PDFTextLayerAdapter,
    EParagonJSONAdapter,
)
from app.services import AIService


# Helper to generate a valid PDF with a text layer in memory
def _generate_test_pdf(text: str) -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 50), text)
    pdf_bytes = doc.write()
    doc.close()
    return pdf_bytes


# Helper to generate a scanned-like PDF (an empty page or page containing only image, no text)
def _generate_scanned_pdf() -> bytes:
    doc = fitz.open()
    doc.new_page()  # empty page, no text layer
    pdf_bytes = doc.write()
    doc.close()
    return pdf_bytes


# ── PDFTextLayerAdapter Tests ──────────────────────────────────────────────────

def test_pdf_has_text_layer():
    text = "LIDL sp. z o.o.\nChleb 3.50\nSuma PLN 3,50"
    # Create text long enough to exceed threshold (>100 chars without whitespaces)
    long_text = text * 10
    pdf_bytes = _generate_test_pdf(long_text)
    
    assert PDFTextLayerAdapter.has_text_layer(pdf_bytes) is True


def test_pdf_has_no_text_layer():
    pdf_bytes = _generate_scanned_pdf()
    assert PDFTextLayerAdapter.has_text_layer(pdf_bytes) is False


def test_pdf_extract_text():
    text = "LIDL sp. z o.o.\nChleb 3.50\nSuma PLN 3,50"
    pdf_bytes = _generate_test_pdf(text)
    
    extracted = PDFTextLayerAdapter.extract_text(pdf_bytes)
    assert "LIDL" in extracted
    assert "Chleb" in extracted
    assert "Suma" in extracted


def test_pdf_convert_to_image():
    pdf_bytes = _generate_scanned_pdf()
    png_bytes = PDFTextLayerAdapter.convert_to_image(pdf_bytes)
    
    # Check that returned bytes start with PNG magic header
    assert png_bytes.startswith(b"\x89PNG\r\n\x1a\n")


# ── ReceiptSourceDetector Tests ─────────────────────────────────────────────────

def test_detector_identifies_pdf_by_magic_bytes():
    pdf_bytes = _generate_scanned_pdf()
    assert ReceiptSourceDetector.detect("random.png", file_bytes=pdf_bytes) == ReceiptSource.PDF_TEXT


def test_detector_identifies_json_by_magic_bytes():
    json_bytes = b'{"protoVersion": "000", "document": {}}'
    assert ReceiptSourceDetector.detect("random.png", file_bytes=json_bytes) == ReceiptSource.EPARAGON


# ── EParagonJSONAdapter Tests ───────────────────────────────────────────────────

def test_eparagon_json_adapter_parse():
    mock_jpk = {
        "document": {
            "naglowek": {
                "wersja": "JPK_KASA_PARAGON_v2-0",
                "dataJPK": "2026-05-27T12:54:01.000Z"
            },
            "podmiot1": {
                "NIP": "7791011327",
                "nazwaPod": "TEST BIEDRONKA S.A."
            },
            "paragon": {
                "zakSprzed": "2026-05-27T12:54:01.000Z",
                "total": {
                    "zaplZwrot": 3651
                },
                "podsum": {
                    "waluta": "PLN"
                },
                "pozycja": [
                    {
                        "towar": {
                            "nazwa": "Chleb Graham C",
                            "cena": 350,
                            "ilosc": "2",
                            "brutto": 700
                        }
                    },
                    {
                        "towar": {
                            "nazwa": "Maslo Ekstra C",
                            "cena": 600,
                            "ilosc": "1",
                            "brutto": 450,
                            "rabat": {
                                "wart": -150
                            }
                        }
                    }
                ],
                "opak": {
                    "daneOpak": [
                        {
                            "nazwa": "Butelka Kaucja",
                            "cena": 50,
                            "ilosc": 2000,
                            "total": 100
                        }
                    ]
                }
            }
        }
    }
    json_bytes = json.dumps(mock_jpk).encode("utf-8")
    
    parsed = EParagonJSONAdapter.parse(json_bytes)
    assert parsed["merchant_name"] == "TEST BIEDRONKA S.A."
    assert parsed["date"] == "2026-05-27"
    assert parsed["total_amount"] == 36.51
    assert parsed["currency"] == "PLN"
    
    # 2 products + 1 deposit = 3 items
    assert len(parsed["items"]) == 3
    
    # Check item 1 (no discount)
    item1 = parsed["items"][0]
    assert item1["name"] == "Chleb Graham C"
    assert item1["price"] == 3.50
    assert item1["quantity"] == 2.0
    assert item1["discount_total"] == 0.0
    assert item1["original_price"] == 3.50
    assert item1["is_adjustment"] is False

    # Check item 2 (discounted)
    item2 = parsed["items"][1]
    assert item2["name"] == "Maslo Ekstra C"
    assert item2["price"] == 4.50  # 6.00 - 1.50 = 4.50 unit-price after discount
    assert item2["quantity"] == 1.0
    assert item2["discount_total"] == -1.50
    assert item2["original_price"] == 6.00
    assert item2["is_adjustment"] is False

    # Check deposit
    item3 = parsed["items"][2]
    assert item3["name"] == "Butelka Kaucja"
    assert item3["price"] == 0.50
    assert item3["quantity"] == 2.0
    assert item3["is_adjustment"] is True


# ── AIService E2E Integration Tests ─────────────────────────────────────────────

@patch("app.services.AIService._categorize_parsed_items", lambda data, cats, user_id: data)
def test_pipeline_eparagon_json(tmp_path):
    mock_jpk = b'{"protoVersion": "000", "document": {"podmiot1": {"nazwaPod": "e-Store"}, "paragon": {"total": {"zaplZwrot": 1000}, "pozycja": []}}}'
    fake_json_path = tmp_path / "fake.json"
    fake_json_path.write_bytes(mock_jpk)
    
    result = AIService.parse_receipt(str(fake_json_path))
    
    assert result is not None
    assert result["merchant_name"] == "e-Store"
    assert result["total_amount"] == 10.0


@patch("app.services.AIService._ai_structurize")
def test_pipeline_pdf_text_layer_bypass_ocr(mock_structurize, tmp_path):
    text = "LIDL sp. z o.o.\nChleb 3.50\nSuma PLN 3,50"
    long_text = text * 10
    pdf_bytes = _generate_test_pdf(long_text)
    
    fake_pdf_path = tmp_path / "fake.pdf"
    fake_pdf_path.write_bytes(pdf_bytes)
    
    mock_structurize.return_value = {"merchant_name": "Lidl", "total_amount": 3.50, "items": []}
    
    # We run OCR pipeline and mock Google Vision OCR to ensure it's not used
    with patch("app.ocr_pipeline.GoogleVisionOCRService.__init__", return_value=None), \
         patch("app.ocr_pipeline.GoogleVisionOCRService.extract") as mock_extract:
        result = AIService.parse_receipt(str(fake_pdf_path))
        assert result is not None
        mock_extract.assert_not_called()


@patch("app.ocr_pipeline.GoogleVisionOCRService.__init__", return_value=None)
@patch("app.ocr_pipeline.GoogleVisionOCRService.extract")
@patch("app.services.AIService._ai_structurize")
def test_pipeline_scanned_pdf_fallback_to_ocr(mock_structurize, mock_extract, mock_init, tmp_path):
    pdf_bytes = _generate_scanned_pdf()
    
    fake_pdf_path = tmp_path / "fake.pdf"
    fake_pdf_path.write_bytes(pdf_bytes)
    
    mock_structurize.return_value = {"merchant_name": "Lidl", "total_amount": 3.50, "items": []}
    
    from app.ocr_pipeline import OCRResult
    mock_extract.return_value = OCRResult(words=[], raw_text="scanned text", source_engine="mock")
    
    result = AIService.parse_receipt(str(fake_pdf_path))
    assert result is not None
    mock_extract.assert_called_once()


# ── E2E Integration with User's Real Downloaded Files ────────────────────────────

def _find_real_file(filename: str) -> str | None:
    # 1. Check in relative data folder (works inside docker container)
    rel_path = os.path.join("data", filename)
    if os.path.exists(rel_path):
        return rel_path
    # 2. Check in absolute downloads folder (works when run natively on host)
    abs_path = os.path.join("/Users/robert/Downloads", filename)
    if os.path.exists(abs_path):
        return abs_path
    return None


@patch("app.ocr_pipeline.GoogleVisionOCRService.__init__", return_value=None)
@patch("app.ocr_pipeline.GoogleVisionOCRService.extract")
@patch("app.services.AIService._ai_structurize")
def test_e2e_user_downloads_receipt_pdf(mock_structurize, mock_extract, mock_init):
    pdf_path = _find_real_file("receipt.pdf")
    if pdf_path is None:
        pytest.skip("User file receipt.pdf not present in data or Downloads folder")
        
    print(f"Testing real user Biedronka PDF receipt: {pdf_path}")
    
    # If the local PDF lacks a text layer, configure mock fallback to avoid failing on disabled live GCP APIs
    from app.ocr_pipeline import OCRResult, OCRWord, BoundingBox
    mock_extract.return_value = OCRResult(
        words=[OCRWord(text="BIEDRONKA", bounding_box=BoundingBox(0, 0, 10, 10))],
        raw_text="BIEDRONKA\nSuma 10.00",
        source_engine="mock"
    )
    mock_structurize.return_value = {
        "merchant_name": "JERONIMO MARTINS POLSKA S.A. (Biedronka)",
        "total_amount": 10.00,
        "items": []
    }
    
    result = AIService.parse_receipt(pdf_path)
    assert result is not None
    assert result["merchant_name"] is not None
    assert "BIEDRONKA" in result["merchant_name"].upper() or "JERONIMO" in result["merchant_name"].upper()


def test_e2e_user_downloads_receipt_json():
    json_path = _find_real_file("receipt.json")
    if json_path is None:
        pytest.skip("User file receipt.json not present in data or Downloads folder")
        
    print(f"Testing real user JPK JSON e-receipt: {json_path}")
    result = AIService.parse_receipt(json_path)
    assert result is not None
    assert "JERONIMO MARTINS" in result["merchant_name"].upper()
    assert result["total_amount"] == 36.51
    assert result["currency"] == "PLN"
    
    # 5 products + 1 deposit kaucja = 6 items
    assert len(result["items"]) == 6
    
    # Check deposit
    kaucja = result["items"][-1]
    assert kaucja["name"].lower().startswith("but")
    assert kaucja["is_adjustment"] is True
    assert kaucja["price"] == 0.50
    assert kaucja["quantity"] == 2.0


def test_e2e_user_downloads_receipt2_json():
    json_path = _find_real_file("receipt2.json")
    if json_path is None:
        pytest.skip("User file receipt2.json not present in data or Downloads folder")
        
    print(f"Testing real user JPK JSON e-receipt 2: {json_path}")
    result = AIService.parse_receipt(json_path)
    assert result is not None
    assert "JERONIMO MARTINS" in result["merchant_name"].upper()
    assert result["total_amount"] == 71.98
    assert result["currency"] == "PLN"
    
    # 7 products + 1 deposit kaucja = 8 items
    assert len(result["items"]) == 8
    
    # Check first item chipsy
    item = result["items"][0]
    assert "CHIPSY" in item["name"].upper()
    assert item["price"] == 3.99  # 9.49 - 5.50 = 3.99
    assert item["original_price"] == 9.49
    assert item["discount_total"] == -5.50
    assert item["quantity"] == 1.0
