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
    for alloc in allocations:
        assert alloc.year == now.year
        assert alloc.month == now.month
        assert alloc.amount > 0

    # Transactions & Inboxes
    transactions = session.exec(select(Transaction).where(Transaction.budget_id == budget.id)).all()
    assert len(transactions) >= 20

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
