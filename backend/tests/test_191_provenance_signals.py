"""Tests for Import Provenance, Canonical Total Validation, and Review Reasons (#191)."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.models import (
    Account,
    Budget,
    Category,
    RawPayloadPolicy,
    ReceiptScan,
    ReconciliationLink,
    ReconciliationMatchKind,
    ReconciliationStatus,
    ReviewStatus,
    ScanStatus,
    SourceRecord,
    SourceType,
    Transaction,
    TransactionLine,
    User,
)
from app.inbox_service import serialize_transaction_read


def _get_user_budget(session: Session) -> tuple[User, Budget]:
    user = session.exec(select(User).where(User.email == "test@example.com")).first()
    budget = session.exec(select(Budget).where(Budget.name == "Domowy")).first()
    assert user is not None and user.id is not None
    assert budget is not None and budget.id is not None
    return user, budget


def test_canonical_total_valid_for_receipts_and_non_receipts(
    client: TestClient,
    session: Session,
) -> None:
    user, budget = _get_user_budget(session)
    assert budget.id is not None and user.id is not None

    acc = Account(name="Bank", type="checking", currency="PLN", budget_id=budget.id)
    session.add(acc)
    session.commit()
    session.refresh(acc)

    # 1. Valid structured receipt with discount & bottle deposit adjustment
    tx_ok = Transaction(
        merchant_name="Lidl Polska",
        total_amount=Decimal("24.00"),
        date=datetime(2026, 6, 1, tzinfo=timezone.utc),
        budget_id=budget.id,
        uploaded_by=user.id,
        account_id=acc.id,
        review_status=ReviewStatus.PENDING,
    )
    session.add(tx_ok)
    session.commit()
    session.refresh(tx_ok)
    assert tx_ok.id is not None

    scan_ok = ReceiptScan(
        transaction_id=tx_ok.id,
        status=ScanStatus.CATEGORIZATION_OK.value,
        processed_via="lidl_plus_v3",
        needs_review=False,
    )
    session.add(scan_ok)
    session.add(
        TransactionLine(
            transaction_id=tx_ok.id,
            name="Mleko 3.2%",
            price=Decimal("4.0000"),
            original_price=Decimal("5.0000"),
            discount_total=Decimal("-2.00"),
            quantity=Decimal("2.0000"),
        )
    )
    session.add(
        TransactionLine(
            transaction_id=tx_ok.id,
            name="Kawa 500g",
            price=Decimal("15.0000"),
            quantity=Decimal("1.0000"),
        )
    )
    session.add(
        TransactionLine(
            transaction_id=tx_ok.id,
            name="Kaucja",
            price=Decimal("1.0000"),
            quantity=Decimal("1.0000"),
            is_adjustment=True,
        )
    )
    session.add(
        SourceRecord(
            budget_id=budget.id,
            transaction_id=tx_ok.id,
            source_type=SourceType.MERCHANT_API,
            provider="lidl",
            external_id="lidl-ok-1",
            adapter_version="lidl_plus_v3",
            raw_payload_policy=RawPayloadPolicy.CANONICAL_ONLY,
        )
    )

    # 2. Mismatched OCR receipt
    tx_mismatch = Transaction(
        merchant_name="Biedronka",
        total_amount=Decimal("30.00"),
        date=datetime(2026, 6, 2, tzinfo=timezone.utc),
        budget_id=budget.id,
        uploaded_by=user.id,
        account_id=acc.id,
        review_status=ReviewStatus.PENDING,
    )
    session.add(tx_mismatch)
    session.commit()
    session.refresh(tx_mismatch)
    assert tx_mismatch.id is not None
    session.add(
        ReceiptScan(
            transaction_id=tx_mismatch.id,
            status=ScanStatus.NEEDS_REVIEW.value,
            needs_review=True,
            validation_message="RECEIPT_SUM_MISMATCH:1.50",
        )
    )
    session.add(
        TransactionLine(
            transaction_id=tx_mismatch.id,
            name="Chleb",
            price=Decimal("28.5000"),
            quantity=Decimal("1.0000"),
        )
    )

    # 3. Manual / Bank CSV without ReceiptScan -> canonical_total_valid is None
    tx_manual = Transaction(
        merchant_name="Manual Entry",
        total_amount=Decimal("50.00"),
        date=datetime(2026, 6, 3, tzinfo=timezone.utc),
        budget_id=budget.id,
        uploaded_by=user.id,
        account_id=acc.id,
        is_manual=True,
        review_status=ReviewStatus.PENDING,
    )
    session.add(tx_manual)

    # 4. In-progress OCR scan -> canonical_total_valid is None
    tx_running = Transaction(
        merchant_name="Scanning...",
        total_amount=Decimal("0.00"),
        date=datetime(2026, 6, 4, tzinfo=timezone.utc),
        budget_id=budget.id,
        uploaded_by=user.id,
        account_id=acc.id,
        review_status=ReviewStatus.PENDING,
    )
    session.add(tx_running)
    session.commit()
    session.refresh(tx_running)
    assert tx_running.id is not None
    session.add(
        ReceiptScan(
            transaction_id=tx_running.id,
            status=ScanStatus.RUNNING.value,
        )
    )
    session.commit()

    session.refresh(tx_ok)
    session.refresh(tx_mismatch)
    session.refresh(tx_manual)
    session.refresh(tx_running)

    assert serialize_transaction_read(tx_ok, session=session).canonical_total_valid is True
    assert serialize_transaction_read(tx_mismatch, session=session).canonical_total_valid is False
    assert serialize_transaction_read(tx_manual, session=session).canonical_total_valid is None
    assert serialize_transaction_read(tx_running, session=session).canonical_total_valid is None


def test_review_reasons_combines_validation_account_and_duplicates(
    client: TestClient,
    session: Session,
) -> None:
    user, budget = _get_user_budget(session)
    assert budget.id is not None and user.id is not None

    tx_primary = Transaction(
        merchant_name="Lidl Polska",
        total_amount=Decimal("42.00"),
        date=datetime(2026, 6, 5, tzinfo=timezone.utc),
        budget_id=budget.id,
        uploaded_by=user.id,
        account_id=None,
        review_status=ReviewStatus.PENDING,
    )
    tx_dup = Transaction(
        merchant_name="Lidl",
        total_amount=Decimal("42.00"),
        date=datetime(2026, 6, 5, tzinfo=timezone.utc),
        budget_id=budget.id,
        uploaded_by=user.id,
        is_manual=True,
        review_status=ReviewStatus.APPROVED,
    )
    session.add(tx_primary)
    session.add(tx_dup)
    session.commit()
    session.refresh(tx_primary)
    session.refresh(tx_dup)
    assert tx_primary.id is not None and tx_dup.id is not None

    session.add(
        ReceiptScan(
            transaction_id=tx_primary.id,
            status=ScanStatus.NEEDS_REVIEW.value,
            needs_review=True,
            validation_message="RECEIPT_SUM_MISMATCH:2.00",
        )
    )
    session.add(
        TransactionLine(
            transaction_id=tx_primary.id,
            name="Zakupy",
            price=Decimal("40.00"),
            quantity=Decimal("1"),
        )
    )
    sr_primary = SourceRecord(
        budget_id=budget.id,
        transaction_id=tx_primary.id,
        source_type=SourceType.MERCHANT_API,
        provider="lidl",
        external_id="dup-1",
        adapter_version="lidl_plus_v3",
    )
    sr_dup = SourceRecord(
        budget_id=budget.id,
        transaction_id=tx_dup.id,
        source_type=SourceType.MANUAL,
        provider="manual",
        adapter_version="manual_v1",
    )
    session.add(sr_primary)
    session.add(sr_dup)
    session.commit()
    session.refresh(sr_primary)
    session.refresh(sr_dup)
    assert sr_primary.id is not None and sr_dup.id is not None

    session.add(
        ReconciliationLink(
            budget_id=budget.id,
            bank_source_record_id=sr_primary.id,
            target_source_record_id=sr_dup.id,
            bank_transaction_id=tx_primary.id,
            target_transaction_id=tx_dup.id,
            match_kind=ReconciliationMatchKind.RECEIPT_DUPLICATE,
            status=ReconciliationStatus.PENDING,
            score=Decimal("0.9200"),
        )
    )

    tx_failed = Transaction(
        merchant_name="Nieznany",
        total_amount=Decimal("0.00"),
        date=datetime(2026, 6, 6, tzinfo=timezone.utc),
        budget_id=budget.id,
        uploaded_by=user.id,
        review_status=ReviewStatus.PENDING,
    )
    session.add(tx_failed)
    session.commit()
    session.refresh(tx_failed)
    assert tx_failed.id is not None
    session.add(
        ReceiptScan(
            transaction_id=tx_failed.id,
            status=ScanStatus.FAILED.value,
            needs_review=True,
            error_message="TEXT_TOO_SHORT",
        )
    )
    session.commit()

    inbox_res = client.get("/api/transactions/inbox?tab=exceptions")
    assert inbox_res.status_code == 200
    items = {item["id"]: item for item in inbox_res.json()}

    primary_dto = items[tx_primary.id]
    assert primary_dto["canonical_total_valid"] is False
    assert primary_dto["review_reasons"] == [
        "RECEIPT_SUM_MISMATCH:2.00",
        "DUPLICATE_REVIEW_REQUIRED",
        "MISSING_ACCOUNT",
    ]

    failed_dto = items[tx_failed.id]
    assert failed_dto["canonical_total_valid"] is False
    assert "TEXT_TOO_SHORT" in failed_dto["review_reasons"]
    assert "MISSING_ACCOUNT" in failed_dto["review_reasons"]


def test_verify_and_line_patch_set_user_category_source_and_consistent_history_dto(
    client: TestClient,
    session: Session,
) -> None:
    user, budget = _get_user_budget(session)
    assert budget.id is not None and user.id is not None

    acc = Account(name="Konto główne", type="checking", currency="PLN", budget_id=budget.id)
    cat_food = Category(name="Food", budget_id=budget.id)
    cat_snacks = Category(name="Snacks", budget_id=budget.id)
    session.add(acc)
    session.add(cat_food)
    session.add(cat_snacks)
    session.commit()
    session.refresh(acc)
    session.refresh(cat_food)
    session.refresh(cat_snacks)
    assert acc.id is not None and cat_food.id is not None and cat_snacks.id is not None

    tx = Transaction(
        merchant_name="Lidl Rybnik",
        total_amount=Decimal("15.00"),
        date=datetime(2026, 6, 7, tzinfo=timezone.utc),
        budget_id=budget.id,
        uploaded_by=user.id,
        account_id=acc.id,
        review_status=ReviewStatus.PENDING,
    )
    session.add(tx)
    session.commit()
    session.refresh(tx)
    assert tx.id is not None

    session.add(
        ReceiptScan(
            transaction_id=tx.id,
            status=ScanStatus.NEEDS_REVIEW.value,
            processed_via="ocr_pipeline_v1",
            needs_review=True,
            validation_message="RECEIPT_SUM_MISMATCH:1.00",
        )
    )
    line = TransactionLine(
        transaction_id=tx.id,
        name="Czekolada",
        price=Decimal("14.00"),
        quantity=Decimal("1"),
        category_id=cat_food.id,
        category_source="ai",
    )
    session.add(line)
    session.add(
        SourceRecord(
            budget_id=budget.id,
            transaction_id=tx.id,
            source_type=SourceType.OCR_PHOTO,
            provider="google_vision",
            adapter_version="ocr_pipeline_v1",
            quality=Decimal("0.8800"),
            raw_payload_policy=RawPayloadPolicy.EPHEMERAL_IMAGE,
        )
    )
    session.commit()
    session.refresh(line)
    assert line.id is not None

    verify_res = client.post(
        f"/api/transactions/{tx.id}/verify",
        json={
            "transaction_update": {
                "merchant_name": "Lidl Rybnik",
                "total_amount": "15.00",
                "account_id": acc.id,
            },
            "lines_update": [
                {
                    "name": "Czekolada",
                    "price": "15.00",
                    "quantity": "1",
                    "category_id": cat_snacks.id,
                }
            ],
            "keep_image": False,
        },
    )
    assert verify_res.status_code == 200, verify_res.text
    verified = verify_res.json()
    assert verified["canonical_total_valid"] is True
    assert verified["review_reasons"] == []
    assert verified["lines"][0]["category_source"] == "user"
    assert verified["source_records"][0]["adapter_version"] == "ocr_pipeline_v1"

    # Transaction history GET /transactions returns the exact same serialized provenance signals
    history_res = client.get("/api/transactions")
    assert history_res.status_code == 200
    history_items = {row["id"]: row for row in history_res.json()}
    assert tx.id in history_items
    assert history_items[tx.id]["canonical_total_valid"] is True
    assert history_items[tx.id]["review_reasons"] == []
    assert history_items[tx.id]["lines"][0]["category_source"] == "user"

    # Direct line category update also marks category_source as "user"
    patch_line_res = client.patch(
        f"/api/transactions/{tx.id}/lines/{line.id}",
        json={"category_id": cat_food.id},
    )
    assert patch_line_res.status_code == 200
    assert patch_line_res.json()["category_source"] == "user"
