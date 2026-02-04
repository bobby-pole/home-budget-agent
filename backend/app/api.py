# backend/app/api.py
import shutil
import os
import hashlib
from uuid import uuid4
from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, BackgroundTasks
from sqlmodel import Session, select, desc
from .models import Receipt, Item, ReceiptCreate, ReceiptRead, ReceiptUpdate, ItemUpdate
from .database import get_session
from .services import AIService
from typing import List

router = APIRouter()
UPLOAD_DIR = "static/uploads"

# --- TASK IN BACKGROUND ---
def process_receipt_in_background(receipt_id: int, image_path: str, session: Session):
    print(f"🤖 AI Processing started for receipt #{receipt_id}...")
    
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


# --- ENDPOINT ---
@router.post("/upload", response_model=Receipt)
async def upload_receipt(
    background_tasks: BackgroundTasks,
    force: bool = False,
    file: UploadFile = File(...), 
    session: Session = Depends(get_session)
):
    # 1. Calculate SHA256 hash to detect duplicates
    file_content = await file.read()
    file_hash = hashlib.sha256(file_content).hexdigest()
    
    # Reset cursor so we can save it later
    await file.seek(0)

    # 2. Check for duplicates (if not forced)
    if not force:
        statement = select(Receipt).where(Receipt.content_hash == file_hash)
        existing_receipt = session.exec(statement).first()
        if existing_receipt:
            raise HTTPException(
                status_code=409, 
                detail="Duplicate receipt detected. Use force=true to upload anyway."
            )

    # File saving
    file_extension = file.filename.split(".")[-1]
    unique_filename = f"{uuid4()}.{file_extension}"
    file_path = f"{UPLOAD_DIR}/{unique_filename}"
    
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    
    # Create initial Receipt entry with status "processing"
    new_receipt = Receipt(
        merchant_name="Processing...",
        image_path=file_path,
        status="processing",
        content_hash=file_hash
    )
    
    session.add(new_receipt)
    session.commit()
    session.refresh(new_receipt)
    
    # AI agent works in background
    background_tasks.add_task(process_receipt_in_background, new_receipt.id, file_path, session)
    
    return new_receipt

@router.post("/receipts/{receipt_id}/retry", response_model=Receipt)
async def retry_receipt(
    receipt_id: int,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session)
):
    receipt = session.get(Receipt, receipt_id)
    if not receipt:
        raise HTTPException(status_code=404, detail="Receipt not found")
        
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
    background_tasks.add_task(process_receipt_in_background, receipt.id, receipt.image_path, session)
    
    return receipt

@router.get("/receipts", response_model=List[ReceiptRead])
async def get_receipts(session: Session = Depends(get_session)):
    # Pobieramy paragony posortowane od najnowszego (data malejąco)
    statement = select(Receipt).order_by(desc(Receipt.date))
    results = session.exec(statement).all()
    return results

@router.patch("/receipts/{receipt_id}", response_model=Receipt)
async def update_receipt(
    receipt_id: int,
    receipt_update: ReceiptUpdate,
    session: Session = Depends(get_session)
):
    db_receipt = session.get(Receipt, receipt_id)
    if not db_receipt:
        raise HTTPException(status_code=404, detail="Receipt not found")
    
    receipt_data = receipt_update.model_dump(exclude_unset=True)
    for key, value in receipt_data.items():
        setattr(db_receipt, key, value)
    
    session.add(db_receipt)
    session.commit()
    session.refresh(db_receipt)
    return db_receipt

@router.patch("/items/{item_id}", response_model=Item)
async def update_item(
    item_id: int,
    item_update: ItemUpdate,
    session: Session = Depends(get_session)
):
    db_item = session.get(Item, item_id)
    if not db_item:
        raise HTTPException(status_code=404, detail="Item not found")
    
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
    session: Session = Depends(get_session)
):
    receipt = session.get(Receipt, receipt_id)
    if not receipt:
        raise HTTPException(status_code=404, detail="Receipt not found")
    
    # Delete file if exists (e.g. pending/error status)
    if receipt.image_path and os.path.exists(receipt.image_path):
        try:
            os.remove(receipt.image_path)
        except OSError:
            pass # Ignore file errors

    # Delete related items manually (SQLModel/SQLite might need explicit cascade)
    for item in receipt.items:
        session.delete(item)
        
    session.delete(receipt)
    session.commit()
    return None