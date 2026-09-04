from datetime import datetime, timezone
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.models import Account


def _create_account(client: TestClient, name: str, is_on_budget: bool = True, account_type: str = "checking") -> dict:
    response = client.post(
        "/api/accounts",
        json={
            "name": name,
            "type": account_type,
            "currency": "PLN",
            "initial_balance": 1000.0,
            "is_on_budget": is_on_budget,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _get_or_create_category_id(client: TestClient) -> int:
    res = client.get("/api/categories")
    categories = res.json()
    if categories:
        return categories[0]["id"]
    created = client.post(
        "/api/categories",
        json={"name": "Investments", "icon": "trending-up", "color": "#10b981"},
    )
    assert created.status_code == 200, created.text
    return created.json()["id"]


def _balance(session: Session, account_id: int) -> float:
    account = session.get(Account, account_id)
    assert account is not None
    session.refresh(account)
    return account.current_balance


def test_create_transfer_endpoint(client: TestClient, session: Session):
    source = _create_account(client, "Checking Account", is_on_budget=True)
    destination = _create_account(client, "Savings Account", is_on_budget=True, account_type="savings")

    # Initial balances are 1000 each (from initial_balance)
    assert _balance(session, source["id"]) == 1000.0
    assert _balance(session, destination["id"]) == 1000.0

    # 1. Create transfer via POST /api/transfers
    transfer_res = client.post(
        "/api/transfers",
        json={
            "source_account_id": source["id"],
            "destination_account_id": destination["id"],
            "amount": 250.0,
            "currency": "PLN",
            "note": "Vacation savings",
        },
    )
    assert transfer_res.status_code == 200, transfer_res.text
    data = transfer_res.json()
    assert data["type"] == "transfer"
    assert data["account_id"] == source["id"]
    assert data["transfer_id"] == destination["id"]
    assert data["total_amount"] == 250.0
    assert "Checking Account" in data["merchant_name"]
    assert "Savings Account" in data["merchant_name"]

    # Balances updated
    assert _balance(session, source["id"]) == 750.0
    assert _balance(session, destination["id"]) == 1250.0

    # 2. Delete transfer via DELETE /api/transfers/{id}
    del_res = client.delete(f"/api/transfers/{data['id']}")
    assert del_res.status_code == 204

    # Balances reverted atomically
    assert _balance(session, source["id"]) == 1000.0
    assert _balance(session, destination["id"]) == 1000.0


def test_transfer_validation_errors(client: TestClient, session: Session):
    source = _create_account(client, "Checking", is_on_budget=True)
    tracking = _create_account(client, "Brokerage Tracking", is_on_budget=False, account_type="tracking_asset")

    # Cannot transfer to same account
    res_same = client.post(
        "/api/transfers",
        json={
            "source_account_id": source["id"],
            "destination_account_id": source["id"],
            "amount": 50.0,
        },
    )
    assert res_same.status_code == 422
    assert "differ" in res_same.text

    # Transfer to tracking account requires category
    res_no_cat = client.post(
        "/api/transfers",
        json={
            "source_account_id": source["id"],
            "destination_account_id": tracking["id"],
            "amount": 100.0,
        },
    )
    assert res_no_cat.status_code == 422
    assert "Category is required" in res_no_cat.text

    # With category, transfer to tracking account succeeds
    cat_id = _get_or_create_category_id(client)
    res_with_cat = client.post(
        "/api/transfers",
        json={
            "source_account_id": source["id"],
            "destination_account_id": tracking["id"],
            "amount": 100.0,
            "category_id": cat_id,
        },
    )
    assert res_with_cat.status_code == 200, res_with_cat.text
    assert res_with_cat.json()["category_id"] == cat_id


def test_internal_transfer_budget_neutrality(client: TestClient):
    source = _create_account(client, "Checking 1", is_on_budget=True)
    destination = _create_account(client, "Savings 1", is_on_budget=True, account_type="savings")

    now = datetime.now(timezone.utc)
    year = now.year
    month = now.month

    # Get summary before transfer
    summary_before = client.get(f"/api/budget/{year}/{month}/summary").json()
    spent_before = summary_before["total_spent"]
    income_before = summary_before["total_income"]

    # Make internal transfer between two on-budget accounts
    transfer_res = client.post(
        "/api/transfers",
        json={
            "source_account_id": source["id"],
            "destination_account_id": destination["id"],
            "amount": 300.0,
            "date": now.isoformat(),
        },
    )
    assert transfer_res.status_code == 200

    # Summary after internal transfer must be completely neutral!
    summary_after = client.get(f"/api/budget/{year}/{month}/summary").json()
    assert summary_after["total_spent"] == spent_before
    assert summary_after["total_income"] == income_before


def test_tracking_account_transfers_in_summary(client: TestClient):
    checking = _create_account(client, "Checking 2", is_on_budget=True)
    tracking = _create_account(client, "Investment Tracking", is_on_budget=False, account_type="tracking_asset")
    cat_id = _get_or_create_category_id(client)

    now = datetime.now(timezone.utc)
    year = now.year
    month = now.month

    summary_before = client.get(f"/api/budget/{year}/{month}/summary").json()
    spent_before = summary_before["total_spent"]
    income_before = summary_before["total_income"]

    # 1. Outflow to tracking: Checking -> Tracking (treated as expense with category)
    outflow_res = client.post(
        "/api/transfers",
        json={
            "source_account_id": checking["id"],
            "destination_account_id": tracking["id"],
            "amount": 400.0,
            "category_id": cat_id,
            "date": now.isoformat(),
        },
    )
    assert outflow_res.status_code == 200

    summary_after_outflow = client.get(f"/api/budget/{year}/{month}/summary").json()
    assert summary_after_outflow["total_spent"] == round(spent_before + 400.0, 2)
    assert summary_after_outflow["total_income"] == income_before

    # Category spent should reflect the tracking transfer
    cat_item = next((c for c in summary_after_outflow["categories"] if c["category_id"] == cat_id), None)
    assert cat_item is not None
    assert cat_item["spent"] >= 400.0

    # 2. Inflow from tracking: Tracking -> Checking (treated as income into budget)
    inflow_res = client.post(
        "/api/transfers",
        json={
            "source_account_id": tracking["id"],
            "destination_account_id": checking["id"],
            "amount": 150.0,
            "date": now.isoformat(),
        },
    )
    assert inflow_res.status_code == 200

    summary_after_inflow = client.get(f"/api/budget/{year}/{month}/summary").json()
    assert summary_after_inflow["total_income"] == round(income_before + 150.0, 2)


def test_get_transactions_filter_by_account_id(client: TestClient):
    acc_a = _create_account(client, "Account Alpha")
    acc_b = _create_account(client, "Account Beta")

    # Regular expense on A
    client.post(
        "/api/transactions/manual",
        json={
            "merchant_name": "Alpha Grocery",
            "total_amount": 50.0,
            "type": "expense",
            "account_id": acc_a["id"],
        },
    )

    # Transfer from A to B
    transfer = client.post(
        "/api/transfers",
        json={
            "source_account_id": acc_a["id"],
            "destination_account_id": acc_b["id"],
            "amount": 75.0,
        },
    ).json()

    # Querying A should return both the expense and the outgoing transfer
    res_a = client.get(f"/api/transactions?account_id={acc_a['id']}")
    assert res_a.status_code == 200
    txs_a = res_a.json()
    tx_ids_a = [tx["id"] for tx in txs_a]
    assert transfer["id"] in tx_ids_a

    # Querying B should return the incoming transfer where transfer_id == acc_b['id']
    res_b = client.get(f"/api/transactions?account_id={acc_b['id']}")
    assert res_b.status_code == 200
    txs_b = res_b.json()
    tx_ids_b = [tx["id"] for tx in txs_b]
    assert transfer["id"] in tx_ids_b
