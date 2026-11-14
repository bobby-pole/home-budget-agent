# Connector Conformance Fixtures & Retention Policy (#259)

Synthetic, anonymized fixtures used by `backend/tests/test_adapter_conformance.py`
to validate all `ReceiptSourceAdapter` and `TransactionSourceAdapter` contracts.

## Anonymization Rules

All fixtures committed to this repository MUST follow these anonymization rules:

1. **No real personal identifiers (PII):** Merchant users, cashiers, and bank
   counterparties use synthetic placeholders (e.g., `Synthetic Test Sp. z o.o.`,
   `Jan Kowalski Demo`, `Sklep Testowy 001`).
2. **No real bank account numbers or card PANs:** Bank statements and receipts
   must never contain valid Polish NRB/IBANs (`PL...`) or unmasked PAN digits;
   use truncated or synthetic placeholders such as `PL00000000000000000000000000`.
3. **No real tax identifiers (NIP):** Omit or replace with clearly synthetic
   test values (`0000000000`).
4. **No secrets or bearer tokens:** External merchant API responses must never
   include real OAuth tokens, cookies, device IDs, or loyalty barcodes.
5. **Shifted synthetic timestamps:** Dates use fixed synthetic values
   (e.g., `2026-04-12`).

## Raw Payload Retention Rules (`RawPayloadPolicy`)

Each `SourceRecord` records how raw ingested material is retained or discarded:

| Policy | Channels | Retention Behavior |
|---|---|---|
| `NONE` | `ing_csv`, `ing_pdf`, bank statements | Uploaded statement bytes are parsed in memory and discarded immediately; only canonical transactions and SHA-256 `canonical_hash` are stored. |
| `CANONICAL_ONLY` | `lidl_plus`, `eparagon_json` | Provider payloads are normalized synchronously into `CanonicalReceipt` + `TransactionLine`; unnormalized raw vendor JSON is not persisted. |
| `EPHEMERAL_IMAGE` | `receipt_upload` (OCR/PDF) | Original receipt upload is kept temporarily on disk strictly for verification/debugging and subject to archival cleanup; provenance tracks hash and quality score. |

## Conformance Scenarios

Every adapter family verifies five canonical behaviors:
- `success`: Valid canonical extraction with expected items/cashflows and high `quality`.
- `duplicate`: Repeated ingestion yields idempotent skip without creating duplicate rows.
- `partial_data`: Missing optional metadata (store code, merchant header, counterparty) emits `PARTIAL_*` warnings and degrades `quality` quantitatively (`Decimal`).
- `schema_drift`: Unknown or extra vendor fields/columns emit `SCHEMA_DRIFT:*` warnings (or `AdapterSchemaError` when required structure breaks).
- `invalid_totals` / `invalid_rows`: Arithmetic mismatch (> `0.01`) sets `validation_status="needs_review"` with `TOTAL_MISMATCH` warning; malformed statement rows emit explicit warnings without corrupting valid entries.
