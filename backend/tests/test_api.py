import hashlib
from unittest.mock import patch, mock_open
from fastapi.testclient import TestClient
from sqlmodel import Session, select
from app.models import Transaction, TransactionLine, ReceiptScan, User

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
def test_upload_creates_transaction_and_scan(mock_bg, mock_file_open, mock_copy, client: TestClient, session: Session):
    file_content = b"fake_receipt_image_data"
    expected_hash = hashlib.sha256(file_content).hexdigest()

    response = client.post(
        "/api/transactions/upload",
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


def test_upload_duplicate_returns_409(client: TestClient, session: Session):
    file_content = b"known_duplicate_receipt"
    file_hash = hashlib.sha256(file_content).hexdigest()

    test_user = session.exec(select(User).where(User.email == "test@example.com")).first()
    transaction = Transaction(merchant_name="Original", uploaded_by=test_user.id, total_amount=30.0)
    session.add(transaction)
    session.commit()
    session.refresh(transaction)

    scan = ReceiptScan(transaction_id=transaction.id, status="done", content_hash=file_hash)
    session.add(scan)
    session.commit()

    response = client.post(
        "/api/transactions/upload",
        files={"file": ("receipt.jpg", file_content, "image/jpeg")},
    )
    assert response.status_code == 409


@patch("app.api.os.path.exists", return_value=True)
@patch("app.api.process_transaction_in_background")
def test_retry_uses_scan_status(mock_bg, mock_exists, client: TestClient, session: Session):
    test_user = session.exec(select(User).where(User.email == "test@example.com")).first()
    transaction = Transaction(merchant_name="Failed Shop", uploaded_by=test_user.id, total_amount=30.0)
    session.add(transaction)
    session.commit()
    session.refresh(transaction)

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
    transaction = Transaction(merchant_name="Old Shop", uploaded_by=test_user.id, total_amount=20.0)
    session.add(transaction)
    session.commit()
    session.refresh(transaction)

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
    # Set Budget
    payload = {"amount": 2500.0}
    response = client.post("/api/budget/2026/3", json=payload)
    assert response.status_code == 200
    assert response.json()["amount"] == 2500.0
    assert response.json()["year"] == 2026
    assert response.json()["month"] == 3

    # Get Budget
    response = client.get("/api/budget/2026/3")
    assert response.status_code == 200
    assert response.json()["amount"] == 2500.0
