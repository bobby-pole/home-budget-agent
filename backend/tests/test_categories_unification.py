"""Tests for unified, budget-scoped categories, Inbox cache learning, and standard demo categories (#278)."""

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.adapters.contracts import (
    CanonicalTransaction,
    SourceProvenanceSpec,
    TransactionAdapterResult,
    TransactionBatchAdapterResult,
)
from app.category_service import (
    DEFAULT_CATEGORIES,
    get_budget_categories,
    seed_default_categories,
)
from app.demo_samples_data import SAMPLE_BIEDRONKA_DATA, SAMPLE_LIDL_DATA
from app.demo_seed import seed_demo_environment
from app.ingestion_service import (
    _categorize_receipt_dict_best_effort,
    ingest_transaction_batch,
)
from app.models import (
    Budget,
    Category,
    ProductCategoryCache,
    ReceiptScan,
    ScanStatus,
    SourceType,
    Transaction,
    TransactionLine,
    User,
)


def test_budget_scoping_excludes_other_budgets_system_and_custom_categories(session: Session):
    """AI category queries must never leak system or custom categories across budgets."""
    user_a = User(email="a@example.com", hashed_password="pw")
    user_b = User(email="b@example.com", hashed_password="pw")
    session.add(user_a)
    session.add(user_b)
    session.commit()
    session.refresh(user_a)
    session.refresh(user_b)
    assert user_a.id is not None
    assert user_b.id is not None

    budget_a = Budget(name="Budget A", owner_id=user_a.id)
    budget_b = Budget(name="Budget B", owner_id=user_b.id)
    session.add(budget_a)
    session.add(budget_b)
    session.commit()
    session.refresh(budget_a)
    session.refresh(budget_b)
    assert budget_a.id is not None
    assert budget_b.id is not None

    seed_default_categories(session, budget_a.id)
    seed_default_categories(session, budget_b.id)

    custom_a = Category(name="Hobby A", budget_id=budget_a.id, is_system=False)
    custom_b = Category(name="Secret B", budget_id=budget_b.id, is_system=False)
    session.add(custom_a)
    session.add(custom_b)
    session.commit()

    scoped_a = get_budget_categories(session, budget_a.id)
    scoped_a_ids = {c.id for c in scoped_a}
    scoped_a_names = [c.name for c in scoped_a]

    # Exact count: 15 system categories for A + 1 custom category for A (no duplicates from B!)
    assert len(scoped_a) == len(DEFAULT_CATEGORIES) + 1
    assert "Hobby A" in scoped_a_names
    assert "Secret B" not in scoped_a_names
    assert all(c.budget_id == budget_a.id for c in scoped_a)

    # Receipt categorization helper passes only Budget A's categories to AIService
    with patch("app.services.AIService._categorize_parsed_items") as mock_cat:
        mock_cat.side_effect = lambda data, cats, uid: data
        _, cat_name_to_id = _categorize_receipt_dict_best_effort(
            session,
            receipt_dict={"items": [{"name": "Klocki LEGO", "price": "50.00"}]},
            budget_id=budget_a.id,
            user_id=user_a.id,
            categorize=True,
        )
        passed_cats = mock_cat.call_args.args[1]
        assert len(passed_cats) == len(DEFAULT_CATEGORIES) + 1
        assert {c["id"] for c in passed_cats} == scoped_a_ids
        assert "secret b" not in cat_name_to_id

    # Batch transaction ingestion passes only Budget A's categories to AIService
    batch = TransactionBatchAdapterResult(
        items=[
            TransactionAdapterResult(
                transaction=CanonicalTransaction(
                    booked_at=datetime.now(timezone.utc),
                    amount=Decimal("-42.00"),
                    currency="PLN",
                    counterparty="Sklep Hobbystyczny",
                    title="Model do sklejania",
                ),
                provenance=SourceProvenanceSpec(
                    source_type=SourceType.BANK_CSV,
                    provider="test_csv",
                    external_id="tx-scope-1",
                ),
            )
        ],
    )
    with patch("app.services.AIService.categorize_descriptions") as mock_batch_ai:
        mock_batch_ai.return_value = {"Sklep Hobbystyczny Model do sklejania": "Hobby A"}
        ingest_transaction_batch(
            session,
            batch,
            budget_id=budget_a.id,
            user_id=user_a.id,
            enable_ai_categorization=True,
        )
        passed_batch_cats = mock_batch_ai.call_args.kwargs["categories"]
        assert len(passed_batch_cats) == len(DEFAULT_CATEGORIES) + 1
        assert {c["id"] for c in passed_batch_cats} == scoped_a_ids


@pytest.mark.asyncio
async def test_process_scan_passes_only_target_budget_categories(session: Session):
    """Background OCR scan must only expose the transaction budget's categories to AIService."""
    from app.api import _process_scan

    user_a = User(email="scan_a@example.com", hashed_password="pw")
    user_b = User(email="scan_b@example.com", hashed_password="pw")
    session.add(user_a)
    session.add(user_b)
    session.commit()
    session.refresh(user_a)
    session.refresh(user_b)
    assert user_a.id is not None
    assert user_b.id is not None

    budget_a = Budget(name="Scan Budget A", owner_id=user_a.id)
    budget_b = Budget(name="Scan Budget B", owner_id=user_b.id)
    session.add(budget_a)
    session.add(budget_b)
    session.commit()
    session.refresh(budget_a)
    session.refresh(budget_b)
    assert budget_a.id is not None
    assert budget_b.id is not None

    seed_default_categories(session, budget_a.id)
    seed_default_categories(session, budget_b.id)
    session.add(Category(name="User Custom A", budget_id=budget_a.id, is_system=False))
    session.commit()

    tx = Transaction(
        merchant_name="Processing...",
        budget_id=budget_a.id,
        uploaded_by=user_a.id,
    )
    session.add(tx)
    session.commit()
    session.refresh(tx)
    assert tx.id is not None

    scan = ReceiptScan(
        transaction_id=tx.id,
        status=ScanStatus.QUEUED.value,
        image_path="/tmp/nonexistent_scan.jpg",
    )
    session.add(scan)
    session.commit()
    session.refresh(scan)
    assert scan.id is not None

    mock_parsed = {
        "merchant_name": "Test Market",
        "total_amount": 10.00,
        "currency": "PLN",
        "date": "2026-11-16",
        "items": [{"name": "Item 1", "price": 10.00, "quantity": 1.0, "category": "User Custom A"}],
        "_validation": {"is_valid": True, "issues": [], "confidence": 0.99},
    }
    with patch("app.api.operations_engine", session.get_bind()), \
         patch("app.api.os.path.exists", return_value=True), \
         patch("app.api.AIService.parse_receipt", return_value=mock_parsed) as mock_parse:
        await _process_scan(scan_id=scan.id, transaction_id=tx.id, image_path="/tmp/nonexistent_scan.jpg")
        passed_cats = mock_parse.call_args.kwargs["categories"]
        expected_ids = {c.id for c in get_budget_categories(session, budget_a.id)}
        assert len(passed_cats) == len(DEFAULT_CATEGORIES) + 1
        assert {c["id"] for c in passed_cats} == expected_ids


def test_user_created_category_learned_on_inbox_verify(client: TestClient, session: Session):
    """User-added categories assigned during Inbox verification are saved to ProductCategoryCache."""
    budget = session.exec(select(Budget)).first()
    user = session.exec(select(User)).first()
    assert budget is not None and budget.id is not None
    assert user is not None and user.id is not None

    seed_default_categories(session, budget.id)

    # 1. Create custom category via API
    cat_res = client.post("/api/categories", json={"name": "Kawa rzemieślnicza", "color": "#6b4423"})
    assert cat_res.status_code == 200
    custom_cat = cat_res.json()
    assert custom_cat["is_system"] is False

    # 2. Seed staged transaction + scan + line in Inbox
    food_cat = session.exec(
        select(Category).where(Category.budget_id == budget.id, Category.name == "Food")
    ).first()
    assert food_cat is not None

    tx = Transaction(
        merchant_name="Palarnia Kawy",
        total_amount=Decimal("49.00"),
        budget_id=budget.id,
        uploaded_by=user.id,
    )
    session.add(tx)
    session.commit()
    session.refresh(tx)
    assert tx.id is not None

    scan = ReceiptScan(transaction_id=tx.id, status=ScanStatus.NEEDS_REVIEW.value, needs_review=True)
    line = TransactionLine(
        transaction_id=tx.id,
        name="Kawa Etiopia Sidamo 250g",
        price=Decimal("49.00"),
        quantity=Decimal("1.000"),
        category_id=food_cat.id,
        category_source="ai",
    )
    session.add(scan)
    session.add(line)
    session.commit()

    # 3. Verify transaction in Inbox while changing the line's category to the user-created one
    verify_res = client.post(
        f"/api/transactions/{tx.id}/verify",
        json={
            "transaction_update": {"merchant_name": "Palarnia Kawy"},
            "lines_update": [
                {
                    "name": "Kawa Etiopia Sidamo 250g",
                    "price": "49.00",
                    "quantity": "1.000",
                    "category_id": custom_cat["id"],
                }
            ],
            "keep_image": False,
        },
    )
    assert verify_res.status_code == 200, verify_res.text

    session.refresh(line)
    assert line.category_id == custom_cat["id"]
    assert line.category_source == "manual"

    cache_entry = session.exec(
        select(ProductCategoryCache).where(
            ProductCategoryCache.user_id == user.id,
            ProductCategoryCache.original_name == "Kawa Etiopia Sidamo 250g",
        )
    ).first()
    assert cache_entry is not None
    assert cache_entry.category_id == custom_cat["id"]


def test_update_category_rename_clears_is_system(client: TestClient, session: Session):
    """Updating only icon/color preserves is_system; renaming clears is_system."""
    budget = session.exec(select(Budget)).first()
    assert budget is not None and budget.id is not None
    seed_default_categories(session, budget.id)

    food = session.exec(
        select(Category).where(Category.budget_id == budget.id, Category.name == "Food")
    ).first()
    assert food is not None and food.id is not None
    assert food.is_system is True

    color_res = client.patch(f"/api/categories/{food.id}", json={"color": "#123456"})
    assert color_res.status_code == 200
    assert color_res.json()["is_system"] is True
    assert color_res.json()["name"] == "Food"

    rename_res = client.patch(f"/api/categories/{food.id}", json={"name": "Moje Jedzenie"})
    assert rename_res.status_code == 200
    assert rename_res.json()["is_system"] is False
    assert rename_res.json()["name"] == "Moje Jedzenie"


def test_demo_seed_and_samples_use_standard_canonical_categories(session: Session):
    """Demo environment and sample receipt fixtures must use the 15 canonical English system categories."""
    demo_user = seed_demo_environment(session, force_reset=True)
    assert demo_user.default_budget_id is not None

    categories = get_budget_categories(session, demo_user.default_budget_id)
    expected_names = {c["name"] for c in DEFAULT_CATEGORIES}
    assert {c.name for c in categories} == expected_names
    assert all(c.is_system is True for c in categories)

    for sample in (SAMPLE_BIEDRONKA_DATA, SAMPLE_LIDL_DATA):
        for item in sample["items"]:
            assert item["category"] in expected_names


def test_cross_budget_category_id_rejected_on_verify_and_update_line(client: TestClient, session: Session):
    """Cross-budget category IDs must be rejected (422) without polluting ProductCategoryCache."""
    user = session.exec(select(User)).first()
    budget = session.exec(select(Budget)).first()
    assert user is not None and user.id is not None
    assert budget is not None and budget.id is not None

    other_user = User(email="other_idor@example.com", hashed_password="pw")
    session.add(other_user)
    session.commit()
    session.refresh(other_user)
    assert other_user.id is not None

    other_budget = Budget(name="Other Budget", owner_id=other_user.id)
    session.add(other_budget)
    session.commit()
    session.refresh(other_budget)
    assert other_budget.id is not None

    foreign_cat = Category(name="Foreign Secret", budget_id=other_budget.id, is_system=False)
    session.add(foreign_cat)
    session.commit()
    session.refresh(foreign_cat)
    assert foreign_cat.id is not None

    tx = Transaction(
        merchant_name="Sklep Test",
        total_amount=Decimal("20.00"),
        budget_id=budget.id,
        uploaded_by=user.id,
    )
    session.add(tx)
    session.commit()
    session.refresh(tx)
    assert tx.id is not None

    scan = ReceiptScan(transaction_id=tx.id, status=ScanStatus.NEEDS_REVIEW.value, needs_review=True)
    line = TransactionLine(
        transaction_id=tx.id,
        name="Produkt X",
        price=Decimal("20.00"),
        quantity=Decimal("1.000"),
    )
    session.add(scan)
    session.add(line)
    session.commit()
    session.refresh(line)
    assert line.id is not None

    # 1. PATCH line with foreign category -> 422
    patch_res = client.patch(
        f"/api/transactions/{tx.id}/lines/{line.id}",
        json={"category_id": foreign_cat.id},
    )
    assert patch_res.status_code == 422

    # 2. Verify transaction with foreign line category -> 422
    verify_line_res = client.post(
        f"/api/transactions/{tx.id}/verify",
        json={
            "transaction_update": {"merchant_name": "Sklep Test"},
            "lines_update": [
                {"name": "Produkt X", "price": "20.00", "quantity": "1.000", "category_id": foreign_cat.id}
            ],
            "keep_image": False,
        },
    )
    assert verify_line_res.status_code == 422

    # 3. Verify transaction with foreign header category -> 422
    verify_header_res = client.post(
        f"/api/transactions/{tx.id}/verify",
        json={
            "transaction_update": {"category_id": foreign_cat.id},
            "keep_image": False,
        },
    )
    assert verify_header_res.status_code == 422

    # Cache must remain untouched
    cache_entries = session.exec(
        select(ProductCategoryCache).where(ProductCategoryCache.user_id == user.id)
    ).all()
    assert len(cache_entries) == 0


def test_demo_seed_replaces_stale_legacy_categories(session: Session):
    """seed_demo_environment(force_reset=False) auto-resets demo DB if legacy non-standard categories remain."""
    demo_user = seed_demo_environment(session, force_reset=True)
    assert demo_user.default_budget_id is not None
    legacy_budget_id = demo_user.default_budget_id

    # Simulate an older demo database that still has pre-refactor Polish categories
    for cat in get_budget_categories(session, legacy_budget_id):
        cat.name = f"Stara_{cat.name}"
        cat.is_system = False
        session.add(cat)
    session.commit()

    reused_user = seed_demo_environment(session, force_reset=False)
    assert reused_user.default_budget_id is not None

    refreshed_cats = get_budget_categories(session, reused_user.default_budget_id)
    assert {c.name for c in refreshed_cats} == {c["name"] for c in DEFAULT_CATEGORIES}
    assert all(c.is_system is True for c in refreshed_cats)

