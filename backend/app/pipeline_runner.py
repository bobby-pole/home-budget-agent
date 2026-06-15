# backend/app/pipeline_runner.py
"""
Receipt OCR pipeline orchestrator.

Extracted from AIService._run_ocr_pipeline() for independent testability.
Each pipeline stage is a separate method with structured logging.

Used by:
  - AIService (production API) — with AI callbacks
  - scripts/debug_pipeline.py (CLI) — with --no-ai flag
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Callable, Optional

from .ocr_pipeline import (
    ReceiptSource,
    ReceiptSourceDetector,
    GoogleVisionOCRService,
    PDFTextLayerAdapter,
    EParagonJSONAdapter,
    reconstruct_lines,
    detect_merchant,
)
from .pipeline_logger import PipelineLogger
from .receipt_validator import ReceiptValidator


# ── AI Callbacks ───────────────────────────────────────────────────────────────

@dataclass
class AICallbacks:
    """
    Optional AI function callbacks injected by the caller.

    When None, the pipeline will skip AI-dependent stages.
    This keeps the pipeline runner free of OpenAI / DB imports.
    """

    structurize: Optional[Callable[[str], Optional[dict]]] = None
    """AI structurizer: receipt_text -> parsed dict."""

    vision_fallback: Optional[Callable[[bytes], Optional[dict]]] = None
    """Direct AI vision: image_bytes -> parsed dict (last resort)."""

    categorize: Optional[Callable[[Optional[dict]], Optional[dict]]] = None
    """Categorize parsed items: data -> data with categories."""


# ── Pipeline Runner ────────────────────────────────────────────────────────────

class PipelineRunner:
    """
    Orchestrates the receipt OCR pipeline with structured logging.

    Stages:
      1. Source Detection    — detect file format (PNG/JPG/PDF/JSON)
      2. Content Extraction  — extract text/lines from the file
      3. Merchant Detection  — identify merchant from header lines
      4. Parsing             — deterministic parser or AI structurizer
      5. Categorization      — cache-first + AI categorization
      6. Validation          — sum check, zero-price, future date

    Usage:
        logger = PipelineLogger(verbose=True)
        runner = PipelineRunner(logger=logger, no_ai=False, ai=callbacks)
        result = runner.run(file_bytes, "receipt.pdf")
    """

    def __init__(
        self,
        logger: PipelineLogger,
        no_ai: bool = False,
        ai: Optional[AICallbacks] = None,
        max_stage: Optional[int] = None,
    ) -> None:
        self.logger = logger
        self.no_ai = no_ai
        self.ai = ai or AICallbacks()
        self.max_stage = max_stage

    def run(self, file_bytes: bytes, filename: str) -> Optional[dict[str, Any]]:
        """Run the full pipeline. Returns parsed receipt dict or None."""
        self.logger.set_file_info(filename, file_bytes)

        try:
            return self._run_stages(file_bytes, filename)
        except Exception as e:
            # Top-level fallback: try AI vision if OCR/parsing failed entirely
            return self._try_ai_vision_fallback(file_bytes, e)

    # ── Internal orchestration ─────────────────────────────────────────────────

    def _run_stages(self, file_bytes: bytes, filename: str) -> Optional[dict[str, Any]]:
        # Stage 1: Source Detection
        source = self._stage_source_detection(filename, file_bytes)
        if self._should_stop(1):
            return {"_debug_source": source.value}

        # Stage 2: Content Extraction (branches by source type)
        if source == ReceiptSource.EPARAGON:
            data = self._stage_eparagon_parse(file_bytes)
            if self._should_stop(2):
                return data
            # e-Paragon skips merchant detection and parsing — go to categorize/validate
            data = self._maybe_categorize(data)
            data = self._stage_validation(data)
            return data

        lines, raw_text = self._stage_content_extraction(file_bytes, source)
        if self._should_stop(2):
            return {"_debug_lines": lines, "_debug_raw_text_length": len(raw_text or "")}

        # Stage 3: Merchant Detection
        merchant = self._stage_merchant_detection(lines)
        if self._should_stop(3):
            return {"_debug_merchant": merchant, "_debug_lines_count": len(lines)}

        # Stage 4: Parsing
        data = self._stage_parsing(lines, merchant, source)
        if self._should_stop(4):
            return data

        # Stage 5: Categorization
        data = self._maybe_categorize(data)
        if self._should_stop(5):
            return data

        # Stage 6: Validation
        data = self._stage_validation(data)

        # Attach metadata for API consumers
        if data is not None:
            data["_raw_ocr_text"] = raw_text
            data["_reconstructed_lines"] = lines if lines else None

        return data

    def _should_stop(self, current_stage: int) -> bool:
        return self.max_stage is not None and current_stage >= self.max_stage

    # ── Stage 1: Source Detection ──────────────────────────────────────────────

    def _stage_source_detection(
        self, filename: str, file_bytes: bytes
    ) -> ReceiptSource:
        with self.logger.stage("source_detection", {
            "filename": filename,
            "size_bytes": len(file_bytes),
            "magic_bytes_hex": file_bytes[:4].hex() if file_bytes else "",
        }) as log:
            source = ReceiptSourceDetector.detect(
                filename=filename, file_bytes=file_bytes
            )
            log.output_summary = {"source": source.value}
            log.route_chosen = source.value
            return source

    # ── Stage 2a: E-Paragon Parse ──────────────────────────────────────────────

    def _stage_eparagon_parse(self, file_bytes: bytes) -> Optional[dict[str, Any]]:
        with self.logger.stage("content_extraction", {
            "source": "eparagon",
            "size_bytes": len(file_bytes),
        }) as log:
            log.route_chosen = "eparagon_json_adapter"
            data = EParagonJSONAdapter.parse(file_bytes)

            items = data.get("items", [])
            log.output_summary = {
                "merchant": data.get("merchant_name"),
                "date": data.get("date"),
                "total": data.get("total_amount"),
                "items_count": len(items),
            }
            self.logger.detail_items(items)
            return data

    # ── Stage 2b: Content Extraction (PDF / Image) ─────────────────────────────

    def _stage_content_extraction(
        self, file_bytes: bytes, source: ReceiptSource
    ) -> tuple[list[str], Optional[str]]:
        with self.logger.stage("content_extraction", {
            "source": source.value,
            "size_bytes": len(file_bytes),
        }) as log:
            if source == ReceiptSource.PDF_TEXT:
                return self._extract_pdf(file_bytes, log)
            else:
                return self._extract_image(file_bytes, source, log)

    def _extract_pdf(
        self, file_bytes: bytes, log: Any
    ) -> tuple[list[str], Optional[str]]:
        has_text = PDFTextLayerAdapter.has_text_layer(file_bytes)
        self.logger.detail(f"PDF text layer: {'YES' if has_text else 'NO'}")

        if has_text:
            log.route_chosen = "pdf_text_layer"
            text = PDFTextLayerAdapter.extract_text(file_bytes)
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            log.output_summary = {
                "method": "pymupdf_text_layer",
                "lines_count": len(lines),
                "raw_text_length": len(text),
            }
            self.logger.detail_lines("Extracted lines", lines)
            return lines, text
        else:
            log.route_chosen = "pdf_render_then_ocr"
            self.logger.detail("Rendering PDF page to PNG…")
            png_bytes = PDFTextLayerAdapter.convert_to_image(file_bytes)
            self.logger.detail(f"Rendered PNG: {len(png_bytes)} bytes")
            return self._run_ocr_and_reconstruct(png_bytes, ReceiptSource.PDF_TEXT, log)

    def _extract_image(
        self, file_bytes: bytes, source: ReceiptSource, log: Any
    ) -> tuple[list[str], Optional[str]]:
        log.route_chosen = "google_vision_ocr"
        return self._run_ocr_and_reconstruct(file_bytes, source, log)

    def _run_ocr_and_reconstruct(
        self, image_bytes: bytes, source: ReceiptSource, log: Any
    ) -> tuple[list[str], Optional[str]]:
        ocr = GoogleVisionOCRService()

        result = ocr.extract(image_bytes)
        self.logger.detail(f"OCR words: {len(result.words)}, engine: {result.source_engine}")

        lines = reconstruct_lines(result.words, source=source)
        log.output_summary = {
            "method": log.route_chosen or "google_vision_ocr",
            "ocr_words_count": len(result.words),
            "lines_count": len(lines),
            "raw_text_length": len(result.raw_text),
        }
        self.logger.detail_lines("Reconstructed lines", lines)
        return lines, result.raw_text

    # ── Stage 3: Merchant Detection ────────────────────────────────────────────

    def _stage_merchant_detection(self, lines: list[str]) -> Optional[str]:
        with self.logger.stage("merchant_detection", {
            "lines_count": len(lines),
            "header_lines_checked": min(len(lines), 30),
        }) as log:
            merchant = detect_merchant(lines)
            log.output_summary = {
                "merchant": merchant or "unknown",
                "has_deterministic_parser": merchant in ("lidl",),
            }
            if merchant:
                log.route_chosen = f"merchant_{merchant}"
            else:
                log.route_chosen = "unknown_merchant"
            return merchant

    # ── Stage 4: Parsing ───────────────────────────────────────────────────────

    def _stage_parsing(
        self,
        lines: list[str],
        merchant: Optional[str],
        source: ReceiptSource,
    ) -> Optional[dict[str, Any]]:
        with self.logger.stage("parsing", {
            "merchant": merchant or "unknown",
            "source": source.value,
            "lines_count": len(lines),
        }) as log:
            # Known merchant with deterministic parser
            if merchant == "lidl":
                return self._parse_lidl(lines, source, log)

            # Camera photo with unknown merchant → AI structurizer
            if source == ReceiptSource.PHOTO_IMAGE:
                log.route_chosen = "ai_structurizer_photo"
                return self._parse_with_ai(lines, log, "Camera photo, unknown merchant")

            # App export / PDF with unknown merchant → AI structurizer
            log.route_chosen = "ai_structurizer_fallback"
            return self._parse_with_ai(lines, log, "Unknown merchant format")

    def _parse_lidl(
        self, lines: list[str], source: ReceiptSource, log: Any
    ) -> Optional[dict[str, Any]]:
        from .lidl_parser import LidlReceiptParser

        log.route_chosen = "lidl_deterministic_parser"
        parsed = LidlReceiptParser().parse(lines)
        data = parsed.to_dict()

        items = data.get("items", [])
        log.output_summary = {
            "parser": "LidlReceiptParser",
            "merchant": data.get("merchant_name"),
            "date": data.get("date"),
            "total": data.get("total_amount"),
            "items_count": len(items),
        }
        self.logger.detail_items(items)

        # For camera photos, validate deterministic result — fall back to AI if bad
        if source == ReceiptSource.PHOTO_IMAGE:
            self.logger.detail("Photo source — validating deterministic result…")
            val_result = self._run_validation(data)
            validation = val_result.get("_validation", {}) if val_result else {}

            if not validation.get("is_valid", True) or validation.get("issues"):
                self.logger.detail(
                    f"⚠️ Validation failed: {validation.get('message', '?')}. "
                    "Falling back to AI structurizer."
                )
                log.route_chosen = "lidl_parser_failed_photo→ai_structurizer"
                return self._parse_with_ai(lines, log, "Lidl parser failed validation on photo")

        return data

    def _parse_with_ai(
        self, lines: list[str], log: Any, reason: str
    ) -> Optional[dict[str, Any]]:
        text = "\n".join(lines)

        if self.no_ai or not self.ai.structurize:
            log.status = "NO_AI"
            log.output_summary = {
                "reason": f"AI skipped ({reason})",
                "text_length": len(text),
                "_raw_text_for_ai": text[:500],
            }
            self.logger.detail(f"🚫 AI structurizer skipped: {reason}")
            # Return stub so validation can still run
            return {
                "merchant_name": "unknown",
                "date": "",
                "total_amount": 0,
                "currency": "PLN",
                "items": [],
                "_ai_skipped": True,
                "_raw_text_for_ai": text,
            }

        self.logger.detail(f"🧠 Calling AI structurizer ({len(text)} chars)…")
        data = self.ai.structurize(text)

        if data:
            items = data.get("items", [])
            log.output_summary = {
                "parser": "ai_structurizer",
                "merchant": data.get("merchant_name"),
                "date": data.get("date"),
                "total": data.get("total_amount"),
                "items_count": len(items),
            }
            self.logger.detail_items(items)
        else:
            log.status = "FAIL"
            log.output_summary = {"error": "AI structurizer returned None"}

        return data

    # ── Stage 5: Categorization ────────────────────────────────────────────────

    def _maybe_categorize(
        self, data: Optional[dict[str, Any]]
    ) -> Optional[dict[str, Any]]:
        if self.no_ai or not self.ai.categorize:
            with self.logger.stage("categorization") as log:
                log.status = "NO_AI" if self.no_ai else "SKIP"
                log.output_summary = {
                    "reason": "--no-ai flag" if self.no_ai else "no categorize callback",
                }
            return data

        with self.logger.stage("categorization", {
            "items_count": len(data.get("items", [])) if data else 0,
        }) as log:
            result = self.ai.categorize(data)
            if result:
                categorized = sum(
                    1 for i in result.get("items", []) if i.get("category")
                )
                log.output_summary = {
                    "categorized_count": categorized,
                    "total_items": len(result.get("items", [])),
                }
            return result

    # ── Stage 6: Validation ────────────────────────────────────────────────────

    def _stage_validation(
        self, data: Optional[dict[str, Any]]
    ) -> Optional[dict[str, Any]]:
        with self.logger.stage("validation", {
            "has_data": data is not None,
            "items_count": len(data.get("items", [])) if data else 0,
        }) as log:
            if data is None:
                log.status = "FAIL"
                log.output_summary = {"error": "No data to validate (upstream stage returned None)"}
                return None

            result = self._run_validation(data)
            validation = result.get("_validation", {}) if result else {}

            log.output_summary = {
                "is_valid": validation.get("is_valid"),
                "confidence": validation.get("confidence"),
                "issues": validation.get("issues", []),
                "message": validation.get("message"),
            }

            if validation.get("issues"):
                log.status = "FAIL" if not validation.get("is_valid") else "OK"
                self.logger.detail(f"Issues: {validation.get('message', '?')}")

            # Log sum comparison
            items = data.get("items", [])
            if items:
                items_sum = sum(
                    float(i.get("price", 0)) * float(i.get("quantity", 1))
                    for i in items
                )
                self.logger.detail(
                    f"Sum check: items_sum={items_sum:.2f} vs total={data.get('total_amount', 0):.2f}"
                )

            return result

    def _run_validation(self, data: dict[str, Any]) -> dict[str, Any]:
        """Run ReceiptValidator and attach _validation metadata."""
        ocr_total = Decimal(str(data.get("total_amount", 0)))
        result = ReceiptValidator().validate(data, ocr_total)

        data["_validation"] = {
            "is_valid": result.is_valid,
            "issues": [i.value for i in result.issues],
            "confidence": result.confidence,
            "message": result.message,
        }
        return data

    # ── AI Vision Fallback (top-level exception handler) ───────────────────────

    def _try_ai_vision_fallback(
        self, file_bytes: bytes, original_error: Exception
    ) -> Optional[dict[str, Any]]:
        if self.no_ai or not self.ai.vision_fallback:
            self.logger.detail(f"❌ Pipeline failed: {original_error}")
            if self.no_ai:
                self.logger.detail("🚫 AI vision fallback skipped (--no-ai)")
            return None

        with self.logger.stage("ai_vision_fallback", {
            "original_error": str(original_error),
        }) as log:
            log.route_chosen = "ai_vision_direct"
            self.logger.detail(f"⚠️ OCR/pipeline failed: {original_error}")
            self.logger.detail("Attempting direct AI vision fallback…")

            try:
                data = self.ai.vision_fallback(file_bytes)
                if data:
                    data = self._maybe_categorize(data)
                    data = self._stage_validation(data)
                    log.output_summary = {"result": "success"}
                else:
                    log.status = "FAIL"
                    log.output_summary = {"result": "ai_returned_none"}
                return data
            except Exception as inner_e:
                log.status = "FAIL"
                log.error = str(inner_e)
                log.output_summary = {"result": "fallback_also_failed"}
                return None
