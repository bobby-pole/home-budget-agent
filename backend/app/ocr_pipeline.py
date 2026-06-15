# backend/app/ocr_pipeline.py
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class ReceiptSource(str, Enum):
    APP_PNG = "app_png"       # clean digital PNG (Lidl Plus, app export)
    PHOTO_IMAGE = "photo_image"  # camera photo — higher Y tolerance for reconstruction
    PDF_TEXT = "pdf_text"     # PDF with text layer — skip OCR entirely
    PDF_IMAGE = "pdf_image"   # PDF without text layer — route through OCR
    EPARAGON = "eparagon"     # structured e-paragon JSON


# ── Data types ─────────────────────────────────────────────────────────────────

@dataclass
class BoundingBox:
    x_min: float
    y_min: float
    x_max: float
    y_max: float

    @property
    def center_y(self) -> float:
        return (self.y_min + self.y_max) / 2

    @property
    def height(self) -> float:
        return self.y_max - self.y_min


@dataclass
class OCRWord:
    text: str
    bounding_box: BoundingBox
    confidence: float = 1.0


@dataclass
class OCRResult:
    words: list[OCRWord]
    raw_text: str
    source_engine: str


# ── Source Detector ────────────────────────────────────────────────────────────

class ReceiptSourceDetector:
    @staticmethod
    def detect(filename: str, content_type: Optional[str] = None, file_bytes: Optional[bytes] = None) -> ReceiptSource:
        # 1. Check binary magic bytes first for bulletproof detection
        if file_bytes:
            if file_bytes.startswith(b"%PDF"):
                return ReceiptSource.PDF_TEXT
            if file_bytes.strip().startswith(b"{"):
                try:
                    data = json.loads(file_bytes.decode("utf-8"))
                    if "document" in data or "protoVersion" in data:
                        return ReceiptSource.EPARAGON
                except Exception:
                    pass

            # Check EXIF for camera photo detection
            try:
                from PIL import Image
                from io import BytesIO
                
                # PNG or JPEG magic bytes
                if file_bytes.startswith(b"\x89PNG\r\n\x1a\n") or file_bytes.startswith(b"\xff\xd8\xff"):
                    image = Image.open(BytesIO(file_bytes))
                    exif = image.getexif()
                    if exif:
                        # 271: Make, 272: Model, 274: Orientation, 306: DateTime, 34665: ExifOffset (contains detailed camera EXIF)
                        camera_tags = {271, 272, 274, 306, 34665}
                        if any(tag in exif for tag in camera_tags):
                            return ReceiptSource.PHOTO_IMAGE
            except Exception as e:
                print(f"⚠️ Error checking EXIF metadata: {e}")

        # 2. Fall back to filename and content type heuristics
        mime = (content_type or "").lower()
        name = (filename or "").lower()

        if name.endswith(".json") or "json" in mime:
            return ReceiptSource.EPARAGON

        if "pdf" in mime or name.endswith(".pdf"):
            return ReceiptSource.PDF_TEXT

        return ReceiptSource.APP_PNG


# ── PDF Text-Layer Adapter ─────────────────────────────────────────────────────

class PDFTextLayerAdapter:
    @staticmethod
    def has_text_layer(file_bytes: bytes) -> bool:
        try:
            import fitz
            doc = fitz.open(stream=file_bytes, filetype="pdf")
            text = ""
            for page in doc:
                text += str(page.get_text()) + "\n"
            doc.close()
            # Threshold: > 100 non-whitespace characters
            cleaned_text = "".join(text.split())
            return len(cleaned_text) > 100
        except Exception as e:
            print(f"⚠️ Error checking PDF text layer: {e}")
            return False

    @staticmethod
    def extract_text(file_bytes: bytes) -> str:
        import fitz
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        text = ""
        for page in doc:
            text += str(page.get_text()) + "\n"
        doc.close()
        return text

    @staticmethod
    def convert_to_image(file_bytes: bytes) -> bytes:
        import fitz
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        page = doc[0]  # Render first page
        pix = page.get_pixmap(dpi=150)
        png_bytes = pix.tobytes("png")
        doc.close()
        return png_bytes


# ── E-Paragon JSON Adapter ─────────────────────────────────────────────────────


def _parse_polish_float(value: str | int | float, divisor: float = 1.0) -> float:
    """Parse a numeric value that may use Polish comma decimal format.

    Handles: "0,038", "2", 799, 8.99, "0.348"
    """
    if isinstance(value, (int, float)):
        return float(value) / divisor
    # Polish e-paragons use comma as decimal separator in string quantities
    return float(str(value).replace(",", ".")) / divisor


class EParagonJSONAdapter:
    @staticmethod
    def parse(file_bytes: bytes) -> dict:
        import base64

        raw_data = json.loads(file_bytes.decode("utf-8"))

        # Decode JPK JWT payload if wrapped in official "data" key
        if isinstance(raw_data, dict) and "data" in raw_data and isinstance(raw_data["data"], str):
            try:
                parts = raw_data["data"].split('.')
                if len(parts) >= 2:
                    payload_segment = parts[1]
                    rem = len(payload_segment) % 4
                    if rem > 0:
                        payload_segment += '=' * (4 - rem)
                    decoded_bytes = base64.urlsafe_b64decode(payload_segment)
                    data = json.loads(decoded_bytes.decode("utf-8"))
                else:
                    data = raw_data
            except Exception as e:
                print(f"⚠️ Failed to decode JWT payload from data: {e}")
                data = raw_data
        else:
            data = raw_data

        doc = data.get("dokument") or data.get("document") or data
        # If 'doc' itself is wrapped in another level
        if isinstance(doc, dict) and ("dokument" in doc or "document" in doc):
            doc = doc.get("dokument") or doc.get("document")

        if not isinstance(doc, dict):
            doc = {}

        paragon = doc.get("paragon", {})
        podmiot = doc.get("podmiot1", {})

        # 1. Merchant name
        merchant = podmiot.get("nazwaPod", "Unknown Merchant")

        # 2. Purchase date
        purchase_date_str = paragon.get("zakSprzed") or doc.get("naglowek", {}).get("dataJPK", "")
        date_str = ""
        if purchase_date_str:
            date_str = purchase_date_str.split("T")[0]

        # 3. Currency and totals
        podsum = paragon.get("podsum", {})
        currency = podsum.get("waluta", "PLN")
        total_gross = _parse_polish_float(paragon.get("total", {}).get("zaplZwrot", 0), divisor=100.0)

        # 4. Items — handle two e-paragon formats:
        #    a) Biedronka: rabat is INLINE in towar → {"towar": {"nazwa":..., "rabat": {"wart": -150}}}
        #    b) Żabka:     rabat is a SEPARATE pozycja entry → {"rabat": {"nazwa":..., "wart": -400}}
        items: list[dict] = []
        positions = paragon.get("pozycja", [])
        for pos in positions:
            # ── Handle towar (product) entries ─────────────────────────────
            towar = pos.get("towar")
            if towar and isinstance(towar, dict):
                name = towar.get("nazwa", "Unknown Item").strip()

                orig_unit_price = _parse_polish_float(towar.get("cena", 0), divisor=100.0)
                qty = _parse_polish_float(towar.get("ilosc", "1"))

                # Inline rabat (Biedronka format: rabat inside towar)
                discount_total = 0.0
                rabat = towar.get("rabat", {})
                if rabat:
                    discount_total = _parse_polish_float(rabat.get("wart", 0), divisor=100.0)

                original_price = orig_unit_price
                final_price = original_price + (discount_total / qty) if qty > 0 else original_price

                items.append({
                    "name": name,
                    "price": final_price,
                    "quantity": qty,
                    "original_price": original_price,
                    "discount_total": discount_total,
                    "final_price": final_price,
                    "is_adjustment": False,
                })
                continue

            # ── Handle standalone rabat entries (Żabka format) ─────────────
            # These are separate pozycja entries: {"rabat": {"nazwa": "...", "wart": -400, ...}}
            # Apply the discount to the last non-adjustment item.
            rabat = pos.get("rabat")
            if rabat and isinstance(rabat, dict) and items:
                discount_val = _parse_polish_float(rabat.get("wart", 0), divisor=100.0)
                # Find last non-adjustment item to apply discount to
                for prev_item in reversed(items):
                    if not prev_item.get("is_adjustment", False):
                        prev_item["discount_total"] += discount_val
                        qty = prev_item["quantity"]
                        prev_item["final_price"] = (
                            prev_item["original_price"] + (prev_item["discount_total"] / qty)
                            if qty > 0 else prev_item["original_price"]
                        )
                        prev_item["price"] = prev_item["final_price"]
                        break
                continue

            # ── Skip unrecognized pozycja entries (defensive) ─────────────
            # Don't create ghost items from entries we don't understand.

        # 5. Packaging / Deposits
        opak = paragon.get("opak", {})
        if opak:
            for op_item in opak.get("daneOpak", []):
                name = op_item.get("nazwa", "Kaucja").strip()
                cena = _parse_polish_float(op_item.get("cena", 0), divisor=100.0)
                ilosc_raw = op_item.get("ilosc", 1000)
                qty = float(ilosc_raw) / 1000.0 if ilosc_raw > 10 else float(ilosc_raw)

                items.append({
                    "name": name,
                    "price": cena,
                    "quantity": qty,
                    "original_price": None,
                    "discount_total": 0.0,
                    "final_price": None,
                    "is_adjustment": True,
                })

        return {
            "merchant_name": merchant,
            "date": date_str,
            "total_amount": total_gross,
            "currency": currency,
            "items": items,
        }


# ── Google Vision OCR ──────────────────────────────────────────────────────────

class GoogleVisionOCRService:
    """
    Wraps Google Vision DOCUMENT_TEXT_DETECTION.
    Use this, not TEXT_DETECTION — it preserves spatial word structure via boundingPoly.
    """

    def __init__(self) -> None:
        try:
            from google.cloud import vision  # type: ignore[import]
            credentials = None
            creds_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
            if creds_json:
                from google.oauth2 import service_account  # type: ignore[import]
                info = json.loads(creds_json)
                credentials = service_account.Credentials.from_service_account_info(
                    info,
                    scopes=["https://www.googleapis.com/auth/cloud-platform"],
                )
            self._client = vision.ImageAnnotatorClient(credentials=credentials)  # type: ignore
            self._vision = vision
        except ImportError:
            self._client = None  # type: ignore
            self._vision = None  # type: ignore

    @property
    def available(self) -> bool:
        return self._client is not None

    def extract(self, image_bytes: bytes) -> OCRResult:
        if not self._client or not self._vision:
            raise RuntimeError(
                "google-cloud-vision is not installed. "
                "Add it to pyproject.toml and set GOOGLE_APPLICATION_CREDENTIALS."
            )

        image = self._vision.Image(content=image_bytes)
        response = self._client.document_text_detection(image=image)  # type: ignore[attr-defined]

        if response.error.message:
            raise RuntimeError(f"Google Vision error: {response.error.message}")

        words: list[OCRWord] = []
        for page in response.full_text_annotation.pages:
            for block in page.blocks:
                for paragraph in block.paragraphs:
                    for word in paragraph.words:
                        text = "".join(symbol.text for symbol in word.symbols)
                        verts = word.bounding_box.vertices
                        xs = [v.x for v in verts]
                        ys = [v.y for v in verts]
                        bbox = BoundingBox(
                            x_min=min(xs), y_min=min(ys),
                            x_max=max(xs), y_max=max(ys),
                        )
                        words.append(OCRWord(
                            text=text,
                            bounding_box=bbox,
                            confidence=getattr(word, "confidence", 1.0),
                        ))

        return OCRResult(
            words=words,
            raw_text=response.full_text_annotation.text,
            source_engine="google_vision_document",
        )


# ── Line Reconstruction ────────────────────────────────────────────────────────

def reconstruct_lines(words: list[OCRWord], y_tolerance: Optional[float] = None, source: Optional[ReceiptSource] = None) -> list[str]:
    """
    Reconstruct text lines from bounding box geometry.

    Algorithm:
      1. Sort words by center_y (top to bottom)
      2. Group into lines: a word joins current line if |center_y - line_avg_y| <= tolerance
      3. Sort words within each line by x_min (left to right)
      4. Join with spaces

    y_tolerance defaults to 50% of average word height — tight for clean PNGs (~5-8px),
    auto-relaxed for photos where lines are less perfectly aligned.
    """
    if not words:
        return []

    if y_tolerance is None:
        heights = [w.bounding_box.height for w in words if w.bounding_box.height > 0]
        avg_height = sum(heights) / len(heights) if heights else 10.0
        if source == ReceiptSource.PHOTO_IMAGE:
            y_tolerance = max(8.0, avg_height * 0.8)
        else:
            y_tolerance = max(5.0, avg_height * 0.5)

    sorted_words = sorted(words, key=lambda w: w.bounding_box.center_y)

    lines: list[list[OCRWord]] = []
    current_line: list[OCRWord] = []
    current_y: Optional[float] = None

    for word in sorted_words:
        cy = word.bounding_box.center_y
        if current_y is None or abs(cy - current_y) <= y_tolerance:
            current_line.append(word)
            current_y = sum(w.bounding_box.center_y for w in current_line) / len(current_line)
        else:
            lines.append(sorted(current_line, key=lambda w: w.bounding_box.x_min))
            current_line = [word]
            current_y = cy

    if current_line:
        lines.append(sorted(current_line, key=lambda w: w.bounding_box.x_min))

    return [" ".join(w.text for w in line) for line in lines]


# ── Format Detector ────────────────────────────────────────────────────────────

# Only the receipt header (~30 lines) is checked — merchant name is always there.
_HEADER_LINES = 30

MERCHANT_SIGNATURES: dict[str, list[str]] = {
    "lidl": [
        r"LIDL\s+sp\.?\s*z\s*o\.?\s*o\.",
        r"Lidl\s+Plus",
        r"ul\.\s*Pozna[ńn]ska\s+48",
    ],
    "biedronka": [
        r"Jeronimo\s+Martins",
        r"BIEDRONKA",
    ],
    "kaufland": [
        r"Kaufland\s+Polska",
    ],
    "auchan": [
        r"Auchan\s+Polska",
        r"AUCHAN",
    ],
    "zabka": [
        r"Żabka\s+Polska",
        r"ŻABKA",
    ],
}


def detect_merchant(lines: list[str]) -> Optional[str]:
    """
    Return merchant key ('lidl', 'biedronka', ...) or None if unknown.
    None → caller should fall back to AI structurizer.
    """
    header = "\n".join(lines[:_HEADER_LINES])
    for merchant, patterns in MERCHANT_SIGNATURES.items():
        if any(re.search(p, header, re.IGNORECASE) for p in patterns):
            return merchant
    return None
