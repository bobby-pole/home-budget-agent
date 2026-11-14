"""Bank statement adapters implementing ``TransactionSourceAdapter`` only (#259).

Bank CSV and bank PDF adapters MUST NOT implement ``ReceiptSourceAdapter`` —
statement cashflows normalize into ``CanonicalTransaction`` and reconcile
against receipts inside the Import Inbox rather than fabricating store items.
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from pypdf import PdfReader

from app.adapters.contracts import (
    AdapterParseError,
    AdapterSchemaError,
    CanonicalTransaction,
    SourceProvenanceSpec,
    TransactionAdapterResult,
    TransactionBatchAdapterResult,
    TransactionSourceAdapter,
    degrade_quality,
)
from app.models import RawPayloadPolicy, SourceType
from app.money import format_money, quantize_money, quantize_score

_ING_CSV_COLUMN_SYNONYMS: dict[str, list[str]] = {
    "date": ["Data transakcji", "Transaction date", "Data"],
    "merchant": ["Dane kontrahenta", "Contractor details", "Kontrahent"],
    "title": ["Tytuł", "Title", "Opis"],
    "amount": ["Kwota transakcji (waluta)", "Transaction amount", "Kwota"],
    "currency": ["Waluta", "Currency"],
}

_KNOWN_ING_CSV_HEADERS_LOWER = frozenset(
    {
        "data transakcji",
        "transaction date",
        "data",
        "data księgowania",
        "posting date",
        "dane kontrahenta",
        "contractor details",
        "kontrahent",
        "tytuł",
        "title",
        "opis",
        "szczegóły",
        "details",
        "nr transakcji",
        "transaction number",
        "kwota transakcji (waluta)",
        "transaction amount",
        "kwota",
        "waluta",
        "currency",
        "konto",
        "account",
        "kwota blokady/zwolnienie blokady",
        "kwota płatności w walucie",
        "saldo po transakcji",
    }
)


def parse_ing_pdf_text(text: str) -> list[dict]:
    """Robust multiline parser for ING individual bank statements.

    Refined to strictly separate Contractor, Title, and Amount.
    """
    transactions: list[dict] = []

    # 1. Pattern starts with two dates (DD.MM.YYYY)
    # 2. Mid text is captured lazily
    # 3. Amount is strictly matched: optional minus, 1-3 digits, spaced thousands, decimal, PLN.
    pattern = re.compile(
        r"(\d{2}\.\d{2}\.\d{4})\s+(\d{2}\.\d{2}\.\d{4})\s+(.*?)\s+(-?\d{1,3}(?:[\s\xa0]\d{3})*[.,]\d{2})\s+PLN",
        re.DOTALL | re.MULTILINE,
    )

    noise_patterns = [
        r"^\d{8}-\d+.*",
        r"^\d{10,}.*",
        r"^\d{2}[\s\xa0]\d{4}.*",
        r"^Nazwa i adres.*",
        r"^Data księgowania.*",
        r"^Szczegóły / nr.*",
        r"^(TR\.KART|TR\.BLIK|PRZELEW|P\.BLIK|ST\.ZLEC)$",
    ]

    for match in pattern.finditer(text):
        date_str, _posting_date, mid_text, amount_str = match.groups()

        try:
            amount = quantize_money(amount_str)
        except ValueError:
            continue

        try:
            d_parts = date_str.split(".")
            iso_date = f"{d_parts[2]}-{d_parts[1]}-{d_parts[0]}"
        except IndexError:
            continue

        lines = [line.strip() for line in mid_text.split("\n") if line.strip()]
        clean_lines: list[str] = []
        for line in lines:
            is_noise = any(re.match(p, line, re.IGNORECASE) for p in noise_patterns)
            if not is_noise:
                cleaned = re.sub(
                    r"Nazwa i adres (odbiorcy|płatnika):\s*",
                    "",
                    line,
                    flags=re.IGNORECASE,
                ).strip()
                if cleaned:
                    clean_lines.append(cleaned)

        if not clean_lines:
            merchant = "Przelew/Transakcja"
            title = mid_text.strip().replace("\n", " ")[:100]
        else:
            merchant = clean_lines[0]
            title = " ".join(clean_lines[1:]) if len(clean_lines) > 1 else merchant

        transactions.append(
            {
                "date": iso_date,
                "merchant": merchant[:100],
                "title": title[:200],
                "amount": amount,
                "currency": "PLN",
            }
        )

    return transactions


def _parse_bank_date(date_str: str) -> Optional[datetime]:
    """Parse common ING bank date formats into timezone-aware UTC midnight."""
    clean = (date_str or "").strip()
    if not clean:
        return None
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(clean, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _compute_bank_row_hash(date_str: str, amount: Decimal, merchant: str, title: str) -> str:
    """Compute canonical bank cashflow hash compatible with legacy ``import_transactions``."""
    raw_hash = f"{date_str}_{format_money(amount)}_{merchant}_{title}".strip()
    return hashlib.sha256(raw_hash.encode("utf-8")).hexdigest()


def _find_csv_column(headers: list[str], targets: list[str]) -> Optional[str]:
    lowered_headers = [(header, header.lower()) for header in headers]
    for target in targets:
        target_lower = target.lower()
        for header, header_lower in lowered_headers:
            if target_lower in header_lower:
                return header
    return None


class IngCsvTransactionAdapter(TransactionSourceAdapter):
    """Bank statement adapter for ING CSV exports."""

    provider = "ing_csv"
    source_type = SourceType.BANK_CSV
    adapter_version = "ing_csv_v1"

    def extract_transactions(
        self,
        payload: bytes,
        *,
        budget_id: int,
        connection_id: Optional[int] = None,
        filename: str = "",
        raw_payload_policy: RawPayloadPolicy = RawPayloadPolicy.NONE,
    ) -> TransactionBatchAdapterResult:
        if not isinstance(payload, bytes) or not payload:
            raise AdapterParseError("CSV payload must be non-empty bytes")

        text_content = ""
        for encoding in ("utf-8-sig", "utf-8", "windows-1250", "iso-8859-2"):
            try:
                text_content = payload.decode(encoding)
                break
            except UnicodeDecodeError:
                continue

        if not text_content.strip():
            raise AdapterParseError("Could not decode CSV file. Use UTF-8 or Windows-1250.")

        sample = text_content[:2000]
        try:
            dialect = csv.Sniffer().sniff(sample) if len(text_content) > 10 else "excel"
        except Exception:
            dialect = "excel"

        reader = csv.DictReader(io.StringIO(text_content), dialect=dialect)
        headers = [h for h in (reader.fieldnames or []) if h is not None]
        if not headers:
            raise AdapterSchemaError("CSV file has no header row")

        mapped = {k: _find_csv_column(headers, targets) for k, targets in _ING_CSV_COLUMN_SYNONYMS.items()}
        if not mapped["date"] or not mapped["amount"]:
            raise AdapterSchemaError(f"Required columns not found. Headers: {headers}")

        batch_warnings: list[str] = []
        base_quality = Decimal("0.9500")

        unknown_headers = [
            h.strip()
            for h in headers
            if h.strip() and h.strip().lower() not in _KNOWN_ING_CSV_HEADERS_LOWER
        ]
        if unknown_headers:
            batch_warnings.append(f"SCHEMA_DRIFT:{','.join(sorted(unknown_headers))}")
            base_quality = degrade_quality(base_quality, "0.0500")

        if not mapped["merchant"] or not mapped["title"]:
            batch_warnings.append("PARTIAL_STATEMENT_COLUMNS")
            base_quality = degrade_quality(base_quality, "0.0500")

        # Keep row-level parse errors out of subsequent rows' warnings.
        schema_warnings = list(batch_warnings)
        items: list[TransactionAdapterResult] = []
        acquired_at = datetime.now(timezone.utc)

        for idx, row in enumerate(reader, start=1):
            date_str = str(row.get(mapped["date"]) or "").strip()
            amount_raw = row.get(mapped["amount"])
            if not date_str or amount_raw is None or not str(amount_raw).strip():
                continue

            try:
                amount = quantize_money(str(amount_raw).strip())
            except (ValueError, TypeError):
                batch_warnings.append(f"MALFORMED_AMOUNT:row_{idx}")
                continue

            booked_at = _parse_bank_date(date_str)
            if booked_at is None:
                batch_warnings.append(f"MALFORMED_DATE:row_{idx}")
                continue

            merchant = str(row.get(mapped["merchant"]) or "") if mapped["merchant"] else ""
            title = str(row.get(mapped["title"]) or "") if mapped["title"] else ""
            currency = (
                str(row.get(mapped["currency"]) or "PLN").strip() or "PLN"
                if mapped["currency"]
                else "PLN"
            )

            row_warnings = list(schema_warnings)
            row_quality = base_quality
            if not merchant.strip() and not title.strip():
                row_warnings.append("PARTIAL_COUNTERPARTY_DESCRIPTION")
                row_quality = degrade_quality(row_quality, "0.1000")

            row_hash = _compute_bank_row_hash(date_str, amount, merchant, title)
            canonical_tx = CanonicalTransaction(
                booked_at=booked_at,
                amount=amount,
                currency=currency,
                counterparty=merchant,
                title=title,
            )
            provenance = SourceProvenanceSpec(
                source_type=self.source_type,
                provider=self.provider,
                external_id=None,
                canonical_hash=row_hash,
                adapter_version=self.adapter_version,
                acquired_at=acquired_at,
                raw_payload_policy=raw_payload_policy,
                connection_id=connection_id,
            )
            items.append(
                TransactionAdapterResult(
                    transaction=canonical_tx,
                    provenance=provenance,
                    warnings=row_warnings,
                    quality=quantize_score(row_quality),
                )
            )

        return TransactionBatchAdapterResult(items=items, warnings=batch_warnings)


class IngPdfTransactionAdapter(TransactionSourceAdapter):
    """Bank statement adapter for ING PDF exports."""

    provider = "ing_pdf"
    source_type = SourceType.BANK_CSV
    adapter_version = "ing_pdf_v1"

    def extract_transactions(
        self,
        payload: bytes,
        *,
        budget_id: int,
        connection_id: Optional[int] = None,
        filename: str = "",
        raw_payload_policy: RawPayloadPolicy = RawPayloadPolicy.NONE,
    ) -> TransactionBatchAdapterResult:
        if not isinstance(payload, bytes) or not payload:
            raise AdapterParseError("PDF payload must be non-empty bytes")

        try:
            reader = PdfReader(io.BytesIO(payload))
            full_text = "\n".join((page.extract_text() or "") for page in reader.pages)
        except Exception as err:
            raise AdapterParseError(f"Failed to parse PDF: {err}") from err

        return self.extract_from_text(
            full_text,
            budget_id=budget_id,
            connection_id=connection_id,
            raw_payload_policy=raw_payload_policy,
        )

    def extract_from_text(
        self,
        text: str,
        *,
        budget_id: int,
        connection_id: Optional[int] = None,
        raw_payload_policy: RawPayloadPolicy = RawPayloadPolicy.NONE,
    ) -> TransactionBatchAdapterResult:
        """Normalize already-extracted ING PDF statement text into ``TransactionBatchAdapterResult``."""
        extracted_rows = parse_ing_pdf_text(text)
        batch_warnings: list[str] = []
        items: list[TransactionAdapterResult] = []
        acquired_at = datetime.now(timezone.utc)

        if not extracted_rows and text.strip():
            batch_warnings.append("SCHEMA_DRIFT_OR_UNRECOGNIZED_STATEMENT")

        for row in extracted_rows:
            date_str = str(row["date"])
            merchant = str(row["merchant"])
            title = str(row["title"])
            amount = quantize_money(row["amount"])
            currency = str(row.get("currency") or "PLN")

            booked_at = _parse_bank_date(date_str)
            if booked_at is None:
                batch_warnings.append("MALFORMED_PDF_DATE")
                continue

            row_warnings: list[str] = []
            row_quality = Decimal("0.9500")
            if merchant == "Przelew/Transakcja":
                row_warnings.append("PARTIAL_COUNTERPARTY_FALLBACK")
                row_quality = degrade_quality(row_quality, "0.1000")

            row_hash = _compute_bank_row_hash(date_str, amount, merchant, title)
            canonical_tx = CanonicalTransaction(
                booked_at=booked_at,
                amount=amount,
                currency=currency,
                counterparty=merchant,
                title=title,
            )
            provenance = SourceProvenanceSpec(
                source_type=self.source_type,
                provider=self.provider,
                external_id=None,
                canonical_hash=row_hash,
                adapter_version=self.adapter_version,
                acquired_at=acquired_at,
                raw_payload_policy=raw_payload_policy,
                connection_id=connection_id,
            )
            items.append(
                TransactionAdapterResult(
                    transaction=canonical_tx,
                    provenance=provenance,
                    warnings=row_warnings,
                    quality=quantize_score(row_quality),
                )
            )

        return TransactionBatchAdapterResult(items=items, warnings=batch_warnings)
