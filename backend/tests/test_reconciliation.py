"""Comprehensive tests for safe receipt-bank reconciliation (#261)."""

from __future__ import annotations

import io
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Optional

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, inspect
from sqlmodel import Session, select

from app.api import get_current_budget
from app.auth import get_current_user
from app.main import app
from app.models import (
    Account,
    Budget,
    BudgetMember,
    ReconciliationLink,
    ReconciliationMatchKind,
    ReconciliationStatus,
    SourceRecord,
    SourceType,
    Transaction,
    TransactionStatus,
    User,
)
from app.provenance_service import compute_canonical_hash, record_manual_source_provenance, record_source_provenance


def _get_test_user_and_budget(session: Session) -> tuple[User, Budget]:
    user = session.exec(select(User).where(User.email == "test@example.com")).first()
    budget = session.exec(select(Budget).where(Budget.name == "Domowy")).first()
    assert user is not None and user.id is not None
    assert budget is not None and budget.id is not None
    return user, budget


def _seed_bank_and_target(
    session: Session,
    *,
    budget_id: int,
    user_id: int,
    merchant: str,
    amount: Decimal,
    tx_date: datetime,
    bank_merchant: Optional[str] = None,
    bank_note: str = "Płatność kartą",
    bank_amount: Optional[Decimal] = None,
    bank_date: Optional[datetime] = None,
    bank_type: str = "expense",
    target_type: str = "expense",
    target_source_type: SourceType = SourceType.OCR_PHOTO,
    provider: str = "receipt_ocr",
    account_id: Optional[int] = None,
    target_account_id: Optional[int] = None,
    currency: str = "PLN",
    unique_tag: str = "1",
) -> tuple[Transaction, SourceRecord, Transaction, SourceRecord]:
    target_tx = Transaction(
        merchant_name=merchant,
        total_amount=amount,
        currency=currency,
        date=tx_date,
        is_manual=(target_source_type == SourceType.MANUAL),
        type=target_type,
        status=TransactionStatus.UNCLEARED,
        uploaded_by=user_id,
        budget_id=budget_id,
        account_id=target_account_id,
        note=f"Receipt note {unique_tag}",
    )
    session.add(target_tx)
    session.flush()
    assert target_tx.id is not None

    if target_source_type == SourceType.MANUAL:
        target_sr, _ = record_manual_source_provenance(
            session, budget_id=budget_id, transaction_id=target_tx.id
        )
    else:
        target_sr, _ = record_source_provenance(
            session,
            budget_id=budget_id,
            transaction_id=target_tx.id,
            source_type=target_source_type,
            provider=provider,
            external_id=f"ext-{unique_tag}",
            canonical_hash=compute_canonical_hash(f"target:{unique_tag}"),
        )

    b_amt = bank_amount if bank_amount is not None else amount
    b_dt = bank_date if bank_date is not None else tx_date
    b_hash = compute_canonical_hash(f"bank:{unique_tag}:{b_amt}:{b_dt.isoformat()}")
    bank_tx = Transaction(
        merchant_name=bank_merchant or merchant,
        total_amount=b_amt,
        currency=currency,
        date=b_dt,
        is_manual=False,
        type=bank_type,
        status=TransactionStatus.CLEARED,
        uploaded_by=user_id,
        budget_id=budget_id,
        account_id=account_id,
        note=bank_note,
        import_hash=b_hash,
    )
    session.add(bank_tx)
    session.flush()
    assert bank_tx.id is not None

    bank_sr, _ = record_source_provenance(
        session,
        budget_id=budget_id,
        transaction_id=bank_tx.id,
        source_type=SourceType.BANK_CSV,
        provider="ing_csv",
        canonical_hash=b_hash,
    )
    session.commit()
    return bank_tx, bank_sr, target_tx, target_sr


def test_csv_import_does_not_silently_merge_within_two_days(client: TestClient, session: Session):
    manual_payload = {
        "merchant_name": "Biedronka",
        "total_amount": "42.50",
        "currency": "PLN",
        "date": "2026-05-10T10:00:00Z",
        "note": "Zakupy sobotnie",
    }
    res_manual = client.post("/api/transactions/manual", json=manual_payload)
    assert res_manual.status_code == 200, res_manual.text
    manual_id = res_manual.json()["id"]

    # Bank posts 1 day later with identical amount 42.50 PLN
    csv_content = (
        "Data transakcji;Kontrahent;Tytuł;Kwota;Waluta\n"
        "2026-05-11;Biedronka Sp. z o.o.;Zakup kartą nr 1234;-42,50;PLN\n"
    )
    res_csv = client.post(
        "/api/transactions/import",
        files={"file": ("ing.csv", io.BytesIO(csv_content.encode("utf-8")), "text/csv")},
    )
    assert res_csv.status_code == 200, res_csv.text
    assert res_csv.json()["created"] == 1

    all_txs = list(session.exec(select(Transaction)).all())
    assert len(all_txs) == 2

    manual_tx = session.get(Transaction, manual_id)
    assert manual_tx is not None
    assert manual_tx.status == TransactionStatus.UNCLEARED
    assert "[Bank:" not in (manual_tx.note or "")
    assert manual_tx.import_hash is None

    all_sources = list(session.exec(select(SourceRecord)).all())
    assert len(all_sources) == 2
    assert {sr.source_type for sr in all_sources} == {SourceType.MANUAL, SourceType.BANK_CSV}

    cand_res = client.get("/api/reconciliation/candidates")
    assert cand_res.status_code == 200, cand_res.text
    body = cand_res.json()
    assert body["pending_count"] == 1
    candidate = body["candidates"][0]
    assert candidate["status"] == "pending"
    assert candidate["match_kind"] == "exact"
    assert Decimal(candidate["score"]) >= Decimal("0.8000")
    signal_codes = {s["code"] for s in candidate["signals"]}
    assert "amount_exact" in signal_codes
    assert "date_within_1d" in signal_codes
    assert "merchant_strong_match" in signal_codes


def test_accept_and_unlink_are_reversible_with_accurate_totals_and_balances(
    client: TestClient, session: Session
):
    user, budget = _get_test_user_and_budget(session)
    assert user.id is not None and budget.id is not None

    checking = Account(
        name="Konto główne",
        type="checking",
        currency="PLN",
        initial_balance=Decimal("1000.00"),
        current_balance=Decimal("1000.00"),
        budget_id=budget.id,
    )
    session.add(checking)
    session.commit()
    session.refresh(checking)
    assert checking.id is not None

    bank_tx, bank_sr, target_tx, target_sr = _seed_bank_and_target(
        session,
        budget_id=budget.id,
        user_id=user.id,
        merchant="Rossmann",
        amount=Decimal("65.00"),
        tx_date=datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc),
        bank_merchant="Rossmann SDP",
        account_id=checking.id,
        target_account_id=None,
        unique_tag="rev-1",
    )

    ref_res = client.post("/api/reconciliation/refresh")
    assert ref_res.status_code == 200
    assert ref_res.json()["pending_count"] == 1
    link_id = ref_res.json()["candidates"][0]["id"]

    # Before accept: two separate transactions exist
    assert len(client.get("/api/transactions").json()) == 2

    accept_res = client.post(f"/api/reconciliation/{link_id}/accept")
    assert accept_res.status_code == 200, accept_res.text
    accepted = accept_res.json()["link"]
    assert accepted["status"] == "accepted"

    # Active transactions list suppresses superseded bank row, no double-counting in summary/account
    tx_list = client.get("/api/transactions").json()
    assert len(tx_list) == 1
    assert tx_list[0]["id"] == target_tx.id
    assert tx_list[0]["status"] == "cleared"
    assert tx_list[0]["account_id"] == checking.id
    assert {sr["id"] for sr in tx_list[0]["source_records"]} == {bank_sr.id, target_sr.id}

    summary = client.get("/api/budget/2026/5/summary").json()
    assert Decimal(summary["total_spent"]) == Decimal("65.00")

    session.refresh(checking)
    assert checking.current_balance == Decimal("935.00")

    # Unlink restores original bank transaction, receipt status, inherited account & source record
    unlink_res = client.post(f"/api/reconciliation/{link_id}/unlink")
    assert unlink_res.status_code == 200, unlink_res.text
    assert unlink_res.json()["link"]["status"] == "unlinked"

    tx_list_after = client.get("/api/transactions").json()
    assert len(tx_list_after) == 2

    session.refresh(bank_tx)
    session.refresh(bank_sr)
    session.refresh(target_tx)
    session.refresh(checking)
    assert bank_tx.reconciled_into_id is None
    assert bank_sr.transaction_id == bank_tx.id
    assert target_tx.status == TransactionStatus.UNCLEARED
    assert target_tx.account_id is None
    assert checking.current_balance == Decimal("935.00")


def test_equal_amount_purchases_same_day_surface_ambiguity_without_auto_merge(
    client: TestClient, session: Session
):
    user, budget = _get_test_user_and_budget(session)
    assert user.id is not None and budget.id is not None

    same_day = datetime(2026, 6, 3, 9, 30, tzinfo=timezone.utc)
    # Two separate receipts of 25.00 PLN on the exact same day
    _seed_bank_and_target(
        session,
        budget_id=budget.id,
        user_id=user.id,
        merchant="Kawiarnia Alfa",
        amount=Decimal("25.00"),
        tx_date=same_day,
        bank_note="Kartą Kawiarnia Alfa",
        unique_tag="same-alfa",
    )
    _seed_bank_and_target(
        session,
        budget_id=budget.id,
        user_id=user.id,
        merchant="Piekarnia Beta",
        amount=Decimal("25.00"),
        tx_date=same_day + timedelta(hours=3),
        bank_note="Kartą Piekarnia Beta",
        unique_tag="same-beta",
    )

    ref = client.post("/api/reconciliation/refresh").json()
    assert len(client.get("/api/transactions").json()) == 4
    assert ref["pending_count"] >= 2

    top_candidates = [c for c in ref["candidates"] if c["same_day_conflict_count"] >= 2]
    assert len(top_candidates) >= 2
    assert any(
        any(sig["code"] == "same_day_equal_amount_ambiguity" for sig in c["signals"])
        for c in top_candidates
    )

    # Matching merchant pairs rank highest cleanly
    best = ref["candidates"][0]
    assert best["bank_transaction"]["merchant_name"] == best["target_transaction"]["merchant_name"]


def test_refund_candidate_discovery_and_link_keeps_net_cashflow_balanced(
    client: TestClient, session: Session
):
    user, budget = _get_test_user_and_budget(session)
    assert user.id is not None and budget.id is not None

    purchase_dt = datetime(2026, 6, 1, 14, 0, tzinfo=timezone.utc)
    refund_dt = datetime(2026, 6, 6, 9, 0, tzinfo=timezone.utc)
    _seed_bank_and_target(
        session,
        budget_id=budget.id,
        user_id=user.id,
        merchant="Sklep RTV Euro",
        amount=Decimal("199.99"),
        tx_date=purchase_dt,
        bank_merchant="RTV Euro AGD",
        bank_note="ZWROT TOWARU KARTA",
        bank_amount=Decimal("199.99"),
        bank_date=refund_dt,
        bank_type="income",
        target_type="expense",
        unique_tag="refund-1",
    )

    res = client.post("/api/reconciliation/refresh")
    assert res.status_code == 200
    data = res.json()
    assert data["pending_count"] == 1
    candidate = data["candidates"][0]
    assert candidate["match_kind"] == ReconciliationMatchKind.REFUND.value
    assert any(s["code"] == "refund_amount_exact" for s in candidate["signals"])

    acc_res = client.post(f"/api/reconciliation/{candidate['id']}/accept")
    assert acc_res.status_code == 200
    assert acc_res.json()["link"]["status"] == "accepted"

    # Both the expense (-199.99) and the refund inflow (+199.99) must remain active so net == 0.00
    summary = client.get("/api/budget/2026/6/summary").json()
    assert Decimal(summary["total_spent"]) == Decimal("199.99")
    assert Decimal(summary["total_income"]) == Decimal("199.99")
    assert Decimal(summary["net_cash_flow"]) == Decimal("0.00")


def test_split_payment_reconciliation_and_incompatible_source_guard(
    client: TestClient, session: Session
):
    user, budget = _get_test_user_and_budget(session)
    assert user.id is not None and budget.id is not None

    dt = datetime(2026, 7, 10, 15, 0, tzinfo=timezone.utc)
    receipt_tx = Transaction(
        merchant_name="IKEA Market",
        total_amount=Decimal("100.00"),
        currency="PLN",
        date=dt,
        is_manual=False,
        type="expense",
        status=TransactionStatus.UNCLEARED,
        uploaded_by=user.id,
        budget_id=budget.id,
    )
    session.add(receipt_tx)
    session.flush()
    assert receipt_tx.id is not None
    receipt_sr, _ = record_source_provenance(
        session,
        budget_id=budget.id,
        transaction_id=receipt_tx.id,
        source_type=SourceType.OCR_PHOTO,
        provider="receipt_ocr",
        canonical_hash=compute_canonical_hash("ikea-100"),
    )

    other_receipt_tx = Transaction(
        merchant_name="Decathlon",
        total_amount=Decimal("60.00"),
        currency="PLN",
        date=dt,
        is_manual=False,
        type="expense",
        status=TransactionStatus.UNCLEARED,
        uploaded_by=user.id,
        budget_id=budget.id,
    )
    session.add(other_receipt_tx)
    session.flush()
    assert other_receipt_tx.id is not None
    other_sr, _ = record_source_provenance(
        session,
        budget_id=budget.id,
        transaction_id=other_receipt_tx.id,
        source_type=SourceType.OCR_PHOTO,
        provider="receipt_ocr",
        canonical_hash=compute_canonical_hash("decathlon-60"),
    )

    bank_parts = [
        ("ikea-card-60", "IKEA Market", Decimal("60.00")),
        ("ikea-blik-40", "IKEA Market", Decimal("40.00")),
        ("ikea-extra-50", "IKEA Market", Decimal("50.00")),
    ]
    bank_srs: dict[str, SourceRecord] = {}
    bank_txs: dict[str, Transaction] = {}
    for key, b_merch, b_amt in bank_parts:
        b_hash = compute_canonical_hash(key)
        b_tx = Transaction(
            merchant_name=b_merch,
            total_amount=b_amt,
            currency="PLN",
            date=dt,
            is_manual=False,
            type="expense",
            status=TransactionStatus.CLEARED,
            uploaded_by=user.id,
            budget_id=budget.id,
            import_hash=b_hash,
        )
        session.add(b_tx)
        session.flush()
        assert b_tx.id is not None
        b_sr, _ = record_source_provenance(
            session,
            budget_id=budget.id,
            transaction_id=b_tx.id,
            source_type=SourceType.BANK_CSV,
            provider="ing_csv",
            canonical_hash=b_hash,
        )
        bank_srs[key] = b_sr
        bank_txs[key] = b_tx
    session.commit()

    ref = client.post("/api/reconciliation/refresh").json()
    split_candidates = [
        c
        for c in ref["candidates"]
        if c["target_transaction_id"] == receipt_tx.id and c["match_kind"] == "split_payment"
    ]
    by_bank_id = {c["bank_transaction_id"]: c for c in split_candidates}
    c60 = by_bank_id[bank_txs["ikea-card-60"].id]
    c40 = by_bank_id[bank_txs["ikea-blik-40"].id]
    assert any(s["code"] == "split_payment_pair_sum" for s in c60["signals"])

    # Accept 60.00 split payment -> receipt remains uncleared until full 100.00 covered
    assert client.post(f"/api/reconciliation/{c60['id']}/accept").status_code == 200
    session.refresh(receipt_tx)
    assert receipt_tx.status == TransactionStatus.UNCLEARED

    # Accept 40.00 split payment -> full 100.00 covered, receipt transitions to cleared
    assert client.post(f"/api/reconciliation/{c40['id']}/accept").status_code == 200
    session.refresh(receipt_tx)
    assert receipt_tx.status == TransactionStatus.CLEARED

    # Attempting to link a 3rd partial bank row (50.00) that exceeds 100.00 must fail with 409
    extra_c = by_bank_id.get(bank_txs["ikea-extra-50"].id)
    if extra_c is not None:
        conflict_over = client.post(f"/api/reconciliation/{extra_c['id']}/accept")
        assert conflict_over.status_code == 409

    # Attempting to link an already-accepted bank SourceRecord (60.00) to Decathlon must be rejected (409)
    incompatible_link = ReconciliationLink(
        budget_id=budget.id,
        bank_source_record_id=bank_srs["ikea-card-60"].id or 0,
        target_source_record_id=other_sr.id or 0,
        bank_transaction_id=bank_txs["ikea-card-60"].id or 0,
        target_transaction_id=other_receipt_tx.id or 0,
        match_kind=ReconciliationMatchKind.EXACT,
        status=ReconciliationStatus.PENDING,
        score=Decimal("0.7500"),
        reasons={"signals": []},
    )
    session.add(incompatible_link)
    session.commit()
    session.refresh(incompatible_link)

    incompat_res = client.post(f"/api/reconciliation/{incompatible_link.id}/accept")
    assert incompat_res.status_code == 409
    assert receipt_sr.id != other_sr.id


def test_reimport_preserves_rejected_and_accepted_decisions_without_duplicates(
    client: TestClient, session: Session
):
    client.post(
        "/api/transactions/manual",
        json={
            "merchant_name": "Piekarnia Rogalik",
            "total_amount": "18.50",
            "currency": "PLN",
            "date": "2026-08-01T08:00:00Z",
        },
    )
    client.post(
        "/api/transactions/manual",
        json={
            "merchant_name": "Kino Helios",
            "total_amount": "54.00",
            "currency": "PLN",
            "date": "2026-08-02T19:00:00Z",
        },
    )

    csv_content = (
        "Data transakcji;Kontrahent;Tytuł;Kwota;Waluta\n"
        "2026-08-01;Piekarnia Rogalik;Zakup kartą;-18,50;PLN\n"
        "2026-08-02;Kino Helios;Bilety;-54,00;PLN\n"
    )
    res1 = client.post(
        "/api/transactions/import",
        files={"file": ("aug.csv", io.BytesIO(csv_content.encode("utf-8")), "text/csv")},
    )
    assert res1.status_code == 200
    assert res1.json()["created"] == 2

    cand_list = client.get("/api/reconciliation/candidates?status=pending").json()["candidates"]
    assert len(cand_list) == 2
    by_merchant = {c["target_transaction"]["merchant_name"]: c["id"] for c in cand_list}

    assert client.post(f"/api/reconciliation/{by_merchant['Piekarnia Rogalik']}/reject").status_code == 200
    assert client.post(f"/api/reconciliation/{by_merchant['Kino Helios']}/accept").status_code == 200

    # Re-import exact same bank statement
    res2 = client.post(
        "/api/transactions/import",
        files={"file": ("aug.csv", io.BytesIO(csv_content.encode("utf-8")), "text/csv")},
    )
    assert res2.status_code == 200
    assert res2.json()["created"] == 0
    assert res2.json()["skipped"] == 2

    after = client.get("/api/reconciliation/candidates").json()
    assert after["pending_count"] == 0
    assert after["rejected_count"] == 1
    assert after["accepted_count"] == 1
    assert len(session.exec(select(ReconciliationLink)).all()) == 2


def test_cross_budget_isolation_and_viewer_rbac(client: TestClient, session: Session):
    user1, budget1 = _get_test_user_and_budget(session)
    assert user1.id is not None and budget1.id is not None

    viewer = User(email="viewer@example.com", hashed_password="pw")
    other_owner = User(email="other@example.com", hashed_password="pw")
    session.add(viewer)
    session.add(other_owner)
    session.commit()
    session.refresh(viewer)
    session.refresh(other_owner)
    assert viewer.id is not None and other_owner.id is not None

    session.add(BudgetMember(budget_id=budget1.id, user_id=viewer.id, role="viewer"))
    other_budget = Budget(name="Obcy", owner_id=other_owner.id)
    session.add(other_budget)
    session.commit()
    session.refresh(other_budget)
    assert other_budget.id is not None
    session.add(BudgetMember(budget_id=other_budget.id, user_id=other_owner.id, role="owner"))
    session.commit()

    _seed_bank_and_target(
        session,
        budget_id=budget1.id,
        user_id=user1.id,
        merchant="Apteka",
        amount=Decimal("33.00"),
        tx_date=datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc),
        unique_tag="rbac-1",
    )
    link_id = client.post("/api/reconciliation/refresh").json()["candidates"][0]["id"]

    # Viewer can list but gets 403 on write operations
    app.dependency_overrides[get_current_user] = lambda: viewer
    assert client.get("/api/reconciliation/candidates").status_code == 200
    assert client.post("/api/reconciliation/refresh").status_code == 403
    assert client.post(f"/api/reconciliation/{link_id}/accept").status_code == 403
    assert client.post(f"/api/reconciliation/{link_id}/reject").status_code == 403
    assert client.post(f"/api/reconciliation/{link_id}/unlink").status_code == 403

    # Other budget gets 404 for budget1's link
    app.dependency_overrides[get_current_user] = lambda: other_owner
    app.dependency_overrides[get_current_budget] = lambda: other_budget
    assert client.get("/api/reconciliation/candidates").json()["candidates"] == []
    assert client.post(f"/api/reconciliation/{link_id}/accept").status_code == 404


def test_alembic_safe_reconciliation_migration_roundtrip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    import app.database as app_database

    db_path = tmp_path / "reconciliation_migration.db"
    db_url = f"sqlite:///{db_path}"
    monkeypatch.setattr(app_database, "DATABASE_URL", db_url)

    backend_dir = Path(__file__).resolve().parent.parent
    alembic_cfg = Config(str(backend_dir / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(backend_dir / "alembic"))
    alembic_cfg.set_main_option("sqlalchemy.url", db_url)

    command.upgrade(alembic_cfg, "f3a9d71b2e04")
    engine = create_engine(db_url)
    insp_pre = inspect(engine)
    assert "reconciliation_link" not in insp_pre.get_table_names()
    pre_tx_cols = {c["name"] for c in insp_pre.get_columns("transaction")}
    assert "reconciled_into_id" not in pre_tx_cols

    command.upgrade(alembic_cfg, "head")
    insp_up = inspect(engine)
    assert "reconciliation_link" in insp_up.get_table_names()
    up_tx_cols = {c["name"] for c in insp_up.get_columns("transaction")}
    assert "reconciled_into_id" in up_tx_cols
    indexes = {idx["name"] for idx in insp_up.get_indexes("reconciliation_link")}
    assert "uq_reconciliation_active_bank_source" in indexes
    assert "uq_reconciliation_active_target_purchase_exclusive" in indexes

    command.downgrade(alembic_cfg, "f3a9d71b2e04")
    insp_down = inspect(engine)
    assert "reconciliation_link" not in insp_down.get_table_names()
    down_tx_cols = {c["name"] for c in insp_down.get_columns("transaction")}
    assert "reconciled_into_id" not in down_tx_cols

    command.upgrade(alembic_cfg, "head")
    insp_reup = inspect(engine)
    assert "reconciliation_link" in insp_reup.get_table_names()


def test_exact_match_cross_account_updates_and_restores_balances(client: TestClient, session: Session) -> None:
    """EXACT reconciliation moves target onto bank account when different, keeping balances exact on accept & unlink."""
    user, budget = _get_test_user_and_budget(session)
    assert user.id is not None and budget.id is not None

    cash_acc = Account(
        name="Gotówka",
        type="cash",
        currency="PLN",
        initial_balance=Decimal("500.00"),
        current_balance=Decimal("500.00"),
        budget_id=budget.id,
    )
    bank_acc = Account(
        name="mBank",
        type="checking",
        currency="PLN",
        initial_balance=Decimal("1000.00"),
        current_balance=Decimal("1000.00"),
        budget_id=budget.id,
    )
    session.add_all([cash_acc, bank_acc])
    session.commit()
    session.refresh(cash_acc)
    session.refresh(bank_acc)

    tx_date = datetime(2026, 4, 5, 14, 0, tzinfo=timezone.utc)
    bank_tx, _, target_tx, _ = _seed_bank_and_target(
        session,
        budget_id=budget.id,
        user_id=user.id,
        merchant="Biedronka",
        amount=Decimal("120.00"),
        tx_date=tx_date,
        account_id=bank_acc.id,
        target_account_id=cash_acc.id,
        unique_tag="cross-acc-exact",
    )
    _ = bank_tx

    # Before accept, target is on cash (-120) and bank tx is on bank (-120)
    session.refresh(cash_acc)
    session.refresh(bank_acc)
    assert cash_acc.current_balance == Decimal("380.00")
    assert bank_acc.current_balance == Decimal("880.00")

    discover_res = client.post("/api/reconciliation/refresh")
    assert discover_res.status_code == 200
    links = client.get("/api/reconciliation/candidates?status=pending").json()["candidates"]
    assert len(links) == 1
    link_id = links[0]["id"]

    acc_res = client.post(f"/api/reconciliation/{link_id}/accept")
    assert acc_res.status_code == 200

    session.expire_all()
    refreshed_cash = session.get(Account, cash_acc.id)
    refreshed_bank = session.get(Account, bank_acc.id)
    refreshed_target = session.get(Transaction, target_tx.id)
    assert refreshed_cash is not None and refreshed_cash.current_balance == Decimal("500.00")
    assert refreshed_bank is not None and refreshed_bank.current_balance == Decimal("880.00")
    assert refreshed_target is not None and refreshed_target.account_id == bank_acc.id

    unlink_res = client.post(f"/api/reconciliation/{link_id}/unlink")
    assert unlink_res.status_code == 200

    session.expire_all()
    restored_cash = session.get(Account, cash_acc.id)
    restored_bank = session.get(Account, bank_acc.id)
    restored_target = session.get(Transaction, target_tx.id)
    assert restored_cash is not None and restored_cash.current_balance == Decimal("380.00")
    assert restored_bank is not None and restored_bank.current_balance == Decimal("880.00")
    assert restored_target is not None and restored_target.account_id == cash_acc.id


def test_split_payment_multi_account_partial_full_and_unlink_orders(client: TestClient, session: Session) -> None:
    """Split payment across two bank accounts preserves exact per-account balances in all accept/unlink orders."""
    user, budget = _get_test_user_and_budget(session)
    assert user.id is not None and budget.id is not None

    acc_a = Account(
        name="Konto A",
        type="checking",
        currency="PLN",
        initial_balance=Decimal("500.00"),
        current_balance=Decimal("500.00"),
        budget_id=budget.id,
    )
    acc_b = Account(
        name="Konto B",
        type="checking",
        currency="PLN",
        initial_balance=Decimal("300.00"),
        current_balance=Decimal("300.00"),
        budget_id=budget.id,
    )
    session.add_all([acc_a, acc_b])
    session.commit()
    session.refresh(acc_a)
    session.refresh(acc_b)

    tx_date = datetime(2026, 4, 8, 12, 0, tzinfo=timezone.utc)
    bank1_tx, bank1_sr, target_tx, target_sr = _seed_bank_and_target(
        session,
        budget_id=budget.id,
        user_id=user.id,
        merchant="Castorama",
        amount=Decimal("100.00"),
        bank_amount=Decimal("60.00"),
        tx_date=tx_date,
        account_id=acc_a.id,
        target_account_id=None,
        unique_tag="split-multi-1",
    )
    bank2_tx = Transaction(
        merchant_name="CASTORAMA SKLEP 2",
        total_amount=Decimal("40.00"),
        currency="PLN",
        date=tx_date,
        is_manual=False,
        type="expense",
        status=TransactionStatus.CLEARED,
        uploaded_by=user.id,
        budget_id=budget.id,
        account_id=acc_b.id,
        note="Split 2",
    )
    session.add(bank2_tx)
    session.flush()
    assert bank2_tx.id is not None
    record_source_provenance(
        session,
        budget_id=budget.id,
        transaction_id=bank2_tx.id,
        source_type=SourceType.BANK_CSV,
        provider="ing_csv",
        external_id="split-multi-2",
        canonical_hash=compute_canonical_hash("split-multi-2"),
    )
    session.commit()

    assert client.post("/api/reconciliation/refresh").status_code == 200
    pending = client.get("/api/reconciliation/candidates?status=pending").json()["candidates"]
    assert len(pending) == 2
    by_bank_tx_id = {item["bank_transaction_id"]: item["id"] for item in pending}
    link1_id = by_bank_tx_id[bank1_tx.id]
    link2_id = by_bank_tx_id[bank2_tx.id]

    # Partial accept (link1 only -> Konto A still -60, target stays without inheriting Konto A)
    assert client.post(f"/api/reconciliation/{link1_id}/accept").status_code == 200
    session.expire_all()
    assert session.get(Account, acc_a.id).current_balance == Decimal("440.00")  # type: ignore[union-attr]
    assert session.get(Account, acc_b.id).current_balance == Decimal("260.00")  # type: ignore[union-attr]
    t_mid = session.get(Transaction, target_tx.id)
    assert t_mid is not None and t_mid.account_id is None and t_mid.status == TransactionStatus.UNCLEARED

    # Full accept (link2 -> Konto A -60, Konto B -40, target becomes CLEARED)
    assert client.post(f"/api/reconciliation/{link2_id}/accept").status_code == 200
    session.expire_all()
    assert session.get(Account, acc_a.id).current_balance == Decimal("440.00")  # type: ignore[union-attr]
    assert session.get(Account, acc_b.id).current_balance == Decimal("260.00")  # type: ignore[union-attr]
    t_full = session.get(Transaction, target_tx.id)
    assert t_full is not None and t_full.account_id is None and t_full.status == TransactionStatus.CLEARED

    # Unlink in FIFO order (link1 first, then link2)
    assert client.post(f"/api/reconciliation/{link1_id}/unlink").status_code == 200
    session.expire_all()
    assert session.get(Account, acc_a.id).current_balance == Decimal("440.00")  # type: ignore[union-attr]
    assert session.get(Account, acc_b.id).current_balance == Decimal("260.00")  # type: ignore[union-attr]
    t_after_1 = session.get(Transaction, target_tx.id)
    assert t_after_1 is not None and t_after_1.status == TransactionStatus.UNCLEARED

    assert client.post(f"/api/reconciliation/{link2_id}/unlink").status_code == 200
    session.expire_all()
    assert session.get(Account, acc_a.id).current_balance == Decimal("440.00")  # type: ignore[union-attr]
    assert session.get(Account, acc_b.id).current_balance == Decimal("260.00")  # type: ignore[union-attr]
    t_after_2 = session.get(Transaction, target_tx.id)
    assert t_after_2 is not None and t_after_2.account_id is None and t_after_2.status == TransactionStatus.UNCLEARED
    _ = (target_sr, bank1_sr)


def test_refund_can_reconcile_with_already_exact_reconciled_receipt(client: TestClient, session: Session) -> None:
    """A refund inflow imported later still discovers and accepts against an EXACT-reconciled receipt."""
    user, budget = _get_test_user_and_budget(session)
    assert user.id is not None and budget.id is not None

    purchase_date = datetime(2026, 4, 2, 10, 0, tzinfo=timezone.utc)
    bank_purchase_tx, _, target_tx, target_sr = _seed_bank_and_target(
        session,
        budget_id=budget.id,
        user_id=user.id,
        merchant="Zalando",
        amount=Decimal("250.00"),
        tx_date=purchase_date,
        unique_tag="zalando-refund",
    )

    assert client.post("/api/reconciliation/refresh").status_code == 200
    purchase_links = client.get("/api/reconciliation/candidates?status=pending").json()["candidates"]
    assert len(purchase_links) == 1
    assert purchase_links[0]["match_kind"] == "exact"
    assert client.post(f"/api/reconciliation/{purchase_links[0]['id']}/accept").status_code == 200

    # Later bank statement adds a REFUND inflow for the same order
    refund_tx = Transaction(
        merchant_name="Zalando",
        total_amount=Decimal("100.00"),
        currency="PLN",
        date=purchase_date + timedelta(days=5),
        is_manual=False,
        type="income",
        status=TransactionStatus.CLEARED,
        uploaded_by=user.id,
        budget_id=budget.id,
        note="Zwrot za część zamówienia",
    )
    session.add(refund_tx)
    session.flush()
    assert refund_tx.id is not None
    record_source_provenance(
        session,
        budget_id=budget.id,
        transaction_id=refund_tx.id,
        source_type=SourceType.BANK_CSV,
        provider="ing_csv",
        external_id="zalando-refund-inflow",
        canonical_hash=compute_canonical_hash("zalando-refund-inflow"),
    )
    session.commit()

    assert client.post("/api/reconciliation/refresh").status_code == 200
    refund_links = client.get("/api/reconciliation/candidates?status=pending").json()["candidates"]
    assert len(refund_links) == 1
    assert refund_links[0]["match_kind"] == "refund"
    assert refund_links[0]["target_source_record_id"] == target_sr.id

    accept_refund = client.post(f"/api/reconciliation/{refund_links[0]['id']}/accept")
    assert accept_refund.status_code == 200
    assert accept_refund.json()["link"]["status"] == "accepted"

    # Unlinking the EXACT link must revert target_tx status even when REFUND remains accepted
    unlink_exact = client.post(f"/api/reconciliation/{purchase_links[0]['id']}/unlink")
    assert unlink_exact.status_code == 200
    session.expire_all()
    t_reverted = session.get(Transaction, target_tx.id)
    b_reverted = session.get(Transaction, bank_purchase_tx.id)
    assert t_reverted is not None and t_reverted.status == TransactionStatus.UNCLEARED
    assert b_reverted is not None and b_reverted.reconciled_into_id is None


def test_delete_accepted_bank_tx_reverts_target_and_reaccept_refreshes_previous_status(
    client: TestClient, session: Session
) -> None:
    """Deleting a linked bank tx reverts target status/account and cleans orphan bank SourceRecords;
    re-accepting after unlink refreshes previous_receipt_status from current state.
    """
    user, budget = _get_test_user_and_budget(session)
    assert user.id is not None and budget.id is not None

    bank_acc = Account(
        name="PKO",
        type="checking",
        currency="PLN",
        initial_balance=Decimal("400.00"),
        current_balance=Decimal("400.00"),
        budget_id=budget.id,
    )
    session.add(bank_acc)
    session.commit()
    session.refresh(bank_acc)

    bank_tx, bank_sr, target_tx, _ = _seed_bank_and_target(
        session,
        budget_id=budget.id,
        user_id=user.id,
        merchant="Empik",
        amount=Decimal("75.00"),
        tx_date=datetime(2026, 4, 10, 15, 0, tzinfo=timezone.utc),
        account_id=bank_acc.id,
        target_account_id=None,
        unique_tag="del-bank-reaccept",
    )
    client.post("/api/reconciliation/refresh")
    link_id = client.get("/api/reconciliation/candidates?status=pending").json()["candidates"][0]["id"]

    # 1. Accept -> Unlink -> user edits target_tx.status = CLEARED -> Re-accept -> Unlink preserves CLEARED
    assert client.post(f"/api/reconciliation/{link_id}/accept").status_code == 200
    assert client.post(f"/api/reconciliation/{link_id}/unlink").status_code == 200

    patch_res = client.patch(
        f"/api/transactions/{target_tx.id}",
        json={"status": "cleared"},
    )
    assert patch_res.status_code == 200

    assert client.post(f"/api/reconciliation/{link_id}/accept").status_code == 200
    assert client.post(f"/api/reconciliation/{link_id}/unlink").status_code == 200
    session.expire_all()
    assert session.get(Transaction, target_tx.id).status == TransactionStatus.CLEARED  # type: ignore[union-attr]

    # Set back to UNCLEARED, re-accept, then delete bank_tx
    assert client.patch(f"/api/transactions/{target_tx.id}", json={"status": "uncleared"}).status_code == 200
    assert client.post(f"/api/reconciliation/{link_id}/accept").status_code == 200

    del_res = client.delete(f"/api/transactions/{bank_tx.id}")
    assert del_res.status_code == 204

    session.expire_all()
    rev_target = session.get(Transaction, target_tx.id)
    assert rev_target is not None
    assert rev_target.status == TransactionStatus.UNCLEARED
    assert rev_target.account_id is None
    assert session.get(SourceRecord, bank_sr.id) is None
    remaining_bank_sources = session.exec(
        select(SourceRecord).where(
            SourceRecord.transaction_id == target_tx.id,
            SourceRecord.source_type == SourceType.BANK_CSV,
        )
    ).all()
    assert remaining_bank_sources == []


def test_patch_transaction_refreshes_reconciliation_candidates(client: TestClient, session: Session) -> None:
    """Editing a transaction amount/merchant/date via PATCH triggers candidate rediscovery."""
    user, budget = _get_test_user_and_budget(session)
    assert user.id is not None and budget.id is not None

    _, _, target_tx, _ = _seed_bank_and_target(
        session,
        budget_id=budget.id,
        user_id=user.id,
        merchant="Apteka Gemini",
        amount=Decimal("99.99"),
        bank_amount=Decimal("150.00"),
        tx_date=datetime(2026, 4, 12, 11, 0, tzinfo=timezone.utc),
        unique_tag="patch-refresh",
    )

    assert client.post("/api/reconciliation/refresh").status_code == 200
    # 150.00 bank vs 99.99 target is neither EXACT nor SPLIT_PAYMENT
    pre_links = client.get("/api/reconciliation/candidates?status=pending").json()["candidates"]
    assert pre_links == []

    # Fix receipt amount via PATCH -> candidate appears automatically without calling /refresh
    patch_res = client.patch(f"/api/transactions/{target_tx.id}", json={"total_amount": "150.00"})
    assert patch_res.status_code == 200

    post_links = client.get("/api/reconciliation/candidates?status=pending").json()["candidates"]
    assert len(post_links) == 1
    assert post_links[0]["match_kind"] == "exact"
