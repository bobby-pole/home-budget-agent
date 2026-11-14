"""Receipt source adapters implementing ``ReceiptSourceAdapter`` (#259).

Covers:
- ``LidlPlusReceiptAdapter`` (``SourceType.MERCHANT_API``, ``lidl_plus``)
- ``EParagonReceiptAdapter`` (``SourceType.E_RECEIPT``, ``eparagon_json``)
- ``OcrPipelineReceiptAdapter`` (``SourceType.OCR_PHOTO``, ``receipt_upload``)
"""

from __future__ import annotations

import base64
import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Callable, Optional

from app.adapters.contracts import (
    AdapterParseError,
    AdapterSchemaError,
    ReceiptAdapterResult,
    ReceiptSourceAdapter,
    SourceProvenanceSpec,
    degrade_quality,
)
from app.adapters.lidl_poc_client import TicketMappingError, lidl_ticket_to_canonical
from app.models import RawPayloadPolicy, SourceType
from app.money import quantize_score
from app.ocr_pipeline import EParagonJSONAdapter
from app.pipeline_logger import PipelineLogger
from app.pipeline_runner import AICallbacks, PipelineRunner
from app.provenance_service import (
    compute_canonical_hash,
    extract_eparagon_external_id,
    normalize_external_id,
)
from app.receipt_schema import CanonicalReceipt
from app.receipt_validator import ReceiptValidator, ValidationIssue

_TOTAL_TOLERANCE = Decimal("0.01")

_KNOWN_LIDL_KEYS = frozenset(
    {
        "id",
        "date",
        "storeCode",
        "store",
        "totalAmount",
        "totalAmountNumeric",
        "itemsLine",
        "htmlPrintedReceipt",
        "ticketType",
        "couponsUsed",
        "ticket",
        "payments",
        "currency",
        "barCode",
        "fiscalNumber",
        "sequenceNumber",
        "workstation",
        "totalTaxes",
    }
)

_KNOWN_EPARAGON_DOC_KEYS = frozenset(
    {
        "naglowek",
        "podmiot1",
        "paragon",
        "protoVersion",
        "dokument",
        "document",
        "documentId",
        "stopka",
    }
)

_KNOWN_EPARAGON_PARAGON_KEYS = frozenset(
    {
        "zakSprzed",
        "total",
        "podsum",
        "pozycja",
        "opak",
        "nrDok",
        "nrKasy",
        "kasjer",
        "platnosci",
        "rabat",
        "waluta",
    }
)


class LidlMappingSchemaError(AdapterSchemaError, TicketMappingError):
    """Raised when a Lidl Plus payload fails schema validation."""


def _assess_receipt_totals_and_validation(
    receipt: CanonicalReceipt,
    *,
    base_quality: Decimal,
    warnings: list[str],
    validation_payload: Optional[dict[str, Any]] = None,
) -> tuple[str, Optional[str], Decimal]:
    """Validate receipt math and map issues into validation status and quality score."""
    quality = quantize_score(base_quality)
    validation_status = "verified"
    validation_message: Optional[str] = None

    val_info = validation_payload
    if val_info is None:
        receipt_dict = receipt.to_dict()
        v_res = ReceiptValidator().validate(receipt_dict, receipt.total_amount)
        val_info = {
            "is_valid": v_res.is_valid,
            "issues": [issue.value for issue in v_res.issues],
            "confidence": v_res.confidence,
            "message": v_res.message,
        }

    issues = list(val_info.get("issues") or [])
    is_valid = bool(val_info.get("is_valid", True))
    msg = val_info.get("message")

    diff = abs(receipt.calculated_total - receipt.total_amount)
    if diff > _TOTAL_TOLERANCE and ValidationIssue.TOTAL_MISMATCH.value not in issues:
        issues.append(ValidationIssue.TOTAL_MISMATCH.value)
        msg = msg or f"RECEIPT_SUM_MISMATCH:{diff:.2f}"

    if not is_valid:
        validation_status = "failed"
        validation_message = msg or "VALIDATION_FAILED"
        for issue_code in issues:
            if issue_code not in warnings:
                warnings.append(issue_code)
        return validation_status, validation_message, Decimal("0.0000")

    if ValidationIssue.TOTAL_MISMATCH.value in issues:
        validation_status = "needs_review"
        validation_message = msg or f"RECEIPT_SUM_MISMATCH:{diff:.2f}"
        warnings.append(f"TOTAL_MISMATCH:{diff:.2f}")
        denom = abs(receipt.total_amount) if receipt.total_amount > Decimal("0") else Decimal("1")
        ratio_score = max(Decimal("0.1000"), Decimal("1") - (diff / denom))
        capped = min(Decimal("0.7500"), quantize_score(ratio_score))
        quality = min(quality, capped)

    other_issues = [issue for issue in issues if issue != ValidationIssue.TOTAL_MISMATCH.value]
    if other_issues:
        if validation_status == "verified":
            validation_status = "needs_review"
            validation_message = validation_message or msg or str(other_issues[0])
        for issue_code in other_issues:
            if issue_code not in warnings:
                warnings.append(issue_code)

    val_conf = val_info.get("confidence")
    if val_conf is not None:
        try:
            conf_dec = max(Decimal("0"), min(Decimal("1"), Decimal(str(val_conf))))
            quality = min(quality, quantize_score(conf_dec))
            if conf_dec < Decimal("0.85") and validation_status == "verified":
                validation_status = "needs_review"
                validation_message = validation_message or "LOW_CONFIDENCE"
        except Exception:
            pass

    return validation_status, validation_message, quantize_score(quality)


class LidlPlusReceiptAdapter(ReceiptSourceAdapter):
    """Adapter mapping Lidl Plus v3 ticket payloads to ``ReceiptAdapterResult``."""

    provider = "lidl_plus"
    source_type = SourceType.MERCHANT_API
    adapter_version = "lidl_plus_v3"

    def extract(
        self,
        payload: Any,
        *,
        budget_id: int,
        connection_id: Optional[int] = None,
        filename: str = "",
        raw_payload_policy: Optional[RawPayloadPolicy] = None,
        ticket_id: Optional[str] = None,
    ) -> ReceiptAdapterResult:
        if not isinstance(payload, dict):
            raise LidlMappingSchemaError("Lidl ticket payload must be a JSON object")

        ticket_obj = (
            payload.get("ticket")
            if isinstance(payload.get("ticket"), dict)
            else payload
        )
        assert isinstance(ticket_obj, dict)

        try:
            canonical = lidl_ticket_to_canonical(payload)
        except TicketMappingError as err:
            raise LidlMappingSchemaError(str(err)) from err

        warnings: list[str] = []
        quality = Decimal("1.0000")

        unknown_keys = sorted(set(ticket_obj.keys()) - _KNOWN_LIDL_KEYS)
        if unknown_keys:
            warnings.append(f"SCHEMA_DRIFT:{','.join(unknown_keys)}")
            quality = degrade_quality(quality, "0.1000")

        raw_lines = ticket_obj.get("itemsLine")
        if (not isinstance(raw_lines, list) or not raw_lines) and ticket_obj.get("htmlPrintedReceipt"):
            warnings.append("PARTIAL_STRUCTURED_LINES:html_fallback")
            quality = degrade_quality(quality, "0.0500")

        has_store = bool(ticket_obj.get("storeCode") or ticket_obj.get("store"))
        if not has_store:
            warnings.append("PARTIAL_STORE_METADATA")
            quality = degrade_quality(quality, "0.1000")

        resolved_id = normalize_external_id(
            ticket_id or canonical.get("source_receipt_id") or ticket_obj.get("id")
        )
        if not resolved_id:
            warnings.append("MISSING_EXTERNAL_ID")
            quality = degrade_quality(quality, "0.1000")
            canonical_hash = compute_canonical_hash(payload)
        else:
            canonical_hash = compute_canonical_hash(f"lidl_plus:{budget_id}:{resolved_id}")

        validation_status, validation_message, final_quality = _assess_receipt_totals_and_validation(
            canonical,
            base_quality=quality,
            warnings=warnings,
        )
        # Preserve Lidl pre-check validation_error phrasing when present
        if canonical.get("validation_error"):
            validation_message = str(canonical["validation_error"])

        provenance = SourceProvenanceSpec(
            source_type=self.source_type,
            provider=self.provider,
            external_id=resolved_id,
            canonical_hash=canonical_hash,
            adapter_version=self.adapter_version,
            acquired_at=datetime.now(timezone.utc),
            raw_payload_policy=raw_payload_policy or RawPayloadPolicy.CANONICAL_ONLY,
            connection_id=connection_id,
        )
        return ReceiptAdapterResult(
            receipt=canonical,
            provenance=provenance,
            warnings=warnings,
            quality=final_quality,
            processed_via=self.adapter_version,
            validation_status=validation_status,
            validation_message=validation_message,
        )


def _decode_eparagon_jwt_payload(jwt_token: str) -> dict[str, Any]:
    """Decode the JSON object payload of a JPK e-Paragon JWT wrapper."""
    parts = jwt_token.split(".")
    if len(parts) < 2 or not parts[1].strip():
        raise AdapterParseError("Invalid e-Paragon JWT 'data' token format")
    segment = parts[1]
    rem = len(segment) % 4
    if rem:
        segment += "=" * (4 - rem)
    try:
        decoded_bytes = base64.urlsafe_b64decode(segment)
        inner = json.loads(decoded_bytes.decode("utf-8"))
    except Exception as err:
        raise AdapterParseError(f"Failed to decode e-Paragon JWT 'data' payload: {err}") from err
    if not isinstance(inner, dict):
        raise AdapterSchemaError("Decoded e-Paragon JWT payload must be a JSON object")
    return inner


class EParagonReceiptAdapter(ReceiptSourceAdapter):
    """Adapter mapping JPK / MF e-Paragon JSON payloads to ``ReceiptAdapterResult``."""

    provider = "eparagon_json"
    source_type = SourceType.E_RECEIPT
    adapter_version = "eparagon_v1"

    def extract(
        self,
        payload: Any,
        *,
        budget_id: int,
        connection_id: Optional[int] = None,
        filename: str = "eparagon.json",
        raw_payload_policy: Optional[RawPayloadPolicy] = None,
    ) -> ReceiptAdapterResult:
        if isinstance(payload, bytes):
            raw_bytes = payload
            try:
                decoded = json.loads(raw_bytes.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as err:
                raise AdapterParseError(f"Invalid e-Paragon JSON payload: {err}") from err
        elif isinstance(payload, dict):
            decoded = payload
            raw_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
        else:
            raise AdapterParseError("e-Paragon payload must be bytes or JSON dict")

        if not isinstance(decoded, dict):
            raise AdapterSchemaError("e-Paragon root must be a JSON object")

        is_jwt_wrapped = isinstance(decoded.get("data"), str)
        inner_decoded = _decode_eparagon_jwt_payload(decoded["data"]) if is_jwt_wrapped else decoded

        doc_raw = inner_decoded.get("dokument") or inner_decoded.get("document") or inner_decoded
        if isinstance(doc_raw, dict) and ("dokument" in doc_raw or "document" in doc_raw):
            doc_raw = doc_raw.get("dokument") or doc_raw.get("document")

        if not isinstance(doc_raw, dict) or not isinstance(doc_raw.get("paragon"), dict):
            raise AdapterSchemaError("e-Paragon payload missing required 'paragon' section")

        try:
            canonical = EParagonJSONAdapter.parse(raw_bytes)
        except AdapterParseError:
            raise
        except Exception as err:
            raise AdapterParseError(f"Failed to parse e-Paragon payload: {err}") from err

        warnings: list[str] = []
        quality = Decimal("1.0000")

        extra_outer = (set(decoded.keys()) - {"data"}) if is_jwt_wrapped else set()
        unknown_doc = set(doc_raw.keys()) - _KNOWN_EPARAGON_DOC_KEYS
        paragon_obj = doc_raw.get("paragon")
        unknown_paragon = (
            set(paragon_obj.keys()) - _KNOWN_EPARAGON_PARAGON_KEYS
            if isinstance(paragon_obj, dict)
            else set()
        )
        drifted = sorted(extra_outer | unknown_doc | unknown_paragon)
        if drifted:
            warnings.append(f"SCHEMA_DRIFT:{','.join(drifted)}")
            quality = degrade_quality(quality, "0.1000")

        if canonical.merchant_name in ("", "Unknown Merchant"):
            warnings.append("PARTIAL_MERCHANT_METADATA")
            quality = degrade_quality(quality, "0.1500")

        if not canonical.date:
            warnings.append("PARTIAL_DATE")
            quality = degrade_quality(quality, "0.1000")

        external_id = extract_eparagon_external_id(raw_bytes)
        if not external_id:
            warnings.append("MISSING_EXTERNAL_ID")
            quality = degrade_quality(quality, "0.0500")

        validation_status, validation_message, final_quality = _assess_receipt_totals_and_validation(
            canonical,
            base_quality=quality,
            warnings=warnings,
        )

        provenance = SourceProvenanceSpec(
            source_type=self.source_type,
            provider=self.provider,
            external_id=external_id,
            canonical_hash=compute_canonical_hash(raw_bytes),
            adapter_version=self.adapter_version,
            acquired_at=datetime.now(timezone.utc),
            raw_payload_policy=raw_payload_policy or RawPayloadPolicy.CANONICAL_ONLY,
            connection_id=connection_id,
        )
        return ReceiptAdapterResult(
            receipt=canonical,
            provenance=provenance,
            warnings=warnings,
            quality=final_quality,
            processed_via="eparagon_json_adapter",
            validation_status=validation_status,
            validation_message=validation_message,
        )


class OcrPipelineReceiptAdapter(ReceiptSourceAdapter):
    """Adapter wrapping ``PipelineRunner`` outputs into ``ReceiptAdapterResult``."""

    provider = "receipt_upload"
    source_type = SourceType.OCR_PHOTO
    adapter_version = "ocr_pipeline_v1"

    def __init__(
        self,
        *,
        no_ai: bool = True,
        ai_callbacks: Optional[AICallbacks] = None,
        runner_factory: Optional[Callable[[], PipelineRunner]] = None,
    ) -> None:
        self._no_ai = no_ai
        self._ai_callbacks = ai_callbacks
        self._runner_factory = runner_factory

    def extract(
        self,
        payload: Any,
        *,
        budget_id: int,
        connection_id: Optional[int] = None,
        filename: str = "receipt.pdf",
        raw_payload_policy: Optional[RawPayloadPolicy] = None,
    ) -> ReceiptAdapterResult:
        if not isinstance(payload, bytes) or not payload:
            raise AdapterParseError("Receipt bytes must be non-empty")

        runner = (
            self._runner_factory()
            if self._runner_factory is not None
            else PipelineRunner(
                logger=PipelineLogger(verbose=False),
                no_ai=self._no_ai,
                ai=self._ai_callbacks,
            )
        )
        data = runner.run(payload, filename or "receipt.pdf")
        if data is None:
            raise AdapterParseError("OCR/receipt pipeline returned no data")

        return self.from_pipeline_output(
            data,
            file_hash=compute_canonical_hash(payload),
            connection_id=connection_id,
            raw_payload_policy=raw_payload_policy or RawPayloadPolicy.EPHEMERAL_IMAGE,
        )

    @classmethod
    def from_pipeline_output(
        cls,
        data: dict[str, Any],
        *,
        file_hash: Optional[str] = None,
        connection_id: Optional[int] = None,
        raw_payload_policy: RawPayloadPolicy = RawPayloadPolicy.EPHEMERAL_IMAGE,
    ) -> ReceiptAdapterResult:
        """Convert an existing ``PipelineRunner`` dict into ``ReceiptAdapterResult``."""
        from app.receipt_schema import CanonicalItem

        warnings: list[str] = []
        raw_items = data.get("items") or []
        canonical_items: list[CanonicalItem] = []
        has_low_item_conf = False

        for item_raw in raw_items:
            if isinstance(item_raw, CanonicalItem):
                canonical_items.append(item_raw)
                continue
            orig_price = item_raw.get("original_price")
            raw_unit = (
                item_raw.get("unit_price")
                if item_raw.get("unit_price") is not None
                else item_raw.get("price", Decimal("0"))
            )
            unit_price = orig_price if orig_price is not None else raw_unit
            discount = item_raw.get("discount_total", Decimal("0"))
            item = CanonicalItem(
                name=str(item_raw.get("name") or "Unknown item"),
                unit_price=unit_price,
                quantity=item_raw.get("quantity", Decimal("1")),
                discount_total=discount,
                category=item_raw.get("category"),
                category_source=item_raw.get("category_source"),
                is_adjustment=bool(item_raw.get("is_adjustment", False)),
                original_price=orig_price,
            )
            if item_raw.get("confidence") is not None:
                try:
                    conf_dec = Decimal(str(item_raw["confidence"]))
                    item["confidence"] = conf_dec
                    if conf_dec < Decimal("0.85"):
                        has_low_item_conf = True
                except Exception:
                    pass
            canonical_items.append(item)

        merchant = str(data.get("merchant_name") or "Unknown").strip() or "Unknown"
        date_str = str(data.get("date") or "").strip()
        if merchant.lower() in ("unknown", "unknown merchant"):
            warnings.append("PARTIAL_MERCHANT_METADATA")
        if not date_str:
            warnings.append("PARTIAL_DATE")
        if data.get("_ai_skipped"):
            warnings.append("AI_STRUCTURIZER_SKIPPED")

        receipt = CanonicalReceipt(
            merchant_name=merchant,
            date=date_str,
            total_amount=data.get("total_amount", Decimal("0.00")),
            currency=str(data.get("currency") or "PLN"),
            items=canonical_items,
        )

        processed_via = data.get("_processed_via")
        is_eparagon = processed_via in (
            "eparagon_json_adapter",
            "biedronka_json_parser",
            "zabka_json_parser",
        )
        is_deterministic = bool(processed_via) and "ai_" not in str(processed_via)
        base_quality = (
            Decimal("1.0000")
            if is_eparagon
            else (Decimal("0.9500") if is_deterministic else Decimal("0.8500"))
        )
        if merchant.lower() in ("unknown", "unknown merchant"):
            base_quality = degrade_quality(base_quality, "0.1000")
        if not date_str:
            base_quality = degrade_quality(base_quality, "0.1000")
        if has_low_item_conf:
            warnings.append("LOW_ITEM_CONFIDENCE")
            base_quality = degrade_quality(base_quality, "0.1500")

        validation_status, validation_message, final_quality = _assess_receipt_totals_and_validation(
            receipt,
            base_quality=base_quality,
            warnings=warnings,
            validation_payload=data.get("_validation"),
        )
        if has_low_item_conf and validation_status == "verified":
            validation_status = "needs_review"
            validation_message = validation_message or "LOW_CONFIDENCE"

        provenance = SourceProvenanceSpec(
            source_type=cls.source_type,
            provider=cls.provider,
            external_id=None,
            canonical_hash=file_hash,
            adapter_version=cls.adapter_version,
            acquired_at=datetime.now(timezone.utc),
            raw_payload_policy=raw_payload_policy,
            connection_id=connection_id,
        )
        return ReceiptAdapterResult(
            receipt=receipt,
            provenance=provenance,
            warnings=warnings,
            quality=final_quality,
            processed_via=processed_via,
            validation_status=validation_status,
            validation_message=validation_message,
            raw_ocr_text=data.get("_raw_ocr_text"),
            reconstructed_lines=data.get("_reconstructed_lines"),
        )
