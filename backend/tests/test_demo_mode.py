# backend/tests/test_demo_mode.py
import pytest
from datetime import datetime, timezone
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.api import get_current_budget
from app.auth import get_current_user, get_current_user_optional
from app.config import settings
from app.demo_seed import seed_demo_environment
from app.main import app
from app.models import (
    Account,
    Budget,
    Category,
    EnvelopeAllocation,
    ReceiptScan,
    ScanStatus,
    Transaction,
    TransactionLine,
    TransactionStatus,
    User,
)


def test_seed_demo_environment_creates_rich_dataset(session: Session):
    """Verify that seed_demo_environment creates all expected entities with valid relations."""
    user = seed_demo_environment(session, force_reset=True)
    assert user.email == settings.DEMO_USER_EMAIL
    assert user.default_budget_id is not None

    budget = session.get(Budget, user.default_budget_id)
    assert budget is not None
    assert budget.name == "Budżet Domowy (Demo)"

    # 3 Accounts
    accounts = session.exec(select(Account).where(Account.budget_id == budget.id)).all()
    assert len(accounts) == 3
    acc_names = {a.name for a in accounts}
    assert "Konto Główne ROR (mBank)" in acc_names
    assert "Konto Oszczędnościowe (ING)" in acc_names
    assert "Portfel / Gotówka" in acc_names

    # Categories & Allocations
    categories = session.exec(select(Category).where(Category.budget_id == budget.id)).all()
    assert len(categories) > 0

    allocations = session.exec(select(EnvelopeAllocation).where(EnvelopeAllocation.budget_id == budget.id)).all()
    assert len(allocations) > 0
    now = datetime.now(timezone.utc)
    prev_month = 12 if now.month == 1 else now.month - 1
    for alloc in allocations:
        assert alloc.month in (now.month, prev_month)
        assert alloc.amount > 0

    # Current month allocations sum to 6500 PLN (leaving 500 PLN buffer from 7000 PLN income)
    cur_allocations = [a for a in allocations if a.year == now.year and a.month == now.month]
    assert sum(a.amount for a in cur_allocations) == 6500.00

    # Transactions & Inboxes
    transactions = session.exec(select(Transaction).where(Transaction.budget_id == budget.id)).all()
    assert len(transactions) >= 40

    cur_txs = [
        t for t in transactions
        if t.date and t.date.year == now.year and t.date.month == now.month and t.status == TransactionStatus.CLEARED
    ]
    cur_income = sum(t.total_amount for t in cur_txs if t.type == "income")
    cur_cleared_expenses = sum(t.total_amount for t in cur_txs if t.type == "expense")
    assert cur_income == 7000.00
    assert cur_cleared_expenses == 6373.20

    # Including the 2 staged inbox receipts (84.50 + 42.30 = 126.80 PLN), total expenses for the month are exactly 6500 PLN
    all_cur_expenses = sum(
        t.total_amount for t in transactions
        if t.date and t.date.year == now.year and t.date.month == now.month and t.type == "expense"
    )
    assert all_cur_expenses == 6500.00
    assert (cur_income - all_cur_expenses) == 500.00

    # Check the 2 staged receipts in Inbox
    scans = session.exec(
        select(ReceiptScan)
        .join(Transaction)
        .where(Transaction.budget_id == budget.id)
    ).all()
    assert len(scans) == 2
    for scan in scans:
        assert scan.status == ScanStatus.NEEDS_REVIEW.value
        assert scan.needs_review is True
        assert scan.reconstructed_lines is not None

    # Check lines of the staged transactions
    for scan in scans:
        lines = session.exec(
            select(TransactionLine).where(TransactionLine.transaction_id == scan.transaction_id)
        ).all()
        assert len(lines) >= 3

    # Check that historical store transactions also have concrete line items
    # and their sums match transaction totals exactly
    all_lines = session.exec(
        select(TransactionLine)
        .join(Transaction)
        .where(Transaction.budget_id == budget.id)
    ).all()
    assert len(all_lines) >= 40

    store_transactions = [
        t for t in transactions
        if t.merchant_name in ("Biedronka", "Lidl", "Rossmann", "Żabka", "Orlen", "Apteka Gemini")
    ]
    assert len(store_transactions) >= 6
    for st in store_transactions:
        lines = session.exec(
            select(TransactionLine).where(TransactionLine.transaction_id == st.id)
        ).all()
        assert len(lines) >= 1
        lines_sum = sum(line.price * line.quantity for line in lines)
        assert lines_sum == pytest.approx(st.total_amount, abs=0.01)


def test_seed_demo_environment_idempotency(session: Session):
    """Repeated calls with force_reset=False must not duplicate users, accounts, or transactions."""
    seed_demo_environment(session, force_reset=True)
    initial_user = session.exec(select(User).where(User.email == settings.DEMO_USER_EMAIL)).first()
    assert initial_user is not None
    initial_budget_id = initial_user.default_budget_id

    initial_tx_count = len(session.exec(select(Transaction).where(Transaction.budget_id == initial_budget_id)).all())
    initial_acc_count = len(session.exec(select(Account).where(Account.budget_id == initial_budget_id)).all())

    # Second run without force_reset
    second_user = seed_demo_environment(session, force_reset=False)
    assert second_user.id == initial_user.id
    assert second_user.default_budget_id == initial_budget_id

    tx_count_after = len(session.exec(select(Transaction).where(Transaction.budget_id == initial_budget_id)).all())
    acc_count_after = len(session.exec(select(Account).where(Account.budget_id == initial_budget_id)).all())

    assert tx_count_after == initial_tx_count
    assert acc_count_after == initial_acc_count


def test_demo_budget_summary_auto_seeds_new_month(client: TestClient, session: Session):
    """Accessing a future or new month summary auto-seeds fresh income and expenses for demo user."""
    demo_user = seed_demo_environment(session, force_reset=True)
    demo_budget = session.get(Budget, demo_user.default_budget_id)

    app.dependency_overrides[get_current_user] = lambda: demo_user
    app.dependency_overrides[get_current_user_optional] = lambda: demo_user
    app.dependency_overrides[get_current_budget] = lambda: demo_budget

    # Target a future month (e.g. month=7 of next year)
    future_year = 2027
    future_month = 7

    response = client.get(f"/api/budget/{future_year}/{future_month}/summary")
    assert response.status_code == 200, response.text
    summary = response.json()

    assert summary["total_income"] == 7000.00
    assert summary["total_spent"] == 6500.00
    assert summary["net_cash_flow"] == 500.00
    assert summary["total_planned"] == 6500.00


def test_auth_demo_endpoint(client: TestClient, session: Session):
    """POST /api/auth/demo should authenticate demo user and return valid token."""
    # Ensure dependency overrides use our test session
    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(get_current_budget, None)

    response = client.post("/api/auth/demo")
    assert response.status_code == 200, response.text
    data = response.json()

    assert "access_token" in data
    assert data["user"]["email"] == settings.DEMO_USER_EMAIL
    assert data["user"]["default_budget_id"] is not None


def test_demo_inbox_staging_receipts(client: TestClient, session: Session):
    """Demo user can fetch staged receipts from /api/transactions/inbox."""
    demo_user = seed_demo_environment(session, force_reset=True)
    demo_budget = session.get(Budget, demo_user.default_budget_id)

    app.dependency_overrides[get_current_user] = lambda: demo_user
    app.dependency_overrides[get_current_budget] = lambda: demo_budget

    response = client.get("/api/transactions/inbox")
    assert response.status_code == 200, response.text
    inbox_items = response.json()

    assert len(inbox_items) == 2
    merchants = {item["merchant_name"] for item in inbox_items}
    assert "Biedronka" in merchants
    assert "Lidl" in merchants


def test_demo_security_guards(client: TestClient, session: Session):
    """Demo user cannot modify profile, change password, or delete their budget."""
    demo_user = seed_demo_environment(session, force_reset=True)
    demo_budget = session.get(Budget, demo_user.default_budget_id)

    app.dependency_overrides[get_current_user] = lambda: demo_user
    app.dependency_overrides[get_current_budget] = lambda: demo_budget

    # 1. PATCH /api/users/me -> 403
    patch_res = client.patch("/api/users/me", json={"default_budget_id": 999})
    assert patch_res.status_code == 403
    assert "Demo account profile cannot be modified" in patch_res.text

    # 2. POST /api/auth/change-password -> 403
    pw_res = client.post("/api/auth/change-password", json={"old_password": "any", "new_password": "newpass123"})
    assert pw_res.status_code == 403
    assert "Demo account password cannot be changed" in pw_res.text

    # 3. DELETE /api/budgets/{id} -> 403
    del_res = client.delete(f"/api/budgets/{demo_budget.id}")
    assert del_res.status_code == 403
    assert "Demo budget cannot be deleted" in del_res.text

    # 4. POST /api/budgets -> 403
    post_b_res = client.post("/api/budgets", json={"name": "Nowy Budżet"})
    assert post_b_res.status_code == 403
    assert "Budget creation is disabled in demo mode" in post_b_res.text

    # 5. PATCH /api/budgets/{id} -> 403
    patch_b_res = client.patch(f"/api/budgets/{demo_budget.id}", json={"name": "Zmieniona Nazwa"})
    assert patch_b_res.status_code == 403
    assert "Demo budget cannot be modified" in patch_b_res.text

    # 6. POST /api/budget/members -> 403
    member_res = client.post("/api/budget/members", json={"email": "member@example.com", "role": "editor"})
    assert member_res.status_code == 403
    assert "Inviting budget members is disabled in demo mode" in member_res.text

    # 7. POST /api/transactions/import -> 403
    import_res = client.post(
        "/api/transactions/import",
        files={"file": ("test.csv", b"Date,Amount,Merchant\n2026-01-01,10.00,Test", "text/csv")},
    )
    assert import_res.status_code == 403
    assert "CSV import is disabled in demo mode" in import_res.text


def test_demo_reset_endpoint_access_control(client: TestClient, session: Session):
    """POST /api/auth/demo/reset is guarded based on demo user or DEMO_MODE flag."""
    demo_user = seed_demo_environment(session, force_reset=True)
    regular_user = User(email="regular@example.com", hashed_password="hashed_pwd")
    session.add(regular_user)
    session.commit()
    session.refresh(regular_user)

    # When DEMO_MODE is False:
    settings.DEMO_MODE = False

    # 1. Regular user trying to reset demo data -> 403
    app.dependency_overrides[get_current_user_optional] = lambda: regular_user
    res = client.post("/api/auth/demo/reset")
    assert res.status_code == 403

    # 2. Anonymous user trying to reset demo data when DEMO_MODE=False -> 403
    app.dependency_overrides[get_current_user_optional] = lambda: None
    res = client.post("/api/auth/demo/reset")
    assert res.status_code == 403

    # 3. Demo user resetting demo data -> 200 OK
    app.dependency_overrides[get_current_user_optional] = lambda: demo_user
    res = client.post("/api/auth/demo/reset")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"

    # 4. Anonymous user when DEMO_MODE=True -> 200 OK
    settings.DEMO_MODE = True
    app.dependency_overrides[get_current_user_optional] = lambda: None
    res = client.post("/api/auth/demo/reset")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"

    # Restore settings
    settings.DEMO_MODE = False


@pytest.mark.asyncio
async def test_demo_mode_ocr_mock(session: Session):
    """In DEMO_MODE=True, _process_scan simulates receipt parsing without external AI calls."""
    from unittest.mock import patch
    from app.api import _process_scan

    demo_user = seed_demo_environment(session, force_reset=True)
    demo_budget = session.get(Budget, demo_user.default_budget_id)

    # Create dummy transaction and queued scan
    tx = Transaction(
        merchant_name="Processing...",
        budget_id=demo_budget.id,
        uploaded_by=demo_user.id,
    )
    session.add(tx)
    session.commit()
    session.refresh(tx)

    scan = ReceiptScan(
        transaction_id=tx.id,
        status=ScanStatus.QUEUED.value,
        image_path="/tmp/fake_demo_receipt.jpg",
    )
    session.add(scan)
    session.commit()
    session.refresh(scan)

    # Enable DEMO_MODE and bind operations_engine to test session
    settings.DEMO_MODE = True
    try:
        with patch("app.api.operations_engine", session.bind):
            await _process_scan(scan_id=scan.id, transaction_id=tx.id, image_path="/tmp/fake_demo_receipt.jpg")

        # Verify processed scan
        session.refresh(scan)
        session.refresh(tx)

        assert tx.merchant_name == "Biedronka (Demo)"
        assert tx.total_amount == 47.90
        assert scan.status in (ScanStatus.CATEGORIZATION_OK.value, ScanStatus.NEEDS_REVIEW.value, ScanStatus.PARSING_OK.value)

        lines = session.exec(select(TransactionLine).where(TransactionLine.transaction_id == tx.id)).all()
        assert len(lines) == 4
        item_names = [line.name for line in lines]
        assert "Mleko Świeże 3.2% 1L" in item_names
    finally:
        settings.DEMO_MODE = False


def test_ephemeral_demo_session_isolation(client: TestClient, session: Session):
    """Different X-Demo-Session-ID headers produce isolated users and budgets."""
    res1 = client.post("/api/auth/demo", headers={"X-Demo-Session-ID": "session_alpha_123"})
    assert res1.status_code == 200
    data1 = res1.json()
    assert data1["user"]["email"] == "demo_session_alpha_123@rachownik.app"

    res2 = client.post("/api/auth/demo", headers={"X-Demo-Session-ID": "session_beta_456"})
    assert res2.status_code == 200
    data2 = res2.json()
    assert data2["user"]["email"] == "demo_session_beta_456@rachownik.app"

    assert data1["user"]["id"] != data2["user"]["id"]
    assert data1["user"]["default_budget_id"] != data2["user"]["default_budget_id"]


def test_demo_quota_endpoint_and_limit(client: TestClient, session: Session):
    """Demo user is limited to 5 successful custom uploads per day."""
    ephemeral_user = User(
        email="demo_quota_test@rachownik.app",
        hashed_password="pw",
        created_at=datetime.now(timezone.utc),
    )
    session.add(ephemeral_user)
    session.commit()
    session.refresh(ephemeral_user)
    seed_demo_environment(session, force_reset=False, custom_user=ephemeral_user)
    budget = session.get(Budget, ephemeral_user.default_budget_id)

    app.dependency_overrides[get_current_user] = lambda: ephemeral_user
    app.dependency_overrides[get_current_budget] = lambda: budget

    # Initially 0 used of 5
    q_res = client.get("/api/demo/quota")
    assert q_res.status_code == 200
    q_data = q_res.json()
    assert q_data["is_demo"] is True
    assert q_data["daily_limit"] == 5
    assert q_data["used"] == 0
    assert q_data["remaining"] == 5
    assert q_data["can_scan"] is True

    # Add 5 scans for this user today
    for i in range(5):
        t = Transaction(merchant_name=f"Tx {i}", budget_id=budget.id, uploaded_by=ephemeral_user.id)
        session.add(t)
        session.commit()
        session.refresh(t)
        scan = ReceiptScan(
            transaction_id=t.id,
            status=ScanStatus.DONE.value,
            content_hash=f"hash_{i}",
            created_at=datetime.now(timezone.utc),
        )
        session.add(scan)
        session.commit()

    q_res2 = client.get("/api/demo/quota")
    assert q_res2.json()["remaining"] == 0
    assert q_res2.json()["can_scan"] is False

    # Attempt 6th scan -> should return HTTP 429
    upload_res = client.post(
        "/api/transactions/scan",
        files={"file": ("receipt.jpg", b"dummy image bytes", "image/jpeg")},
    )
    assert upload_res.status_code == 429
    assert "Dzienny limit 5 skanów demonstracyjnych" in upload_res.text


def test_demo_sample_scan_endpoint(client: TestClient, session: Session):
    """POST /api/transactions/scan-sample creates transaction from curated sample."""
    demo_user = seed_demo_environment(session, force_reset=True)
    demo_budget = session.get(Budget, demo_user.default_budget_id)

    app.dependency_overrides[get_current_user] = lambda: demo_user
    app.dependency_overrides[get_current_budget] = lambda: demo_budget

    res = client.post("/api/transactions/scan-sample?sample_id=biedronka")
    assert res.status_code == 200
    tx_data = res.json()
    assert "Biedronka (Wzorzec)" in tx_data["merchant_name"]


def test_receipt_validator_plausibility():
    """Verify ReceiptValidator.is_plausible_receipt_text."""
    from app.receipt_validator import ReceiptValidator

    valid_text = "BIEDRONKA SP Z O O ... NIP 779-101-13-27 ... PARAGON FISKALNY ... SUMA PLN 101,74"
    is_valid, reason = ReceiptValidator.is_plausible_receipt_text(valid_text)
    assert is_valid is True
    assert reason == "OK"

    dog_text = "Cute golden retriever playing in the grass with a tennis ball on Sunday afternoon"
    is_valid, reason = ReceiptValidator.is_plausible_receipt_text(dog_text)
    assert is_valid is False
    assert reason in ("MISSING_RECEIPT_KEYWORDS", "MISSING_PRICE_PATTERNS")


def test_cleanup_expired_demo_sessions(session: Session):
    """Verify cleanup_expired_demo_sessions removes users and budgets >24h old."""
    from app.demo_seed import cleanup_expired_demo_sessions
    from datetime import timedelta

    # 1. User created 30 hours ago (should be cleaned)
    old_user = User(
        email="demo_old_12345@rachownik.app",
        hashed_password="pw",
        created_at=datetime.now(timezone.utc) - timedelta(hours=30),
    )
    session.add(old_user)
    session.commit()
    session.refresh(old_user)
    seed_demo_environment(session, force_reset=False, custom_user=old_user)

    # 2. User created 2 hours ago (should NOT be cleaned)
    recent_user = User(
        email="demo_recent_67890@rachownik.app",
        hashed_password="pw",
        created_at=datetime.now(timezone.utc) - timedelta(hours=2),
    )
    session.add(recent_user)
    session.commit()
    session.refresh(recent_user)
    seed_demo_environment(session, force_reset=False, custom_user=recent_user)

    removed = cleanup_expired_demo_sessions(session, max_age_hours=24)
    assert removed >= 1

    # old_user should be deleted
    assert session.get(User, old_user.id) is None
    # recent_user should still exist
    assert session.get(User, recent_user.id) is not None


def test_get_app_config(client: TestClient):
    """Verify /api/config returns demo_mode and environment without authentication."""
    response = client.get("/api/config")
    assert response.status_code == 200
    data = response.json()
    assert "demo_mode" in data
    assert "environment" in data

