import hashlib
from unittest.mock import patch, mock_open
from fastapi.testclient import TestClient
from sqlmodel import Session, select
from app.models import Transaction, TransactionLine, ReceiptScan, User, Budget, BudgetMember, Category, Tag


def test_health_check(client: TestClient):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "message": "Backend is running!"}


def test_create_manual_transaction(client: TestClient, session: Session):
    payload = {
        "merchant_name": "Test Store",
        "total_amount": 100.50,
        "currency": "PLN",
        "date": "2023-10-01T12:00:00Z",
        "type": "expense",
        "lines": [
            {"name": "Test Item 1", "price": 50.00, "quantity": 1},
            {"name": "Test Item 2", "price": 25.25, "quantity": 2},
        ],
    }

    response = client.post("/api/transactions/manual", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["merchant_name"] == "Test Store"
    assert data["total_amount"] == 100.50
    assert data["is_manual"] is True
    assert data["type"] == "expense"
    assert len(data["lines"]) == 2

    # Verify DB state
    db_transaction = session.exec(select(Transaction).where(Transaction.id == data["id"])).first()
    assert db_transaction is not None
    assert db_transaction.merchant_name == "Test Store"

    lines = session.exec(select(TransactionLine).where(TransactionLine.transaction_id == db_transaction.id)).all()
    assert len(lines) == 2


def test_manual_transaction_receipt_scan_is_null(client: TestClient, session: Session):
    payload = {
        "merchant_name": "Manual Store",
        "total_amount": 75.0,
        "currency": "PLN",
        "type": "expense",
    }
    response = client.post("/api/transactions/manual", json=payload)
    assert response.status_code == 200
    assert response.json()["receipt_scan"] is None


@patch("app.api.shutil.copyfileobj")
@patch("builtins.open", new_callable=mock_open)
@patch("app.api.process_transaction_in_background")
def test_scan_creates_transaction_and_scan(mock_bg, mock_file_open, mock_copy, client: TestClient, session: Session):
    file_content = b"fake_receipt_image_data"
    expected_hash = hashlib.sha256(file_content).hexdigest()

    response = client.post(
        "/api/transactions/scan",
        files={"file": ("receipt.jpg", file_content, "image/jpeg")},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["merchant_name"] == "Processing..."
    assert data["receipt_scan"] is not None
    assert data["receipt_scan"]["status"] == "processing"
    assert data["receipt_scan"]["content_hash"] == expected_hash

    scan = session.exec(select(ReceiptScan).where(ReceiptScan.transaction_id == data["id"])).first()
    assert scan is not None
    assert scan.content_hash == expected_hash


def test_scan_duplicate_returns_409(client: TestClient, session: Session):
    file_content = b"known_duplicate_receipt"
    file_hash = hashlib.sha256(file_content).hexdigest()

    test_user = session.exec(select(User).where(User.email == "test@example.com")).first()
    assert test_user is not None
    test_budget = session.exec(select(Budget).where(Budget.name == "Domowy")).first()
    assert test_budget is not None
    transaction = Transaction(merchant_name="Original", uploaded_by=test_user.id, budget_id=test_budget.id, total_amount=30.0)
    session.add(transaction)
    session.commit()
    session.refresh(transaction)

    assert transaction.id is not None
    scan = ReceiptScan(transaction_id=transaction.id, status="done", content_hash=file_hash)
    session.add(scan)
    session.commit()

    response = client.post(
        "/api/transactions/scan",
        files={"file": ("receipt.jpg", file_content, "image/jpeg")},
    )
    assert response.status_code == 409


@patch("app.api.os.path.exists", return_value=True)
@patch("app.api.process_transaction_in_background")
def test_retry_uses_scan_status(mock_bg, mock_exists, client: TestClient, session: Session):
    test_user = session.exec(select(User).where(User.email == "test@example.com")).first()
    assert test_user is not None
    test_budget = session.exec(select(Budget).where(Budget.name == "Domowy")).first()
    assert test_budget is not None
    transaction = Transaction(merchant_name="Failed Shop", uploaded_by=test_user.id, budget_id=test_budget.id, total_amount=30.0)
    session.add(transaction)
    session.commit()
    session.refresh(transaction)

    assert transaction.id is not None
    scan = ReceiptScan(transaction_id=transaction.id, status="error", image_path="/fake/path/image.jpg")
    session.add(scan)
    session.commit()
    session.refresh(scan)
    scan_id = scan.id

    response = client.post(f"/api/transactions/{transaction.id}/retry")
    assert response.status_code == 200

    session.refresh(scan)
    assert scan.status == "processing"
    mock_bg.assert_called_once_with(transaction.id, scan_id, "/fake/path/image.jpg")


def test_delete_removes_receipt_scan(client: TestClient, session: Session):
    test_user = session.exec(select(User).where(User.email == "test@example.com")).first()
    assert test_user is not None
    test_budget = session.exec(select(Budget).where(Budget.name == "Domowy")).first()
    assert test_budget is not None
    transaction = Transaction(merchant_name="Old Shop", uploaded_by=test_user.id, budget_id=test_budget.id, total_amount=20.0)
    session.add(transaction)
    session.commit()
    session.refresh(transaction)

    assert transaction.id is not None
    scan = ReceiptScan(transaction_id=transaction.id, status="done", image_path=None)
    session.add(scan)
    session.commit()
    scan_id = scan.id
    transaction_id = transaction.id

    response = client.delete(f"/api/transactions/{transaction_id}")
    assert response.status_code == 204

    assert session.get(Transaction, transaction_id) is None
    assert session.get(ReceiptScan, scan_id) is None


def test_set_and_get_budget(client: TestClient, session: Session):
    test_budget = session.exec(select(Budget).where(Budget.name == "Domowy")).first()
    assert test_budget is not None

    # Set MonthlyBudget
    payload = {"amount": 2500.0}
    response = client.post("/api/budget/2026/3", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["amount"] == 2500.0
    assert data["year"] == 2026
    assert data["month"] == 3
    assert data["budget_id"] == test_budget.id

    # Get MonthlyBudget
    response = client.get("/api/budget/2026/3")
    assert response.status_code == 200
    data = response.json()
    assert data["amount"] == 2500.0
    assert data["budget_id"] == test_budget.id


# --- AUTH ---

def test_register_creates_default_budget(client: TestClient, session: Session):
    """Registering a new user must create a Budget and BudgetMember with role='owner'."""
    from app.api import get_current_budget
    # Remove overrides so the real register logic runs (no auth needed for /register)
    from app.main import app as _app
    _app.dependency_overrides.pop(get_current_budget, None)

    payload = {"email": "newuser@example.com", "password": "secret123"}
    response = client.post("/api/auth/register", json=payload)
    assert response.status_code == 200
    token_data = response.json()
    assert "access_token" in token_data

    new_user = session.exec(select(User).where(User.email == "newuser@example.com")).first()
    assert new_user is not None

    budget = session.exec(select(Budget).where(Budget.owner_id == new_user.id)).first()
    assert budget is not None
    assert budget.name == "Domowy"

    membership = session.exec(
        select(BudgetMember).where(
            BudgetMember.user_id == new_user.id,
            BudgetMember.budget_id == budget.id,
        )
    ).first()
    assert membership is not None
    assert membership.role == "owner"


# --- DEPENDENCY: get_current_budget ---

def test_get_current_budget_lazy_creates_for_user_without_budget(session: Session):
    """get_current_budget must create a Budget on-the-fly for users missing one."""
    from app.api import get_current_budget

    orphan_user = User(email="orphan@example.com", hashed_password="x")
    session.add(orphan_user)
    session.commit()
    session.refresh(orphan_user)

    # Confirm no membership exists yet
    assert session.exec(select(BudgetMember).where(BudgetMember.user_id == orphan_user.id)).first() is None

    budget = get_current_budget(current_user=orphan_user, session=session)

    assert budget.id is not None
    assert budget.name == "Domowy"
    assert budget.owner_id == orphan_user.id

    membership = session.exec(
        select(BudgetMember).where(BudgetMember.user_id == orphan_user.id)
    ).first()
    assert membership is not None
    assert membership.role == "owner"
    assert membership.budget_id == budget.id


def test_get_current_budget_returns_existing(session: Session):
    """get_current_budget must return existing Budget without creating a new one."""
    from app.api import get_current_budget

    user = User(email="existing@example.com", hashed_password="x")
    session.add(user)
    session.commit()
    session.refresh(user)

    existing_budget = Budget(name="Rodzinny", owner_id=user.id)
    session.add(existing_budget)
    session.commit()
    session.refresh(existing_budget)
    session.add(BudgetMember(budget_id=existing_budget.id, user_id=user.id, role="owner"))
    session.commit()

    budget = get_current_budget(current_user=user, session=session)

    assert budget.id == existing_budget.id
    # No extra budgets should have been created
    all_budgets = session.exec(select(Budget).where(Budget.owner_id == user.id)).all()
    assert len(all_budgets) == 1


# --- CATEGORIES ---

def test_create_and_get_category_uses_budget_id(client: TestClient, session: Session):
    """Categories must be scoped to budget_id, not owner_id."""
    test_budget = session.exec(select(Budget).where(Budget.name == "Domowy")).first()
    assert test_budget is not None

    payload = {"name": "Groceries", "icon": "🛒", "color": "#00ff00"}
    response = client.post("/api/categories", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Groceries"
    assert data["budget_id"] == test_budget.id
    assert "owner_id" not in data

    # Verify in DB
    cat = session.get(Category, data["id"])
    assert cat is not None
    assert cat.budget_id == test_budget.id

    # GET must return it
    response = client.get("/api/categories")
    assert response.status_code == 200
    names = [c["name"] for c in response.json()]
    assert "Groceries" in names


def test_category_from_other_budget_not_visible(client: TestClient, session: Session):
    """Categories belonging to a different budget must not be returned."""
    other_user = User(email="other@example.com", hashed_password="x")
    session.add(other_user)
    session.commit()
    session.refresh(other_user)

    other_budget = Budget(name="Cudzy", owner_id=other_user.id)
    session.add(other_budget)
    session.commit()
    session.refresh(other_budget)

    other_cat = Category(name="Hidden Category", budget_id=other_budget.id, is_system=False)
    session.add(other_cat)
    session.commit()

    response = client.get("/api/categories")
    assert response.status_code == 200
    names = [c["name"] for c in response.json()]
    assert "Hidden Category" not in names


# --- TAGS ---

def test_create_and_get_tag_uses_budget_id(client: TestClient, session: Session):
    """Tags must be scoped to budget_id, not owner_id."""
    test_budget = session.exec(select(Budget).where(Budget.name == "Domowy")).first()
    assert test_budget is not None

    payload = {"name": "urgent", "color": "#ff0000"}
    response = client.post("/api/tags", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "urgent"
    assert data["budget_id"] == test_budget.id
    assert "owner_id" not in data

    tag = session.get(Tag, data["id"])
    assert tag is not None
    assert tag.budget_id == test_budget.id

    response = client.get("/api/tags")
    assert response.status_code == 200
    names = [t["name"] for t in response.json()]
    assert "urgent" in names


def test_tag_from_other_budget_not_visible(client: TestClient, session: Session):
    """Tags belonging to a different budget must not be returned."""
    other_user = User(email="tagother@example.com", hashed_password="x")
    session.add(other_user)
    session.commit()
    session.refresh(other_user)

    other_budget = Budget(name="Cudzy2", owner_id=other_user.id)
    session.add(other_budget)
    session.commit()
    session.refresh(other_budget)

    other_tag = Tag(name="hidden-tag", budget_id=other_budget.id)
    session.add(other_tag)
    session.commit()

    response = client.get("/api/tags")
    assert response.status_code == 200
    names = [t["name"] for t in response.json()]
    assert "hidden-tag" not in names
