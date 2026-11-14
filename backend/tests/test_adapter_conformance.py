"""Connector conformance suite for dual source adapter contracts (#259)."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional

import pytest
from sqlmodel import Session, select

from app.adapters import (
    AdapterParseError,
    AdapterSchemaError,
    CanonicalTransaction,
    EParagonReceiptAdapter,
    IngCsvTransactionAdapter,
    IngPdfTransactionAdapter,
    LidlMappingSchemaError,
    LidlPlusReceiptAdapter,
    OcrPipelineReceiptAdapter,
    ReceiptAdapterResult,
    ReceiptSourceAdapter,
    SourceProvenanceSpec,
    TransactionAdapterResult,
    TransactionBatchAdapterResult,
    TransactionSourceAdapter,
)
from app.ingestion_service import ingest_receipt_result, ingest_transaction_batch
from app.models import (
    Budget,
    RawPayloadPolicy,
    ReceiptScan,
    ScanStatus,
    SourceRecord,
    SourceType,
    Transaction,
    TransactionLine,
    User,
)
from app.provenance_service import compute_canonical_hash
from app.receipt_schema import CanonicalItem, CanonicalReceipt

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "conformance"


def _load_json_fixture(channel: str, name: str) -> dict[str, Any]:
    return json.loads((FIXTURES_DIR / channel / f"{name}.json").read_text(encoding="utf-8"))


def _load_bytes_fixture(channel: str, filename: str) -> bytes:
    return (FIXTURES_DIR / channel / filename).read_bytes()


def _seed_user_and_budget(session: Session) -> tuple[User, Budget]:
    user = User(email="conformance@example.com", hashed_password="hashed_mock_password")
    session.add(user)
    session.commit()
    session.refresh(user)
    assert user.id is not None

    budget = Budget(name="Conformance Budget", owner_id=user.id)
    session.add(budget)
    session.commit()
    session.refresh(budget)
    assert budget.id is not None
    return user, budget


class _StubNewReceiptAdapter(ReceiptSourceAdapter):
    """Minimal synthetic receipt provider used to prove zero provider-specific commit code."""

    provider = "biedronka_api_stub"
    source_type = SourceType.MERCHANT_API
    adapter_version = "stub_v1"

    def extract(
        self,
        payload: Any,
        *,
        budget_id: int,
        connection_id: Optional[int] = None,
        filename: str = "",
        raw_payload_policy: Optional[RawPayloadPolicy] = None,
    ) -> ReceiptAdapterResult:
        receipt = CanonicalReceipt(
            merchant_name=payload["store"],
            date=payload["date"],
            total_amount=Decimal(payload["total"]),
            currency="PLN",
            items=[
                CanonicalItem(
                    name=row["name"],
                    unit_price=Decimal(row["price"]),
                    quantity=Decimal(row.get("qty", "1")),
                )
                for row in payload["items"]
            ],
        )
        return ReceiptAdapterResult(
            receipt=receipt,
            provenance=SourceProvenanceSpec(
                source_type=self.source_type,
                provider=self.provider,
                external_id=payload["receipt_id"],
                canonical_hash=compute_canonical_hash(payload),
                adapter_version=self.adapter_version,
                raw_payload_policy=raw_payload_policy or RawPayloadPolicy.CANONICAL_ONLY,
                connection_id=connection_id,
            ),
            warnings=[],
            quality=Decimal("1.0000"),
            processed_via=self.adapter_version,
            validation_status="verified",
        )


class _StubNewTransactionAdapter(TransactionSourceAdapter):
    """Minimal synthetic bank provider used to verify provider-agnostic bank ingestion."""

    provider = "mbank_csv_stub"
    source_type = SourceType.BANK_CSV
    adapter_version = "mbank_stub_v1"

    def extract_transactions(
        self,
        payload: bytes,
        *,
        budget_id: int,
        connection_id: Optional[int] = None,
        filename: str = "",
        raw_payload_policy: RawPayloadPolicy = RawPayloadPolicy.NONE,
    ) -> TransactionBatchAdapterResult:
        decoded = json.loads(payload.decode("utf-8"))
        items: list[TransactionAdapterResult] = []
        for row in decoded["rows"]:
            items.append(
                TransactionAdapterResult(
                    transaction=CanonicalTransaction(
                        booked_at=datetime.strptime(row["date"], "%Y-%m-%d").replace(tzinfo=timezone.utc),
                        amount=Decimal(row["amount"]),
                        currency="PLN",
                        counterparty=row["counterparty"],
                        title=row["title"],
                    ),
                    provenance=SourceProvenanceSpec(
                        source_type=self.source_type,
                        provider=self.provider,
                        external_id=row.get("external_id"),
                        canonical_hash=compute_canonical_hash(row),
                        adapter_version=self.adapter_version,
                        raw_payload_policy=raw_payload_policy,
                        connection_id=connection_id,
                    ),
                    warnings=[],
                    quality=Decimal("0.9800"),
                )
            )
        return TransactionBatchAdapterResult(items=items, warnings=[])


# ---------------------------------------------------------------------------
# 1. Dual Interface Separation & Value Object Invariants
# ---------------------------------------------------------------------------


def test_dual_adapter_contract_separation():
    receipt_adapters = (
        LidlPlusReceiptAdapter(),
        EParagonReceiptAdapter(),
        OcrPipelineReceiptAdapter(),
    )
    tx_adapters = (
        IngCsvTransactionAdapter(),
        IngPdfTransactionAdapter(),
    )

    for adapter in receipt_adapters:
        assert isinstance(adapter, ReceiptSourceAdapter)
        assert not isinstance(adapter, TransactionSourceAdapter)

    for adapter in tx_adapters:
        assert isinstance(adapter, TransactionSourceAdapter)
        assert not isinstance(adapter, ReceiptSourceAdapter)


def test_canonical_transaction_uses_decimal_and_utc_timestamps():
    tx = CanonicalTransaction(
        booked_at=datetime(2026, 4, 12, 8, 30),  # naive datetime gets UTC normalized
        amount=Decimal("-45.50"),
        currency="pln",
        counterparty="  Sklep Testowy  ",
        title="  Zakup karta  ",
    )
    assert isinstance(tx.amount, Decimal)
    assert isinstance(tx.abs_amount, Decimal)
    assert tx.amount == Decimal("-45.50")
    assert tx.abs_amount == Decimal("45.50")
    assert tx.direction == "debit"
    assert tx.currency == "PLN"
    assert tx.booked_at.tzinfo is not None

    inflow = CanonicalTransaction(booked_at=datetime(2026, 4, 13, tzinfo=timezone.utc), amount=Decimal("5200.00"))
    assert inflow.direction == "credit"


# ---------------------------------------------------------------------------
# 2. Fixture Anonymization & Retention Policy Documentation Audit
# ---------------------------------------------------------------------------


def test_conformance_fixtures_are_anonymized_and_retention_is_documented():
    readme_text = (FIXTURES_DIR / "README.md").read_text(encoding="utf-8")
    for required_token in ("NONE", "CANONICAL_ONLY", "EPHEMERAL_IMAGE", "Anonymization Rules"):
        assert required_token in readme_text

    real_iban_re = re.compile(r"\bPL(?!0{26})\d{26}\b")
    for fixture_file in FIXTURES_DIR.rglob("*"):
        if not fixture_file.is_file() or fixture_file.name == "README.md":
            continue
        content = fixture_file.read_text(encoding="utf-8")
        assert not real_iban_re.search(content), f"Real IBAN detected in {fixture_file}"
        assert "Bearer " not in content, f"Auth token detected in {fixture_file}"


# ---------------------------------------------------------------------------
# 3. Receipt Adapter Conformance Suite
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "channel,adapter_factory,loader",
    [
        ("lidl_plus", LidlPlusReceiptAdapter, lambda name: _load_json_fixture("lidl_plus", name)),
        ("eparagon", EParagonReceiptAdapter, lambda name: _load_bytes_fixture("eparagon", f"{name}.json")),
    ],
)
def test_receipt_adapter_conformance_scenarios(
    session: Session,
    channel: str,
    adapter_factory: type[ReceiptSourceAdapter],
    loader: Any,
):
    user, budget = _seed_user_and_budget(session)
    assert user.id is not None and budget.id is not None
    adapter = adapter_factory()

    # 1) success
    success_res = adapter.extract(loader("success"), budget_id=budget.id)
    assert success_res.validation_status == "verified"
    assert success_res.warnings == []
    assert isinstance(success_res.quality, Decimal)
    assert success_res.quality == Decimal("1.0000")
    assert success_res.provenance.external_id is not None

    outcome = ingest_receipt_result(
        session,
        success_res,
        budget_id=budget.id,
        user_id=user.id,
        categorize=False,
    )
    assert outcome.imported is True
    assert outcome.skipped is False

    # 2) duplicate (idempotent replay through shared commit path)
    replay_res = adapter.extract(loader("success"), budget_id=budget.id)
    replay_outcome = ingest_receipt_result(
        session,
        replay_res,
        budget_id=budget.id,
        user_id=user.id,
        categorize=False,
    )
    assert replay_outcome.imported is False
    assert replay_outcome.skipped is True
    assert len(session.exec(select(Transaction).where(Transaction.budget_id == budget.id)).all()) == 1
    assert len(session.exec(select(SourceRecord).where(SourceRecord.budget_id == budget.id)).all()) == 1

    # 3) partial_data (degrades quality & records warning without crashing)
    partial_res = adapter.extract(loader("partial_data"), budget_id=budget.id)
    assert any(w.startswith("PARTIAL_") for w in partial_res.warnings)
    assert partial_res.quality < Decimal("1.0000")

    # 4) schema_drift (unknown fields emit SCHEMA_DRIFT warning & degrade quality)
    drift_res = adapter.extract(loader("schema_drift"), budget_id=budget.id)
    assert any(w.startswith("SCHEMA_DRIFT:") for w in drift_res.warnings)
    assert drift_res.quality < Decimal("1.0000")

    # 5) invalid_totals (total mismatch marks needs_review, warns TOTAL_MISMATCH, degrades quality)
    invalid_res = adapter.extract(loader("invalid_totals"), budget_id=budget.id)
    assert invalid_res.validation_status == "needs_review"
    assert any(w.startswith("TOTAL_MISMATCH:") for w in invalid_res.warnings)
    assert invalid_res.quality <= Decimal("0.7500")

    invalid_outcome = ingest_receipt_result(
        session,
        invalid_res,
        budget_id=budget.id,
        user_id=user.id,
        categorize=False,
    )
    assert invalid_outcome.imported is True
    assert invalid_outcome.receipt_scan_id is not None
    scan = session.get(ReceiptScan, invalid_outcome.receipt_scan_id)
    assert scan is not None
    assert scan.status == ScanStatus.NEEDS_REVIEW
    assert scan.needs_review is True


def test_receipt_adapter_rejects_broken_schema():
    with pytest.raises(LidlMappingSchemaError):
        LidlPlusReceiptAdapter().extract("not-a-dict", budget_id=1)

    with pytest.raises(AdapterSchemaError):
        EParagonReceiptAdapter().extract({"unexpected": {}}, budget_id=1)

    with pytest.raises(AdapterParseError):
        EParagonReceiptAdapter().extract(b"{broken-json", budget_id=1)

    with pytest.raises(AdapterParseError):
        EParagonReceiptAdapter().extract({"data": "not-a-jwt"}, budget_id=1)


def test_eparagon_jwt_wrapped_unwraps_cleanly_without_false_schema_drift():
    import base64

    inner_payload = json.loads(_load_bytes_fixture("eparagon", "success.json").decode("utf-8"))
    header = base64.urlsafe_b64encode(b'{"alg":"none"}').decode("ascii").rstrip("=")
    body = base64.urlsafe_b64encode(json.dumps(inner_payload).encode("utf-8")).decode("ascii").rstrip("=")
    jwt_wrapped = json.dumps({"data": f"{header}.{body}.sig"}).encode("utf-8")

    res = EParagonReceiptAdapter().extract(jwt_wrapped, budget_id=1)
    assert res.validation_status == "verified"
    assert res.warnings == []
    assert res.quality == Decimal("1.0000")
    assert res.provenance.external_id == "0000000000:SYN-EP-0001"

    # Unknown keys inside decoded JWT payload ARE caught as schema drift
    drifted_inner = json.loads(_load_bytes_fixture("eparagon", "schema_drift.json").decode("utf-8"))
    drifted_body = base64.urlsafe_b64encode(json.dumps(drifted_inner).encode("utf-8")).decode("ascii").rstrip("=")
    jwt_drifted = json.dumps({"data": f"{header}.{drifted_body}.sig"}).encode("utf-8")
    drifted_res = EParagonReceiptAdapter().extract(jwt_drifted, budget_id=1)
    assert any(w.startswith("SCHEMA_DRIFT:") for w in drifted_res.warnings)
    assert drifted_res.quality < Decimal("1.0000")


def test_ocr_pipeline_receipt_adapter_conformance(session: Session):
    user, budget = _seed_user_and_budget(session)
    assert user.id is not None and budget.id is not None

    # success output from deterministic PDF/OCR pipeline
    ok_output = {
        "merchant_name": "Test Market",
        "date": "2026-04-12",
        "total_amount": Decimal("10.00"),
        "currency": "PLN",
        "items": [{"name": "Mleko", "unit_price": Decimal("5.00"), "quantity": Decimal("2")}],
        "_processed_via": "biedronka_deterministic",
        "_validation": {"is_valid": True, "issues": [], "confidence": 1.0, "message": None},
    }
    res_ok = OcrPipelineReceiptAdapter.from_pipeline_output(ok_output, file_hash="ocr-ok-hash-1")
    assert res_ok.validation_status == "verified"
    assert res_ok.quality == Decimal("0.9500")
    assert res_ok.provenance.raw_payload_policy == RawPayloadPolicy.EPHEMERAL_IMAGE

    # duplicate
    first = ingest_receipt_result(session, res_ok, budget_id=budget.id, user_id=user.id, categorize=False)
    second = ingest_receipt_result(session, res_ok, budget_id=budget.id, user_id=user.id, categorize=False)
    assert first.imported is True and second.skipped is True

    # partial_data + low item confidence + total mismatch
    bad_output = {
        "merchant_name": "",
        "date": "",
        "total_amount": Decimal("50.00"),
        "currency": "PLN",
        "items": [{"name": "Chleb", "unit_price": Decimal("5.00"), "quantity": Decimal("1"), "confidence": 0.60}],
        "_processed_via": "ai_vision_fallback",
        "_validation": {
            "is_valid": True,
            "issues": ["total_mismatch"],
            "confidence": 0.65,
            "message": "Sum mismatch",
        },
    }
    res_bad = OcrPipelineReceiptAdapter.from_pipeline_output(bad_output, file_hash="ocr-bad-hash-2")
    assert "PARTIAL_MERCHANT_METADATA" in res_bad.warnings
    assert "PARTIAL_DATE" in res_bad.warnings
    assert "LOW_ITEM_CONFIDENCE" in res_bad.warnings
    assert any(w.startswith("TOTAL_MISMATCH:") for w in res_bad.warnings)
    assert res_bad.validation_status == "needs_review"
    assert res_bad.quality <= Decimal("0.6500")

    # Explicit unit_price=None falls back to price without zeroing out line item
    none_unit_output = {
        "merchant_name": "Test Market",
        "date": "2026-04-12",
        "total_amount": Decimal("5.99"),
        "currency": "PLN",
        "items": [{"name": "Masło", "unit_price": None, "price": Decimal("5.99"), "quantity": Decimal("1")}],
        "_processed_via": "eparagon_json_adapter",
    }
    res_ep = OcrPipelineReceiptAdapter.from_pipeline_output(none_unit_output, file_hash="ep-hash-3")
    assert res_ep.receipt.items[0].unit_price == Decimal("5.99")
    assert res_ep.quality == Decimal("1.0000")
    assert res_ep.validation_status == "verified"

    # extract() validates non-empty bytes and delegates to runner_factory
    with pytest.raises(AdapterParseError):
        OcrPipelineReceiptAdapter().extract(b"", budget_id=budget.id)

    class _FakeRunner:
        def run(self, file_bytes: bytes, filename: str) -> dict[str, Any]:
            return ok_output

    extracted = OcrPipelineReceiptAdapter(runner_factory=lambda: _FakeRunner()).extract(  # type: ignore[arg-type]
        b"fake-pdf-bytes",
        budget_id=budget.id,
        filename="paragon.pdf",
    )
    assert extracted.validation_status == "verified"
    assert extracted.quality == Decimal("0.9500")


def test_new_receipt_and_transaction_providers_require_zero_commit_code(session: Session):
    user, budget = _seed_user_and_budget(session)
    assert user.id is not None and budget.id is not None

    stub_receipt = _StubNewReceiptAdapter().extract(
        {
            "receipt_id": "BIED-9901",
            "store": "Biedronka Test",
            "date": "2026-04-12",
            "total": "9.98",
            "items": [{"name": "Woda", "price": "4.99", "qty": "2"}],
        },
        budget_id=budget.id,
    )
    r_out = ingest_receipt_result(session, stub_receipt, budget_id=budget.id, user_id=user.id, categorize=False)
    assert r_out.imported is True
    assert r_out.transaction_id is not None
    lines = session.exec(select(TransactionLine).where(TransactionLine.transaction_id == r_out.transaction_id)).all()
    assert len(lines) == 1 and lines[0].name == "Woda"

    r_dup = ingest_receipt_result(session, stub_receipt, budget_id=budget.id, user_id=user.id, categorize=False)
    assert r_dup.skipped is True

    bank_payload = json.dumps(
        {
            "rows": [
                {
                    "external_id": "MBANK-1",
                    "date": "2026-04-12",
                    "amount": "-9.98",
                    "counterparty": "Biedronka Test",
                    "title": "Platnosc karta",
                }
            ]
        }
    ).encode("utf-8")
    batch = _StubNewTransactionAdapter().extract_transactions(bank_payload, budget_id=budget.id)
    summary = ingest_transaction_batch(
        session,
        batch,
        budget_id=budget.id,
        user_id=user.id,
        filename="mbank.json",
    )
    assert summary["created"] == 1
    assert summary["skipped"] == 0

    # Replay with same external_id (even if canonical_hash changed) is pre-deduplicated before commit
    changed_hash_payload = json.dumps(
        {
            "rows": [
                {
                    "external_id": "MBANK-1",
                    "date": "2026-04-12",
                    "amount": "-9.98",
                    "counterparty": "Biedronka Updated Name",
                    "title": "Platnosc karta",
                }
            ]
        }
    ).encode("utf-8")
    replay_ext_batch = _StubNewTransactionAdapter().extract_transactions(changed_hash_payload, budget_id=budget.id)
    replay_ext_summary = ingest_transaction_batch(
        session,
        replay_ext_batch,
        budget_id=budget.id,
        user_id=user.id,
        filename="mbank_replay.json",
    )
    assert replay_ext_summary["created"] == 0
    assert replay_ext_summary["skipped"] == 1


# ---------------------------------------------------------------------------
# 4. Bank Statement Adapter Conformance Suite (CSV & PDF)
# ---------------------------------------------------------------------------


def test_ing_csv_transaction_adapter_conformance(session: Session):
    user, budget = _seed_user_and_budget(session)
    assert user.id is not None and budget.id is not None
    adapter = IngCsvTransactionAdapter()

    # 1) success
    ok_batch = adapter.extract_transactions(_load_bytes_fixture("ing_csv", "success.csv"), budget_id=budget.id)
    assert len(ok_batch.items) == 2
    assert ok_batch.warnings == []
    assert ok_batch.items[0].transaction.direction == "debit"
    assert ok_batch.items[0].transaction.abs_amount == Decimal("45.50")
    assert ok_batch.items[1].transaction.direction == "credit"
    assert ok_batch.items[1].transaction.abs_amount == Decimal("5200.00")
    assert ok_batch.items[0].provenance.raw_payload_policy == RawPayloadPolicy.NONE

    res_first = ingest_transaction_batch(session, ok_batch, budget_id=budget.id, user_id=user.id, filename="success.csv")
    assert res_first["created"] == 2
    assert res_first["skipped"] == 0

    # 2) duplicate (intra-batch duplicate + DB replay)
    dup_batch = adapter.extract_transactions(_load_bytes_fixture("ing_csv", "duplicate.csv"), budget_id=budget.id)
    assert len(dup_batch.items) == 2
    dup_first = ingest_transaction_batch(session, dup_batch, budget_id=budget.id, user_id=user.id, filename="dup.csv")
    assert dup_first["created"] == 1
    assert dup_first["skipped"] == 1
    dup_second = ingest_transaction_batch(session, dup_batch, budget_id=budget.id, user_id=user.id, filename="dup.csv")
    assert dup_second["created"] == 0
    assert dup_second["skipped"] == 2

    # 3) partial_data (missing counterparty/title columns)
    partial_batch = adapter.extract_transactions(_load_bytes_fixture("ing_csv", "partial_data.csv"), budget_id=budget.id)
    assert len(partial_batch.items) == 1
    assert "PARTIAL_STATEMENT_COLUMNS" in partial_batch.warnings
    assert "PARTIAL_COUNTERPARTY_DESCRIPTION" in partial_batch.items[0].warnings
    assert partial_batch.items[0].quality < Decimal("0.9500")

    # 4) schema_drift (unexpected extra header)
    drift_batch = adapter.extract_transactions(_load_bytes_fixture("ing_csv", "schema_drift.csv"), budget_id=budget.id)
    assert len(drift_batch.items) == 1
    assert any(w.startswith("SCHEMA_DRIFT:") for w in drift_batch.warnings)
    assert drift_batch.items[0].quality < Decimal("0.9500")

    # 5) invalid_rows (invalid amount & invalid date skipped with explicit warnings, valid row preserved)
    invalid_batch = adapter.extract_transactions(_load_bytes_fixture("ing_csv", "invalid_rows.csv"), budget_id=budget.id)
    assert len(invalid_batch.items) == 1
    assert invalid_batch.items[0].transaction.abs_amount == Decimal("10.00")
    assert any(w.startswith("MALFORMED_AMOUNT:") for w in invalid_batch.warnings)
    assert any(w.startswith("MALFORMED_DATE:") for w in invalid_batch.warnings)

    # Row-level malformed warnings must not leak onto subsequent valid rows
    mixed_csv = (
        "Data księgowania;Data transakcji;Dane kontrahenta;Tytuł;Kwota transakcji (waluta);Waluta\n"
        "2026-04-16;2026-04-15;Zły Wiersz;Błąd;BAD_AMT;PLN\n"
        "2026-04-17;2026-04-16;Poprawny Sklep;Zakup;-25,00;PLN\n"
    ).encode("utf-8")
    mixed_batch = adapter.extract_transactions(mixed_csv, budget_id=budget.id)
    assert len(mixed_batch.items) == 1
    assert mixed_batch.items[0].transaction.booked_at.strftime("%Y-%m-%d") == "2026-04-16"
    assert not any(w.startswith("MALFORMED_") for w in mixed_batch.items[0].warnings)
    assert any(w.startswith("MALFORMED_AMOUNT:") for w in mixed_batch.warnings)

    # Fatal schema errors when required columns are absent or bytes invalid
    with pytest.raises(AdapterSchemaError):
        adapter.extract_transactions(b"KolumnaA;KolumnaB\n1;2\n", budget_id=budget.id)
    with pytest.raises(AdapterParseError):
        adapter.extract_transactions(b"", budget_id=budget.id)


def test_ing_pdf_transaction_adapter_conformance(session: Session):
    user, budget = _seed_user_and_budget(session)
    assert user.id is not None and budget.id is not None
    adapter = IngPdfTransactionAdapter()

    synthetic_pdf_text = (
        "12.04.2026 13.04.2026\n"
        "Sklep Testowy Sp. z o.o.\n"
        "Platnosc karta nr 0000\n"
        "-45,50 PLN\n"
        "13.04.2026 14.04.2026\n"
        "10500031-99999999\n"
        "TR.BLIK\n"
        "-12,00 PLN\n"
    )
    batch = adapter.extract_from_text(synthetic_pdf_text, budget_id=budget.id)
    assert len(batch.items) == 2
    assert batch.items[0].transaction.counterparty == "Sklep Testowy Sp. z o.o."
    assert batch.items[0].transaction.abs_amount == Decimal("45.50")
    assert batch.items[1].transaction.counterparty == "Przelew/Transakcja"
    assert "PARTIAL_COUNTERPARTY_FALLBACK" in batch.items[1].warnings
    assert batch.items[1].quality < batch.items[0].quality

    out1 = ingest_transaction_batch(session, batch, budget_id=budget.id, user_id=user.id, filename="wyciag.pdf")
    out2 = ingest_transaction_batch(session, batch, budget_id=budget.id, user_id=user.id, filename="wyciag.pdf")
    assert out1["created"] == 2 and out2["created"] == 0 and out2["skipped"] == 2

    drift_batch = adapter.extract_from_text("Unexpected bank PDF export format without dates", budget_id=budget.id)
    assert drift_batch.items == []
    assert "SCHEMA_DRIFT_OR_UNRECOGNIZED_STATEMENT" in drift_batch.warnings

    with pytest.raises(AdapterParseError):
        adapter.extract_transactions(b"not-a-pdf", budget_id=budget.id)


def test_process_scan_preserves_eparagon_quality_and_ingest_history_skips_null_categories(
    session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    import asyncio
    from app.api import _process_scan
    from app.models import Category
    from app.provenance_service import build_source_record
    from app.services import AIService

    user, budget = _seed_user_and_budget(session)
    assert user.id is not None and budget.id is not None

    ep_bytes = _load_bytes_fixture("eparagon", "success.json")
    ep_path = tmp_path / "eparagon.json"
    ep_path.write_bytes(ep_bytes)

    tx = Transaction(budget_id=budget.id, uploaded_by=user.id, merchant_name="Pending", total_amount=Decimal("0.00"))
    session.add(tx)
    session.commit()
    session.refresh(tx)
    assert tx.id is not None

    scan = ReceiptScan(
        transaction_id=tx.id,
        image_path=str(ep_path),
        status=ScanStatus.QUEUED.value,
        content_hash="ep-scan-hash-1",
    )
    session.add(scan)
    session.commit()
    session.refresh(scan)
    assert scan.id is not None

    session.add(
        build_source_record(
            budget_id=budget.id,
            transaction_id=tx.id,
            receipt_scan_id=scan.id,
            source_type=SourceType.E_RECEIPT,
            provider="eparagon_json",
            external_id="0000000000:SYN-EP-0001",
            canonical_hash="ep-scan-hash-1",
            adapter_version="eparagon_v1",
            quality="1.00",
            raw_payload_policy=RawPayloadPolicy.CANONICAL_ONLY,
        )
    )
    session.commit()

    import app.api as app_api

    monkeypatch.setattr(app_api, "operations_engine", session.bind)
    monkeypatch.setattr(
        AIService,
        "parse_receipt",
        staticmethod(
            lambda *a, **kw: {
                "merchant_name": "Sklep Testowy Sp. z o.o.",
                "date": "2026-04-12",
                "total_amount": Decimal("15.98"),
                "currency": "PLN",
                "items": [
                    {"name": "KAWA ZIARNISTA 250G", "unit_price": Decimal("10.99"), "quantity": Decimal("1")},
                    {"name": "CZEKOLADA GORZKA", "unit_price": Decimal("4.99"), "quantity": Decimal("1")},
                ],
                "_processed_via": "eparagon_json_adapter",
                "_validation": {"is_valid": True, "issues": [], "confidence": 1.0, "message": None},
            }
        ),
    )

    asyncio.run(_process_scan(scan.id, tx.id, str(ep_path)))
    sr = session.exec(select(SourceRecord).where(SourceRecord.receipt_scan_id == scan.id)).first()
    assert sr is not None
    assert sr.quality == Decimal("1.0000")

    # Verify history lookup in ingest_transaction_batch excludes category_id=None rows
    cat = Category(name="GroceriesTest", budget_id=budget.id)
    session.add(cat)
    session.commit()
    session.refresh(cat)
    assert cat.id is not None

    # Older categorized transaction + newer uncategorized transaction for same merchant
    session.add(
        Transaction(
            budget_id=budget.id,
            uploaded_by=user.id,
            merchant_name="Sklep Cache",
            total_amount=Decimal("10.00"),
            category_id=cat.id,
            date=datetime(2026, 4, 1, tzinfo=timezone.utc),
        )
    )
    session.add(
        Transaction(
            budget_id=budget.id,
            uploaded_by=user.id,
            merchant_name="Sklep Uncat",
            total_amount=Decimal("12.00"),
            category_id=None,
            date=datetime(2026, 4, 10, tzinfo=timezone.utc),
        )
    )
    session.commit()

    ai_called_with: list[list[str]] = []

    def fake_categorize_descriptions(descriptions: list[str], categories: list[dict]) -> dict[str, str]:
        ai_called_with.append(descriptions)
        return {d: "GroceriesTest" for d in descriptions}

    monkeypatch.setattr(AIService, "categorize_descriptions", staticmethod(fake_categorize_descriptions))

    batch = TransactionBatchAdapterResult(
        items=[
            TransactionAdapterResult(
                transaction=CanonicalTransaction(
                    booked_at=datetime(2026, 4, 12, tzinfo=timezone.utc),
                    amount=Decimal("-20.00"),
                    counterparty="Sklep Cache",
                    title="",
                ),
                provenance=SourceProvenanceSpec(
                    source_type=SourceType.BANK_CSV,
                    provider="ing_csv",
                    canonical_hash="cache-hit-hash-1",
                ),
            )
        ]
    )
    out = ingest_transaction_batch(
        session,
        batch,
        budget_id=budget.id,
        user_id=user.id,
        filename="cache.csv",
        enable_ai_categorization=True,
    )
    assert out["created"] == 1
    assert ai_called_with == []
