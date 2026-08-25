from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.models import Account, Transaction


def _create_account(client: TestClient, name: str, **overrides: object) -> dict:
    payload = {
        "name": name,
        "type": "checking",
        "currency": "PLN",
        "initial_balance": 0,
        "is_on_budget": True,
    }
    payload.update(overrides)
    response = client.post("/api/accounts", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def _create_transaction(client: TestClient, account_id: int, amount: float, transaction_type: str) -> dict:
    response = client.post(
        "/api/transactions/manual",
        json={
            "merchant_name": "Account test",
            "total_amount": amount,
            "currency": "PLN",
            "type": transaction_type,
            "account_id": account_id,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _balance(session: Session, account_id: int) -> float:
    account = session.get(Account, account_id)
    assert account is not None
    session.refresh(account)
    return account.current_balance


def test_account_crud_validates_input_and_soft_deletes(client: TestClient, session: Session):
    created = _create_account(client, "  Savings  ", type="savings", currency="eur")
    assert created["name"] == "Savings"
    assert created["type"] == "savings"
    assert created["currency"] == "EUR"

    response = client.patch(
        f"/api/accounts/{created['id']}",
        json={"name": "Emergency fund", "type": "cash"},
    )
    assert response.status_code == 200
    assert response.json()["name"] == "Emergency fund"
    assert response.json()["type"] == "cash"

    assert client.post("/api/accounts", json={"name": "   "}).status_code == 422
    assert client.post("/api/accounts", json={"name": "Invalid", "type": "brokerage"}).status_code == 422
    assert client.patch(f"/api/accounts/{created['id']}", json={"current_balance": 999}).status_code == 422

    assert client.delete(f"/api/accounts/{created['id']}").status_code == 204
    assert created["id"] not in {account["id"] for account in client.get("/api/accounts").json()}
    deleted = session.get(Account, created["id"])
    assert deleted is not None and deleted.is_active is False


def test_initial_balance_creates_adjustment_transaction(client: TestClient, session: Session):
    created = _create_account(client, "Opening balance", initial_balance=125.5)
    assert created["current_balance"] == 125.5

    opening_transaction = session.exec(
        select(Transaction).where(Transaction.account_id == created["id"])
    ).one()
    assert opening_transaction.type == "income"
    assert opening_transaction.total_amount == 125.5
    assert opening_transaction.note == "Auto-generated initial balance"


def test_transaction_mutations_recalculate_both_account_balances(client: TestClient, session: Session):
    source = _create_account(client, "Source")
    destination = _create_account(client, "Destination")

    _create_transaction(client, source["id"], 100, "income")
    expense = _create_transaction(client, source["id"], 30, "expense")
    assert _balance(session, source["id"]) == 70

    assert client.patch(f"/api/transactions/{expense['id']}", json={"total_amount": 10}).status_code == 200
    assert _balance(session, source["id"]) == 90

    assert client.patch(f"/api/transactions/{expense['id']}", json={"account_id": destination["id"]}).status_code == 200
    assert _balance(session, source["id"]) == 100
    assert _balance(session, destination["id"]) == -10

    assert client.delete(f"/api/transactions/{expense['id']}").status_code == 204
    assert _balance(session, destination["id"]) == 0
    assert _balance(session, source["id"]) == 100

    transfer = _create_transaction(client, source["id"], 40, "transfer")
    assert client.patch(
        f"/api/transactions/{transfer['id']}",
        json={"transfer_id": destination["id"]},
    ).status_code == 200
    assert _balance(session, source["id"]) == 60
    assert _balance(session, destination["id"]) == 40

    assert client.patch(f"/api/transactions/{transfer['id']}", json={"total_amount": 25}).status_code == 200
    assert _balance(session, source["id"]) == 75
    assert _balance(session, destination["id"]) == 25

    assert client.delete(f"/api/transactions/{transfer['id']}").status_code == 204
    assert _balance(session, source["id"]) == 100
    assert _balance(session, destination["id"]) == 0


def test_creating_budget_seeds_required_cash_account(client: TestClient, session: Session):
    response = client.post("/api/budgets", json={"name": "New household"})
    assert response.status_code == 200
    budget_id = response.json()["id"]

    accounts = session.exec(select(Account).where(Account.budget_id == budget_id)).all()
    assert len(accounts) == 1
    assert accounts[0].name == "Cash"
    assert accounts[0].currency == "PLN"
    assert accounts[0].type == "checking"
