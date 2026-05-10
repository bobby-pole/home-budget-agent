import json
import pytest
from unittest.mock import MagicMock, patch, mock_open

from app.services import AIService
from app.ocr_pipeline import (
    BoundingBox,
    OCRWord,
    ReceiptSource,
    ReceiptSourceDetector,
    detect_merchant,
    reconstruct_lines,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def ai_response():
    data = {
        "merchant_name": "Test Supermarket",
        "date": "2024-05-10",
        "total_amount": 150.00,
        "currency": "PLN",
        "items": [
            {"name": "Bread", "price": 5.0, "quantity": 1, "category": "Food"},
            {"name": "Milk", "price": 3.5, "quantity": 2, "category": "Food"},
        ],
    }
    msg = MagicMock()
    msg.content = json.dumps(data)
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    return resp


def _make_word(text: str, x: float, y: float, w: float = 20, h: float = 10) -> OCRWord:
    return OCRWord(text=text, bounding_box=BoundingBox(x, y, x + w, y + h))


# ── ReceiptSourceDetector ─────────────────────────────────────────────────────

def test_detect_source_png():
    assert ReceiptSourceDetector.detect("receipt.png", "image/png") == ReceiptSource.APP_PNG

def test_detect_source_jpg():
    assert ReceiptSourceDetector.detect("receipt.jpg", "image/jpeg") == ReceiptSource.APP_PNG

def test_detect_source_pdf():
    assert ReceiptSourceDetector.detect("receipt.pdf", "application/pdf") == ReceiptSource.PDF_TEXT

def test_detect_source_pdf_by_filename():
    assert ReceiptSourceDetector.detect("receipt.pdf") == ReceiptSource.PDF_TEXT


# ── reconstruct_lines ─────────────────────────────────────────────────────────

def test_reconstruct_lines_two_rows():
    words = [
        _make_word("Mleko", x=10, y=100),
        _make_word("3.50", x=200, y=100),
        _make_word("Chleb", x=10, y=120),
        _make_word("2.00", x=200, y=120),
    ]
    lines = reconstruct_lines(words, y_tolerance=8)
    assert len(lines) == 2
    assert "Mleko" in lines[0] and "3.50" in lines[0]
    assert "Chleb" in lines[1] and "2.00" in lines[1]


def test_reconstruct_lines_single_row():
    words = [_make_word("LIDL", x=50, y=10), _make_word("sp.z.o.o.", x=90, y=10)]
    lines = reconstruct_lines(words, y_tolerance=5)
    assert len(lines) == 1
    assert "LIDL" in lines[0]


def test_reconstruct_lines_preserves_left_to_right_order():
    # Words in reversed X order — should be sorted correctly
    words = [
        _make_word("4.99", x=200, y=50),
        _make_word("Masło", x=10, y=50),
    ]
    lines = reconstruct_lines(words, y_tolerance=5)
    assert lines[0].startswith("Masło")


def test_reconstruct_lines_empty():
    assert reconstruct_lines([]) == []


# ── detect_merchant ───────────────────────────────────────────────────────────

def test_detect_merchant_lidl():
    lines = ["LIDL sp. z o.o.", "ul. Jakaś 1", "Suma PLN 45.00"]
    assert detect_merchant(lines) == "lidl"


def test_detect_merchant_lidl_plus():
    lines = ["Lidl Plus voucher -2.00", "Chleb tostowy 3.49"]
    assert detect_merchant(lines) == "lidl"


def test_detect_merchant_biedronka():
    lines = ["Jeronimo Martins Polska S.A.", "BIEDRONKA 1234"]
    assert detect_merchant(lines) == "biedronka"


def test_detect_merchant_unknown():
    lines = ["Sklep XYZ", "ul. Nieznana 5", "Suma 12.00"]
    assert detect_merchant(lines) is None


# ── AIService.parse_receipt ───────────────────────────────────────────────────

@patch("builtins.open", mock_open(read_data=b"fake_image_bytes"))
@patch("app.services.AIService._run_ocr_pipeline")
def test_parse_receipt_success(mock_pipeline, ai_response):
    mock_pipeline.return_value = {
        "merchant_name": "Test Supermarket",
        "total_amount": 150.00,
        "items": [],
    }
    result = AIService.parse_receipt("fake/receipt.jpg")
    assert result is not None
    assert result["merchant_name"] == "Test Supermarket"
    mock_pipeline.assert_called_once()


@patch("builtins.open", side_effect=FileNotFoundError)
def test_parse_receipt_file_not_found(mock_file):
    result = AIService.parse_receipt("missing/receipt.jpg")
    assert result is None


@patch("builtins.open", mock_open(read_data=b"fake_image_bytes"))
@patch("app.services.AIService._ai_structurize")
@patch("app.ocr_pipeline.GoogleVisionOCRService.__init__", return_value=None)
@patch("app.ocr_pipeline.GoogleVisionOCRService.extract")
def test_parse_receipt_calls_ai_structurize_for_unknown_merchant(mock_extract, mock_init, mock_structurize):
    from app.ocr_pipeline import OCRResult
    mock_extract.return_value = OCRResult(words=[], raw_text="Sklep XYZ\nChleb 3.50", source_engine="test")
    mock_structurize.return_value = {"merchant_name": "Sklep XYZ", "total_amount": 3.50, "items": []}

    result = AIService.parse_receipt("receipt.jpg")
    assert result is not None
    mock_structurize.assert_called_once()


@patch("builtins.open", mock_open(read_data=b"fake_image_bytes"))
@patch("app.services.AIService._ai_vision_fallback")
@patch("app.ocr_pipeline.GoogleVisionOCRService.__init__", return_value=None)
@patch("app.ocr_pipeline.GoogleVisionOCRService.extract", side_effect=RuntimeError("not configured"))
def test_parse_receipt_falls_back_to_ai_vision_when_ocr_unavailable(mock_extract, mock_init, mock_fallback):
    mock_fallback.return_value = {"merchant_name": "Fallback", "total_amount": 10.0, "items": []}
    result = AIService.parse_receipt("receipt.jpg")
    assert result is not None
    mock_fallback.assert_called_once()


@patch("app.services.client.chat.completions.create")
def test_ai_structurize_includes_categories_in_prompt(mock_create, ai_response):
    mock_create.return_value = ai_response
    categories = [{"id": 1, "name": "Food"}, {"id": 2, "name": "Alcohol"}]

    AIService._ai_structurize("Mleko 3.50\nSuma 3.50", categories=categories)

    system_prompt = mock_create.call_args.kwargs["messages"][0]["content"]
    assert "Food" in system_prompt
    assert "Alcohol" in system_prompt


@patch("app.services.client.chat.completions.create")
def test_ai_structurize_empty_response_returns_none(mock_create):
    msg = MagicMock()
    msg.content = None
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    mock_create.return_value = resp

    result = AIService._ai_structurize("some text")
    # Empty content → json.loads("{}") → {} which is falsy — same effect as None for callers
    assert not result


# ── AIService.categorize_descriptions ────────────────────────────────────────

@patch("app.services.client.chat.completions.create")
def test_categorize_descriptions_success(mock_create):
    msg = MagicMock()
    msg.content = json.dumps({"BIEDRONKA": "Food", "ALLEGRO": "Shopping"})
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    mock_create.return_value = resp

    result = AIService.categorize_descriptions(
        ["BIEDRONKA", "ALLEGRO"],
        [{"id": 1, "name": "Food"}, {"id": 2, "name": "Shopping"}],
    )
    assert result["BIEDRONKA"] == "Food"
    assert result["ALLEGRO"] == "Shopping"


def test_categorize_descriptions_empty():
    result = AIService.categorize_descriptions([], [{"id": 1, "name": "Food"}])
    assert result == {}
