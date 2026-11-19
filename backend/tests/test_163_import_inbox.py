"""Comprehensive integration & migration tests for Import Inbox & Exception Reconciliation (#163)."""

from __future__ import annotations

import copy
import io
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, inspect, text
from sqlmodel import Session, select

from app.adapters.contracts import ReceiptAdapterResult, SourceProvenanceSpec
from app.adapters.lidl_poc_client import LidlPoCClient, MOCK_LIDL_V3_TICKET, get_lidl_live_config
from app.receipt_schema import CanonicalItem, CanonicalReceipt
from app.auth import get_current_user
from app.connection_service import ConnectionService
from app.core.encryption import get_encryption_service
from app.ingestion_service import ingest_receipt_result
from app.main import app
from app.models import (
    Account,
    AutoMergePolicy,
    Budget,
    BudgetMember,
    ConnectionStatus,
    ExternalReceiptConnection,
    ImportJob,
    ImportJobStatus,
    RawPayloadPolicy,
    ReceiptScan,
    ReconciliationMatchKind,
    ReconciliationStatus,
    ReviewStatus,
    ScanStatus,
    SourceType,
    Transaction,
    TransactionLine,
    User,
)
from app.provenance_service import compute_canonical_hash


@pytest.fixture(autouse=True)
def setup_test_encryption_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("CONNECTION_ENCRYPTION_KEYS", raising=False)
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode("utf-8"))
    monkeypatch.setenv("TOKEN_PRIMARY_KEY_ID", "v1")
    get_encryption_service(reload_env=True)


def _get_user_budget(session: Session) -> tuple[User, Budget]:
    user = session.exec(select(User).where(User.email == "test@example.com")).first()
    budget = session.exec(select(Budget).where(Budget.name == "Domowy")).first()
    assert user is not None and user.id is not None
    assert budget is not None and budget.id is not None
    return user, budget


def _make_receipt_result(
    *,
    budget_id: int,
    external_id: str,
    merchant_name: str = "Lidl Polska",
    date_str: str = "2026-05-12",
    total_amount: Decimal = Decimal("45.00"),
    validation_status: str = "verified",
    validation_message: str | None = None,
    source_type: SourceType = SourceType.MERCHANT_API,
    provider: str = "lidl",
    items: list[CanonicalItem] | None = None,
) -> ReceiptAdapterResult:
    resolved_items: list[CanonicalItem] = (
        items
        if items is not None
        else [
            CanonicalItem(
                name="Chleb",
                unit_price=total_amount,
                quantity=Decimal("1"),
                discount_total=Decimal("0.00"),
            )
        ]
    )
    canonical = CanonicalReceipt(
        merchant_name=merchant_name,
        date=date_str,
        total_amount=total_amount,
        currency="PLN",
        items=resolved_items,
    )
    return ReceiptAdapterResult(
        receipt=canonical,
        provenance=SourceProvenanceSpec(
            source_type=source_type,
            provider=provider,
            external_id=external_id,
            canonical_hash=compute_canonical_hash(f"{provider}:{external_id}:{date_str}:{total_amount}"),
            adapter_version="lidl_v3",
            acquired_at=datetime(2026, 5, 12, 12, 0, tzinfo=timezone.utc),
            raw_payload_policy=RawPayloadPolicy.CANONICAL_ONLY,
        ),
        validation_status=validation_status,
        validation_message=validation_message,
        quality=Decimal("1.0000") if validation_status == "verified" else Decimal("0.7000"),
        warnings=[],
    )


def test_alembic_163_inbox_lifecycle_migration_roundtrip(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    import app.database as app_database

    db_file = tmp_path / "alembic_163.db"
    db_url = f"sqlite:///{db_file}"
    monkeypatch.setattr(app_database, "DATABASE_URL", db_url)

    backend_dir = Path(__file__).resolve().parents[1]
    cfg = Config(str(backend_dir / "alembic.ini"))
    cfg.config_file_name = None
    cfg.set_main_option("script_location", str(backend_dir / "alembic"))
    cfg.set_main_option("sqlalchemy.url", db_url)

    command.upgrade(cfg, "j7e1b42a9c03")
    engine = create_engine(db_url)
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO user (email, hashed_password, created_at) VALUES "
                    "('mig@example.com', 'hash', '2026-01-01 00:00:00')"
                )
            )
            uid = conn.execute(text("SELECT id FROM user WHERE email='mig@example.com'")).scalar_one()
            conn.execute(
                text(
                    "INSERT INTO budget (name, owner_id, created_at) VALUES "
                    "('TestBudget', :uid, '2026-01-01 00:00:00')"
                ),
                {"uid": uid},
            )
            bid = conn.execute(text("SELECT id FROM budget WHERE name='TestBudget'")).scalar_one()
            conn.execute(
                text(
                    "INSERT INTO \"transaction\" (merchant_name, total_amount, currency, date, is_manual, type, status, uploaded_by, budget_id) "
                    "VALUES ('DoneTx', 25.00, 'PLN', '2026-05-01 10:00:00', 0, 'expense', 'uncleared', :uid, :bid)"
                ),
                {"uid": uid, "bid": bid},
            )
            done_tx_id = conn.execute(
                text("SELECT id FROM \"transaction\" WHERE merchant_name='DoneTx'")
            ).scalar_one()
            conn.execute(
                text(
                    "INSERT INTO \"transaction\" (merchant_name, total_amount, currency, date, is_manual, type, status, uploaded_by, budget_id) "
                    "VALUES ('ScanTx', 15.00, 'PLN', '2026-05-02 10:00:00', 0, 'expense', 'uncleared', :uid, :bid)"
                ),
                {"uid": uid, "bid": bid},
            )
            scan_tx_id = conn.execute(
                text("SELECT id FROM \"transaction\" WHERE merchant_name='ScanTx'")
            ).scalar_one()
            conn.execute(
                text(
                    "INSERT INTO receiptscan (transaction_id, status, keep_image, created_at, needs_review) "
                    "VALUES (:tx_id, 'NEEDS_REVIEW', 0, '2026-05-02 10:00:00', 1)"
                ),
                {"tx_id": scan_tx_id},
            )

        command.upgrade(cfg, "k8f2c53b0d14")
        tx_cols = {c["name"] for c in inspect(engine).get_columns("transaction")}
        conn_cols = {c["name"] for c in inspect(engine).get_columns("external_receipt_connection")}
        assert {"review_status", "rejected_at", "rejection_reason", "import_batch_id"}.issubset(tx_cols)
        assert {"default_account_id", "auto_merge_policy", "auto_approve_clean", "sync_from_date"}.issubset(conn_cols)

        with engine.connect() as db_conn:
            ver = db_conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            assert ver == "k8f2c53b0d14"
            done_review = db_conn.execute(
                text("SELECT review_status FROM \"transaction\" WHERE id = :id"),
                {"id": done_tx_id},
            ).scalar_one()
            scan_review = db_conn.execute(
                text("SELECT review_status FROM \"transaction\" WHERE id = :id"),
                {"id": scan_tx_id},
            ).scalar_one()
            assert done_review == "approved"
            assert scan_review == "pending"

        command.downgrade(cfg, "j7e1b42a9c03")
        tx_cols_down = {c["name"] for c in inspect(engine).get_columns("transaction")}
        conn_cols_down = {c["name"] for c in inspect(engine).get_columns("external_receipt_connection")}
        assert "review_status" not in tx_cols_down
        assert "default_account_id" not in conn_cols_down

        command.upgrade(cfg, "head")
        tx_cols_final = {c["name"] for c in inspect(engine).get_columns("transaction")}
        assert "review_status" in tx_cols_final
    finally:
        engine.dispose()


def test_clean_import_auto_approves_while_exceptions_stay_in_inbox_and_exclude_summary(
    client: TestClient, session: Session
):
    user, budget = _get_user_budget(session)
    assert user.id is not None and budget.id is not None

    checking = Account(
        name="Konto Główne",
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

    # 1. Clean receipt with assigned account -> auto-promotes to APPROVED
    clean_outcome = ingest_receipt_result(
        session,
        _make_receipt_result(
            budget_id=budget.id,
            external_id="clean-001",
            merchant_name="Lidl Clean",
            date_str="2026-05-12",
            total_amount=Decimal("100.00"),
        ),
        budget_id=budget.id,
        user_id=user.id,
        categorize=False,
        account_id=checking.id,
        auto_approve_clean=True,
    )
    assert clean_outcome.imported is True
    assert clean_outcome.auto_approved is True
    assert clean_outcome.pending_inbox is False

    # 2. Exception receipt without account + mismatch -> stays PENDING in Inbox
    exc_outcome = ingest_receipt_result(
        session,
        _make_receipt_result(
            budget_id=budget.id,
            external_id="exc-002",
            merchant_name="Lidl Mismatch",
            date_str="2026-05-13",
            total_amount=Decimal("50.00"),
            validation_status="needs_review",
            validation_message="RECEIPT_SUM_MISMATCH:5.00",
        ),
        budget_id=budget.id,
        user_id=user.id,
        categorize=False,
        account_id=None,
    )
    assert exc_outcome.imported is True
    assert exc_outcome.auto_approved is False
    assert exc_outcome.pending_inbox is True

    txs = client.get("/api/transactions").json()
    assert len(txs) == 1
    assert txs[0]["id"] == clean_outcome.transaction_id

    inbox = client.get("/api/transactions/inbox?tab=exceptions").json()
    assert len(inbox) == 1
    assert inbox[0]["id"] == exc_outcome.transaction_id
    assert inbox[0]["suggested_account_id"] == checking.id

    summary = client.get("/api/budget/2026/5/summary").json()
    assert Decimal(summary["total_spent"]) == Decimal("100.00")

    session.refresh(checking)
    assert checking.current_balance == Decimal("900.00")

    # 3. Bulk approve the exception onto checking account
    assert exc_outcome.transaction_id is not None
    bulk_res = client.post(
        "/api/inbox/bulk-approve",
        json={"transaction_ids": [exc_outcome.transaction_id], "account_id": checking.id},
    )
    assert bulk_res.status_code == 200, bulk_res.text
    assert bulk_res.json()["approved_count"] == 1

    assert client.get("/api/transactions/inbox?tab=exceptions").json() == []
    assert len(client.get("/api/transactions").json()) == 2

    summary_after = client.get("/api/budget/2026/5/summary").json()
    assert Decimal(summary_after["total_spent"]) == Decimal("150.00")
    session.refresh(checking)
    assert checking.current_balance == Decimal("850.00")


def test_bulk_approve_skips_failed_scan_and_enforces_viewer_rbac(
    client: TestClient, session: Session
):
    user, budget = _get_user_budget(session)
    assert user.id is not None and budget.id is not None

    checking = Account(
        name="Konto Test",
        type="checking",
        currency="PLN",
        initial_balance=Decimal("500.00"),
        current_balance=Decimal("500.00"),
        budget_id=budget.id,
    )
    session.add(checking)

    failed_tx = Transaction(
        merchant_name="Failed OCR",
        total_amount=Decimal("0.00"),
        currency="PLN",
        date=datetime(2026, 5, 10, tzinfo=timezone.utc),
        budget_id=budget.id,
        uploaded_by=user.id,
        review_status=ReviewStatus.PENDING,
    )
    ok_pending_tx = Transaction(
        merchant_name="Missing Account Lidl",
        total_amount=Decimal("30.00"),
        currency="PLN",
        date=datetime(2026, 5, 10, tzinfo=timezone.utc),
        budget_id=budget.id,
        uploaded_by=user.id,
        review_status=ReviewStatus.PENDING,
    )
    session.add(failed_tx)
    session.add(ok_pending_tx)
    session.commit()
    session.refresh(checking)
    session.refresh(failed_tx)
    session.refresh(ok_pending_tx)
    assert checking.id and failed_tx.id and ok_pending_tx.id

    session.add(ReceiptScan(transaction_id=failed_tx.id, status=ScanStatus.FAILED.value, needs_review=True))
    session.add(ReceiptScan(transaction_id=ok_pending_tx.id, status=ScanStatus.NEEDS_REVIEW.value, needs_review=True))

    viewer = User(email="viewer-163@example.com", hashed_password="pw")
    session.add(viewer)
    session.commit()
    session.refresh(viewer)
    assert viewer.id is not None
    session.add(BudgetMember(budget_id=budget.id, user_id=viewer.id, role="viewer"))
    session.commit()

    # Viewer gets 403
    app.dependency_overrides[get_current_user] = lambda: viewer
    try:
        res_forbidden = client.post(
            "/api/inbox/bulk-approve",
            json={"transaction_ids": [ok_pending_tx.id], "account_id": checking.id},
        )
        assert res_forbidden.status_code == 403
    finally:
        app.dependency_overrides[get_current_user] = lambda: user

    # Invalid account returns 422
    res_bad_acc = client.post(
        "/api/inbox/bulk-approve",
        json={"transaction_ids": [ok_pending_tx.id], "account_id": 99999},
    )
    assert res_bad_acc.status_code == 422

    res_ok = client.post(
        "/api/inbox/bulk-approve",
        json={"transaction_ids": [failed_tx.id, ok_pending_tx.id], "account_id": checking.id},
    )
    assert res_ok.status_code == 200
    payload = res_ok.json()
    assert payload["approved_count"] == 1
    assert payload["skipped_ids"] == [failed_tx.id]


def test_cross_source_receipt_duplicate_auto_and_manual_merge_and_unlink(
    client: TestClient, session: Session
):
    user, budget = _get_user_budget(session)
    assert user.id is not None and budget.id is not None

    spouse_cash = Account(
        name="Gotówka Żony",
        type="cash",
        currency="PLN",
        initial_balance=Decimal("500.00"),
        current_balance=Decimal("500.00"),
        budget_id=budget.id,
    )
    lidl_card = Account(
        name="Karta Wspólna",
        type="checking",
        currency="PLN",
        initial_balance=Decimal("1000.00"),
        current_balance=Decimal("1000.00"),
        budget_id=budget.id,
    )
    session.add(spouse_cash)
    session.add(lidl_card)
    session.commit()
    session.refresh(spouse_cash)
    session.refresh(lidl_card)
    assert spouse_cash.id and lidl_card.id

    # Spouse creates a MANUAL Lidl entry first (no itemized lines, her note & account)
    manual_res = client.post(
        "/api/transactions/manual",
        json={
            "merchant_name": "Lidl",
            "total_amount": 85.40,
            "currency": "PLN",
            "date": "2026-05-12T10:00:00Z",
            "account_id": spouse_cash.id,
            "note": "Zakupy żony",
        },
    )
    assert manual_res.status_code == 200
    manual_id = manual_res.json()["id"]

    # Incoming Lidl receipt arrives under auto_merge_policy="auto"
    lidl_res = ingest_receipt_result(
        session,
        _make_receipt_result(
            budget_id=budget.id,
            external_id="lidl-auto-dup-1",
            merchant_name="Lidl Polska",
            date_str="2026-05-12",
            total_amount=Decimal("85.40"),
            items=[
                CanonicalItem(name="Masło", unit_price=Decimal("15.40"), quantity=Decimal("1"), discount_total=Decimal("0.00")),
                CanonicalItem(name="Kawa", unit_price=Decimal("70.00"), quantity=Decimal("1"), discount_total=Decimal("0.00")),
            ],
        ),
        budget_id=budget.id,
        user_id=user.id,
        categorize=False,
        account_id=lidl_card.id,
        auto_merge_policy=AutoMergePolicy.AUTO.value,
        auto_approve_clean=True,
    )
    assert lidl_res.imported is True
    assert lidl_res.auto_merged is True
    assert lidl_res.transaction_id is not None

    # Surviving manual transaction retains spouse's account & note while gaining Lidl lines & SourceRecord
    txs = client.get("/api/transactions").json()
    assert len(txs) == 1
    assert txs[0]["id"] == manual_id
    assert txs[0]["account_id"] == spouse_cash.id
    assert txs[0]["note"] == "Zakupy żony"
    line_names = {line_item["name"] for line_item in txs[0]["lines"]}
    assert {"Masło", "Kawa"}.issubset(line_names)
    src_types = {sr["source_type"] for sr in txs[0]["source_records"]}
    assert src_types == {"MANUAL", "MERCHANT_API"}

    session.refresh(spouse_cash)
    session.refresh(lidl_card)
    assert spouse_cash.current_balance == Decimal("414.60")
    assert lidl_card.current_balance == Decimal("1000.00")

    # Merge is recorded as accepted RECEIPT_DUPLICATE link and is cleanly reversible via unlink
    links = client.get("/api/reconciliation/candidates?status=accepted").json()["candidates"]
    dup_link = next(link for link in links if link["match_kind"] == ReconciliationMatchKind.RECEIPT_DUPLICATE.value)

    unlink_res = client.post(f"/api/reconciliation/{dup_link['id']}/unlink")
    assert unlink_res.status_code == 200
    assert unlink_res.json()["link"]["status"] == ReconciliationStatus.UNLINKED.value

    txs_after_unlink = client.get("/api/transactions").json()
    inbox_after_unlink = client.get("/api/transactions/inbox?tab=exceptions").json()
    assert len(txs_after_unlink) == 1
    assert len(inbox_after_unlink) == 1
    restored_lines = session.exec(
        select(TransactionLine).where(TransactionLine.transaction_id == manual_id)
    ).all()
    assert [rl.name for rl in restored_lines] == ["Zakupy żony"]

    # Under manual policy, duplicate stays pending in Inbox/Reconciliation and does not auto-merge
    manual_dup = ingest_receipt_result(
        session,
        _make_receipt_result(
            budget_id=budget.id,
            external_id="lidl-manual-dup-2",
            merchant_name="Lidl Polska",
            date_str="2026-05-12",
            total_amount=Decimal("85.40"),
        ),
        budget_id=budget.id,
        user_id=user.id,
        categorize=False,
        account_id=lidl_card.id,
        auto_merge_policy=AutoMergePolicy.MANUAL.value,
        auto_approve_clean=True,
    )
    assert manual_dup.auto_merged is False
    assert manual_dup.pending_inbox is True
    pending_links = client.get("/api/reconciliation/candidates?status=pending").json()["candidates"]
    assert any(link["match_kind"] == ReconciliationMatchKind.RECEIPT_DUPLICATE.value for link in pending_links)


def test_deleted_imported_receipt_tombstone_prevents_resync_and_supports_restore_and_purge(
    client: TestClient, session: Session
):
    user, budget = _get_user_budget(session)
    assert user.id is not None and budget.id is not None

    checking = Account(
        name="Konto",
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

    result = _make_receipt_result(
        budget_id=budget.id,
        external_id="tombstone-lidl-001",
        merchant_name="Lidl Tombstone",
        date_str="2026-05-14",
        total_amount=Decimal("60.00"),
    )
    outcome = ingest_receipt_result(
        session,
        result,
        budget_id=budget.id,
        user_id=user.id,
        categorize=False,
        account_id=checking.id,
        auto_approve_clean=True,
    )
    assert outcome.imported is True and outcome.transaction_id is not None
    tx_id = outcome.transaction_id

    # Soft delete preserving provenance tombstone
    del_res = client.delete(f"/api/transactions/{tx_id}?preserve_source=true")
    assert del_res.status_code == 204

    assert client.get("/api/transactions").json() == []
    session.refresh(checking)
    assert checking.current_balance == Decimal("1000.00")

    rejected_list = client.get("/api/transactions/inbox?tab=rejected").json()
    assert len(rejected_list) == 1
    assert rejected_list[0]["id"] == tx_id
    assert len(rejected_list[0]["source_records"]) == 1

    # Re-importing same Lidl receipt skips cleanly (does NOT resurrect!)
    replay = ingest_receipt_result(
        session,
        result,
        budget_id=budget.id,
        user_id=user.id,
        categorize=False,
        account_id=checking.id,
    )
    assert replay.imported is False
    assert replay.skipped is True
    assert client.get("/api/transactions").json() == []
    assert client.get("/api/transactions/inbox?tab=exceptions").json() == []

    # Restore brings item back into Exceptions tab
    rest_res = client.post(f"/api/inbox/{tx_id}/restore")
    assert rest_res.status_code == 200
    assert rest_res.json()["review_status"] == ReviewStatus.PENDING.value
    assert len(client.get("/api/transactions/inbox?tab=exceptions").json()) == 1

    # Reject again then hard-purge ("Zapomnij trwale") allows fresh re-import
    assert client.post(f"/api/inbox/{tx_id}/reject", json={"reason": "test"}).status_code == 200
    assert client.delete(f"/api/transactions/{tx_id}").status_code == 204
    assert client.get("/api/transactions/inbox?tab=rejected").json() == []

    reimport_after_purge = ingest_receipt_result(
        session,
        result,
        budget_id=budget.id,
        user_id=user.id,
        categorize=False,
        account_id=checking.id,
    )
    assert reimport_after_purge.imported is True


def test_csv_dry_run_preview_and_required_account_plus_lidl_date_range_sync(
    client: TestClient, session: Session, monkeypatch: pytest.MonkeyPatch
):
    from app.services import AIService

    monkeypatch.setattr(AIService, "categorize_descriptions", lambda *args, **kwargs: {})
    user, budget = _get_user_budget(session)
    assert user.id is not None and budget.id is not None

    budget.created_at = datetime(2026, 2, 10, tzinfo=timezone.utc)
    session.add(budget)

    checking = Account(
        name="ING Bank",
        type="checking",
        currency="PLN",
        initial_balance=Decimal("2000.00"),
        current_balance=Decimal("2000.00"),
        budget_id=budget.id,
    )
    session.add(checking)
    session.commit()
    session.refresh(checking)
    assert checking.id is not None

    csv_content = (
        "Data transakcji;Kontrahent;Tytuł;Kwota;Waluta\n"
        "2026-05-15;Lidl 123;Zakupy karta;-80,00;PLN\n"
    )
    files = {"file": ("ing.csv", io.BytesIO(csv_content.encode("utf-8")), "text/csv")}

    # 1. Preview endpoint returns parsed summary without mutating DB
    preview_res = client.post("/api/transactions/import/preview", files=files)
    assert preview_res.status_code == 200, preview_res.text
    preview = preview_res.json()
    assert preview["total_rows"] == 1
    assert preview["new_count"] == 1
    assert preview["duplicate_count"] == 0
    assert preview["suggested_account_id"] == checking.id
    assert client.get("/api/transactions").json() == []

    # 2. require_account=true without account_id returns 422
    files_req = {"file": ("ing.csv", io.BytesIO(csv_content.encode("utf-8")), "text/csv")}
    err_res = client.post(
        "/api/transactions/import",
        files=files_req,
        data={"require_account": "true"},
    )
    assert err_res.status_code == 422

    # 3. Commit with account_id + auto_merge_policy=auto
    files_ok = {"file": ("ing.csv", io.BytesIO(csv_content.encode("utf-8")), "text/csv")}
    ok_res = client.post(
        "/api/transactions/import",
        files=files_ok,
        data={
            "account_id": str(checking.id),
            "auto_merge_policy": "auto",
            "require_account": "true",
        },
    )
    assert ok_res.status_code == 200
    assert ok_res.json()["created"] == 1
    session.refresh(checking)
    assert checking.current_balance == Decimal("1920.00")

    # 4. Connection settings & sync_from_date filtering + backfill reset
    conn = ExternalReceiptConnection(
        budget_id=budget.id,
        owner_user_id=user.id,
        provider="lidl",
        status=ConnectionStatus.ACTIVE,
        encrypted_refresh_token=get_encryption_service().encrypt("refresh-token")[0],
        encryption_key_id="v1",
    )
    session.add(conn)
    session.commit()
    session.refresh(conn)
    assert conn.id is not None

    patch_res = client.patch(
        f"/api/connections/{conn.id}/settings",
        json={
            "default_account_id": checking.id,
            "auto_merge_policy": "auto",
            "sync_from_date": "2026-04-10",
        },
    )
    assert patch_res.status_code == 200, patch_res.text
    patched = patch_res.json()
    assert patched["default_account_id"] == checking.id
    assert patched["budget_first_month_date"] == "2026-02-01"
    assert patched["sync_from_date"] == "2026-04-10"

    # Build two mock tickets: tkt-new (2026-04-17) & tkt-old (2026-03-01)
    class _FakeResp:
        def __init__(self, payload: dict[str, Any]):
            self.status_code = 200
            self._payload = payload
            self.headers: dict[str, str] = {}
            self.text = ""

        def json(self) -> dict[str, Any]:
            return self._payload

    class _RangeHttpSession:
        def post(self, url: str, **kwargs: Any) -> _FakeResp:
            return _FakeResp({"access_token": "tok", "refresh_token": "rt2"})

        def get(self, url: str, **kwargs: Any) -> _FakeResp:
            if "/api/v2/" in url:
                return _FakeResp(
                    {
                        "tickets": [
                            {"id": "tkt-new", "date": "2026-04-17T10:00:00Z"},
                            {"id": "tkt-old", "date": "2026-03-01T10:00:00Z"},
                        ]
                    }
                )
            tkt = copy.deepcopy(MOCK_LIDL_V3_TICKET)
            if "tkt-old" in url:
                tkt["id"] = "tkt-old"
                tkt["date"] = "2026-03-01T10:00:00"
            return _FakeResp(tkt)

    fake_client = LidlPoCClient(get_lidl_live_config(), session=_RangeHttpSession())

    # First sync with cutoff 2026-04-10 imports only tkt-new and stops before tkt-old
    sync_1 = ConnectionService.trigger_sync_now(
        session, budget.id, conn.id, user, execute_live=True, client_override=fake_client
    )
    assert sync_1.imported_count == 1

    # Seed pending job cursor to verify moving sync_from_date earlier resets cursor & backfills tkt-old
    job = ImportJob(
        provider="lidl",
        connection_id=conn.id,
        budget_id=budget.id,
        status=ImportJobStatus.PENDING,
        cursor="latest:tkt-new",
        correlation_id="corr-163",
    )
    session.add(job)
    session.commit()

    sync_2 = ConnectionService.trigger_sync_now(
        session,
        budget.id,
        conn.id,
        user,
        execute_live=True,
        client_override=fake_client,
        sync_from_date="2026-02-01",
    )
    assert sync_2.imported_count == 1
    assert sync_2.skipped_count == 1  # tkt-new deduplicated by SourceRecord!
