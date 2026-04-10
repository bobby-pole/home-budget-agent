# backend/app/api.py
import shutil
import os
import hashlib
from uuid import uuid4
from datetime import datetime, timezone
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Depends, BackgroundTasks, Path
from sqlmodel import Session, select, desc, col
from sqlalchemy import extract, func
from .models import (
    Transaction, TransactionLine, TransactionRead, TransactionUpdate,
    TransactionLineUpdate, ManualTransactionCreate,
    ReceiptScan,
    Budget, BudgetMember,
    MonthlyBudgetSummary, CategoryBudgetSummaryItem, EnvelopeAllocation,
    User, UserCreate, UserRead, Token,
    Category, Tag, CategoryCreate, CategoryUpdate, CategoryRead, TagCreate, TagRead, TagUpdate, TransactionTagLink,
    BudgetMemberCreate, BudgetMemberRead
)
from .database import get_session, get_ops_session, operations_engine
from .services import AIService
from .auth import get_current_user, hash_password, verify_password, create_access_token
from typing import List, Optional

router = APIRouter()
UPLOAD_DIR = "static/uploads"


# --- DEPENDENCY: resolve current user's budget (lazy-create if missing) ---

def get_current_budget(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_ops_session),
) -> Budget:
    membership = session.exec(
        select(BudgetMember).where(BudgetMember.user_id == current_user.id)
    ).first()
    if membership:
        budget = session.get(Budget, membership.budget_id)
        if budget:
            return budget

    # Lazy migration: user existed before multi-tenancy — create a default budget on the fly
    new_budget = Budget(name="Domowy", owner_id=current_user.id)
    session.add(new_budget)
    session.commit()
    session.refresh(new_budget)
    if new_budget.id is None:
        raise HTTPException(status_code=500, detail="Failed to create budget")
    session.add(BudgetMember(budget_id=new_budget.id, user_id=current_user.id, role="owner"))
    session.commit()
    return new_budget


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
    if user.id is None:
        raise HTTPException(status_code=500, detail="Failed to create user")

    # Create default budget for the new user and link user as owner
    new_budget = Budget(name="Domowy", owner_id=user.id)
    session.add(new_budget)
    session.commit()
    session.refresh(new_budget)
    if new_budget.id is None:
        raise HTTPException(status_code=500, detail="Failed to create budget")
    session.add(BudgetMember(budget_id=new_budget.id, user_id=user.id, role="owner"))

    default_cats = [
        {"name": "Food", "icon": "🍔", "color": "#f87171"},
        {"name": "Housing", "icon": "🏠", "color": "#fb923c"},
        {"name": "Transport", "icon": "🚗", "color": "#60a5fa"},
        {"name": "Utilities", "icon": "💡", "color": "#facc15"},
        {"name": "Entertainment", "icon": "🎬", "color": "#c084fc"},
        {"name": "Health", "icon": "⚕️", "color": "#4ade80"},
        {"name": "Clothing", "icon": "👕", "color": "#f472b6"},
        {"name": "Kids", "icon": "🧸", "color": "#38bdf8"},
        {"name": "Pets", "icon": "🐕", "color": "#a78bfa"},
        {"name": "Travel", "icon": "✈️", "color": "#34d399"},
        {"name": "Education", "icon": "📚", "color": "#818cf8"},
        {"name": "Savings", "icon": "💰", "color": "#fbbf24"},
        {"name": "Gifts", "icon": "🎁", "color": "#fb7185"},
        {"name": "Alcohol", "icon": "🍻", "color": "#fcd34d"},
        {"name": "Other", "icon": "📦", "color": "#9ca3af"},
        {"name": "Salary", "icon": "💵", "color": "#10b981"},
    ]
    for i, cat_data in enumerate(default_cats):
        cat = Category(
            name=cat_data["name"],
            icon=cat_data["icon"],
            color=cat_data["color"],
            is_system=False,
            budget_id=new_budget.id,
            order_index=i
        )
        session.add(cat)

    session.commit()

    token = create_access_token({"sub": user.email})
    return Token(access_token=token, user=UserRead(id=user.id, email=user.email, created_at=user.created_at))


@router.post("/auth/login", response_model=Token)
def login(user_data: UserCreate, session: Session = Depends(get_session)):
    user = session.exec(select(User).where(User.email == user_data.email)).first()
    if not user or not verify_password(user_data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if user.id is None:
        raise HTTPException(status_code=500, detail="Invalid user state")
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

        # Fetch categories for the current budget to pass to AI
        db_categories = session.exec(select(Category).where((Category.budget_id == transaction.budget_id) | (Category.is_system))).all()
        cat_dicts = [{"id": c.id, "name": c.name} for c in db_categories]

        data = AIService.parse_receipt(image_path, categories=cat_dicts)

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

        # Map AI returned category names back to DB category IDs
        cat_name_to_id = {c.name.lower(): c.id for c in db_categories}

        items_data = data.get("items", [])
        for item_raw in items_data:
            category_name = item_raw.get("category", "")
            cat_id = cat_name_to_id.get(category_name.lower()) if category_name else None

            session.add(TransactionLine(
                name=item_raw.get("name", "Unknown item"),
                price=float(item_raw.get("price", 0.0)),
                quantity=float(item_raw.get("quantity", 1.0)),
                category_id=cat_id,
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
    current_budget: Budget = Depends(get_current_budget),
):
    if not current_budget:
        raise HTTPException(status_code=404, detail="Budget not found")
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
        budget_id=current_budget.id,
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
    note: Optional[str] = Form(None),
    file: UploadFile = File(...),
    session: Session = Depends(get_ops_session),
    current_user: User = Depends(get_current_user),
    current_budget: Budget = Depends(get_current_budget),
):
    if not current_budget:
        raise HTTPException(status_code=404, detail="Budget not found")
    file_content = await file.read()
    file_hash = hashlib.sha256(file_content).hexdigest()

    await file.seek(0)

    if not force:
        existing_scan = session.exec(
            select(ReceiptScan).where(
                ReceiptScan.content_hash == file_hash,
                ReceiptScan.transaction_id.in_(  # type: ignore
                    select(Transaction.id).where(Transaction.budget_id == current_budget.id)
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
        budget_id=current_budget.id,
        note=note,
    )
    session.add(new_transaction)
    session.commit()
    session.refresh(new_transaction)

    if new_transaction.id is None:
        raise HTTPException(status_code=500, detail="Failed to create transaction")
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

    if scan.id is None:
        raise HTTPException(status_code=500, detail="Failed to create receipt scan")
    background_tasks.add_task(process_transaction_in_background, new_transaction.id, scan.id, file_path)

    session.refresh(new_transaction)
    return new_transaction


@router.post("/transactions/{transaction_id}/retry", response_model=TransactionRead)
async def retry_transaction(
    transaction_id: int,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_ops_session),
    current_user: User = Depends(get_current_user),
    current_budget: Budget = Depends(get_current_budget),
):
    if not current_budget:
        raise HTTPException(status_code=404, detail="Budget not found")
    transaction = session.get(Transaction, transaction_id)
    if not transaction:
        raise HTTPException(status_code=404, detail="Transaction not found")

    if transaction.budget_id != current_budget.id:
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

    if transaction.id is None:
        raise HTTPException(status_code=500, detail="Invalid transaction state")
    if scan.id is None:
        raise HTTPException(status_code=500, detail="Invalid scan state")
    background_tasks.add_task(process_transaction_in_background, transaction.id, scan.id, scan.image_path)

    return transaction


@router.get("/transactions", response_model=List[TransactionRead])
async def get_transactions(
    limit: int = 50,
    offset: int = 0,
    type: Optional[str] = None,
    session: Session = Depends(get_ops_session),
    current_user: User = Depends(get_current_user),
    current_budget: Budget = Depends(get_current_budget),
):
    if not current_budget:
        raise HTTPException(status_code=404, detail="Budget not found")
    statement = (
        select(Transaction)
        .where(Transaction.budget_id == current_budget.id)
    )
    
    if type:
        statement = statement.where(Transaction.type == type)
        
    statement = statement.order_by(desc(Transaction.date)).offset(offset).limit(limit)
    results = session.exec(statement).all()
    return results


@router.patch("/transactions/{transaction_id}", response_model=TransactionRead)
async def update_transaction(
    transaction_id: int,
    transaction_update: TransactionUpdate,
    session: Session = Depends(get_ops_session),
    current_user: User = Depends(get_current_user),
    current_budget: Budget = Depends(get_current_budget),
):
    if not current_budget:
        raise HTTPException(status_code=404, detail="Budget not found")
    db_transaction = session.get(Transaction, transaction_id)
    if not db_transaction:
        raise HTTPException(status_code=404, detail="Transaction not found")

    if db_transaction.budget_id != current_budget.id:
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
    current_budget: Budget = Depends(get_current_budget),
):
    if not current_budget:
        raise HTTPException(status_code=404, detail="Budget not found")
    db_line = session.get(TransactionLine, line_id)
    if not db_line or db_line.transaction_id != transaction_id:
        raise HTTPException(status_code=404, detail="Transaction line not found")

    parent_transaction = session.get(Transaction, transaction_id)
    if not parent_transaction or parent_transaction.budget_id != current_budget.id:
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
    current_budget: Budget = Depends(get_current_budget),
):
    if not current_budget:
        raise HTTPException(status_code=404, detail="Budget not found")
    transaction = session.get(Transaction, transaction_id)
    if not transaction:
        raise HTTPException(status_code=404, detail="Transaction not found")

    if transaction.budget_id != current_budget.id:
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

@router.get("/budget/{year}/{month}/limits", response_model=list)
def get_limits_dummy(year: int, month: int):
    return []

@router.put("/budget/{year}/{month}/limits/{category_id}", response_model=dict)
def put_limit_dummy(year: int, month: int, category_id: int):
    return {}

@router.delete("/budget/{year}/{month}/limits/{category_id}")
def delete_limit_dummy(year: int, month: int, category_id: int):
    return {}

@router.get("/budget/{year}/{month}/summary", response_model=MonthlyBudgetSummary)
def get_summary(
    year: int = Path(..., ge=2000, le=2100, description="Year of the budget"),
    month: int = Path(..., ge=1, le=12, description="Month of the budget (1-12)"),
    session: Session = Depends(get_ops_session),
    current_budget: Budget = Depends(get_current_budget),
):
    if not current_budget:
        raise HTTPException(status_code=404, detail="Budget not found")

    # 1. Calculate total income
    income_stmt = select(func.sum(Transaction.total_amount)).where(
        Transaction.budget_id == current_budget.id,
        Transaction.type == "income",
        extract('year', col(Transaction.date)) == year,
        extract('month', col(Transaction.date)) == month
    )
    total_income = session.scalar(income_stmt) or 0.0

    # 2. Calculate total spent (from expenses)
    expense_stmt = select(func.sum(Transaction.total_amount)).where(
        Transaction.budget_id == current_budget.id,
        Transaction.type == "expense",
        extract('year', col(Transaction.date)) == year,
        extract('month', col(Transaction.date)) == month
    )
    total_spent = session.scalar(expense_stmt) or 0.0

    # 3. Retrieve category allocations (planning)
    allocations_stmt = select(EnvelopeAllocation).where(
        EnvelopeAllocation.budget_id == current_budget.id,
        EnvelopeAllocation.year == year,
        EnvelopeAllocation.month == month
    )
    allocations = session.exec(allocations_stmt).all()
    total_planned = sum(a.amount for a in allocations)

    # Calculate category expenses breakdown
    expenses_by_cat_stmt = select(
        Transaction.category_id, 
        func.sum(Transaction.total_amount)
    ).where(
        Transaction.budget_id == current_budget.id,
        Transaction.type == "expense",
        extract('year', col(Transaction.date)) == year,
        extract('month', col(Transaction.date)) == month
    ).group_by(col(Transaction.category_id))
    
    spent_by_category = dict(session.exec(expenses_by_cat_stmt).all())

    # Build the category summary items
    categories_summary = []
    # Get all categories belonging to the budget
    all_categories = session.exec(select(Category).where(Category.budget_id == current_budget.id)).all()
    
    # Also include system categories if they are somehow accessible or fallback
    
    allocations_by_cat = {a.category_id: a.amount for a in allocations}
    
    for cat in all_categories:
        if cat.id is None:
            continue
        planned = allocations_by_cat.get(cat.id, 0.0)
        spent = spent_by_category.get(cat.id, 0.0)
        
        # Only include if there is planned or spent amount
        if planned > 0 or spent > 0:
            categories_summary.append(CategoryBudgetSummaryItem(
                category_id=cat.id,
                category_name=cat.name,
                planned=planned,
                spent=spent,
                remaining=planned - spent
            ))

    total_remaining = total_income - total_spent

    return MonthlyBudgetSummary(
        year=year, 
        month=month, 
        total_planned=total_planned, 
        total_spent=total_spent, 
        total_remaining=total_remaining, 
        total_income=total_income, 
        categories=categories_summary
    )


@router.post("/budget/members", response_model=BudgetMemberRead)
async def invite_member(
    member_data: BudgetMemberCreate,
    session: Session = Depends(get_ops_session),
    current_user: User = Depends(get_current_user),
    current_budget: Budget = Depends(get_current_budget),
):
    # Verify if current user is owner/editor of the budget
    # We need to query from identity_engine to find the user by email, 
    # but the membership is in operations_engine. 
    # Actually User is in identity_engine, and BudgetMember is in operations_engine.
    # Our get_ops_session and get_session point to the same DB for now.

    # Find the user to invite by email
    from .database import identity_engine
    with Session(identity_engine) as auth_session:
        target_user = auth_session.exec(select(User).where(User.email == member_data.email)).first()
    
    if not target_user:
        raise HTTPException(status_code=404, detail=f"User with email {member_data.email} not found")

    # Check permissions and existing membership in ops session
    membership = session.exec(
        select(BudgetMember).where(
            BudgetMember.budget_id == current_budget.id,
            BudgetMember.user_id == current_user.id
        )
    ).first()
    
    if not membership or membership.role not in ["owner", "editor"]:
        raise HTTPException(status_code=403, detail="Only owners or editors can invite members")

    # Check if already a member
    existing = session.exec(
        select(BudgetMember).where(
            BudgetMember.budget_id == current_budget.id,
            BudgetMember.user_id == target_user.id
        )
    ).first()
    
    if existing:
        raise HTTPException(status_code=400, detail="User is already a member of this budget")

    new_member = BudgetMember(
        budget_id=current_budget.id,
        user_id=target_user.id,
        role=member_data.role
    )
    session.add(new_member)
    session.commit()
    session.refresh(new_member)
    return new_member

@router.get("/categories", response_model=List[CategoryRead])
async def get_categories(
    session: Session = Depends(get_ops_session),
    current_budget: Budget = Depends(get_current_budget),
):
    statement = select(Category).where(
        (Category.budget_id == current_budget.id) | (Category.is_system)
    )
    categories = session.exec(statement).all()
    return categories

@router.post("/categories", response_model=CategoryRead)
async def create_category(
    category_data: CategoryCreate,
    session: Session = Depends(get_ops_session),
    current_budget: Budget = Depends(get_current_budget),
):
    dump_data = category_data.model_dump(exclude={"is_system"})
    category = Category(
        **dump_data,
        budget_id=current_budget.id,
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
    current_budget: Budget = Depends(get_current_budget),
):
    category = session.get(Category, category_id)
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")
    if not category.is_system and category.budget_id != current_budget.id:
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
    reassign_to: Optional[int] = None,
    session: Session = Depends(get_ops_session),
    current_budget: Budget = Depends(get_current_budget),
):
    category = session.get(Category, category_id)
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")
    if category.is_system or category.budget_id != current_budget.id:
        raise HTTPException(status_code=403, detail="Not authorized to delete this category")

    target_category_id = reassign_to
    if target_category_id is not None:
        target_category = session.get(Category, target_category_id)
        if not target_category or (target_category.budget_id != current_budget.id and not target_category.is_system):
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
    current_budget: Budget = Depends(get_current_budget),
):
    statement = select(Tag).where(Tag.budget_id == current_budget.id)
    return session.exec(statement).all()

@router.post("/tags", response_model=TagRead)
async def create_tag(
    tag_data: TagCreate,
    session: Session = Depends(get_ops_session),
    current_budget: Budget = Depends(get_current_budget),
):
    tag = Tag(**tag_data.model_dump(), budget_id=current_budget.id)
    session.add(tag)
    session.commit()
    session.refresh(tag)
    return tag

@router.patch("/tags/{tag_id}", response_model=TagRead)
async def update_tag(
    tag_id: int,
    tag_update: TagUpdate,
    session: Session = Depends(get_ops_session),
    current_budget: Budget = Depends(get_current_budget),
):
    tag = session.get(Tag, tag_id)
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")
    if tag.budget_id != current_budget.id:
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
    current_budget: Budget = Depends(get_current_budget),
):
    tag = session.get(Tag, tag_id)
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")
    if tag.budget_id != current_budget.id:
        raise HTTPException(status_code=403, detail="Not authorized to delete this tag")

    links_statement = select(TransactionTagLink).where(TransactionTagLink.tag_id == tag_id)
    links = session.exec(links_statement).all()
    for link in links:
        session.delete(link)

    session.delete(tag)
    session.commit()
    return None
