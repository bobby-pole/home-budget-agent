import io
from fastapi.testclient import TestClient

from app.models import TransactionStatus


def test_default_status_uncleared(client: TestClient):
    response = client.post(
        "/api/transactions/manual",
        json={
            "merchant_name": "Corner Store",
            "total_amount": 42.50,
            "currency": "PLN",
            "type": "expense",
        },
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["status"] == TransactionStatus.UNCLEARED.value


def test_create_transaction_with_explicit_status(client: TestClient):
    # Cleared
    res_cleared = client.post(
        "/api/transactions/manual",
        json={
            "merchant_name": "Supermarket",
            "total_amount": 100.0,
            "currency": "PLN",
            "status": "cleared",
        },
    )
    assert res_cleared.status_code == 200, res_cleared.text
    assert res_cleared.json()["status"] == "cleared"

    # Pending
    res_pending = client.post(
        "/api/transactions/manual",
        json={
            "merchant_name": "Gas Station",
            "total_amount": 200.0,
            "currency": "PLN",
            "status": "pending",
        },
    )
    assert res_pending.status_code == 200, res_pending.text
    assert res_pending.json()["status"] == "pending"

    # Invalid status
    res_invalid = client.post(
        "/api/transactions/manual",
        json={
            "merchant_name": "Invalid Store",
            "total_amount": 10.0,
            "currency": "PLN",
            "status": "not_a_valid_status",
        },
    )
    assert res_invalid.status_code == 422


def test_update_transaction_status(client: TestClient):
    created = client.post(
        "/api/transactions/manual",
        json={
            "merchant_name": "Coffee Shop",
            "total_amount": 18.0,
            "currency": "PLN",
        },
    ).json()
    tx_id = created["id"]
    assert created["status"] == "uncleared"

    # Update to cleared
    patch_res = client.patch(
        f"/api/transactions/{tx_id}",
        json={"status": "cleared"},
    )
    assert patch_res.status_code == 200, patch_res.text
    assert patch_res.json()["status"] == "cleared"

    # Update to pending
    patch_res = client.patch(
        f"/api/transactions/{tx_id}",
        json={"status": "pending"},
    )
    assert patch_res.status_code == 200, patch_res.text
    assert patch_res.json()["status"] == "pending"

    # Update with invalid status
    patch_res = client.patch(
        f"/api/transactions/{tx_id}",
        json={"status": "invalid_status"},
    )
    assert patch_res.status_code == 422


def test_filter_transactions_by_status(client: TestClient):
    # Create one of each status
    res1 = client.post(
        "/api/transactions/manual",
        json={"merchant_name": "Filter Test Cleared", "total_amount": 10.0, "status": "cleared"},
    )
    assert res1.status_code == 200
    res2 = client.post(
        "/api/transactions/manual",
        json={"merchant_name": "Filter Test Uncleared", "total_amount": 20.0, "status": "uncleared"},
    )
    assert res2.status_code == 200
    res3 = client.post(
        "/api/transactions/manual",
        json={"merchant_name": "Filter Test Pending", "total_amount": 30.0, "status": "pending"},
    )
    assert res3.status_code == 200

    # Filter cleared
    cleared_list = client.get("/api/transactions?status=cleared").json()
    assert any(tx["merchant_name"] == "Filter Test Cleared" for tx in cleared_list)
    assert all(tx["status"] == "cleared" for tx in cleared_list)

    # Filter uncleared
    uncleared_list = client.get("/api/transactions?status=uncleared").json()
    assert any(tx["merchant_name"] == "Filter Test Uncleared" for tx in uncleared_list)
    assert all(tx["status"] == "uncleared" for tx in uncleared_list)

    # Filter pending
    pending_list = client.get("/api/transactions?status=pending").json()
    assert any(tx["merchant_name"] == "Filter Test Pending" for tx in pending_list)
    assert all(tx["status"] == "pending" for tx in pending_list)

    # Filter invalid status
    invalid_res = client.get("/api/transactions?status=unknown_status")
    assert invalid_res.status_code == 422


def test_transfer_status(client: TestClient):
    acc1 = client.post("/api/accounts", json={"name": "Acc 1", "type": "checking", "currency": "PLN", "initial_balance": 500.0}).json()
    acc2 = client.post("/api/accounts", json={"name": "Acc 2", "type": "savings", "currency": "PLN", "initial_balance": 500.0}).json()

    # Default transfer -> uncleared
    t1 = client.post(
        "/api/transfers",
        json={"source_account_id": acc1["id"], "destination_account_id": acc2["id"], "amount": 50.0},
    ).json()
    assert t1["status"] == "uncleared"

    # Transfer with explicit cleared status
    t2 = client.post(
        "/api/transfers",
        json={"source_account_id": acc1["id"], "destination_account_id": acc2["id"], "amount": 60.0, "status": "cleared"},
    ).json()
    assert t2["status"] == "cleared"


def test_bank_csv_import_status_cleared(client: TestClient):
    csv_content = (
        "Data transakcji;Kontrahent;Tytuł;Kwota;Waluta\n"
        "2026-03-01;Sklep ABC;Płatność kartą;-75,20;PLN\n"
    )
    file_payload = {"file": ("statement.csv", io.BytesIO(csv_content.encode("utf-8")), "text/csv")}
    response = client.post("/api/transactions/import", files=file_payload)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["created"] == 1

    # Verify that the imported transaction has status "cleared"
    transactions = client.get("/api/transactions").json()
    imported_tx = next(t for t in transactions if t.get("merchant_name") == "Sklep ABC")
    assert imported_tx["status"] == "cleared"
