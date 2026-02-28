from fastapi.testclient import TestClient
from sqlmodel import Session, select
from app.models import Receipt

def test_health_check(client: TestClient):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "message": "Backend is running!"}

def test_create_manual_receipt(client: TestClient, session: Session):
    payload = {
        "merchant_name": "Test Store",
        "total_amount": 100.50,
        "currency": "PLN",
        "date": "2023-10-01T12:00:00Z",
        "items": [
            {
                "name": "Test Item 1",
                "price": 50.00,
                "quantity": 1,
                "category": "Food"
            },
            {
                "name": "Test Item 2",
                "price": 25.25,
                "quantity": 2,
                "category": "Household"
            }
        ]
    }

    response = client.post("/api/receipts/manual", json=payload)
    
    assert response.status_code == 200
    data = response.json()
    assert data["merchant_name"] == "Test Store"
    assert data["total_amount"] == 100.50
    assert data["is_manual"] is True
    
    # Verify DB state
    db_receipt = session.exec(select(Receipt).where(Receipt.id == data["id"])).first()
    assert db_receipt is not None
    assert db_receipt.merchant_name == "Test Store"

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
