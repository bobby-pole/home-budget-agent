# backend/app/api.py
import shutil
import os
import hashlib
from uuid import uuid4
from datetime import datetime, timezone
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Depends, BackgroundTasks
from sqlalchemy import extract
from sqlmodel import Session, select, desc, col
from .models import (
    Transaction, TransactionLine, TransactionRead, TransactionUpdate,
    TransactionLineUpdate, ManualTransactionCreate,
    ReceiptScan,
    MonthlyBudget, MonthlyBudgetUpdate, MonthlyBudgetRead,
    BudgetCategoryLimit, BudgetCategoryLimitUpdate, BudgetCategoryLimitRead,
    CategoryBudgetSummaryItem, MonthlyBudgetSummary,
    User, UserCreate, UserRead, Token,
    Category, Tag, CategoryCreate, CategoryUpdate, CategoryRead, TagCreate, TagRead, TagUpdate, TransactionTagLink
)
from .database import get_session, get_ops_session, operations_engine
from .services import AIService
from .auth import get_current_user, hash_password, verify_password, create_access_token
from typing import List

router = APIRouter()
UPLOAD_DIR = "static/uploads"


# --- AUTH ---

@router.post("/auth/register", response_model=Token)
def register(user_data: UserCreate, session: Session = Depends(get_session)):
    existing = session.exec(select(User).where(User.email == user_data.email)).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    user = User(email=user_data.email, hashed_password=hash_password(user_data.password))
    session.add(user)
    session.commit()
    session.refresh(user)
    assert user.id is not None
    token = create_access_token({"sub": user.email})
    return Token(access_token=token, user=UserRead(id=user.id, email=user.email, created_at=user.created_at))


@router.post("/auth/login", response_model=Token)
def login(user_data: UserCreate, session: Session = Depends(get_session)):
    user = session.exec(select(User).where(User.email == user_data.email)).first()
    if not user or not verify_password(user_data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    assert user.id is not None
    token = create_access_token({"sub": user.email})
    return Token(access_token=token, user=UserRead(id=user.id, email=user.email, created_at=user.created_at))


@router.get("/auth/me", response_model=UserRead)
def get_me(current_user: User = Depends(get_current_user)):
    return current_user


# --- BACKGROUND TASK ---

def process_transaction_in_background(transaction_id: int, scan_id: int, image_path: str):
    print(f"🤖 AI Processing started for transaction #{transaction_id}...")

    with Session(operations_engine) as session:
        transaction = session.get(Transaction, transaction_id)
        scan = session.get(ReceiptScan, scan_id)

        if not transaction or not scan:
            print("❌ Transaction or ReceiptScan not found")
            if scan:
                scan.status = "error"
                session.add(scan)
                session.commit()
            return

        data = AIService.parse_receipt(image_path)

        if not data:
            print("❌ AI Failed to parse receipt")
            scan.status = "error"
            session.add(scan)
            session.commit()
            return

        merchant = data.get("merchant_name")
        total = data.get("total_amount", 0.0)

        if not merchant or merchant == "Unknown" or total <= 0:
            print(f"⚠️ AI Validation Failed: Merchant='{merchant}', Total={total}")
            scan.status = "error"
            transaction.merchant_name = merchant or "Unknown"
            transaction.total_amount = total
            transaction.currency = data.get("currency", "PLN")
            session.add(scan)
            session.add(transaction)
            session.commit()
            return

        transaction.merchant_name = merchant
        transaction.total_amount = total
        transaction.currency = data.get("currency", "PLN")
        scan.status = "done"

        ai_date_str = data.get("date")
        if ai_date_str:
            try:
                transaction.date = datetime.strptime(ai_date_str, "%Y-%m-%d")
            except (ValueError, TypeError):
                print(f"⚠️ Could not parse AI date: {ai_date_str}")

        items_data = data.get("items", [])
        for item_raw in items_data:
            category_name = item_raw.get("category", "Other")
            category = session.exec(
                select(Category).where(Category.name == category_name)
            ).first()
            session.add(TransactionLine(
                name=item_raw["name"],
                price=item_raw["price"],
                quantity=item_raw.get("quantity", 1),
                category_id=category.id if category else None,
                transaction_id=transaction.id,
            ))

        session.add(transaction)
        session.add(scan)
        session.commit()
        print(f"✅ AI Processing finished for transaction #{transaction_id}")

        # --- LOGIKA OSZCZĘDZANIA MIEJSCA NA VPS ---
        # Usuwamy plik tylko jeśli użytkownik NIE zaznaczył opcji zachowania obrazu (np. do gwarancji)
        if not scan.keep_image and image_path and os.path.exists(image_path):
            try:
                os.remove(image_path)
                print(f"🗑️  Deleted processed image: {image_path} (Storage limit protection)")
                scan.image_path = None
                session.add(scan)
                session.commit()
            except Exception as e:
                print(f"⚠️  Failed to delete image {image_path}: {e}")
        elif scan.keep_image:
            print(f"💾 Image preserved for transaction #{transaction_id} (User request)")


# --- TRANSACTIONS ---

@router.post("/transactions/manual", response_model=TransactionRead)
def create_manual_transaction(
    data: ManualTransactionCreate,
    session: Session = Depends(get_ops_session),
    current_user: User = Depends(get_current_user),
):
    total = (
        sum(line.price * line.quantity for line in data.lines)
        if data.lines
        else data.total_amount
    )

    transaction = Transaction(
        merchant_name=data.merchant_name,
        total_amount=total,
        currency=data.currency,
        date=data.date or datetime.now(timezone.utc),
        is_manual=True,
        type=data.type,
        uploaded_by=current_user.id,
        category_id=data.category_id,
        note=data.note,
    )

    if data.tag_ids:
        tags = session.exec(select(Tag).where(col(Tag.id).in_(data.tag_ids))).all()
        transaction.tags = list(tags)

    session.add(transaction)
    session.commit()
    session.refresh(transaction)

    if data.lines:
        for line_data in data.lines:
            session.add(TransactionLine(
                name=line_data.name,
                price=line_data.price,
                quantity=line_data.quantity,
                category_id=line_data.category_id,
                transaction_id=transaction.id,
            ))
    else:
        session.add(TransactionLine(
            name=data.note or "Wpis ręczny",
            price=data.total_amount,
            quantity=1.0,
            category_id=data.category_id,
            transaction_id=transaction.id,
        ))

    session.commit()
    session.refresh(transaction)
    return transaction


@router.post("/transactions/scan", response_model=TransactionRead)
async def scan_transaction(
    background_tasks: BackgroundTasks,
    force: bool = False,
    keep_image: bool = Form(False),
    note: str | None = Form(None),
    file: UploadFile = File(...),
    session: Session = Depends(get_ops_session),
    current_user: User = Depends(get_current_user),
):
    file_content = await file.read()
    file_hash = hashlib.sha256(file_content).hexdigest()

    await file.seek(0)

    if not force:
        existing_scan = session.exec(
            select(ReceiptScan).where(
                ReceiptScan.content_hash == file_hash,
                ReceiptScan.transaction_id.in_(  # type: ignore
                    select(Transaction.id).where(Transaction.uploaded_by == current_user.id)
                ),
            )
        ).first()
        if existing_scan:
            raise HTTPException(
                status_code=409,
                detail="Duplicate receipt detected. Use force=true to upload anyway."
            )

    filename = file.filename or "upload.jpg"
    file_extension = filename.split(".")[-1]
    unique_filename = f"{uuid4()}.{file_extension}"
    file_path = f"{UPLOAD_DIR}/{unique_filename}"

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    new_transaction = Transaction(
        merchant_name="Processing...",
        uploaded_by=current_user.id,
        note=note,
    )
    session.add(new_transaction)
    session.commit()
    session.refresh(new_transaction)

    assert new_transaction.id is not None
    scan = ReceiptScan(
        transaction_id=new_transaction.id,
        image_path=file_path,
        status="processing",
        content_hash=file_hash,
        keep_image=keep_image,
    )
    session.add(scan)
    session.commit()
    session.refresh(scan)

    assert scan.id is not None
    background_tasks.add_task(process_transaction_in_background, new_transaction.id, scan.id, file_path)

    session.refresh(new_transaction)
    return new_transaction


@router.post("/transactions/{transaction_id}/retry", response_model=TransactionRead)
async def retry_transaction(
    transaction_id: int,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_ops_session),
    current_user: User = Depends(get_current_user),
):
    transaction = session.get(Transaction, transaction_id)
    if not transaction:
        raise HTTPException(status_code=404, detail="Transaction not found")

    if transaction.uploaded_by != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to retry this transaction")

    scan = session.exec(
        select(ReceiptScan).where(ReceiptScan.transaction_id == transaction_id)
    ).first()
    if not scan:
        raise HTTPException(status_code=404, detail="No receipt scan found for this transaction")

    if scan.status != "error":
        raise HTTPException(status_code=400, detail="Only failed scans can be retried")

    if not scan.image_path or not os.path.exists(scan.image_path):
        raise HTTPException(status_code=404, detail="Original image file not found. Please re-upload.")

    scan.status = "processing"
    session.add(scan)
    session.commit()
    session.refresh(transaction)

    assert transaction.id is not None
    assert scan.id is not None
    background_tasks.add_task(process_transaction_in_background, transaction.id, scan.id, scan.image_path)

    return transaction


@router.get("/transactions", response_model=List[TransactionRead])
async def get_transactions(
    limit: int = 50,
    offset: int = 0,
    session: Session = Depends(get_ops_session),
    current_user: User = Depends(get_current_user),
):
    statement = (
        select(Transaction)
        .where(Transaction.uploaded_by == current_user.id)
        .order_by(desc(Transaction.date))
        .offset(offset)
        .limit(limit)
    )
    results = session.exec(statement).all()
    return results


@router.patch("/transactions/{transaction_id}", response_model=TransactionRead)
async def update_transaction(
    transaction_id: int,
    transaction_update: TransactionUpdate,
    session: Session = Depends(get_ops_session),
    current_user: User = Depends(get_current_user),
):
    db_transaction = session.get(Transaction, transaction_id)
    if not db_transaction:
        raise HTTPException(status_code=404, detail="Transaction not found")

    if db_transaction.uploaded_by != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to modify this transaction")

    transaction_data = transaction_update.model_dump(exclude_unset=True, exclude={"tag_ids"})
    for key, value in transaction_data.items():
        setattr(db_transaction, key, value)

    if transaction_update.tag_ids is not None:
        tags = session.exec(select(Tag).where(col(Tag.id).in_(transaction_update.tag_ids))).all()
        db_transaction.tags = list(tags)

    session.add(db_transaction)
    session.commit()
    session.refresh(db_transaction)
    return db_transaction


@router.patch("/transactions/{transaction_id}/lines/{line_id}", response_model=TransactionLine)
async def update_line(
    transaction_id: int,
    line_id: int,
    line_update: TransactionLineUpdate,
    session: Session = Depends(get_ops_session),
    current_user: User = Depends(get_current_user),
):
    db_line = session.get(TransactionLine, line_id)
    if not db_line or db_line.transaction_id != transaction_id:
        raise HTTPException(status_code=404, detail="Transaction line not found")

    parent_transaction = session.get(Transaction, transaction_id)
    if not parent_transaction or parent_transaction.uploaded_by != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to modify this line")

    line_data = line_update.model_dump(exclude_unset=True)
    for key, value in line_data.items():
        setattr(db_line, key, value)

    session.add(db_line)
    session.commit()
    session.refresh(db_line)
    return db_line


@router.delete("/transactions/{transaction_id}", status_code=204)
async def delete_transaction(
    transaction_id: int,
    session: Session = Depends(get_ops_session),
    current_user: User = Depends(get_current_user),
):
    transaction = session.get(Transaction, transaction_id)
    if not transaction:
        raise HTTPException(status_code=404, detail="Transaction not found")

    if transaction.uploaded_by != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to delete this transaction")

    scan = session.exec(
        select(ReceiptScan).where(ReceiptScan.transaction_id == transaction_id)
    ).first()
    if scan:
        if scan.image_path and os.path.exists(scan.image_path):
            try:
                os.remove(scan.image_path)
            except OSError:
                pass
        session.delete(scan)

    for line in transaction.lines:
        session.delete(line)

    session.delete(transaction)
    session.commit()
    return None


# --- BUDGET ---

@router.get("/budget/{year}/{month}", response_model=MonthlyBudgetRead)
async def get_budget(
    year: int,
    month: int,
    session: Session = Depends(get_ops_session),
    current_user: User = Depends(get_current_user),
):
    statement = (
        select(MonthlyBudget)
        .where(MonthlyBudget.year == year)
        .where(MonthlyBudget.month == month)
        .where(MonthlyBudget.user_id == current_user.id)
    )
    budget = session.exec(statement).first()
    if not budget:
        return MonthlyBudgetRead(year=year, month=month, amount=0.0, user_id=current_user.id or 0)
    return budget


@router.post("/budget/{year}/{month}", response_model=MonthlyBudgetRead)
async def set_budget(
    year: int,
    month: int,
    budget_data: MonthlyBudgetUpdate,
    session: Session = Depends(get_ops_session),
    current_user: User = Depends(get_current_user),
):
    statement = (
        select(MonthlyBudget)
        .where(MonthlyBudget.year == year)
        .where(MonthlyBudget.month == month)
        .where(MonthlyBudget.user_id == current_user.id)
    )
    existing = session.exec(statement).first()

    if existing:
        if budget_data.amount is not None:
            existing.amount = budget_data.amount
        session.add(existing)
        session.commit()
        session.refresh(existing)
        return existing

    new_budget = MonthlyBudget(year=year, month=month, amount=budget_data.amount or 0.0, user_id=current_user.id)
    session.add(new_budget)
    session.commit()
    session.refresh(new_budget)
    return new_budget



@router.get("/budget/{year}/{month}/limits", response_model=List[BudgetCategoryLimitRead])
async def get_category_limits(
    year: int,
    month: int,
    session: Session = Depends(get_ops_session),
    current_user: User = Depends(get_current_user),
):
    budget_stmt = select(MonthlyBudget).where(
        MonthlyBudget.year == year,
        MonthlyBudget.month == month,
        MonthlyBudget.user_id == current_user.id,
    )
    budget = session.exec(budget_stmt).first()
    if not budget:
        return []

    limits_stmt = select(BudgetCategoryLimit).where(
        BudgetCategoryLimit.monthly_budget_id == budget.id
    )
    return session.exec(limits_stmt).all()


@router.put("/budget/{year}/{month}/limits/{category_id}", response_model=BudgetCategoryLimitRead)
async def upsert_category_limit(
    year: int,
    month: int,
    category_id: int,
    limit_data: BudgetCategoryLimitUpdate,
    session: Session = Depends(get_ops_session),
    current_user: User = Depends(get_current_user),
):
    # Ensure MonthlyBudget exists
    budget_stmt = select(MonthlyBudget).where(
        MonthlyBudget.year == year,
        MonthlyBudget.month == month,
        MonthlyBudget.user_id == current_user.id,
    )
    budget = session.exec(budget_stmt).first()
    if not budget:
        budget = MonthlyBudget(year=year, month=month, amount=0.0, user_id=current_user.id)
        session.add(budget)
        session.commit()
        session.refresh(budget)

    limit_stmt = select(BudgetCategoryLimit).where(
        BudgetCategoryLimit.monthly_budget_id == budget.id,
        BudgetCategoryLimit.category_id == category_id,
    )
    limit = session.exec(limit_stmt).first()

    if limit:
        limit.amount = limit_data.amount
    else:
        assert budget.id is not None, "Budget ID is None after commit"
        limit = BudgetCategoryLimit(
            monthly_budget_id=budget.id,
            category_id=category_id,
            amount=limit_data.amount,
        )

    session.add(limit)
    session.commit()
    session.refresh(limit)
    return limit


@router.delete("/budget/{year}/{month}/limits/{category_id}", status_code=204)
async def delete_category_limit(
    year: int,
    month: int,
    category_id: int,
    session: Session = Depends(get_ops_session),
    current_user: User = Depends(get_current_user),
):
    budget_stmt = select(MonthlyBudget).where(
        MonthlyBudget.year == year,
        MonthlyBudget.month == month,
        MonthlyBudget.user_id == current_user.id,
    )
    budget = session.exec(budget_stmt).first()
    if not budget:
        raise HTTPException(status_code=404, detail="Limit not found")

    limit_stmt = select(BudgetCategoryLimit).where(
        BudgetCategoryLimit.monthly_budget_id == budget.id,
        BudgetCategoryLimit.category_id == category_id,
    )
    limit = session.exec(limit_stmt).first()
    if not limit:
        raise HTTPException(status_code=404, detail="Limit not found")

    session.delete(limit)
    session.commit()
    return None


@router.get("/budget/{year}/{month}/summary", response_model=MonthlyBudgetSummary)
async def get_budget_summary(
    year: int,
    month: int,
    session: Session = Depends(get_ops_session),
    current_user: User = Depends(get_current_user),
):
    # --- Fetch category limits for this month ---
    budget_stmt = select(MonthlyBudget).where(
        MonthlyBudget.year == year,
        MonthlyBudget.month == month,
        MonthlyBudget.user_id == current_user.id,
    )
    budget = session.exec(budget_stmt).first()

    limits: dict[int, float] = {}  # category_id -> planned amount
    if budget:
        limits_stmt = select(BudgetCategoryLimit).where(
            BudgetCategoryLimit.monthly_budget_id == budget.id
        )
        for lim in session.exec(limits_stmt).all():
            limits[lim.category_id] = lim.amount

    # --- Fetch transactions for this month/year belonging to current user ---
    transactions_stmt = select(Transaction).where(
        Transaction.uploaded_by == current_user.id,
        extract("year", col(Transaction.date)) == year,
        extract("month", col(Transaction.date)) == month,
    )
    month_transactions = session.exec(transactions_stmt).all()

    # --- total_income: sum of income transactions ---
    income_stmt = select(Transaction).where(
        Transaction.uploaded_by == current_user.id,
        Transaction.type == "income",
        extract("year", col(Transaction.date)) == year,
        extract("month", col(Transaction.date)) == month,
    )
    total_income = sum(t.total_amount for t in session.exec(income_stmt).all())

    # --- Build spent per category from TransactionLines (non-income transactions) ---
    expense_transaction_ids = {
        t.id for t in month_transactions if t.type != "income" and t.id is not None
    }

    spent_per_category: dict[int, float] = {}
    if expense_transaction_ids:
        lines_stmt = select(TransactionLine).where(
            col(TransactionLine.transaction_id).in_(expense_transaction_ids)
        )
        lines = session.exec(lines_stmt).all()
        for line in lines:
            if line.category_id is not None:
                spent_per_category[line.category_id] = (
                    spent_per_category.get(line.category_id, 0.0) + line.price
                )

    # --- Merge limits and spent into per-category summary ---
    all_category_ids = set(limits.keys()) | set(spent_per_category.keys())

    category_items: list[CategoryBudgetSummaryItem] = []
    for cat_id in all_category_ids:
        category = session.get(Category, cat_id)
        cat_name = category.name if category else f"Category {cat_id}"
        planned = limits.get(cat_id, 0.0)
        spent = spent_per_category.get(cat_id, 0.0)
        category_items.append(
            CategoryBudgetSummaryItem(
                category_id=cat_id,
                category_name=cat_name,
                planned=planned,
                spent=spent,
                remaining=planned - spent,
            )
        )

    # Sort for stable ordering: categories with limits first, then by name
    category_items.sort(key=lambda x: (x.planned == 0.0, x.category_name))

    total_planned = sum(item.planned for item in category_items)
    total_spent = sum(item.spent for item in category_items)

    return MonthlyBudgetSummary(
        year=year,
        month=month,
        total_planned=total_planned,
        total_spent=total_spent,
        total_remaining=total_planned - total_spent,
        total_income=total_income,
        categories=category_items,
    )


# --- CATEGORIES ---

@router.get("/categories", response_model=List[CategoryRead])
async def get_categories(
    session: Session = Depends(get_ops_session),
    current_user: User = Depends(get_current_user),
):
    statement = select(Category).where(
        (Category.owner_id == current_user.id) | (Category.is_system)
    )
    categories = session.exec(statement).all()
    return categories

@router.post("/categories", response_model=CategoryRead)
async def create_category(
    category_data: CategoryCreate,
    session: Session = Depends(get_ops_session),
    current_user: User = Depends(get_current_user),
):
    dump_data = category_data.model_dump(exclude={"is_system"})
    category = Category(
        **dump_data,
        owner_id=current_user.id,
        is_system=False
    )
    session.add(category)
    session.commit()
    session.refresh(category)
    return category

@router.patch("/categories/{category_id}", response_model=CategoryRead)
async def update_category(
    category_id: int,
    category_update: CategoryUpdate,
    session: Session = Depends(get_ops_session),
    current_user: User = Depends(get_current_user),
):
    category = session.get(Category, category_id)
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")
    if not category.is_system and category.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to modify this category")

    update_data = category_update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(category, key, value)

    session.add(category)
    session.commit()
    session.refresh(category)
    return category

@router.delete("/categories/{category_id}", status_code=204)
async def delete_category(
    category_id: int,
    reassign_to: int | None = None,
    session: Session = Depends(get_ops_session),
    current_user: User = Depends(get_current_user),
):
    category = session.get(Category, category_id)
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")
    if category.is_system or category.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to delete this category")

    target_category_id = reassign_to
    if target_category_id is not None:
        target_category = session.get(Category, target_category_id)
        if not target_category or (target_category.owner_id != current_user.id and not target_category.is_system):
            raise HTTPException(status_code=400, detail="Invalid target category for reassignment")
    else:
        target_category_id = category.parent_id

    transactions_statement = select(Transaction).where(Transaction.category_id == category_id)
    transactions = session.exec(transactions_statement).all()
    for t in transactions:
        t.category_id = target_category_id
        session.add(t)

    subcategories_statement = select(Category).where(Category.parent_id == category_id)
    subcategories = session.exec(subcategories_statement).all()
    for sub in subcategories:
        sub.parent_id = target_category_id
        session.add(sub)

    session.delete(category)
    session.commit()
    return None


# --- TAGS ---

@router.get("/tags", response_model=List[TagRead])
async def get_tags(
    session: Session = Depends(get_ops_session),
    current_user: User = Depends(get_current_user),
):
    statement = select(Tag).where(Tag.owner_id == current_user.id)
    return session.exec(statement).all()

@router.post("/tags", response_model=TagRead)
async def create_tag(
    tag_data: TagCreate,
    session: Session = Depends(get_ops_session),
    current_user: User = Depends(get_current_user),
):
    tag = Tag(**tag_data.model_dump(), owner_id=current_user.id)
    session.add(tag)
    session.commit()
    session.refresh(tag)
    return tag

@router.patch("/tags/{tag_id}", response_model=TagRead)
async def update_tag(
    tag_id: int,
    tag_update: TagUpdate,
    session: Session = Depends(get_ops_session),
    current_user: User = Depends(get_current_user),
):
    tag = session.get(Tag, tag_id)
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")
    if tag.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to modify this tag")

    update_data = tag_update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(tag, key, value)

    session.add(tag)
    session.commit()
    session.refresh(tag)
    return tag

@router.delete("/tags/{tag_id}", status_code=204)
async def delete_tag(
    tag_id: int,
    session: Session = Depends(get_ops_session),
    current_user: User = Depends(get_current_user),
):
    tag = session.get(Tag, tag_id)
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")
    if tag.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to delete this tag")

    links_statement = select(TransactionTagLink).where(TransactionTagLink.tag_id == tag_id)
    links = session.exec(links_statement).all()
    for link in links:
        session.delete(link)

    session.delete(tag)
    session.commit()
    return None
