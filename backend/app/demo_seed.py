# backend/app/demo_seed.py
"""
Deterministic Demo Environment Seed Service.

Provides a rich, realistic showcase dataset for public demo mode:
- Demo User & Household Budget
- Bank & Cash Accounts with realistic balances
- Envelope Categories & Monthly Allocations
- Recent Transactions with dynamic relative dates
- Staged / Inbox Receipts (Biedronka, Lidl) with parsed line items
"""

import argparse
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlmodel import Session, col, delete, select

from .auth import hash_password
from .config import settings
from .models import (
    Account,
    Budget,
    BudgetMember,
    Category,
    EnvelopeAllocation,
    ReceiptScan,
    ScanStatus,
    Transaction,
    TransactionLine,
    TransactionStatus,
    User,
)

logger = logging.getLogger(__name__)

DEMO_USER_PASSWORD = "demo_password_123"
DEMO_BUDGET_NAME = "Budżet Domowy (Demo)"


def clean_demo_data(session: Session, user: User) -> None:
    """Delete all budgets, accounts, categories, transactions and allocations owned by demo user."""
    logger.info("Cleaning existing demo data for user %s", user.email)
    
    # Find all budgets where demo user is a member or owner
    memberships = session.exec(select(BudgetMember).where(BudgetMember.user_id == user.id)).all()
    budget_ids = [m.budget_id for m in memberships]
    
    owned_budgets = session.exec(select(Budget).where(Budget.owner_id == user.id)).all()
    for b in owned_budgets:
        if b.id and b.id not in budget_ids:
            budget_ids.append(b.id)

    for budget_id in budget_ids:
        # 1. Delete transaction lines & receipt scans
        transactions = session.exec(select(Transaction).where(Transaction.budget_id == budget_id)).all()
        t_ids = [t.id for t in transactions if t.id is not None]
        if t_ids:
            session.exec(delete(TransactionLine).where(col(TransactionLine.transaction_id).in_(t_ids)))
            session.exec(delete(ReceiptScan).where(col(ReceiptScan.transaction_id).in_(t_ids)))
            session.exec(delete(Transaction).where(col(Transaction.id).in_(t_ids)))

        # 2. Delete envelope allocations
        session.exec(delete(EnvelopeAllocation).where(EnvelopeAllocation.budget_id == budget_id))

        # 3. Delete accounts
        session.exec(delete(Account).where(Account.budget_id == budget_id))

        # 4. Delete categories (handle subcategories first to avoid FK constraint issues)
        session.exec(
            delete(Category).where(
                Category.budget_id == budget_id,
                Category.parent_id != None  # noqa: E711
            )
        )
        session.exec(delete(Category).where(Category.budget_id == budget_id))

        # 5. Delete budget members and the budget itself
        session.exec(delete(BudgetMember).where(BudgetMember.budget_id == budget_id))
        session.exec(delete(Budget).where(Budget.id == budget_id))

    user.default_budget_id = None
    session.add(user)
    session.commit()


def seed_demo_environment(session: Session, force_reset: bool = False) -> User:
    """
    Seed a complete, idempotent demo environment.
    If force_reset=False and demo user already has a configured budget, returns existing user.
    """
    now = datetime.now(timezone.utc)
    current_year = now.year
    current_month = now.month

    # 1. Ensure Demo User exists
    demo_user = session.exec(select(User).where(User.email == settings.DEMO_USER_EMAIL)).first()
    if not demo_user:
        demo_user = User(
            email=settings.DEMO_USER_EMAIL,
            hashed_password=hash_password(DEMO_USER_PASSWORD),
            created_at=now - timedelta(days=60),
        )
        session.add(demo_user)
        session.commit()
        session.refresh(demo_user)
    elif force_reset:
        clean_demo_data(session, demo_user)
        session.refresh(demo_user)
    else:
        # If not force_reset, check if budget already exists
        if demo_user.default_budget_id:
            existing_budget = session.get(Budget, demo_user.default_budget_id)
            if existing_budget:
                account_count = session.exec(select(Account).where(Account.budget_id == existing_budget.id)).all()
                if account_count:
                    logger.info("Demo environment already seeded for %s, skipping.", demo_user.email)
                    return demo_user

    # 2. Create Budget & Owner Membership
    budget = Budget(name=DEMO_BUDGET_NAME, owner_id=demo_user.id)
    session.add(budget)
    session.commit()
    session.refresh(budget)

    assert budget.id is not None
    member = BudgetMember(budget_id=budget.id, user_id=demo_user.id, role="owner")
    session.add(member)

    demo_user.default_budget_id = budget.id
    session.add(demo_user)
    session.commit()

    # 3. Create Accounts
    # Target Balances:
    # Checking: 4 250.00 PLN
    # Savings: 18 500.00 PLN
    # Cash: 320.00 PLN
    acc_checking = Account(
        name="Konto Główne ROR (mBank)",
        type="checking",
        currency="PLN",
        initial_balance=4250.00,
        current_balance=4250.00,
        budget_id=budget.id,
        is_on_budget=True,
        is_active=True,
    )
    acc_savings = Account(
        name="Konto Oszczędnościowe (ING)",
        type="savings",
        currency="PLN",
        initial_balance=18500.00,
        current_balance=18500.00,
        budget_id=budget.id,
        is_on_budget=True,
        is_active=True,
    )
    acc_cash = Account(
        name="Portfel / Gotówka",
        type="cash",
        currency="PLN",
        initial_balance=320.00,
        current_balance=320.00,
        budget_id=budget.id,
        is_on_budget=True,
        is_active=True,
    )
    session.add(acc_checking)
    session.add(acc_savings)
    session.add(acc_cash)
    session.commit()
    session.refresh(acc_checking)
    session.refresh(acc_savings)
    session.refresh(acc_cash)

    # 4. Create Category Groups & Categories
    categories_def = [
        # (Group name, icon, color, [(Subcat name, icon, color, planned_amount)])
        (
            "Stałe opłaty", "home", "#fb923c", [
                ("Mieszkanie / Czynsz", "home", "#fb923c", 2500.00),
                ("Prąd i Gaz", "lightbulb", "#facc15", 350.00),
                ("Internet i Telefon", "lightbulb", "#60a5fa", 120.00),
            ]
        ),
        (
            "Codzienne wydatki", "utensils", "#f87171", [
                ("Żywność i Supermarket", "utensils", "#f87171", 1800.00),
                ("Restauracje i Kawiarnie", "cookie", "#c084fc", 400.00),
                ("Transport i Paliwo", "car", "#38bdf8", 600.00),
                ("Drogeria i Zdrowie", "heart-pulse", "#f472b6", 300.00),
            ]
        ),
        (
            "Rozrywka i Czas wolny", "clapperboard", "#a78bfa", [
                ("Subskrypcje (Netflix, Spotify)", "clapperboard", "#a78bfa", 100.00),
                ("Rozrywka i Wyjścia", "gift", "#fb7185", 250.00),
            ]
        ),
        (
            "Oszczędności", "coins", "#fbbf24", [
                ("Fundusz Awaryjny", "coins", "#fbbf24", 1000.00),
                ("Wakacje", "plane", "#34d399", 500.00),
            ]
        ),
    ]

    cat_map = {}
    order_idx = 0

    for group_name, g_icon, g_color, subcats in categories_def:
        group_cat = Category(
            name=group_name,
            icon=g_icon,
            color=g_color,
            is_system=False,
            budget_id=budget.id,
            parent_id=None,
            order_index=order_idx,
        )
        session.add(group_cat)
        session.commit()
        session.refresh(group_cat)
        order_idx += 1

        for sub_name, s_icon, s_color, planned in subcats:
            sub_cat = Category(
                name=sub_name,
                icon=s_icon,
                color=s_color,
                is_system=False,
                budget_id=budget.id,
                parent_id=group_cat.id,
                order_index=order_idx,
            )
            session.add(sub_cat)
            session.commit()
            session.refresh(sub_cat)
            order_idx += 1

            cat_map[sub_name] = sub_cat

            # Envelope allocation for current month
            allocation = EnvelopeAllocation(
                budget_id=budget.id,
                category_id=sub_cat.id,
                year=current_year,
                month=current_month,
                amount=planned,
            )
            session.add(allocation)

    session.commit()

    # 5. Seed Real-world Transactions (Spread across past 21 days)
    # Helper to get category safely
    def get_cat(name: str) -> Optional[int]:
        cat = cat_map.get(name)
        return cat.id if cat else None

    transactions_data = [
        # (merchant, days_ago, hours_ago, amount, acc, type, status, cat_name, note)
        ("Wynagrodzenie (Pracodawca)", 20, 9, 8500.00, acc_checking, "income", TransactionStatus.CLEARED, None, "Wypłata za poprzedni miesiąc"),
        ("Spółdzielnia Mieszkaniowa", 19, 10, 2500.00, acc_checking, "expense", TransactionStatus.CLEARED, "Mieszkanie / Czynsz", "Czynsz administracyjny"),
        ("PGE Polska Grupa Energetyczna", 18, 14, 210.50, acc_checking, "expense", TransactionStatus.CLEARED, "Prąd i Gaz", "Faktura za energię"),
        ("Orange Polska", 17, 11, 89.99, acc_checking, "expense", TransactionStatus.CLEARED, "Internet i Telefon", "Światłowód i abonament komórkowy"),
        ("Biedronka", 16, 17, 164.20, acc_checking, "expense", TransactionStatus.CLEARED, "Żywność i Supermarket", "Zakupy tygodniowe"),
        ("Orlen", 15, 8, 245.00, acc_checking, "expense", TransactionStatus.CLEARED, "Transport i Paliwo", "Tankowanie Pb95"),
        ("Rossmann", 14, 16, 78.40, acc_checking, "expense", TransactionStatus.CLEARED, "Drogeria i Zdrowie", "Kosmetyki i środki czystości"),
        ("Żabka", 13, 19, 18.50, acc_cash, "expense", TransactionStatus.CLEARED, "Żywność i Supermarket", "Przekąski"),
        ("Netflix", 12, 6, 43.00, acc_checking, "expense", TransactionStatus.CLEARED, "Subskrypcje (Netflix, Spotify)", "Abonament Standard"),
        ("Spotify", 12, 6, 24.99, acc_checking, "expense", TransactionStatus.CLEARED, "Subskrypcje (Netflix, Spotify)", "Pakiet Duo"),
        ("Lidl", 11, 18, 132.80, acc_checking, "expense", TransactionStatus.CLEARED, "Żywność i Supermarket", "Zakupy spożywcze"),
        ("Piekarnia Rzemieślnicza", 10, 8, 26.50, acc_cash, "expense", TransactionStatus.CLEARED, "Żywność i Supermarket", "Chleb na zakwasie"),
        ("Green Caffe Nero", 9, 15, 42.00, acc_checking, "expense", TransactionStatus.CLEARED, "Restauracje i Kawiarnie", "Kawa i ciasto"),
        ("Uber", 8, 23, 34.50, acc_checking, "expense", TransactionStatus.CLEARED, "Transport i Paliwo", "Powrót ze spotkania"),
        ("Restauracja Manekin", 7, 19, 94.00, acc_checking, "expense", TransactionStatus.CLEARED, "Restauracje i Kawiarnie", "Obiad dla dwojga"),
        ("Apteka Gemini", 6, 12, 64.30, acc_checking, "expense", TransactionStatus.CLEARED, "Drogeria i Zdrowie", "Witaminy i leki"),
        ("Biedronka", 5, 17, 98.70, acc_checking, "expense", TransactionStatus.CLEARED, "Żywność i Supermarket", "Uzupełnienie zapasów"),
        ("Multikino", 4, 20, 72.00, acc_checking, "expense", TransactionStatus.CLEARED, "Rozrywka i Wyjścia", "Bilety na seans filmowy"),
        ("Allegro", 3, 14, 119.00, acc_checking, "expense", TransactionStatus.CLEARED, "Rozrywka i Wyjścia", "Akcesoria domowe"),
        ("Żabka", 2, 12, 14.20, acc_cash, "expense", TransactionStatus.CLEARED, "Żywność i Supermarket", "Kawa i kanapka"),
        ("Stacja Shell", 1, 16, 180.00, acc_checking, "expense", TransactionStatus.CLEARED, "Transport i Paliwo", "Paliwo na weekend"),
    ]

    for merchant, days_ago, hours_ago, amount, acc, t_type, status, cat_name, note in transactions_data:
        t_date = now - timedelta(days=days_ago, hours=hours_ago)
        t = Transaction(
            merchant_name=merchant,
            date=t_date,
            total_amount=amount,
            currency="PLN",
            type=t_type,
            status=status,
            account_id=acc.id,
            budget_id=budget.id,
            uploaded_by=demo_user.id,
            category_id=get_cat(cat_name) if cat_name else None,
            note=note,
        )
        session.add(t)

    session.commit()

    # 6. Showcase Staging Receipts in /inbox (Awaiting Verification)
    # Staging Receipt 1: Biedronka (Total: 84.50 PLN)
    t1_date = now - timedelta(hours=3)
    t1 = Transaction(
        merchant_name="Biedronka",
        date=t1_date,
        total_amount=84.50,
        currency="PLN",
        type="expense",
        status=TransactionStatus.UNCLEARED,
        account_id=acc_checking.id,
        budget_id=budget.id,
        uploaded_by=demo_user.id,
        category_id=get_cat("Żywność i Supermarket"),
        note="Paragon ze skanera OCR (oczekuje na potwierdzenie)",
    )
    session.add(t1)
    session.commit()
    session.refresh(t1)

    scan1 = ReceiptScan(
        transaction_id=t1.id,
        status=ScanStatus.NEEDS_REVIEW.value,
        needs_review=True,
        validation_message="Sprawdź przypisane kategorie przed zatwierdzeniem",
        raw_ocr_text="Jeronimo Martins Polska S.A. Biedronka... SUMA PLN 84.50",
        reconstructed_lines=[
            "Jeronimo Martins Polska S.A.",
            "BIEDRONKA UL. PROSTA 12",
            "Mleko Wiejskie 3.2% 1L   2 x 3.69 = 7.38 A",
            "Chleb Żytni Krojony 500g 1 x 4.50 = 4.50 A",
            "Kawa Ziarnista Lavazza 1kg 1 x 49.99 = 49.99 A",
            "Jabłka Polskie Gala 1.5kg  1 x 7.49 = 7.49 A",
            "Płyn do naczyń Pur 750ml   1 x 15.14 = 15.14 B",
            "SUMA PLN: 84.50",
        ],
        created_at=t1_date,
    )
    session.add(scan1)

    t1_lines = [
        ("Mleko Wiejskie 3.2% 1L", 7.38, 2.0, "Żywność i Supermarket"),
        ("Chleb Żytni Krojony 500g", 4.50, 1.0, "Żywność i Supermarket"),
        ("Kawa Ziarnista Lavazza 1kg", 49.99, 1.0, "Żywność i Supermarket"),
        ("Jabłka Polskie Gala 1.5kg", 7.49, 1.0, "Żywność i Supermarket"),
        ("Płyn do naczyń Pur 750ml", 15.14, 1.0, "Drogeria i Zdrowie"),
    ]
    for line_name, price, qty, c_name in t1_lines:
        session.add(
            TransactionLine(
                transaction_id=t1.id,
                name=line_name,
                price=price,
                quantity=qty,
                category_id=get_cat(c_name),
                category_source="auto_categorizer",
            )
        )

    # Staging Receipt 2: Lidl (Total: 42.30 PLN)
    t2_date = now - timedelta(days=1, hours=2)
    t2 = Transaction(
        merchant_name="Lidl",
        date=t2_date,
        total_amount=42.30,
        currency="PLN",
        type="expense",
        status=TransactionStatus.UNCLEARED,
        account_id=acc_checking.id,
        budget_id=budget.id,
        uploaded_by=demo_user.id,
        category_id=get_cat("Żywność i Supermarket"),
        note="Paragon ze skanera OCR (oczekuje na potwierdzenie)",
    )
    session.add(t2)
    session.commit()
    session.refresh(t2)

    scan2 = ReceiptScan(
        transaction_id=t2.id,
        status=ScanStatus.NEEDS_REVIEW.value,
        needs_review=True,
        validation_message="Sprawdź przypisane kategorie przed zatwierdzeniem",
        raw_ocr_text="LIDL SP Z O O SP K... SUMA PLN 42.30",
        reconstructed_lines=[
            "LIDL POLSKA",
            "Masło Pilos Ekstra 200g 2 x 6.99 = 13.98 A",
            "Ser Gouda w plastrach 400g 1 x 12.49 = 12.49 A",
            "Pomidory Gałązka 1kg 1 x 15.83 = 15.83 A",
            "SUMA PLN: 42.30",
        ],
        created_at=t2_date,
    )
    session.add(scan2)

    t2_lines = [
        ("Masło Pilos Ekstra 200g", 13.98, 2.0, "Żywność i Supermarket"),
        ("Ser Gouda w plastrach 400g", 12.49, 1.0, "Żywność i Supermarket"),
        ("Pomidory Gałązka 1kg", 15.83, 1.0, "Żywność i Supermarket"),
    ]
    for line_name, price, qty, c_name in t2_lines:
        session.add(
            TransactionLine(
                transaction_id=t2.id,
                name=line_name,
                price=price,
                quantity=qty,
                category_id=get_cat(c_name),
                category_source="auto_categorizer",
            )
        )

    session.commit()
    session.refresh(demo_user)
    logger.info("Demo environment successfully seeded for %s (Budget ID: %s)", demo_user.email, budget.id)
    return demo_user


if __name__ == "__main__":
    from .database import operations_engine

    parser = argparse.ArgumentParser(description="Seed demo environment")
    parser.add_argument("--force-reset", action="store_true", help="Force clean and re-seed demo data")
    args = parser.parse_args()

    with Session(operations_engine) as session:
        user = seed_demo_environment(session, force_reset=args.force_reset)
        print(f"✅ Demo environment ready for {user.email} (Budget ID: {user.default_budget_id})")
