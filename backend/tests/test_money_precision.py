"""Money precision contract, Decimal DB storage, and Alembic migration tests (#256)."""

from decimal import Decimal
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
from sqlmodel import Session

from app.models import Account, EnvelopeAllocation, Transaction, TransactionLine
from app.money import (
    format_money,
    format_quantity,
    format_unit_price,
    parse_decimal,
    quantize_money,
    quantize_quantity,
    quantize_unit_price,
)
from app.receipt_schema import CanonicalItem, CanonicalReceipt


def test_decimal_helpers_polish_and_precision():
    assert parse_decimal("1 234,56") == Decimal("1234.56")
    assert parse_decimal("2\u00a0500,05") == Decimal("2500.05")
    assert parse_decimal("\u221242,90") == Decimal("-42.90")
    assert parse_decimal("1,234.56") == Decimal("1234.56")
    assert parse_decimal("1.234,56") == Decimal("1234.56")

    assert quantize_money("0.1") + quantize_money("0.2") == Decimal("0.30")
    assert format_money(Decimal("100")) == "100.00"
    assert format_money(Decimal("10.125")) == "10.13"

    assert quantize_unit_price("3.9943") == Decimal("3.9943")
    assert format_unit_price(Decimal("3.9943")) == "3.9943"
    assert format_unit_price(Decimal("10.5000")) == "10.50"

    assert quantize_quantity("1.976") == Decimal("1.9760")
    assert format_quantity(Decimal("1.9760")) == "1.976"
    assert format_quantity(Decimal("1.0000")) == "1"
    assert format_quantity(Decimal("0.0000")) == "0"

    for invalid in (True, False, "", "   ", float("nan"), float("inf"), "abc"):
        with pytest.raises(ValueError):
            parse_decimal(invalid)


def test_canonical_receipt_to_dict_has_zero_float_round_trips():
    item_weighted = CanonicalItem(
        name="Banany luz",
        unit_price=Decimal("4.13"),
        quantity=Decimal("1.976"),
        discount_total=Decimal("-0.27"),
    )
    item_regular = CanonicalItem(
        name="Chleb",
        unit_price=Decimal("3.50"),
        quantity=Decimal("1"),
    )
    receipt = CanonicalReceipt(
        merchant_name="Lidl",
        date="2026-11-14",
        total_amount=Decimal("11.39"),
        items=[item_weighted, item_regular],
    )

    payload = receipt.to_dict()
    assert isinstance(payload["total_amount"], Decimal)
    assert payload["total_amount"] == Decimal("11.39")
    assert not isinstance(payload["total_amount"], float)

    first = payload["items"][0]
    for key in ("unit_price", "price", "quantity", "original_price", "discount_total", "final_price", "final_line_total"):
        assert isinstance(first[key], Decimal), f"Expected Decimal for {key}, got {type(first[key])}"
    assert first["quantity"] == Decimal("1.976")
    assert first["price"] == Decimal("3.9929")


def test_api_accepts_polish_decimals_and_serializes_decimal_strings(client: TestClient, session: Session):
    acc_res = client.post(
        "/api/accounts",
        json={
            "name": "Konto Główne",
            "type": "checking",
            "currency": "PLN",
            "initial_balance": "1 234,56",
            "is_on_budget": True,
        },
    )
    assert acc_res.status_code == 200, acc_res.text
    acc = acc_res.json()
    assert acc["initial_balance"] == "0.00"
    assert acc["current_balance"] == "1234.56"

    # Weighted item with 4-decimal unit price & 0.10 + 0.20 precision
    tx1_res = client.post(
        "/api/transactions/manual",
        json={
            "merchant_name": "Lidl",
            "total_amount": "0.10",
            "currency": "PLN",
            "date": "2026-11-14T10:00:00Z",
            "type": "expense",
            "account_id": acc["id"],
            "lines": [
                {"name": "Bułka", "price": "0,10", "quantity": "1"},
            ],
        },
    )
    assert tx1_res.status_code == 200, tx1_res.text
    assert tx1_res.json()["total_amount"] == "0.10"

    tx2_res = client.post(
        "/api/transactions/manual",
        json={
            "merchant_name": "Warzywniak",
            "total_amount": "8.09",
            "currency": "PLN",
            "date": "2026-11-14T11:00:00Z",
            "type": "expense",
            "account_id": acc["id"],
            "lines": [
                {"name": "Jabłka", "price": "3.9943", "quantity": "1,976"},
                {"name": "Torba", "price": "0.20", "quantity": "1"},
            ],
        },
    )
    assert tx2_res.status_code == 200, tx2_res.text
    tx2 = tx2_res.json()
    assert tx2["total_amount"] == "8.09"
    assert tx2["lines"][0]["price"] == "3.9943"
    assert tx2["lines"][0]["quantity"] == "1.976"

    # Account balance: 1234.56 - 0.10 - 8.09 = 1226.37 exact
    db_acc = session.get(Account, acc["id"])
    assert db_acc is not None
    session.refresh(db_acc)
    assert db_acc.current_balance == Decimal("1226.37")

    # Budget summary returns clean decimal strings
    summary_res = client.get("/api/budget/2026/11/summary")
    assert summary_res.status_code == 200
    summary = summary_res.json()
    assert summary["total_income"] == "1234.56"
    assert summary["total_spent"] == "8.19"
    assert summary["net_cash_flow"] == "1226.37"


def test_reconcile_handles_exact_one_grosz_difference(client: TestClient, session: Session):
    acc_res = client.post(
        "/api/accounts",
        json={"name": "ReconcileTest", "type": "checking", "currency": "PLN", "initial_balance": "100.00"},
    )
    assert acc_res.status_code == 200
    acc_id = acc_res.json()["id"]

    rec_res = client.post(f"/api/accounts/{acc_id}/reconcile", json={"real_balance": "100,01"})
    assert rec_res.status_code == 200, rec_res.text
    assert rec_res.json()["current_balance"] == "100.01"


def test_balance_trigger_avoids_binary_float_drift(client: TestClient, session: Session):
    acc_res = client.post(
        "/api/accounts",
        json={"name": "FloatDriftCheck", "type": "checking", "currency": "PLN", "initial_balance": "0.00"},
    )
    acc_id = acc_res.json()["id"]

    for amt in ("0.10", "0.20"):
        res = client.post(
            "/api/transactions/manual",
            json={"merchant_name": "Płatność", "total_amount": amt, "type": "income", "account_id": acc_id},
        )
        assert res.status_code == 200

    acc = session.get(Account, acc_id)
    assert acc is not None
    session.refresh(acc)
    assert acc.current_balance == Decimal("0.30")


def test_alembic_decimal_migration_upgrade_downgrade_roundtrip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Verify Alembic upgrade/downgrade preserves data and cleans IEEE-754 float noise."""
    import app.database as app_database

    db_path = tmp_path / "migration_test.db"
    db_url = f"sqlite:///{db_path}"
    monkeypatch.setattr(app_database, "DATABASE_URL", db_url)

    backend_dir = Path(__file__).resolve().parent.parent
    alembic_cfg = Config(str(backend_dir / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(backend_dir / "alembic"))
    alembic_cfg.set_main_option("sqlalchemy.url", db_url)

    # 1. Migrate to pre-Decimal revision
    command.upgrade(alembic_cfg, "3b1c8f42d1e0")

    engine = create_engine(db_url)
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO budget (id, name, created_at) VALUES (1, 'Home', '2026-11-14 00:00:00')"))
        conn.execute(text("INSERT INTO category (id, name, is_system, order_index, budget_id) VALUES (1, 'Food', 0, 0, 1)"))
        conn.execute(
            text(
                "INSERT INTO account (id, name, type, currency, initial_balance, current_balance, is_on_budget, is_active, budget_id) "
                "VALUES (1, 'Checking', 'checking', 'PLN', :init_b, :cur_b, 1, 1, 1)"
            ),
            {"init_b": 100.0, "cur_b": 10.990000000000002},
        )
        conn.execute(
            text(
                'INSERT INTO "transaction" (id, merchant_name, date, total_amount, currency, is_manual, type, status, budget_id, account_id) '
                "VALUES (1, 'Lidl', '2026-11-14 12:00:00', :tot, 'PLN', 1, 'expense', 'uncleared', 1, 1)"
            ),
            {"tot": 0.1 + 0.2},
        )
        conn.execute(
            text(
                "INSERT INTO transactionline (id, name, price, quantity, transaction_id, original_price, discount_total, final_price, is_adjustment) "
                "VALUES (1, 'Banany', 3.9943, 1.976, 1, 4.13, -0.27, 3.9943, 0)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO envelope_allocation (id, budget_id, category_id, month, year, amount) "
                "VALUES (1, 1, 1, 11, 2026, :alloc)"
            ),
            {"alloc": 250.55000000000001},
        )

    # 2. Upgrade to head (Decimal / NUMERIC)
    command.upgrade(alembic_cfg, "head")

    insp = inspect(engine)
    acc_cols = {c["name"]: c["type"] for c in insp.get_columns("account")}
    tx_cols = {c["name"]: c["type"] for c in insp.get_columns("transaction")}
    line_cols = {c["name"]: c["type"] for c in insp.get_columns("transactionline")}
    alloc_cols = {c["name"]: c["type"] for c in insp.get_columns("envelope_allocation")}

    assert "NUMERIC(12, 2)" in str(acc_cols["initial_balance"]).upper()
    assert "NUMERIC(12, 2)" in str(acc_cols["current_balance"]).upper()
    assert "NUMERIC(12, 2)" in str(tx_cols["total_amount"]).upper()
    assert "NUMERIC(12, 4)" in str(line_cols["price"]).upper()
    assert "NUMERIC(12, 4)" in str(line_cols["quantity"]).upper()
    assert "NUMERIC(12, 4)" in str(line_cols["original_price"]).upper()
    assert "NUMERIC(12, 2)" in str(line_cols["discount_total"]).upper()
    assert "NUMERIC(12, 4)" in str(line_cols["final_price"]).upper()
    assert "NUMERIC(12, 2)" in str(alloc_cols["amount"]).upper()

    with Session(engine) as s:
        acc = s.get(Account, 1)
        tx = s.get(Transaction, 1)
        line = s.get(TransactionLine, 1)
        alloc = s.get(EnvelopeAllocation, 1)
        assert acc is not None and acc.current_balance == Decimal("10.99")
        assert tx is not None and tx.total_amount == Decimal("0.30")
        assert line is not None
        assert line.price == Decimal("3.9943")
        assert line.quantity == Decimal("1.9760")
        assert line.discount_total == Decimal("-0.27")
        assert alloc is not None and alloc.amount == Decimal("250.55")

    # 3. Downgrade -1 back to FLOAT
    command.downgrade(alembic_cfg, "-1")

    insp_down = inspect(engine)
    tx_cols_down = {c["name"]: c["type"] for c in insp_down.get_columns("transaction")}
    assert "FLOAT" in str(tx_cols_down["total_amount"]).upper()

    # 4. Re-upgrade back to head
    command.upgrade(alembic_cfg, "head")
    with Session(engine) as s:
        tx_re = s.get(Transaction, 1)
        assert tx_re is not None and tx_re.total_amount == Decimal("0.30")
    engine.dispose()


def test_dto_rejects_negative_amounts_and_non_positive_quantities(client: TestClient):
    acc_res = client.post(
        "/api/accounts",
        json={"name": "ValidationAcc", "type": "checking", "currency": "PLN", "initial_balance": "100.00"},
    )
    assert acc_res.status_code == 200
    acc_id = acc_res.json()["id"]

    neg_tx = client.post(
        "/api/transactions/manual",
        json={"merchant_name": "Bad", "total_amount": "-10.00", "type": "expense", "account_id": acc_id},
    )
    assert neg_tx.status_code == 422

    bad_qty = client.post(
        "/api/transactions/manual",
        json={
            "merchant_name": "BadQty",
            "total_amount": "5.00",
            "type": "expense",
            "account_id": acc_id,
            "lines": [{"name": "Item", "price": "5.00", "quantity": "0"}],
        },
    )
    assert bad_qty.status_code == 422

    neg_alloc = client.put("/api/budget/2026/11/limits/1", json={"amount": "-5.00"})
    assert neg_alloc.status_code == 422
