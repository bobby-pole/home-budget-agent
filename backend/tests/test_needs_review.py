import asyncio
from unittest.mock import patch
from datetime import datetime, timezone
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.models import (
    Transaction,
    TransactionLine,
    ReceiptScan,
    ScanStatus,
    User,
    Budget,
    ReceiptScanRead,
)
from app.api import _process_scan
from app.services import AIService


def test_scan_status_enum_values():
    """Verify ScanStatus enum members and backwards compatibility mappings."""
    assert ScanStatus.NEEDS_REVIEW == "NEEDS_REVIEW"
    assert ScanStatus.CATEGORIZATION_OK == "CATEGORIZATION_OK"
    assert ScanStatus.DONE == "DONE"
    assert ScanStatus.FAILED == "FAILED"

    # Legacy mappings via _missing_
    assert ScanStatus("needs_review") == ScanStatus.NEEDS_REVIEW
    assert ScanStatus("categorization_ok") == ScanStatus.CATEGORIZATION_OK
    assert ScanStatus("done") == ScanStatus.DONE
    assert ScanStatus("processing") == ScanStatus.RUNNING
    assert ScanStatus("error") == ScanStatus.FAILED


def test_receipt_scan_model_needs_review_default():
    """Verify default value of needs_review in ReceiptScan and ReceiptScanRead."""
    scan = ReceiptScan(transaction_id=1, status=ScanStatus.QUEUED.value)
    assert scan.needs_review is False

    scan_read = ReceiptScanRead(
        id=1,
        status="CATEGORIZATION_OK",
        created_at=datetime.now(timezone.utc),
    )
    assert scan_read.needs_review is False
    assert hasattr(scan_read, "needs_review")


def test_process_scan_valid_receipt(client: TestClient, session: Session):
    """When receipt validation passes and confidence is high, status is CATEGORIZATION_OK and needs_review is False."""
    user = session.exec(select(User).where(User.email == "test@example.com")).first()
    budget = session.exec(select(Budget).where(Budget.name == "Domowy")).first()
    assert user and budget

    tx = Transaction(budget_id=budget.id, uploaded_by=user.id, merchant_name="Pending", total_amount=0.0)
    session.add(tx)
    session.commit()
    session.refresh(tx)
    assert tx.id is not None

    scan = ReceiptScan(transaction_id=tx.id, status=ScanStatus.QUEUED.value, image_path="/fake/receipt.jpg")
    session.add(scan)
    session.commit()
    session.refresh(scan)
    assert scan.id is not None

    mock_parsed_data = {
        "merchant_name": "Biedronka",
        "total_amount": 10.0,
        "currency": "PLN",
        "date": "2026-09-14",
        "items": [
            {"name": "Mleko", "price": 4.0, "quantity": 1.0, "confidence": 0.95},
            {"name": "Chleb", "price": 6.0, "quantity": 1.0, "confidence": 0.92},
        ],
        "_validation": {
            "is_valid": True,
            "issues": [],
            "confidence": 1.0,
            "message": None,
        },
    }

    with patch("app.api.operations_engine", session.bind), patch.object(AIService, "parse_receipt", return_value=mock_parsed_data):
        asyncio.run(_process_scan(scan.id, tx.id, "/fake/receipt.jpg"))

    session.refresh(scan)
    session.refresh(tx)

    assert scan.status == ScanStatus.CATEGORIZATION_OK
    assert scan.needs_review is False
    assert scan.validation_message is None
    assert tx.merchant_name == "Biedronka"
    assert tx.total_amount == 10.0

    lines = session.exec(select(TransactionLine).where(TransactionLine.transaction_id == tx.id)).all()
    assert len(lines) == 2
    assert {line.name for line in lines} == {"Mleko", "Chleb"}


def test_process_scan_sum_mismatch_sets_needs_review_and_persists_lines(client: TestClient, session: Session):
    """When receipt sum validation fails, status is NEEDS_REVIEW, needs_review is True, and lines are persisted."""
    user = session.exec(select(User).where(User.email == "test@example.com")).first()
    budget = session.exec(select(Budget).where(Budget.name == "Domowy")).first()
    assert user and budget

    tx = Transaction(budget_id=budget.id, uploaded_by=user.id, merchant_name="Pending", total_amount=0.0)
    session.add(tx)
    session.commit()
    session.refresh(tx)
    assert tx.id is not None

    scan = ReceiptScan(transaction_id=tx.id, status=ScanStatus.QUEUED.value, image_path="/fake/receipt.jpg")
    session.add(scan)
    session.commit()
    session.refresh(scan)
    assert scan.id is not None

    # Total says 15.00, but items sum to 10.00
    mock_parsed_data = {
        "merchant_name": "Lidl",
        "total_amount": 15.0,
        "currency": "PLN",
        "date": "2026-09-14",
        "items": [
            {"name": "Ser", "price": 10.0, "quantity": 1.0, "confidence": 0.95},
        ],
        "_validation": {
            "is_valid": True,
            "issues": ["TOTAL_MISMATCH"],
            "confidence": 0.6667,
            "message": "RECEIPT_SUM_MISMATCH:5.00",
        },
    }

    with patch("app.api.operations_engine", session.bind), patch.object(AIService, "parse_receipt", return_value=mock_parsed_data):
        asyncio.run(_process_scan(scan.id, tx.id, "/fake/receipt.jpg"))

    session.refresh(scan)
    session.refresh(tx)

    assert scan.status == ScanStatus.NEEDS_REVIEW
    assert scan.needs_review is True
    assert scan.validation_message == "RECEIPT_SUM_MISMATCH:5.00"
    assert tx.merchant_name == "Lidl"
    assert tx.total_amount == 15.0

    # Lines MUST be persisted so user can correct them in Inbox
    lines = session.exec(select(TransactionLine).where(TransactionLine.transaction_id == tx.id)).all()
    assert len(lines) == 1
    assert lines[0].name == "Ser"
    assert lines[0].price == 10.0


def test_process_scan_low_confidence_line_sets_needs_review(client: TestClient, session: Session):
    """When a line item has confidence below 0.85, status is NEEDS_REVIEW and needs_review is True."""
    user = session.exec(select(User).where(User.email == "test@example.com")).first()
    budget = session.exec(select(Budget).where(Budget.name == "Domowy")).first()
    assert user and budget

    tx = Transaction(budget_id=budget.id, uploaded_by=user.id, merchant_name="Pending", total_amount=0.0)
    session.add(tx)
    session.commit()
    session.refresh(tx)
    assert tx.id is not None

    scan = ReceiptScan(transaction_id=tx.id, status=ScanStatus.QUEUED.value, image_path="/fake/receipt.jpg")
    session.add(scan)
    session.commit()
    session.refresh(scan)
    assert scan.id is not None

    mock_parsed_data = {
        "merchant_name": "Kaufland",
        "total_amount": 8.0,
        "currency": "PLN",
        "date": "2026-09-14",
        "items": [
            {"name": "Masło", "price": 8.0, "quantity": 1.0, "confidence": 0.72},  # < 0.85
        ],
        "_validation": {
            "is_valid": True,
            "issues": [],
            "confidence": 1.0,
            "message": None,
        },
    }

    with patch("app.api.operations_engine", session.bind), patch.object(AIService, "parse_receipt", return_value=mock_parsed_data):
        asyncio.run(_process_scan(scan.id, tx.id, "/fake/receipt.jpg"))

    session.refresh(scan)
    session.refresh(tx)

    assert scan.status == ScanStatus.NEEDS_REVIEW
    assert scan.needs_review is True
    assert scan.validation_message == "LOW_CONFIDENCE"

    lines = session.exec(select(TransactionLine).where(TransactionLine.transaction_id == tx.id)).all()
    assert len(lines) == 1
    assert lines[0].name == "Masło"


def test_inbox_filtering_by_needs_review(client: TestClient, session: Session):
    """Verify Inbox API supports filtering by needs_review query param (true, false, None)."""
    user = session.exec(select(User).where(User.email == "test@example.com")).first()
    budget = session.exec(select(Budget).where(Budget.name == "Domowy")).first()
    assert user and budget

    # Transaction 1: Ready / Categorized (needs_review = False)
    t1 = Transaction(budget_id=budget.id, uploaded_by=user.id, merchant_name="Tx Ready", total_amount=20.0)
    session.add(t1)
    session.commit()
    session.refresh(t1)
    assert t1.id is not None
    s1 = ReceiptScan(transaction_id=t1.id, status=ScanStatus.CATEGORIZATION_OK.value, needs_review=False)
    session.add(s1)

    # Transaction 2: Review required (needs_review = True, NEEDS_REVIEW)
    t2 = Transaction(budget_id=budget.id, uploaded_by=user.id, merchant_name="Tx Needs Review", total_amount=30.0)
    session.add(t2)
    session.commit()
    session.refresh(t2)
    assert t2.id is not None
    s2 = ReceiptScan(transaction_id=t2.id, status=ScanStatus.NEEDS_REVIEW.value, needs_review=True)
    session.add(s2)

    # Transaction 3: Review required (needs_review = True, FAILED)
    t3 = Transaction(budget_id=budget.id, uploaded_by=user.id, merchant_name="Tx Failed", total_amount=40.0)
    session.add(t3)
    session.commit()
    session.refresh(t3)
    assert t3.id is not None
    s3 = ReceiptScan(transaction_id=t3.id, status=ScanStatus.FAILED.value, needs_review=True)
    session.add(s3)

    session.commit()

    # 1. Query with needs_review=true -> should return t2 and t3
    res_true = client.get("/api/transactions/inbox?needs_review=true")
    assert res_true.status_code == 200
    ids_true = [t["id"] for t in res_true.json()]
    assert t2.id in ids_true
    assert t3.id in ids_true
    assert t1.id not in ids_true

    # 2. Query with needs_review=false -> should return t1
    res_false = client.get("/api/transactions/inbox?needs_review=false")
    assert res_false.status_code == 200
    ids_false = [t["id"] for t in res_false.json()]
    assert t1.id in ids_false
    assert t2.id not in ids_false
    assert t3.id not in ids_false

    # 3. Query without filter -> should return all unverified (t1, t2, t3)
    res_all = client.get("/api/transactions/inbox")
    assert res_all.status_code == 200
    ids_all = [t["id"] for t in res_all.json()]
    assert t1.id in ids_all
    assert t2.id in ids_all
    assert t3.id in ids_all


def test_verify_transaction_sets_done_and_removes_from_inbox(client: TestClient, session: Session):
    """Verifying a transaction sets status to DONE and needs_review to False, removing it from inbox."""
    user = session.exec(select(User).where(User.email == "test@example.com")).first()
    budget = session.exec(select(Budget).where(Budget.name == "Domowy")).first()
    assert user and budget

    tx = Transaction(budget_id=budget.id, uploaded_by=user.id, merchant_name="Unverified", total_amount=50.0)
    session.add(tx)
    session.commit()
    session.refresh(tx)
    assert tx.id is not None

    scan = ReceiptScan(transaction_id=tx.id, status=ScanStatus.NEEDS_REVIEW.value, needs_review=True)
    session.add(scan)
    session.commit()

    # Inbox should contain this transaction before verification
    inbox_before = client.get("/api/transactions/inbox").json()
    assert any(t["id"] == tx.id for t in inbox_before)

    # Verify transaction
    verify_payload = {
        "keep_image": False,
        "transaction_update": {"merchant_name": "Verified Store", "total_amount": 50.0},
        "lines_update": [{"name": "Verified Item", "price": 50.0, "quantity": 1.0}],
    }
    verify_res = client.post(f"/api/transactions/{tx.id}/verify", json=verify_payload)
    assert verify_res.status_code == 200
    verified_data = verify_res.json()

    assert verified_data["receipt_scan"]["status"] == ScanStatus.DONE
    assert verified_data["receipt_scan"]["needs_review"] is False

    # Inbox should NO LONGER contain this transaction
    inbox_after = client.get("/api/transactions/inbox").json()
    assert not any(t["id"] == tx.id for t in inbox_after)


def test_app_status_endpoint_includes_all_inbox_items(client: TestClient, session: Session):
    """GET /api/status includes both CATEGORIZATION_OK and NEEDS_REVIEW in inbox_items."""
    user = session.exec(select(User).where(User.email == "test@example.com")).first()
    budget = session.exec(select(Budget).where(Budget.name == "Domowy")).first()
    assert user and budget

    t1 = Transaction(budget_id=budget.id, uploaded_by=user.id, merchant_name="App Status 1", total_amount=12.0)
    session.add(t1)
    session.commit()
    session.refresh(t1)
    assert t1.id is not None
    s1 = ReceiptScan(transaction_id=t1.id, status=ScanStatus.CATEGORIZATION_OK.value, needs_review=False)
    session.add(s1)

    t2 = Transaction(budget_id=budget.id, uploaded_by=user.id, merchant_name="App Status 2", total_amount=15.0)
    session.add(t2)
    session.commit()
    session.refresh(t2)
    assert t2.id is not None
    s2 = ReceiptScan(transaction_id=t2.id, status=ScanStatus.NEEDS_REVIEW.value, needs_review=True)
    session.add(s2)

    session.commit()

    res = client.get("/api/status")
    assert res.status_code == 200
    data = res.json()
    inbox_ids = [item["id"] for item in data["inbox_items"]]
    assert t1.id in inbox_ids
    assert t2.id in inbox_ids
