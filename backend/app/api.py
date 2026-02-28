# backend/app/api.py
import shutil
import os
import hashlib
from uuid import uuid4
from datetime import datetime, timezone
from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, BackgroundTasks
from sqlmodel import Session, select, desc
from .models import (
    Receipt, Item, ReceiptRead, ReceiptUpdate, ItemUpdate,
    ManualReceiptCreate,
    MonthlyBudget, MonthlyBudgetUpdate,
    User, UserCreate, UserRead, Token,
    Category, Tag, CategoryCreate, CategoryUpdate, CategoryRead, TagCreate, TagRead, TagUpdate, ReceiptTagLink
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


# --- TASK IN BACKGROUND ---
def process_receipt_in_background(receipt_id: int, image_path: str):
    print(f"🤖 AI Processing started for receipt #{receipt_id}...")

    # Tworzymy nową sesję dla zadania w tle, aby uniknąć problemu z zamkniętym połączeniem
    with Session(operations_engine) as session:
        # 1. Call AI to parse receipt
        data = AIService.parse_receipt(image_path)

        # Load receipt from DB
        receipt = session.get(Receipt, receipt_id)

        if not data or not receipt:
            print("❌ AI Failed or Receipt not found")
            if receipt:
                receipt.status = "error"
                session.add(receipt)
                session.commit()
            return

        # Validate business data (AI might return JSON with empty values)
        merchant = data.get("merchant_name")
        total = data.get("total_amount", 0.0)

        if not merchant or merchant == "Unknown" or total <= 0:
            print(f"⚠️ AI Validation Failed: Merchant='{merchant}', Total={total}")
            if receipt:
                receipt.status = "error"
                # Save partial data so user can see it
                receipt.merchant_name = merchant or "Unknown"
                receipt.total_amount = total
                receipt.currency = data.get("currency", "PLN")
                session.add(receipt)
                session.commit()
            return

        # 2. Update receipt details (Success path)
        receipt.merchant_name = merchant
        receipt.total_amount = total
        receipt.currency = data.get("currency", "PLN")
        receipt.status = "done"

        # Update date from AI if available
        ai_date_str = data.get("date")
        if ai_date_str:
            try:
                receipt.date = datetime.strptime(ai_date_str, "%Y-%m-%d")
            except (ValueError, TypeError):
                print(f"⚠️ Could not parse AI date: {ai_date_str}")

        # 3. Add positions
        items_data = data.get("items", [])
        for item_raw in items_data:
            new_item = Item(
                name=item_raw["name"],
                price=item_raw["price"],
                quantity=item_raw.get("quantity", 1),
                category=item_raw.get("category", "Other"),
                receipt_id=receipt.id
            )
            session.add(new_item)

        session.add(receipt)
        session.commit()
        print(f"✅ AI Processing finished for receipt #{receipt_id}")

        # 4. OPTIMIZATION: Delete image file after success
        if receipt.status == "done" and image_path and os.path.exists(image_path):
            try:
                os.remove(image_path)
                print(f"🗑️  Deleted processed image: {image_path}")

                # Update DB to reflect deletion
                receipt.image_path = None
                session.add(receipt)
                session.commit()
            except Exception as e:
                print(f"⚠️  Failed to delete image {image_path}: {e}")


# --- RECEIPTS ---

@router.post("/receipts/manual", response_model=ReceiptRead)
def create_manual_receipt(
    data: ManualReceiptCreate,
    session: Session = Depends(get_ops_session),
    current_user: User = Depends(get_current_user),
):
    total = (
        sum(i.price * i.quantity for i in data.items)
        if data.items
        else data.total_amount
    )

    receipt = Receipt(
        merchant_name=data.merchant_name,
        total_amount=total,
        currency=data.currency,
        date=data.date or datetime.now(timezone.utc),
        status="done",
        is_manual=True,
        uploaded_by=current_user.id,
        category_id=data.category_id,
    )
    
    if data.tag_ids:
        tags = session.exec(select(Tag).where(Tag.id.in_(data.tag_ids))).all()
        receipt.tags = tags

    session.add(receipt)
    session.commit()
    session.refresh(receipt)

    if data.items:
        for item_data in data.items:
            session.add(Item(
                name=item_data.name,
                price=item_data.price,
                quantity=item_data.quantity,
                category=item_data.category,
                receipt_id=receipt.id,
            ))
    else:
        session.add(Item(
            name=data.note or "Wpis ręczny",
            price=data.total_amount,
            quantity=1.0,
            category=data.category or "Other",
            receipt_id=receipt.id,
        ))

    session.commit()
    session.refresh(receipt)
    return receipt


@router.post("/upload", response_model=Receipt)
async def upload_receipt(
    background_tasks: BackgroundTasks,
    force: bool = False,
    file: UploadFile = File(...),
    session: Session = Depends(get_ops_session),
    current_user: User = Depends(get_current_user),
):
    # 1. Calculate SHA256 hash to detect duplicates
    file_content = await file.read()
    file_hash = hashlib.sha256(file_content).hexdigest()

    # Reset cursor so we can save it later
    await file.seek(0)

    # 2. Check for duplicates (if not forced) — scoped to the current user
    if not force:
        statement = select(Receipt).where(
            Receipt.content_hash == file_hash,
            Receipt.uploaded_by == current_user.id,
        )
        existing_receipt = session.exec(statement).first()
        if existing_receipt:
            raise HTTPException(
                status_code=409,
                detail="Duplicate receipt detected. Use force=true to upload anyway."
            )

    # File saving
    filename = file.filename or "upload.jpg"
    file_extension = filename.split(".")[-1]
    unique_filename = f"{uuid4()}.{file_extension}"
    file_path = f"{UPLOAD_DIR}/{unique_filename}"

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    # Create initial Receipt entry with status "processing"
    new_receipt = Receipt(
        merchant_name="Processing...",
        image_path=file_path,
        status="processing",
        content_hash=file_hash,
        uploaded_by=current_user.id,
    )

    session.add(new_receipt)
    session.commit()
    session.refresh(new_receipt)

    # AI agent works in background
    assert new_receipt.id is not None
    background_tasks.add_task(process_receipt_in_background, new_receipt.id, file_path)

    return new_receipt


@router.post("/receipts/{receipt_id}/retry", response_model=Receipt)
async def retry_receipt(
    receipt_id: int,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_ops_session),
    current_user: User = Depends(get_current_user),
):
    receipt = session.get(Receipt, receipt_id)
    if not receipt:
        raise HTTPException(status_code=404, detail="Receipt not found")

    if receipt.uploaded_by != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to retry this receipt")

    if receipt.status != "error":
        raise HTTPException(status_code=400, detail="Only failed receipts can be retried")

    if not receipt.image_path or not os.path.exists(receipt.image_path):
        raise HTTPException(status_code=404, detail="Original image file not found. Please re-upload.")

    # Reset status
    receipt.status = "processing"
    session.add(receipt)
    session.commit()
    session.refresh(receipt)

    # Restart AI task
    assert receipt.id is not None
    background_tasks.add_task(process_receipt_in_background, receipt.id, receipt.image_path)

    return receipt


@router.get("/receipts", response_model=List[ReceiptRead])
async def get_receipts(
    session: Session = Depends(get_ops_session),
    current_user: User = Depends(get_current_user),
):
    statement = (
        select(Receipt)
        .where(Receipt.uploaded_by == current_user.id)
        .order_by(desc(Receipt.date))
    )
    results = session.exec(statement).all()
    return results


@router.patch("/receipts/{receipt_id}", response_model=Receipt)
async def update_receipt(
    receipt_id: int,
    receipt_update: ReceiptUpdate,
    session: Session = Depends(get_ops_session),
    current_user: User = Depends(get_current_user),
):
    db_receipt = session.get(Receipt, receipt_id)
    if not db_receipt:
        raise HTTPException(status_code=404, detail="Receipt not found")

    if db_receipt.uploaded_by != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to modify this receipt")

    receipt_data = receipt_update.model_dump(exclude_unset=True, exclude={"tag_ids"})
    for key, value in receipt_data.items():
        setattr(db_receipt, key, value)

    if receipt_update.tag_ids is not None:
        tags = session.exec(select(Tag).where(Tag.id.in_(receipt_update.tag_ids))).all()
        db_receipt.tags = tags

    session.add(db_receipt)
    session.commit()
    session.refresh(db_receipt)
    return db_receipt


@router.patch("/items/{item_id}", response_model=Item)
async def update_item(
    item_id: int,
    item_update: ItemUpdate,
    session: Session = Depends(get_ops_session),
    current_user: User = Depends(get_current_user),
):
    db_item = session.get(Item, item_id)
    if not db_item:
        raise HTTPException(status_code=404, detail="Item not found")

    parent_receipt = session.get(Receipt, db_item.receipt_id)
    if not parent_receipt or parent_receipt.uploaded_by != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to modify this item")

    item_data = item_update.model_dump(exclude_unset=True)
    for key, value in item_data.items():
        setattr(db_item, key, value)

    session.add(db_item)
    session.commit()
    session.refresh(db_item)
    return db_item


@router.delete("/receipts/{receipt_id}", status_code=204)
async def delete_receipt(
    receipt_id: int,
    session: Session = Depends(get_ops_session),
    current_user: User = Depends(get_current_user),
):
    receipt = session.get(Receipt, receipt_id)
    if not receipt:
        raise HTTPException(status_code=404, detail="Receipt not found")

    if receipt.uploaded_by != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to delete this receipt")

    # Delete file if exists (e.g. pending/error status)
    if receipt.image_path and os.path.exists(receipt.image_path):
        try:
            os.remove(receipt.image_path)
        except OSError:
            pass  # Ignore file errors

    # Delete related items manually (SQLModel/SQLite might need explicit cascade)
    for item in receipt.items:
        session.delete(item)

    session.delete(receipt)
    session.commit()
    return None


# --- BUDGET ---

@router.get("/budget/{year}/{month}", response_model=MonthlyBudget)
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
        return MonthlyBudget(year=year, month=month, amount=0.0, user_id=current_user.id)
    return budget


@router.post("/budget/{year}/{month}", response_model=MonthlyBudget)
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
        existing.amount = budget_data.amount
        session.add(existing)
        session.commit()
        session.refresh(existing)
        return existing

    new_budget = MonthlyBudget(year=year, month=month, amount=budget_data.amount, user_id=current_user.id)
    session.add(new_budget)
    session.commit()
    session.refresh(new_budget)
    return new_budget


# --- CATEGORIES ---

@router.get("/categories", response_model=List[CategoryRead])
async def get_categories(
    session: Session = Depends(get_ops_session),
    current_user: User = Depends(get_current_user),
):
    # Returns all categories for the user (and system ones)
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

    # Reassign transactions
    target_category_id = reassign_to
    if target_category_id is not None:
        target_category = session.get(Category, target_category_id)
        if not target_category or (target_category.owner_id != current_user.id and not target_category.is_system):
            raise HTTPException(status_code=400, detail="Invalid target category for reassignment")
    else:
        # Check if parent exists, if yes reassign to parent, else None
        target_category_id = category.parent_id

    # Reassign all receipts
    receipts_statement = select(Receipt).where(Receipt.category_id == category_id)
    receipts = session.exec(receipts_statement).all()
    for r in receipts:
        r.category_id = target_category_id
        session.add(r)
        
    # Reassign subcategories
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

    tag.name = tag_update.name
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
        
    # Delete links first (if not cascading)
    links_statement = select(ReceiptTagLink).where(ReceiptTagLink.tag_id == tag_id)
    links = session.exec(links_statement).all()
    for link in links:
        session.delete(link)

    session.delete(tag)
    session.commit()
    return None

