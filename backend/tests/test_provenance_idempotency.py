"""Tests for Issue #193: SourceRecord provenance, external identity, and import idempotency."""

from __future__ import annotations

import hashlib
import io
import json
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, create_engine, select

from app.adapters.lidl_poc_client import MOCK_LIDL_V3_TICKET
from app.connection_service import ConnectionService
from app.models import (
    Account,
    Budget,
    RawPayloadPolicy,
    SourceRecord,
    SourceType,
    Transaction,
    User,
)
from app.provenance_service import (
    compute_canonical_hash,
    find_existing_source_record,
    record_manual_source_provenance,
    record_source_provenance,
)


def _get_test_user_and_budget(session: Session) -> tuple[User, Budget]:
    user = session.exec(select(User).where(User.email == "test@example.com")).first()
    budget = session.exec(select(Budget).where(Budget.name == "Domowy")).first()
    assert user is not None and budget is not None
    assert budget.id is not None and user.id is not None
    return user, budget


def test_source_record_created_for_manual_and_transfer(client: TestClient, session: Session):
    acc1 = Account(name="Checking", type="checking", currency="PLN", budget_id=1)
    acc2 = Account(name="Savings", type="savings", currency="PLN", budget_id=1)
    session.add(acc1)
    session.add(acc2)
    session.commit()
    session.refresh(acc1)
    session.refresh(acc2)

    # Two identical manual entries without external_id/canonical_hash must both succeed
    for _ in range(2):
        res = client.post(
            "/api/transactions/manual",
            json={
                "merchant_name": "Kawiarnia",
                "total_amount": "15.00",
                "currency": "PLN",
                "type": "expense",
                "account_id": acc1.id,
            },
        )
        assert res.status_code == 200
        payload = res.json()
        assert len(payload["source_records"]) == 1
        src = payload["source_records"][0]
        assert src["source_type"] == "MANUAL"
        assert src["provider"] == "manual"
        assert src["external_id"] is None
        assert src["canonical_hash"] is None
        assert src["quality"] == "1.00"
        assert src["raw_payload_policy"] == "none"

    tr_res = client.post(
        "/api/transfers",
        json={
            "source_account_id": acc1.id,
            "destination_account_id": acc2.id,
            "amount": "100.00",
            "currency": "PLN",
        },
    )
    assert tr_res.status_code == 200
    tr_src = tr_res.json()["source_records"][0]
    assert tr_src["source_type"] == "MANUAL"

    assert len(session.exec(select(SourceRecord)).all()) == 3


@patch("app.api.process_transaction_in_background")
def test_scan_ocr_and_eparagon_provenance_and_verify_retention(
    mock_bg, client: TestClient, session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    import app.api as app_api

    monkeypatch.setattr(app_api, "UPLOAD_DIR", str(tmp_path))

    # 1. OCR_PHOTO upload + verify keep_image retention update
    photo_bytes = b"\xff\xd8\xff\xe0fake-jpeg-payload"
    res = client.post(
        "/api/transactions/scan",
        files={"file": ("paragon.jpg", photo_bytes, "image/jpeg")},
    )
    assert res.status_code == 200
    tx_id = res.json()["id"]
    src_ocr = res.json()["source_records"][0]
    assert src_ocr["source_type"] == "OCR_PHOTO"
    assert src_ocr["provider"] == "receipt_upload"
    assert src_ocr["external_id"] is None
    assert src_ocr["canonical_hash"] == hashlib.sha256(photo_bytes).hexdigest()
    assert src_ocr["raw_payload_policy"] == "ephemeral_image"

    # Re-upload with same bytes returns 409; force=true succeeds without violating unique index
    dup_res = client.post(
        "/api/transactions/scan",
        files={"file": ("paragon.jpg", photo_bytes, "image/jpeg")},
    )
    assert dup_res.status_code == 409

    force_res = client.post(
        "/api/transactions/scan?force=true",
        files={"file": ("paragon.jpg", photo_bytes, "image/jpeg")},
    )
    assert force_res.status_code == 200
    assert force_res.json()["source_records"][0]["canonical_hash"] is None

    # Verify with keep_image=False updates policy to canonical_only
    verify_res = client.post(
        f"/api/transactions/{tx_id}/verify",
        json={"transaction_update": {}, "keep_image": False},
    )
    assert verify_res.status_code == 200
    assert verify_res.json()["source_records"][0]["raw_payload_policy"] == "canonical_only"

    # 2. E_RECEIPT upload with explicit document number vs without document number
    eparagon_with_id = json.dumps(
        {
            "protoVersion": "000",
            "document": {
                "podmiot1": {"NIP": "7791011327", "nazwaPod": "TEST STORE"},
                "paragon": {"nrDok": "PAR-2026-991", "total": {"zaplZwrot": 1000}, "pozycja": []},
            },
        }
    ).encode("utf-8")
    ep_res = client.post(
        "/api/transactions/scan",
        files={"file": ("eparagon.json", eparagon_with_id, "application/json")},
    )
    assert ep_res.status_code == 200
    ep_src = ep_res.json()["source_records"][0]
    assert ep_src["source_type"] == "E_RECEIPT"
    assert ep_src["provider"] == "eparagon_json"
    assert ep_src["external_id"] == "7791011327:PAR-2026-991"
    assert ep_src["raw_payload_policy"] == "canonical_only"

    # Same external document ID even with tweaked JSON payload whitespace is rejected (not duplicated)
    eparagon_reformatted = json.dumps(
        {
            "protoVersion": "000",
            "document": {
                "podmiot1": {"NIP": "7791011327", "nazwaPod": "TEST STORE"},
                "paragon": {"nrDok": "PAR-2026-991", "total": {"zaplZwrot": 1000}, "pozycja": []},
            },
            "reexport": True,
        }
    ).encode("utf-8")
    ep_dup = client.post(
        "/api/transactions/scan",
        files={"file": ("eparagon2.json", eparagon_reformatted, "application/json")},
    )
    assert ep_dup.status_code == 409

    # E_RECEIPT without nrDok keeps external_id=None (never fabricated)
    eparagon_no_id = json.dumps(
        {
            "protoVersion": "000",
            "document": {
                "podmiot1": {"nazwaPod": "NO DOC ID"},
                "paragon": {"total": {"zaplZwrot": 500}, "pozycja": []},
            },
        }
    ).encode("utf-8")
    ep_no_id_res = client.post(
        "/api/transactions/scan",
        files={"file": ("eparagon_no_id.json", eparagon_no_id, "application/json")},
    )
    assert ep_no_id_res.status_code == 200
    assert ep_no_id_res.json()["source_records"][0]["external_id"] is None


def test_bank_csv_provenance_and_idempotent_reimport(client: TestClient, session: Session):
    # Include both duplicate row inside same file and a second import call
    csv_content = (
        "Data transakcji;Kontrahent;Tytuł;Kwota;Waluta\n"
        "2026-04-01;Sklep XYZ;Zakupy kartą;-42,50;PLN\n"
        "2026-04-01;Sklep XYZ;Zakupy kartą;-42,50;PLN\n"
        "2026-04-02;Piekarnia;Bułki;-12,00;PLN\n"
    )
    res1 = client.post(
        "/api/transactions/import",
        files={"file": ("ing.csv", io.BytesIO(csv_content.encode("utf-8")), "text/csv")},
    )
    assert res1.status_code == 200
    assert res1.json()["created"] == 2
    assert res1.json()["skipped"] == 1

    res2 = client.post(
        "/api/transactions/import",
        files={"file": ("ing.csv", io.BytesIO(csv_content.encode("utf-8")), "text/csv")},
    )
    assert res2.status_code == 200
    assert res2.json()["created"] == 0
    assert res2.json()["skipped"] == 3

    records = session.exec(select(SourceRecord)).all()
    assert len(records) == 2
    assert all(r.source_type == SourceType.BANK_CSV and r.provider == "ing_csv" for r in records)
    assert all(r.external_id is None and r.canonical_hash is not None for r in records)


def test_sqlite_partial_unique_indexes_and_cross_budget_isolation(client: TestClient, session: Session):
    user, budget1 = _get_test_user_and_budget(session)
    budget2 = Budget(name="Drugi", owner_id=user.id)
    session.add(budget2)
    session.commit()
    session.refresh(budget2)
    assert budget1.id is not None and budget2.id is not None

    # 1. Multiple NULL external_id and NULL canonical_hash allowed for same (budget, provider)
    for _ in range(3):
        tx = Transaction(merchant_name="Coffee", total_amount=Decimal("10.00"), budget_id=budget1.id)
        session.add(tx)
        session.flush()
        session.add(
            SourceRecord(
                budget_id=budget1.id,
                transaction_id=tx.id,
                source_type=SourceType.MANUAL,
                provider="manual",
                external_id=None,
                canonical_hash=None,
            )
        )
    session.commit()

    # 2. Same external_id in DIFFERENT budget succeeds
    for b_id in (budget1.id, budget2.id):
        tx = Transaction(merchant_name="Lidl", total_amount=Decimal("25.00"), budget_id=b_id)
        session.add(tx)
        session.flush()
        session.add(
            SourceRecord(
                budget_id=b_id,
                transaction_id=tx.id,
                source_type=SourceType.MERCHANT_API,
                provider="lidl_plus",
                external_id="ticket-shared-id",
                canonical_hash=compute_canonical_hash(f"shared:{b_id}"),
            )
        )
    session.commit()

    # 3. Duplicate (budget1, lidl_plus, ticket-shared-id) violates DB partial unique index
    with pytest.raises(IntegrityError):
        with session.begin_nested():
            session.add(
                SourceRecord(
                    budget_id=budget1.id,
                    transaction_id=None,
                    source_type=SourceType.MERCHANT_API,
                    provider="lidl_plus",
                    external_id="ticket-shared-id",
                    canonical_hash=None,
                )
            )
            session.flush()

    # 4. Duplicate (budget1, canonical_hash) violates DB partial unique index
    shared_hash = compute_canonical_hash("shared:1")
    with pytest.raises(IntegrityError):
        with session.begin_nested():
            session.add(
                SourceRecord(
                    budget_id=budget1.id,
                    transaction_id=None,
                    source_type=SourceType.OCR_PHOTO,
                    provider="receipt_upload",
                    external_id=None,
                    canonical_hash=shared_hash,
                )
            )
            session.flush()


def test_lidl_ingestion_idempotency_and_race_recovery(client: TestClient, session: Session, monkeypatch: pytest.MonkeyPatch):
    from app.services import AIService

    user, budget = _get_test_user_and_budget(session)
    assert user.id is not None and budget.id is not None
    monkeypatch.setattr(AIService, "_categorize_parsed_items", lambda receipt, *args: receipt)

    imported1, skipped1 = ConnectionService._ingest_lidl_canonical_receipt(
        session, budget.id, user.id, "tkt-lidl-001", MOCK_LIDL_V3_TICKET
    )
    assert (imported1, skipped1) == (True, False)

    # Normal second ingestion catches duplicate before write
    imported2, skipped2 = ConnectionService._ingest_lidl_canonical_receipt(
        session, budget.id, user.id, "tkt-lidl-001", MOCK_LIDL_V3_TICKET
    )
    assert (imported2, skipped2) == (False, True)

    # Simulate race condition: bypass initial pre-check so IntegrityError triggers inside savepoint
    import app.connection_service as cs_mod

    calls = {"count": 0}
    orig_find = find_existing_source_record

    def race_find(sess, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            return None  # Pretend not found before insert race
        return orig_find(sess, **kwargs)

    monkeypatch.setattr(cs_mod, "find_existing_source_record", race_find)
    monkeypatch.setattr(cs_mod, "has_legacy_scan_duplicate", lambda *a, **kw: None)

    imported3, skipped3 = ConnectionService._ingest_lidl_canonical_receipt(
        session, budget.id, user.id, "tkt-lidl-001", MOCK_LIDL_V3_TICKET
    )
    assert (imported3, skipped3) == (False, True)
    assert len(session.exec(select(Transaction)).all()) == 1
    assert len(session.exec(select(SourceRecord)).all()) == 1

    # Also verify deleting the transaction cleans up SourceRecord rows
    tx = session.exec(select(Transaction)).first()
    assert tx is not None and tx.id is not None
    del_res = client.delete(f"/api/transactions/{tx.id}")
    assert del_res.status_code == 204
    assert session.exec(select(SourceRecord)).all() == []


def test_record_source_provenance_integrity_race(session: Session, monkeypatch: pytest.MonkeyPatch):
    user = User(email="race@example.com", hashed_password="pw")
    session.add(user)
    session.commit()
    session.refresh(user)
    budget = Budget(name="RaceBudget", owner_id=user.id)
    session.add(budget)
    session.commit()
    session.refresh(budget)
    assert budget.id is not None

    rec1, created1 = record_source_provenance(
        session,
        budget_id=budget.id,
        transaction_id=None,
        source_type=SourceType.E_RECEIPT,
        provider="eparagon_json",
        external_id="EXT-777",
        canonical_hash=compute_canonical_hash("ext-777"),
    )
    session.commit()
    assert created1 is True

    import app.provenance_service as ps_mod

    first_pass = {"done": False}
    orig_find = ps_mod.find_existing_source_record

    def simulated_race_find(sess, **kwargs):
        if not first_pass["done"]:
            first_pass["done"] = True
            return None
        return orig_find(sess, **kwargs)

    monkeypatch.setattr(ps_mod, "find_existing_source_record", simulated_race_find)
    rec2, created2 = record_source_provenance(
        session,
        budget_id=budget.id,
        transaction_id=None,
        source_type=SourceType.E_RECEIPT,
        provider="eparagon_json",
        external_id="EXT-777",
        canonical_hash=compute_canonical_hash("ext-777"),
    )
    assert created2 is False
    assert rec2.id == rec1.id


def test_alembic_source_record_migration_and_backfill(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Verify e9a1c3d5f702 upgrades, backfills legacy channels cleanly without fabricating IDs, and downgrades."""
    import app.database as app_database

    db_path = tmp_path / "provenance_migration.db"
    db_url = f"sqlite:///{db_path}"
    monkeypatch.setattr(app_database, "DATABASE_URL", db_url)

    backend_dir = Path(__file__).resolve().parent.parent
    alembic_cfg = Config(str(backend_dir / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(backend_dir / "alembic"))
    alembic_cfg.set_main_option("sqlalchemy.url", db_url)

    # 1. Start from pre-provenance revision d4f8a92c1e01
    command.upgrade(alembic_cfg, "d4f8a92c1e01")

    engine = create_engine(db_url)
    lidl_hash = hashlib.sha256(b"lidl_plus:1:tkt-42").hexdigest()
    ocr_hash = hashlib.sha256(b"legacy-ocr-img").hexdigest()
    csv_hash = hashlib.sha256(b"2026-01-01_-10.00_Biedronka_Karta").hexdigest()

    with engine.begin() as conn:
        conn.execute(text("INSERT INTO budget (id, name, created_at) VALUES (1, 'Home', '2026-11-14 00:00:00')"))
        # Legacy Lidl Plus receipt
        conn.execute(
            text(
                'INSERT INTO "transaction" (id, merchant_name, date, total_amount, currency, is_manual, type, status, budget_id, import_hash, note) '
                "VALUES (1, 'Lidl', '2026-11-01 10:00:00', 45.00, 'PLN', 0, 'expense', 'uncleared', 1, :ih, 'Lidl Plus #tkt-42')"
            ),
            {"ih": lidl_hash},
        )
        conn.execute(
            text(
                "INSERT INTO receiptscan (id, transaction_id, status, content_hash, keep_image, created_at, needs_review) "
                "VALUES (1, 1, 'CATEGORIZATION_OK', :ch, 0, '2026-11-01 10:05:00', 0)"
            ),
            {"ch": lidl_hash},
        )
        # Legacy OCR scan + forced duplicate scan with identical content_hash
        conn.execute(
            text(
                'INSERT INTO "transaction" (id, merchant_name, date, total_amount, currency, is_manual, type, status, budget_id) '
                "VALUES (2, 'Shop A', '2026-11-02 10:00:00', 20.00, 'PLN', 0, 'expense', 'uncleared', 1)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO receiptscan (id, transaction_id, image_path, status, content_hash, keep_image, created_at, needs_review) "
                "VALUES (2, 2, '/uploads/a.jpg', 'DONE', :ch, 1, '2026-11-02 10:05:00', 0)"
            ),
            {"ch": ocr_hash},
        )
        conn.execute(
            text(
                'INSERT INTO "transaction" (id, merchant_name, date, total_amount, currency, is_manual, type, status, budget_id) '
                "VALUES (3, 'Shop A Dup', '2026-11-02 11:00:00', 20.00, 'PLN', 0, 'expense', 'uncleared', 1)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO receiptscan (id, transaction_id, status, content_hash, keep_image, created_at, needs_review) "
                "VALUES (3, 3, 'DONE', :ch, 0, '2026-11-02 11:05:00', 0)"
            ),
            {"ch": ocr_hash},
        )
        # Legacy CSV bank transaction
        conn.execute(
            text(
                'INSERT INTO "transaction" (id, merchant_name, date, total_amount, currency, is_manual, type, status, budget_id, import_hash) '
                "VALUES (4, 'Biedronka', '2026-11-03 10:00:00', 10.00, 'PLN', 0, 'expense', 'cleared', 1, :ch)"
            ),
            {"ch": csv_hash},
        )
        # Legacy Manual transaction
        conn.execute(
            text(
                'INSERT INTO "transaction" (id, merchant_name, date, total_amount, currency, is_manual, type, status, budget_id) '
                "VALUES (5, 'Coffee', '2026-11-04 10:00:00', 12.00, 'PLN', 1, 'expense', 'cleared', 1)"
            )
        )

    # 2. Upgrade to head (e9a1c3d5f702)
    command.upgrade(alembic_cfg, "head")

    insp = inspect(engine)
    assert "source_record" in insp.get_table_names()
    scan_cols = {c["name"] for c in insp.get_columns("receiptscan")}
    assert "processed_via" in scan_cols

    with Session(engine) as s:
        records = sorted(s.exec(select(SourceRecord)).all(), key=lambda r: r.transaction_id or 0)
        assert len(records) == 5

        by_tx = {r.transaction_id: r for r in records}
        assert by_tx[1].source_type == SourceType.MERCHANT_API
        assert by_tx[1].provider == "lidl_plus"
        assert by_tx[1].external_id == "tkt-42"
        assert by_tx[1].canonical_hash == lidl_hash

        assert by_tx[2].source_type == SourceType.OCR_PHOTO
        assert by_tx[2].external_id is None
        assert by_tx[2].canonical_hash == ocr_hash
        assert by_tx[2].raw_payload_policy == RawPayloadPolicy.RETAINED_IMAGE

        # Duplicate legacy hash safely nulled instead of crashing backfill
        assert by_tx[3].source_type == SourceType.OCR_PHOTO
        assert by_tx[3].external_id is None
        assert by_tx[3].canonical_hash is None
        assert by_tx[3].raw_payload_policy == RawPayloadPolicy.CANONICAL_ONLY

        assert by_tx[4].source_type == SourceType.BANK_CSV
        assert by_tx[4].external_id is None
        assert by_tx[4].canonical_hash == csv_hash

        assert by_tx[5].source_type == SourceType.MANUAL
        assert by_tx[5].external_id is None
        assert by_tx[5].canonical_hash is None

    # 3. Downgrade -1 back to d4f8a92c1e01
    command.downgrade(alembic_cfg, "-1")
    insp_down = inspect(engine)
    assert "source_record" not in insp_down.get_table_names()
    assert "processed_via" not in {c["name"] for c in insp_down.get_columns("receiptscan")}

    # 4. Re-upgrade to head
    command.upgrade(alembic_cfg, "head")
    with Session(engine) as s:
        assert len(s.exec(select(SourceRecord)).all()) == 5


def test_account_opening_and_reconcile_create_source_records(client: TestClient, session: Session):
    acc_res = client.post(
        "/api/accounts",
        json={"name": "ProvAcc", "type": "checking", "currency": "PLN", "initial_balance": "100.00"},
    )
    assert acc_res.status_code == 200
    acc_id = acc_res.json()["id"]

    rec_res = client.post(f"/api/accounts/{acc_id}/reconcile", json={"real_balance": "125.00"})
    assert rec_res.status_code == 200

    records = session.exec(select(SourceRecord)).all()
    providers = {r.provider for r in records}
    assert "system_opening_balance" in providers
    assert "system_reconcile" in providers


def test_delete_budget_cleans_up_source_records(client: TestClient, session: Session):
    user, _ = _get_test_user_and_budget(session)
    budget_res = client.post("/api/budgets", json={"name": "Temp Budget"})
    assert budget_res.status_code == 200
    temp_budget_id = budget_res.json()["id"]

    tx = Transaction(
        merchant_name="Cafe",
        total_amount=Decimal("15.00"),
        currency="PLN",
        is_manual=True,
        type="expense",
        budget_id=temp_budget_id,
        uploaded_by=user.id,
    )
    session.add(tx)
    session.flush()
    assert tx.id is not None
    record_manual_source_provenance(session, budget_id=temp_budget_id, transaction_id=tx.id)
    session.commit()

    assert (
        session.exec(select(SourceRecord).where(SourceRecord.budget_id == temp_budget_id)).first()
        is not None
    )

    del_res = client.delete(f"/api/budgets/{temp_budget_id}")
    assert del_res.status_code == 200
    assert (
        session.exec(select(SourceRecord).where(SourceRecord.budget_id == temp_budget_id)).all()
        == []
    )


def test_scan_transaction_race_condition_returns_409_without_orphans(
    client: TestClient, session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    import app.api as app_api

    monkeypatch.setattr(app_api, "UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(app_api, "process_transaction_in_background", lambda *a, **kw: None)

    img_bytes = b"fake-jpeg-race-bytes"
    first = client.post(
        "/api/transactions/scan",
        files={"file": ("race.jpg", io.BytesIO(img_bytes), "image/jpeg")},
    )
    assert first.status_code == 200

    # Simulate TOCTOU race: initial duplicate check misses, DB unique constraint triggers IntegrityError,
    # and handler recovers inside savepoint without leaving orphan Transaction/ReceiptScan rows.
    calls = {"n": 0}
    real_find = find_existing_source_record

    def raced_find(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return None
        return real_find(*args, **kwargs)

    monkeypatch.setattr(app_api, "find_existing_source_record", raced_find)
    monkeypatch.setattr(app_api, "has_legacy_scan_duplicate", lambda *a, **kw: None)

    second = client.post(
        "/api/transactions/scan",
        files={"file": ("race.jpg", io.BytesIO(img_bytes), "image/jpeg")},
    )
    assert second.status_code == 409
    assert len(session.exec(select(Transaction)).all()) == 1
    assert len(session.exec(select(SourceRecord)).all()) == 1
