# backend/app/ocr_pipeline.py
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class ReceiptSource(str, Enum):
    APP_PNG = "app_png"       # clean digital PNG (Lidl Plus, app export)
    PHOTO_IMAGE = "photo_image"  # camera photo — higher Y tolerance for reconstruction
    PDF_TEXT = "pdf_text"     # PDF with text layer — skip OCR entirely
    PDF_IMAGE = "pdf_image"   # PDF without text layer — route through OCR


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
    def detect(filename: str, content_type: Optional[str] = None) -> ReceiptSource:
        mime = (content_type or "").lower()
        name = (filename or "").lower()

        if "pdf" in mime or name.endswith(".pdf"):
            # PDFTextLayerAdapter will verify if text layer actually exists (#179)
            return ReceiptSource.PDF_TEXT

        # All PNG/JPG treated as APP_PNG for now.
        # PHOTO_IMAGE distinction (EXIF heuristic) is future work.
        return ReceiptSource.APP_PNG


# ── Google Vision OCR ──────────────────────────────────────────────────────────

class GoogleVisionOCRService:
    """
    Wraps Google Vision DOCUMENT_TEXT_DETECTION.
    Use this, not TEXT_DETECTION — it preserves spatial word structure via boundingPoly.
    """

    def __init__(self) -> None:
        try:
            from google.cloud import vision  # type: ignore[import]
            self._client = vision.ImageAnnotatorClient()
            self._vision = vision
        except ImportError:
            self._client = None
            self._vision = None

    @property
    def available(self) -> bool:
        return self._client is not None

    def extract(self, image_bytes: bytes) -> OCRResult:
        if not self._client or not self._vision:
            raise RuntimeError(
                "google-cloud-vision is not installed. "
                "Add it to requirements.txt and set GOOGLE_APPLICATION_CREDENTIALS."
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

def reconstruct_lines(words: list[OCRWord], y_tolerance: Optional[float] = None) -> list[str]:
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
